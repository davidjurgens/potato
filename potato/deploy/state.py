"""Local record of what has been deployed where.

Kept beside the project as ``.potato/deployments.json`` so a second `up` for the
same name updates the existing host instead of provisioning a duplicate.

Providers also tag every resource they create (``potato``, ``potato-<name>``), so
losing this file costs convenience rather than the ability to find and destroy
what is running. That matters: a deploy tool whose only record of a billable
resource is a JSON file in a working directory will eventually orphan one.

Secrets never land here. ``SecretStore`` is a separate 0600 file for values that
must survive a restart (the generated admin key, an SSH private key path);
provider API tokens are resolved per-invocation and never written at all.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STATE_DIRNAME = ".potato"
STATE_FILENAME = "deployments.json"
SECRETS_FILENAME = "secrets.json"
SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: str, fallback: str = "potato-task") -> str:
    """Turn a task name into something usable as a host/repo name."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:48] or fallback


@dataclass
class DeploymentRecord:
    """One deployment of one project to one provider."""

    name: str
    provider: str
    provider_ref: Dict[str, Any] = field(default_factory=dict)
    url: Optional[str] = None
    status: str = "pending"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    bundle_sha: Optional[str] = None
    spec: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)
    last_pull_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DeploymentRecord":
        known = {f for f in cls.__dataclass_fields__}  # noqa: SLF001
        return cls(**{k: v for k, v in data.items() if k in known})


class DeploymentStore:
    """Reads and writes ``.potato/deployments.json`` next to a config file."""

    def __init__(self, config_path: str):
        project_dir = os.path.dirname(os.path.abspath(config_path))
        self.state_dir = os.path.join(project_dir, STATE_DIRNAME)
        self.path = os.path.join(self.state_dir, STATE_FILENAME)

    # -- reading -------------------------------------------------------

    def _load_raw(self) -> dict:
        if not os.path.isfile(self.path):
            return {"version": SCHEMA_VERSION, "deployments": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            # A corrupt state file must not block a deploy: providers can still
            # find their resources by tag. Move it aside and start clean.
            backup = f"{self.path}.corrupt"
            logger.warning("Could not read %s (%s); moving it to %s",
                           self.path, exc, backup)
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            return {"version": SCHEMA_VERSION, "deployments": {}}
        if not isinstance(data, dict):
            return {"version": SCHEMA_VERSION, "deployments": {}}
        data.setdefault("deployments", {})
        return data

    def get(self, name: str) -> Optional[DeploymentRecord]:
        entry = self._load_raw()["deployments"].get(name)
        return DeploymentRecord.from_dict(entry) if entry else None

    def list(self) -> List[DeploymentRecord]:
        records = [DeploymentRecord.from_dict(v)
                   for v in self._load_raw()["deployments"].values()]
        return sorted(records, key=lambda r: r.created_at)

    # -- writing -------------------------------------------------------

    def _write_raw(self, data: dict) -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        # Write to a temp file in the same directory then rename, so an
        # interrupted write cannot truncate an existing record.
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.state_dir,
            prefix=".deployments-", suffix=".tmp", delete=False)
        try:
            with handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, self.path)
        except Exception:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise

    def upsert(self, record: DeploymentRecord) -> DeploymentRecord:
        """Insert or replace a record. Called as soon as a resource gets an id."""
        data = self._load_raw()
        existing = data["deployments"].get(record.name)
        if existing and existing.get("created_at"):
            record.created_at = existing["created_at"]
        record.updated_at = utc_now()
        data["deployments"][record.name] = record.to_dict()
        data["version"] = SCHEMA_VERSION
        self._write_raw(data)
        return record

    def remove(self, name: str) -> bool:
        data = self._load_raw()
        if name not in data["deployments"]:
            return False
        del data["deployments"][name]
        self._write_raw(data)
        return True

    def mark_pulled(self, name: str) -> None:
        record = self.get(name)
        if record:
            record.last_pull_at = utc_now()
            self.upsert(record)


class SecretStore:
    """0600-mode store for per-deployment secrets that must survive a restart."""

    def __init__(self, config_path: str):
        project_dir = os.path.dirname(os.path.abspath(config_path))
        self.state_dir = os.path.join(project_dir, STATE_DIRNAME)
        self.path = os.path.join(self.state_dir, SECRETS_FILENAME)

    def _load(self) -> dict:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            logger.warning("Could not read secret store at %s", self.path)
            return {}

    def _save(self, data: dict) -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.state_dir,
            prefix=".secrets-", suffix=".tmp", delete=False)
        with handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(handle.name, self.path)

    def put(self, name: str, key: str, value: str) -> None:
        data = self._load()
        data.setdefault(name, {})[key] = value
        self._save(data)

    def get(self, name: str, key: str) -> Optional[str]:
        return self._load().get(name, {}).get(key)

    def forget(self, name: str) -> None:
        data = self._load()
        if data.pop(name, None) is not None:
            self._save(data)
