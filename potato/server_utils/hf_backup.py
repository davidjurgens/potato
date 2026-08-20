"""Continuous backup of annotation output to a HuggingFace Dataset repo.

For a host whose filesystem does not survive a restart — a Space, a free-tier
container, anything that redeploys in place — this is the only thing standing
between a study and losing its data. It is offered on every provider, not only
HuggingFace, because the failure it guards against is not HuggingFace-specific.

Lives in its own module because it has to run on *both* startup paths. It used
to sit inside ``run_server()``, which only ``potato start`` reaches; every
container starts through the ``create_app`` WSGI factory instead, so the backup
had never once run on a deployed host — exactly where it is load-bearing.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULE_MINUTES = 5

# Module-level so a second call is a no-op rather than a second uploader racing
# the first over the same files.
_scheduler = None


def get_scheduler():
    """The active CommitScheduler, or None. Exposed for tests and /admin."""
    return _scheduler


def reset_scheduler() -> None:
    """Drop the reference. Tests only — does not stop a running thread."""
    global _scheduler
    _scheduler = None


def resolve_token(backup_config: Dict[str, Any]) -> Optional[str]:
    return (backup_config.get("token")
            or os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGING_FACE_HUB_TOKEN"))


def backup_folder(config: Dict[str, Any]) -> str:
    """The directory whose contents get mirrored."""
    return os.path.join(config.get("task_dir", "."),
                        config.get("output_annotation_dir", "annotation_output"))


def init_backup(config: Dict[str, Any]):
    """Start the uploader if ``huggingface_backup.enabled`` is set.

    Never raises. A misconfigured backup must not stop a server from serving —
    losing the backup is bad, refusing to run the study is worse — so every
    failure is logged at a level that will be noticed and the server continues.
    """
    global _scheduler

    backup_config = config.get("huggingface_backup") or {}
    if not backup_config.get("enabled", False):
        return None

    if _scheduler is not None:
        logger.debug("HuggingFace backup already running; not starting a second")
        return _scheduler

    repo_id = backup_config.get("repo_id")
    if not repo_id:
        logger.error("huggingface_backup.enabled is true but repo_id is missing; "
                     "annotations will NOT be backed up")
        return None

    token = resolve_token(backup_config)
    if not token:
        logger.error("huggingface_backup is enabled for %s but no token was found "
                     "(huggingface_backup.token or HF_TOKEN); annotations will NOT "
                     "be backed up", repo_id)
        return None

    folder = backup_folder(config)
    # CommitScheduler watches a directory; if it does not exist yet the first
    # commit finds nothing and the scheduler quietly does nothing thereafter.
    os.makedirs(folder, exist_ok=True)

    every = backup_config.get("schedule_minutes", DEFAULT_SCHEDULE_MINUTES)

    try:
        from huggingface_hub import CommitScheduler
    except ImportError:
        logger.error("huggingface_backup is enabled but huggingface_hub is not "
                     "installed, so annotations will NOT be backed up. Install "
                     "with: pip install 'potato-annotation[huggingface]'")
        return None

    # A dataset repo, which is what the documentation has always described.
    # The original call omitted repo_type entirely, so it defaulted to "model"
    # and the code contradicted its own docs. Overridable for anyone who built
    # against the accidental behaviour.
    repo_type = backup_config.get("repo_type", "dataset")

    try:
        _scheduler = CommitScheduler(
            repo_id=repo_id,
            repo_type=repo_type,
            folder_path=folder,
            token=token,
            private=backup_config.get("private", True),
            every=every,
        )
    except Exception as exc:
        logger.error("Could not start the HuggingFace backup to %s, so annotations "
                     "will NOT be backed up: %s", repo_id, exc)
        return None

    logger.info("HuggingFace backup: %s -> %s (%s) every %s minute(s)",
                folder, repo_id, repo_type, every)
    return _scheduler
