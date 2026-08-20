"""Deploy a Potato task to a HuggingFace Space.

Two platform facts shape everything here, and both have been verified against
the live API rather than taken from documentation.

**The filesystem does not survive.** A Space is wiped on every rebuild and every
restart, and free Spaces sleep after 48 hours idle. Annotations written to disk
are therefore temporary by construction. So this provider creates a private
Dataset repo and mirrors the annotation output into it on a schedule, and refuses
to deploy without either that or an explicit `--demo`. The backup is not an
add-on; on this target it is where the data lives.

**Docker Spaces need a paid plan.** From the Hub documentation: *"Static Spaces
are free for everyone. Gradio and Docker Spaces run on compute and require a
paid plan to create: PRO for personal accounts, Team or Enterprise for
organizations."* Potato Spaces are `sdk: docker`. A free organization also caps
concurrent running Spaces at three, and exceeding it leaves a Space PAUSED —
which, unlike SLEEPING, never wakes for a visitor.

The Space itself is small. It derives from the published image and adds only the
project, rather than copying the whole potato package as the demo catalog does.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterator, Optional

from potato.deploy.providers.base import (
    Action,
    DeployPlan,
    DeploymentStatus,
    DeploySpec,
    Provider,
    ProviderError,
    PullResult,
    register_provider,
)
from potato.deploy.providers.digitalocean import render_template
from potato.deploy.state import DeploymentRecord

DEFAULT_IMAGE = "ghcr.io/davidjurgens/potato:latest"
DEFAULT_BACKUP_MINUTES = 5

# Concurrent running Spaces a free organization gets. A fourth cannot start.
CPU_BASIC_QUOTA = 3

# Stages from which a visitor gets a working demo. SLEEPING counts: a sleeping
# Space wakes on the next request. PAUSED does not — only its owner can restart
# it, so a visitor sees a dead page.
HEALTHY_STAGES = {"RUNNING", "SLEEPING"}
BUILDING_STAGES = {"BUILDING", "APP_STARTING", "RUNNING_BUILDING",
                   "RUNNING_APP_STARTING"}


def _hf_api(token: Optional[str]):
    try:
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise ProviderError(
            "The huggingface provider needs huggingface_hub. Install it with:\n"
            "    pip install 'potato-annotation[huggingface]'") from exc
    return HfApi(token=token)


def space_files(spec: DeploySpec, *, backup_repo: Optional[str] = None,
                title: Optional[str] = None,
                summary: str = "") -> Dict[str, str]:
    """The files a Space needs beyond the project itself.

    Pure, so a test can assert the frontmatter and the Dockerfile without a
    token. The README's YAML frontmatter is not decoration: HuggingFace reads
    `sdk` and `app_port` from it, and a Space without them does not build.
    """
    config_rel = spec.extra.get("config_rel", "config.yaml")
    return {
        "Dockerfile": render_template(
            "hf-space.Dockerfile.j2",
            image=spec.image or DEFAULT_IMAGE,
            config_rel=config_rel,
            threads=spec.threads),
        "README.md": render_template(
            "hf-space-README.md.j2",
            title=title or spec.name,
            summary=summary or "An annotation task built with Potato.",
            config_rel=config_rel,
            backup_repo=backup_repo,
            backup_minutes=spec.extra.get("backup_minutes",
                                          DEFAULT_BACKUP_MINUTES)),
    }


def backup_repo_id(owner: str, name: str) -> str:
    return f"{owner}/{name}-annotations"


@register_provider
class HuggingFaceProvider(Provider):
    """A Docker Space backed by a private Dataset repo."""

    name = "huggingface"
    requires = ("huggingface_hub",)
    ephemeral_fs = True
    public = True
    # Build and run logs are behind JWT-gated, undocumented endpoints. Reporting
    # the stage and a link beats pretending to stream something.
    supports_logs = False
    supports_pull = True        # from the backup dataset, not from the Space

    # -- plan ----------------------------------------------------------

    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        owner = spec.extra.get("owner") or "<your-username>"
        repo_id = f"{owner}/{spec.name}"
        backup = None if spec.demo else backup_repo_id(owner, spec.name)

        env = self.runtime_env(spec, spec.extra.get("generated"))

        result = DeployPlan(
            result_url_pattern=f"https://{_slug(owner)}-{_slug(spec.name)}.hf.space",
            estimated_cost_usd_month=0.0)
        result.actions = [
            Action("hf.whoami", "verify the token with GET /api/whoami-v2"),
        ]
        if backup:
            result.actions.append(Action(
                "hf.dataset", f"create the private Dataset {backup} for backups",
                {"repo_id": backup, "private": True}))
        result.actions += [
            Action("hf.space", f"create the Docker Space {repo_id}",
                   {"repo_id": repo_id, "space_sdk": "docker",
                    "private": spec.private}),
            Action("state.persist", "record the repo id before anything else runs"),
            Action("hf.secrets",
                   "set Space secrets (never committed to the repo)",
                   # Keys only: a plan is printed to a terminal.
                   {"secret_keys": sorted(env)}),
            Action("hf.upload",
                   f"upload {bundle.file_count if bundle else '?'} project files "
                   "plus a Dockerfile and README",
                   {"files": bundle.file_count if bundle else None}),
            Action("wait.build", "poll get_space_runtime until the stage is RUNNING"),
        ]

        result.warnings.append(
            "Creating a Docker Space requires a paid HuggingFace plan (PRO for a "
            "personal account, Team or Enterprise for an organization). Restarting "
            "an existing Space does not.")
        result.warnings.append(
            f"A free account runs at most {CPU_BASIC_QUOTA} Spaces at once, and a "
            "Space over that limit stays PAUSED, which never wakes for a visitor.")
        if spec.demo:
            result.warnings.append(
                "--demo: no backup Dataset. A Space's filesystem is wiped on every "
                "rebuild and restart, so annotations collected here will be lost.")
        else:
            result.warnings.append(
                f"Annotations are mirrored to {backup} every "
                f"{spec.extra.get('backup_minutes', DEFAULT_BACKUP_MINUTES)} "
                "minutes. Nothing else keeps them.")
        if not bundle:
            result.warnings.append("No bundle was built; this plan cannot run.")
        return result

    # -- create --------------------------------------------------------

    def create(self, spec: DeploySpec, bundle, existing, store) -> DeploymentRecord:
        missing = self.check_requirements()
        if missing:
            raise ProviderError(
                f"The huggingface provider needs {', '.join(missing)}. "
                "Install with: pip install 'potato-annotation[huggingface]'")

        api = _hf_api(self.token)
        try:
            identity = api.whoami()
        except Exception as exc:
            raise ProviderError(
                f"HuggingFace rejected the token: {exc}. Create one with write "
                "access at https://huggingface.co/settings/tokens") from exc

        owner = spec.extra.get("owner") or identity.get("name")
        if not owner:
            raise ProviderError("Could not determine the HuggingFace account name.")
        repo_id = f"{owner}/{spec.name}"

        record = existing or DeploymentRecord(name=spec.name, provider=self.name)
        record.spec.update({
            "config_path": os.path.abspath(spec.config_path),
            "owner": owner,
            "output_annotation_dir": spec.extra.get("output_annotation_dir",
                                                    "annotation_output"),
        })
        record.status = "creating"
        record.provider_ref["repo_id"] = repo_id
        record.url = f"https://{_slug(owner)}-{_slug(spec.name)}.hf.space"
        store.upsert(record)

        backup = None
        if not spec.demo:
            backup = backup_repo_id(owner, spec.name)
            self._ensure_dataset(api, backup)
            record.provider_ref["backup_repo"] = backup
            store.upsert(record)

        self._ensure_space(api, repo_id, private=spec.private)
        store.upsert(record)

        env = self.runtime_env(spec, spec.extra.get("generated"))
        if backup:
            # The in-process CommitScheduler needs a token of its own, and it
            # must be a secret rather than a repo file.
            env["HF_TOKEN"] = self.token
        self._set_secrets(api, repo_id, env)

        self._upload(api, repo_id, spec, bundle, backup=backup)
        record.bundle_sha = bundle.sha256() if bundle else None
        store.upsert(record)

        self.console("Waiting for the Space to build...")
        stage = self._wait_for_stage(api, repo_id)
        record.status = "running" if stage in HEALTHY_STAGES else "unhealthy"
        store.upsert(record)

        if stage not in HEALTHY_STAGES:
            raise ProviderError(
                f"The Space was created but its stage is {stage}. "
                f"{_stage_advice(stage)}\n"
                f"Build logs: https://huggingface.co/spaces/{repo_id}?logs=build")

        self.console(f"Live at {record.url}")
        if backup:
            self.console(f"Annotations back up to "
                         f"https://huggingface.co/datasets/{backup}")
        return record

    def _ensure_dataset(self, api, repo_id: str) -> None:
        try:
            api.create_repo(repo_id, repo_type="dataset", private=True,
                            exist_ok=True)
            self.console(f"Backup dataset ready: {repo_id}")
        except Exception as exc:
            raise ProviderError(
                f"Could not create the backup dataset {repo_id}: {exc}\n"
                "Without it a Space rebuild destroys the annotations. Pass "
                "--demo only if that is acceptable.") from exc

    def _ensure_space(self, api, repo_id: str, *, private: bool) -> None:
        # Deliberately broad. huggingface_hub raises several exception types for
        # an HTTP error and has changed which, so matching on a class would let
        # the 402 through as a bare traceback -- and a paid-plan requirement is
        # the single most likely first failure now that Docker Spaces cost money.
        try:
            api.create_repo(repo_id, repo_type="space", space_sdk="docker",
                            private=private, exist_ok=True)
        except Exception as exc:
            message = str(exc)
            if "402" in message or "payment" in message.lower():
                raise ProviderError(
                    "HuggingFace requires a paid plan to create a Docker Space "
                    "(PRO for a personal account, Team or Enterprise for an "
                    "organization). See https://huggingface.co/pricing\n"
                    "Free alternatives: `--provider render`, or `potato share` "
                    "to expose a local server through a tunnel.") from exc
            raise ProviderError(f"Could not create the Space {repo_id}: {exc}") from exc
        self.console(f"Space ready: {repo_id}")

    def _set_secrets(self, api, repo_id: str, env: Dict[str, str]) -> None:
        """Space secrets, not repo files.

        A Space repo is world-readable unless it is private, and even a private
        one is readable by anyone with access. The session signing key and the
        admin API key must not be committed into it.
        """
        for key, value in sorted(env.items()):
            try:
                api.add_space_secret(repo_id=repo_id, key=key, value=str(value))
            except Exception as exc:
                raise ProviderError(
                    f"Could not set the Space secret {key}: {exc}. Refusing to "
                    "continue, because the alternative is committing it into the "
                    "repository.") from exc
        self.console(f"Set {len(env)} Space secret(s)")

    def _upload(self, api, repo_id: str, spec, bundle, *,
                backup: Optional[str]) -> None:
        import tempfile
        import shutil

        if bundle is None:
            raise ProviderError("No bundle to upload.")

        with tempfile.TemporaryDirectory(prefix="potato-space-") as staging:
            shutil.copytree(bundle.bundle_dir, staging, dirs_exist_ok=True)

            if backup:
                _inject_backup_config(
                    os.path.join(staging, spec.extra.get("config_rel",
                                                         "config.yaml")),
                    backup,
                    spec.extra.get("backup_minutes", DEFAULT_BACKUP_MINUTES))

            for filename, content in space_files(
                    spec, backup_repo=backup,
                    title=spec.extra.get("title"),
                    summary=spec.extra.get("summary", "")).items():
                with open(os.path.join(staging, filename), "w",
                          encoding="utf-8") as handle:
                    handle.write(content)

            self.console("Uploading...")
            api.upload_folder(folder_path=staging, repo_id=repo_id,
                              repo_type="space",
                              commit_message="Deploy with potato deploy")

    def _wait_for_stage(self, api, repo_id: str, timeout: int = 900) -> str:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                runtime = api.get_space_runtime(repo_id)
                stage = runtime.stage
            except Exception:
                stage = "UNKNOWN"
            if stage != last:
                self.console(f"  stage: {stage}")
                last = stage
            if stage in HEALTHY_STAGES:
                return stage
            if stage not in BUILDING_STAGES and stage != "UNKNOWN":
                return stage
            time.sleep(10)
        return last or "UNKNOWN"

    # -- status --------------------------------------------------------

    def status(self, record) -> DeploymentStatus:
        repo_id = record.provider_ref.get("repo_id")
        if not repo_id:
            return DeploymentStatus(state="unknown", detail="no Space recorded")

        api = _hf_api(self.token)
        try:
            runtime = api.get_space_runtime(repo_id)
        except Exception as exc:
            return DeploymentStatus(
                state="absent", url=record.url,
                detail=f"could not read the Space runtime: {exc}")

        raw = getattr(runtime, "raw", {}) or {}
        stage = runtime.stage
        detail = raw.get("errorMessage") or ""
        if stage == "PAUSED":
            detail = (detail + " A paused Space does not wake when a visitor opens "
                              "it; only its owner can restart it.").strip()
        return DeploymentStatus(state=stage.lower(), url=record.url,
                                healthy=stage in HEALTHY_STAGES,
                                detail=detail, raw=raw)

    def logs(self, record, *, lines: int = 200, follow: bool = False) -> Iterator[str]:
        repo_id = record.provider_ref.get("repo_id", "")
        raise ProviderError(
            "HuggingFace's Space log endpoints are undocumented and JWT-gated, so "
            "Potato does not stream them. Read them here:\n"
            f"  https://huggingface.co/spaces/{repo_id}?logs=build\n"
            f"  https://huggingface.co/spaces/{repo_id}?logs=container")

    # -- pull ----------------------------------------------------------

    def pull(self, record, dest: str) -> PullResult:
        """Download the backup Dataset, which is where the data actually is.

        Not from the Space: its filesystem is wiped on rebuild, so whatever is
        on it right now is at best a partial copy of the backup.
        """
        backup = record.provider_ref.get("backup_repo")
        if not backup:
            # A --demo Space has no Dataset, but it may still be running with
            # real annotations on it. Reach the Space itself over HTTPS rather
            # than telling the user there is nothing to be done.
            from potato.deploy.pull import pull_over_https
            from potato.deploy.state import SecretStore

            config_path = record.spec.get("config_path")
            admin_key = (SecretStore(config_path).get(record.name, "admin_api_key")
                         if config_path else None)
            if not admin_key or not record.url:
                raise ProviderError(
                    "This Space was deployed with --demo, so no backup Dataset "
                    "exists, and no admin key was found in .potato/secrets.json "
                    "to read the Space directly. A Space's filesystem is wiped on "
                    "rebuild, so anything collected may already be gone.")
            self.console("No backup Dataset (--demo); reading the Space directly. "
                         "Anything it lost in a rebuild is not recoverable.")
            return pull_over_https(record.url, admin_key, dest,
                                   console=self.console)

        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise ProviderError(
                "Pulling needs huggingface_hub: "
                "pip install 'potato-annotation[huggingface]'") from exc

        os.makedirs(dest, exist_ok=True)
        self.console(f"Downloading {backup}...")
        snapshot_download(repo_id=backup, repo_type="dataset", token=self.token,
                          local_dir=dest)

        result = PullResult(dest=dest)
        for dirpath, dirnames, filenames in os.walk(dest):
            # .cache holds hub bookkeeping, not annotations.
            dirnames[:] = [d for d in dirnames if d != ".cache"]
            for filename in filenames:
                result.files += 1
                try:
                    result.bytes += os.path.getsize(os.path.join(dirpath, filename))
                except OSError:
                    pass
        result.notes.append(f"downloaded from the backup dataset {backup}")
        return result

    # -- destroy -------------------------------------------------------

    def destroy(self, record, *, keep_data: bool = False) -> None:
        api = _hf_api(self.token)
        repo_id = record.provider_ref.get("repo_id")
        if repo_id:
            api.delete_repo(repo_id=repo_id, repo_type="space")
            self.console(f"Deleted Space {repo_id}")

        backup = record.provider_ref.get("backup_repo")
        if not backup:
            return
        if keep_data:
            self.console(f"Kept the backup dataset {backup}")
            return
        # Deleting the Space costs nothing; deleting the annotations is the
        # unrecoverable half, so it is never implied by destroying the host.
        self.console(
            f"Left the backup dataset {backup} in place — it holds the "
            f"annotations. Remove it yourself when you no longer need it:\n"
            f"  https://huggingface.co/datasets/{backup}/settings")


def _inject_backup_config(config_path: str, repo_id: str, minutes: int) -> None:
    """Turn on the in-process backup in the bundled config.

    The token is not written here. It arrives as the HF_TOKEN Space secret, and
    `huggingface_backup.token` is left unset so the server reads it from the
    environment.
    """
    import yaml

    if not os.path.isfile(config_path):
        raise ProviderError(
            f"The bundled config is not where it was expected: {config_path}")
    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    config["huggingface_backup"] = {
        "enabled": True,
        "repo_id": repo_id,
        "repo_type": "dataset",
        "private": True,
        "schedule_minutes": minutes,
    }
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)


def _stage_advice(stage: str) -> str:
    if stage == "PAUSED":
        return ("PAUSED usually means the account is at its concurrent-Space "
                f"limit ({CPU_BASIC_QUOTA} on a free plan). Pause another Space "
                "and restart this one.")
    if stage in ("BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"):
        return "The build or the container failed; the logs say why."
    return "Check the Space in the HuggingFace UI."


def _slug(value: str) -> str:
    """Space subdomains lowercase everything and replace non-alphanumerics."""
    return "".join(c if c.isalnum() else "-" for c in value.lower()).strip("-")
