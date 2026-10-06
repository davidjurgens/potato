"""Continuous off-host backup of collected data, and restore on boot.

Hosts with an ephemeral filesystem (Heroku, Render's free tier, every
HuggingFace Space) lose everything the server wrote whenever the process
restarts. A backup that only uploads is not enough there: the server comes
back empty, a returning annotator gets a fresh ``user_state.json``, and the
next sync overwrites the copy that held their earlier work. So the sinks here
do both halves: mirror on a schedule, and restore into an empty task before
the state managers load.

What travels:

* the annotation output directory, file for file;
* ``.backup`` snapshots of ``project.sqlite`` and ``datasets.sqlite``, written
  to ``<task_dir>/.potato-backup/`` and mirrored under ``_databases/``. The
  live files run in WAL mode with a writer attached, so copying them directly
  yields a database missing recent work.

Configuration::

    backup:
      schedule_minutes: 5
      restore_on_boot: true
      sinks:
        - type: huggingface
          repo_id: me/my-task-annotations
        - type: s3
          bucket: my-bucket
          prefix: potato/my-task
          region: us-east-1
          endpoint_url: https://<account>.r2.cloudflarestorage.com   # optional

The older ``huggingface_backup:`` block is read as a single huggingface sink,
with ``restore_on_boot`` off so an existing deployment keeps its behaviour.

Nothing here raises into the server. A broken backup logs at ERROR and the
study keeps running: losing the backup is bad, refusing to collect data is
worse.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULE_MINUTES = 5

#: Where database snapshots are staged inside task_dir before upload.
SNAPSHOT_DIRNAME = ".potato-backup"
#: Remote subdirectory holding the snapshots, on every sink.
REMOTE_DB_DIR = "_databases"
#: Remote subdirectory holding deploy bundles; never restored as data.
REMOTE_BUNDLE_DIR = "_bundle"

_lock = threading.Lock()
_started: List[Any] = []
_snapshot_thread: Optional[threading.Thread] = None
_stop = threading.Event()


@dataclass
class BackupSettings:
    sinks: List[Dict[str, Any]] = field(default_factory=list)
    schedule_minutes: float = DEFAULT_SCHEDULE_MINUTES
    restore_on_boot: bool = True

    @property
    def enabled(self) -> bool:
        return bool(self.sinks)


def resolve_settings(config: Dict[str, Any]) -> BackupSettings:
    """Read ``backup:``, falling back to the legacy ``huggingface_backup:``."""
    block = config.get("backup")
    if isinstance(block, dict) and block.get("enabled", True):
        sinks = [dict(s) for s in (block.get("sinks") or []) if isinstance(s, dict)]
        return BackupSettings(
            sinks=sinks,
            schedule_minutes=block.get("schedule_minutes", DEFAULT_SCHEDULE_MINUTES),
            restore_on_boot=bool(block.get("restore_on_boot", True)),
        )

    legacy = config.get("huggingface_backup")
    if isinstance(legacy, dict) and legacy.get("enabled", False):
        sink = {"type": "huggingface"}
        for key in ("repo_id", "repo_type", "private", "token"):
            if key in legacy:
                sink[key] = legacy[key]
        return BackupSettings(
            sinks=[sink],
            schedule_minutes=legacy.get("schedule_minutes", DEFAULT_SCHEDULE_MINUTES),
            restore_on_boot=bool(legacy.get("restore_on_boot", False)),
        )
    return BackupSettings()


def task_dir(config: Dict[str, Any]) -> str:
    return config.get("task_dir", ".") or "."


def output_dir(config: Dict[str, Any]) -> str:
    """The directory load_user_data() reads, resolved exactly as it does."""
    return config.get("output_annotation_dir") or "annotation_output"


def snapshot_dir(config: Dict[str, Any]) -> str:
    return os.path.join(task_dir(config), SNAPSHOT_DIRNAME)


def safe_join(root: str, parts) -> Optional[str]:
    """Join remote path parts under root, or None if they would escape it.

    Restore writes paths that came from a bucket or repo, which is input.
    """
    if any(p in ("", ".", "..") or os.sep in p or "/" in p for p in parts):
        return None
    target = os.path.realpath(os.path.join(root, *parts))
    base = os.path.realpath(root)
    if target != base and not target.startswith(base + os.sep):
        return None
    return target


def _make_sink(spec: Dict[str, Any], config: Dict[str, Any]):
    kind = str(spec.get("type", "")).lower()
    if kind in ("huggingface", "hf"):
        from potato.server_utils.backup.hf_sink import HuggingFaceSink
        return HuggingFaceSink(spec, config)
    if kind == "s3":
        from potato.server_utils.backup.s3_sink import S3Sink
        return S3Sink(spec, config)
    logger.error("backup sink type %r is not supported (use huggingface or s3); "
                 "it will NOT back anything up", spec.get("type"))
    return None


def snapshot_databases(config: Dict[str, Any]) -> List[str]:
    """Write ``.backup`` copies of the project databases into the staging dir.

    Each snapshot lands in a temporary file and is renamed into place, so a
    sink that uploads concurrently never sees a half-written database.
    """
    from potato.server_utils.data_archive import DATABASES, snapshot_sqlite

    written = []
    staging = snapshot_dir(config)
    for name in DATABASES:
        source = os.path.join(task_dir(config), name)
        if not os.path.isfile(source):
            continue
        os.makedirs(staging, exist_ok=True)
        target = os.path.join(staging, name)
        partial = target + ".partial"
        try:
            if snapshot_sqlite(source, partial):
                os.replace(partial, target)
                written.append(target)
        except Exception as exc:
            logger.error("Could not snapshot %s for backup: %s", source, exc)
            try:
                os.remove(partial)
            except OSError:
                pass
    return written


#: The file whose presence means an annotator's work exists locally.
USER_STATE_FILE = "user_state.json"


def output_is_empty(config: Dict[str, Any]) -> bool:
    """True when no annotator state exists locally yet.

    Judged by user_state.json rather than by any file: the server writes
    potato.log, user_config.json and pocket/ into the output directory during
    startup, before restore runs, so "no files" was never true and an earlier
    version never restored anything.
    """
    root = output_dir(config)
    if not os.path.isdir(root):
        return True
    for _dirpath, _dirnames, filenames in os.walk(root):
        if USER_STATE_FILE in filenames:
            return False
    return True


def restorable(relative_path: str) -> bool:
    """Whether a backed-up file should be written back on restore.

    Logs are open for append by the running server; overwriting one in place
    corrupts it and gains nothing.
    """
    return not relative_path.endswith(".log")


def restore_on_boot(config: Dict[str, Any]) -> bool:
    """Pull the latest backup into an empty task. Returns True if it did.

    Runs before the state managers read the output directory. It never
    overwrites local data: a task that already holds annotations is the
    authoritative copy, and is left alone.
    """
    settings = resolve_settings(config)
    if not settings.enabled or not settings.restore_on_boot:
        return False
    if not output_is_empty(config):
        logger.info("Backup restore skipped: %s already holds data",
                    output_dir(config))
        return False

    for spec in settings.sinks:
        sink = _make_sink(spec, config)
        if sink is None:
            continue
        try:
            restored = sink.restore(output_dir(config), snapshot_dir(config))
        except Exception as exc:
            logger.error("Restoring from the %s backup failed: %s",
                         sink.describe(), exc)
            continue
        if restored:
            _install_restored_databases(config)
            logger.warning(
                "RESTORED %d file(s) from the %s backup into an empty task. "
                "This is expected after a restart on a host without a "
                "persistent disk.", restored, sink.describe())
            return True
    logger.info("Backup restore: no backed-up data found")
    return False


def _install_restored_databases(config: Dict[str, Any]) -> None:
    """Move restored snapshots to their live paths, never over a live file."""
    staging = snapshot_dir(config)
    if not os.path.isdir(staging):
        return
    for name in os.listdir(staging):
        if not name.endswith(".sqlite"):
            continue
        live = os.path.join(task_dir(config), name)
        if os.path.exists(live):
            continue
        shutil.copy2(os.path.join(staging, name), live)
        logger.info("Restored %s from backup", name)


def start_backups(config: Dict[str, Any]) -> List[Any]:
    """Start every configured sink. Idempotent; never raises."""
    global _snapshot_thread

    settings = resolve_settings(config)
    if not settings.enabled:
        return []

    with _lock:
        if _started:
            logger.debug("Backups already running; not starting a second set")
            return list(_started)

        os.makedirs(output_dir(config), exist_ok=True)
        # The HF scheduler watching the snapshot directory gives up quietly on
        # a path that does not exist yet.
        os.makedirs(snapshot_dir(config), exist_ok=True)
        snapshot_databases(config)

        for spec in settings.sinks:
            sink = _make_sink(spec, config)
            if sink is None:
                continue
            try:
                if sink.start(settings.schedule_minutes):
                    _started.append(sink)
            except Exception as exc:
                logger.error("Could not start the %s backup, so annotations "
                             "will NOT be backed up there: %s", sink.describe(), exc)

        if _started and _snapshot_thread is None:
            _stop.clear()
            interval = max(float(settings.schedule_minutes), 0.1) * 60
            _snapshot_thread = threading.Thread(
                target=_snapshot_loop, args=(config, interval),
                name="potato-backup-snapshots", daemon=True)
            _snapshot_thread.start()
        return list(_started)


def _snapshot_loop(config: Dict[str, Any], interval: float) -> None:
    while not _stop.wait(interval):
        snapshot_databases(config)
        for sink in list(_started):
            try:
                sink.tick()
            except Exception as exc:
                logger.error("The %s backup failed this cycle: %s",
                             sink.describe(), exc)


def flush() -> None:
    """Snapshot and push once, synchronously. For shutdown and tests."""
    for sink in list(_started):
        try:
            sink.flush()
        except Exception as exc:
            logger.error("Flushing the %s backup failed: %s", sink.describe(), exc)


def running_sinks() -> List[Any]:
    return list(_started)


def reset() -> None:
    """Stop the snapshot loop and forget started sinks. Tests only."""
    global _snapshot_thread
    _stop.set()
    if _snapshot_thread is not None:
        _snapshot_thread.join(timeout=5)
    _snapshot_thread = None
    for sink in list(_started):
        try:
            sink.stop()
        except Exception:
            pass
    _started.clear()
