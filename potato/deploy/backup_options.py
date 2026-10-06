"""Turn `potato deploy up` backup flags into config and runtime secrets.

Before this module, ``--hf-token`` only did anything on HuggingFace. Render and
DigitalOcean exported ``HF_TOKEN`` into the container and never wrote a backup
block into the bundled config, so the server had nothing to start; Render's
free-tier refusal counted the flag as a configured backup all the same. Every
provider now gets the same two things from here:

* a ``backup:`` block, written into the bundled config by the CLI's patch;
* the credentials, carried as runtime secrets and never written to the bundle.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

VALID_KINDS = ("hf", "s3")


class BackupOptionsError(ValueError):
    """The flags ask for a backup that cannot be configured."""


@dataclass
class BackupOptions:
    kinds: List[str] = field(default_factory=list)
    hf_token: Optional[str] = None
    hf_repo: Optional[str] = None
    s3_bucket: Optional[str] = None
    s3_prefix: Optional[str] = None
    s3_region: Optional[str] = None
    s3_endpoint: Optional[str] = None
    s3_access_key_id: Optional[str] = None
    s3_secret_access_key: Optional[str] = None
    minutes: int = 5

    @property
    def enabled(self) -> bool:
        return bool(self.kinds)

    def describe(self) -> str:
        parts = []
        if "hf" in self.kinds:
            parts.append(f"HuggingFace dataset {self.hf_repo or '<account>/<name>-annotations'}")
        if "s3" in self.kinds:
            where = f"s3://{self.s3_bucket}"
            parts.append(f"{where}/{self.s3_prefix}" if self.s3_prefix else where)
        return " + ".join(parts) or "none"

    def sinks(self) -> List[Dict[str, Any]]:
        """The ``backup.sinks`` entries. Credentials are deliberately absent."""
        sinks: List[Dict[str, Any]] = []
        if "hf" in self.kinds:
            sinks.append({"type": "huggingface", "repo_id": self.hf_repo,
                          "repo_type": "dataset", "private": True})
        if "s3" in self.kinds:
            sink: Dict[str, Any] = {"type": "s3", "bucket": self.s3_bucket}
            for key, value in (("prefix", self.s3_prefix), ("region", self.s3_region),
                               ("endpoint_url", self.s3_endpoint)):
                if value:
                    sink[key] = value
            sinks.append(sink)
        return sinks

    def config_block(self) -> Dict[str, Any]:
        return {"enabled": True, "schedule_minutes": self.minutes,
                "restore_on_boot": True, "sinks": self.sinks()}

    def secrets(self) -> Dict[str, str]:
        """Environment the server reads its sink credentials from."""
        env: Dict[str, str] = {}
        if "hf" in self.kinds and self.hf_token:
            env["HF_TOKEN"] = self.hf_token
        if "s3" in self.kinds:
            if self.s3_access_key_id:
                env["POTATO_S3_ACCESS_KEY_ID"] = self.s3_access_key_id
            if self.s3_secret_access_key:
                env["POTATO_S3_SECRET_ACCESS_KEY"] = self.s3_secret_access_key
        return env


def from_args(args, name: str, *, environ=None,
              require_credentials: bool = True) -> BackupOptions:
    """Build options from parsed `up` arguments.

    ``--hf-token`` (or ``HF_TOKEN``) on its own still means an HF backup, which
    is what it meant before ``--backup`` existed. ``--s3-bucket`` on its own
    likewise implies ``s3``.
    """
    environ = os.environ if environ is None else environ

    requested = getattr(args, "backup", None)
    kinds: List[str] = []
    if requested:
        for item in str(requested).replace("+", ",").split(","):
            item = item.strip().lower()
            if not item:
                continue
            if item in ("huggingface", "hugging-face"):
                item = "hf"
            if item not in VALID_KINDS:
                raise BackupOptionsError(
                    f"--backup {item!r} is not a backup target; use hf, s3 or hf,s3")
            if item not in kinds:
                kinds.append(item)

    hf_token = getattr(args, "hf_token", None) or environ.get("HF_TOKEN")
    s3_bucket = getattr(args, "s3_bucket", None)
    if not requested:
        if getattr(args, "hf_token", None) or (hf_token and getattr(args, "hf_backup_repo", None)):
            kinds.append("hf")
        if s3_bucket:
            kinds.append("s3")

    options = BackupOptions(
        kinds=kinds,
        hf_token=hf_token,
        hf_repo=getattr(args, "hf_backup_repo", None),
        s3_bucket=s3_bucket,
        s3_prefix=getattr(args, "s3_prefix", None) or f"potato/{name}",
        s3_region=getattr(args, "s3_region", None),
        s3_endpoint=getattr(args, "s3_endpoint", None),
        s3_access_key_id=environ.get("POTATO_S3_ACCESS_KEY_ID"),
        s3_secret_access_key=environ.get("POTATO_S3_SECRET_ACCESS_KEY"),
        minutes=getattr(args, "backup_minutes", None) or 5,
    )

    # A deploy button's credentials come from whoever clicks it, at deploy time.
    if "hf" in kinds and not hf_token and require_credentials:
        raise BackupOptionsError(
            "An HF backup needs a HuggingFace token with write access: pass "
            "--hf-token or set HF_TOKEN.")
    if "s3" in kinds and not s3_bucket:
        raise BackupOptionsError("An S3 backup needs --s3-bucket.")
    return options


def default_hf_repo(token: str, name: str) -> str:
    """``<account>/<name>-annotations``, asking HuggingFace who the token is."""
    from potato.deploy.providers.huggingface import _hf_api, backup_repo_id

    identity = _hf_api(token).whoami()
    owner = identity.get("name")
    if not owner:
        raise BackupOptionsError("Could not determine the HuggingFace account name.")
    return backup_repo_id(owner, name)


def apply_to_config(config: Dict[str, Any], options: BackupOptions) -> Dict[str, Any]:
    """Write the ``backup:`` block, replacing the legacy one so only one runs."""
    if not options.enabled:
        return config
    config["backup"] = options.config_block()
    config.pop("huggingface_backup", None)
    return config
