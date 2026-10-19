"""Backup sink: a private HuggingFace Dataset repo.

The annotation directory mirrors to the repo root, which is the layout the
original ``huggingface_backup`` always used, so an existing backup keeps
working and a restore reads it. Database snapshots go under ``_databases/``.
With ``responses: true`` the sink also keeps ``responses/*.jsonl`` and a
dataset card at the root, so ``datasets.load_dataset`` reads the answers
(see hub_responses.py).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any, Dict, List

from potato.server_utils.backup import (
    REMOTE_BUNDLE_DIR,
    SNAPSHOT_DIRNAME,
    REMOTE_DB_DIR,
    output_dir,
    restorable,
    safe_join,
    snapshot_dir,
)
from potato.server_utils.backup import task_dir
from potato.server_utils.backup.hub_responses import is_export_path

#: Where the responses export is staged inside task_dir. Not inside the
#: snapshot directory, whose own scheduler would upload it a second time
#: under _databases/ and restore would bring it back.
HUB_EXPORT_DIRNAME = ".potato-hub"

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
        self.responses = bool(spec.get("responses", False))
        self._schedulers: List[Any] = []

    def _hub_dir(self) -> str:
        return os.path.join(task_dir(self.config), HUB_EXPORT_DIRNAME)

    def _write_responses(self) -> None:
        if not self.responses:
            return
        from potato.server_utils.backup.hub_responses import write_hub_export
        try:
            write_hub_export(self.config, self._hub_dir(), self.repo_id)
        except Exception as exc:
            logger.error("Could not write the annotators' responses for %s: %s",
                         self.describe(), exc)

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
        # An output directory that is the task directory itself (".") would
        # otherwise upload the snapshot staging area and the responses export
        # a second time from here.
        self._schedulers.append(CommitScheduler(
            folder_path=output_dir(self.config),
            ignore_patterns=[f"{SNAPSHOT_DIRNAME}/**", f"{HUB_EXPORT_DIRNAME}/**"],
            **common))
        # Snapshots are written to a .partial file and renamed; a commit that
        # caught one mid-write would upload half a file.
        self._schedulers.append(CommitScheduler(folder_path=snapshot_dir(self.config),
                                                path_in_repo=REMOTE_DB_DIR,
                                                ignore_patterns=["*.partial"], **common))
        if self.responses:
            if not self.private:
                logger.warning(
                    "The backup to %s is public and writes every annotator's id "
                    "and answers there as a dataset (responses: true); anyone "
                    "can read them", self.repo_id)
            self._write_responses()
            self._schedulers.append(CommitScheduler(folder_path=self._hub_dir(),
                                                    ignore_patterns=["*.partial"],
                                                    **common))
        logger.info("Backup: %s -> %s every %s minute(s)",
                    output_dir(self.config), self.describe(), schedule_minutes)
        return True

    def tick(self) -> None:
        """CommitScheduler uploads on its own thread; this refreshes the
        responses export it uploads."""
        self._write_responses()

    def flush(self) -> None:
        self._write_responses()
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
    # The responses export is derived from the annotators' state, which is
    # restored. Only its own files are skipped: a user folder may share its
    # directory's name.
    if parts[0] == REMOTE_BUNDLE_DIR or is_export_path(relative) \
            or relative in _NOT_DATA or not restorable(relative):
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
