"""Backup sink: a private HuggingFace Dataset repo.

The annotation directory mirrors to the repo root, which is the layout the
original ``huggingface_backup`` always used, so an existing backup keeps
working and a restore reads it. Database snapshots go under ``_databases/``.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any, Dict, List

from potato.server_utils.backup import (
    REMOTE_BUNDLE_DIR,
    REMOTE_DB_DIR,
    output_dir,
    restorable,
    safe_join,
    snapshot_dir,
)

logger = logging.getLogger(__name__)

# Repo files that are not collected data.
_NOT_DATA = (".gitattributes", "README.md")


def _token(spec: Dict[str, Any]):
    return (spec.get("token")
            or os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGING_FACE_HUB_TOKEN"))


class HuggingFaceSink:
    def __init__(self, spec: Dict[str, Any], config: Dict[str, Any]):
        self.spec = spec
        self.config = config
        self.repo_id = spec.get("repo_id")
        self.repo_type = spec.get("repo_type", "dataset")
        self.private = spec.get("private", True)
        self._schedulers: List[Any] = []

    def describe(self) -> str:
        return f"HuggingFace dataset {self.repo_id or '(no repo_id)'}"

    def _check(self) -> bool:
        if not self.repo_id:
            logger.error("A huggingface backup sink has no repo_id; annotations "
                         "will NOT be backed up there")
            return False
        if not _token(self.spec):
            logger.error("The huggingface backup to %s has no token (token or "
                         "HF_TOKEN); annotations will NOT be backed up there",
                         self.repo_id)
            return False
        return True

    def start(self, schedule_minutes: float) -> bool:
        if not self._check():
            return False
        try:
            from huggingface_hub import CommitScheduler
        except ImportError:
            logger.error("The huggingface backup is configured but huggingface_hub "
                         "is not installed, so annotations will NOT be backed up. "
                         "Install with: pip install 'potato-annotation[hosting]'")
            return False

        common = dict(repo_id=self.repo_id, repo_type=self.repo_type,
                      token=_token(self.spec), private=self.private,
                      every=schedule_minutes)
        self._schedulers.append(CommitScheduler(folder_path=output_dir(self.config),
                                                **common))
        self._schedulers.append(CommitScheduler(folder_path=snapshot_dir(self.config),
                                                path_in_repo=REMOTE_DB_DIR, **common))
        logger.info("Backup: %s -> %s every %s minute(s)",
                    output_dir(self.config), self.describe(), schedule_minutes)
        return True

    def tick(self) -> None:
        """CommitScheduler runs its own thread; nothing to do per cycle."""

    def flush(self) -> None:
        for scheduler in self._schedulers:
            scheduler.trigger().result()

    def stop(self) -> None:
        for scheduler in self._schedulers:
            try:
                scheduler.stop()
            except Exception:
                pass

    def restore(self, out_dir: str, snap_dir: str) -> int:
        if not self._check():
            return 0
        from huggingface_hub import snapshot_download

        restored = 0
        with tempfile.TemporaryDirectory(prefix="potato-restore-") as staging:
            snapshot_download(repo_id=self.repo_id, repo_type=self.repo_type,
                              token=_token(self.spec), local_dir=staging)
            for dirpath, dirnames, filenames in os.walk(staging):
                dirnames[:] = [d for d in dirnames if d != ".cache"]
                for filename in filenames:
                    source = os.path.join(dirpath, filename)
                    relative = os.path.relpath(source, staging)
                    restored += _place(relative, source, out_dir, snap_dir)
        return restored


def _place(relative: str, source: str, out_dir: str, snap_dir: str) -> int:
    """Copy one remote file to where it belongs. Returns 1 if it was data."""
    parts = relative.replace(os.sep, "/").split("/")
    if parts[0] == REMOTE_BUNDLE_DIR or relative in _NOT_DATA \
            or not restorable(relative):
        return 0
    if parts[0] == REMOTE_DB_DIR:
        target = safe_join(snap_dir, parts[1:])
    else:
        target = safe_join(out_dir, parts)
    if target is None:
        logger.warning("Skipping backup entry outside the task: %s", relative)
        return 0
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy2(source, target)
    return 0 if parts[-1] == ".gitkeep" else 1
