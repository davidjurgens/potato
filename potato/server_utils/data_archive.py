"""Package a running task's collected data into a downloadable archive.

The server side of `potato deploy pull`. SSH is the better transport where it
exists, but it does not exist on a Space, a Render service, or anything
serverless — and those are exactly the hosts whose filesystem does not survive a
restart. This gives every deployment one way to get its data back over plain
HTTPS, using the admin API key `potato deploy` already holds.

What goes in is what cannot be recreated: the annotation output directory,
`project.sqlite` (memos, the codebook, cases, typing sessions, the review
workflow) and `datasets.sqlite`. What stays out is anything regenerable and
anything that is a credential.

The SQLite databases are snapshotted through the connection rather than copied.
They run in WAL mode with a live writer, so the file on disk is not a complete
database on its own — the `-wal` sidecar holds committed pages it does not have.
Copying it yields something corrupt or stale, and nothing says so at the time.
"""

from __future__ import annotations

import io
import logging
import os
import sqlite3
import tarfile
import tempfile
import time
from typing import Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Databases worth carrying: neither can be regenerated from the annotations.
DATABASES = ("project.sqlite", "datasets.sqlite")

# Never archived. `.item_cache.sqlite` is rebuilt from the data files on demand,
# and `admin_api_key.txt` is the credential guarding this very endpoint.
EXCLUDED_NAMES = frozenset({
    ".item_cache.sqlite",
    ".item_cache.sqlite-wal",
    ".item_cache.sqlite-shm",
    "admin_api_key.txt",
    ".DS_Store",
})
EXCLUDED_SUFFIXES = (".pyc",)
EXCLUDED_DIRS = frozenset({"__pycache__", ".git", ".potato", "exports"})


def snapshot_sqlite(source_path: str, destination_path: str) -> bool:
    """Copy a live SQLite database safely, via the backup API.

    Returns False when the source does not exist, which is normal: a task with
    no codebook and no memos has no project.sqlite.

    Raises on a real failure rather than falling back to a file copy. A silent
    fallback here produces a database that looks fine and is missing recent
    work, discovered weeks later with no way back.
    """
    if not os.path.isfile(source_path):
        return False

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30)
    try:
        destination = sqlite3.connect(destination_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return True


def _skip(name: str) -> bool:
    return name in EXCLUDED_NAMES or name.endswith(EXCLUDED_SUFFIXES)


def collect_entries(output_dir: str, task_dir: str) -> List[Tuple[str, str]]:
    """(archive_name, absolute_path) for every real file to include.

    Databases are not listed here — they need snapshotting first and are added
    by ``build_archive``.
    """
    entries: List[Tuple[str, str]] = []
    if os.path.isdir(output_dir):
        base = os.path.basename(os.path.normpath(output_dir)) or "annotation_output"
        for dirpath, dirnames, filenames in os.walk(output_dir):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
            for filename in sorted(filenames):
                if _skip(filename):
                    continue
                absolute = os.path.join(dirpath, filename)
                relative = os.path.relpath(absolute, output_dir)
                entries.append((os.path.join(base, relative), absolute))
    return entries


def archive_manifest(output_dir: str, task_dir: str) -> Dict:
    """What an archive would contain, without building it.

    Lets a client show a size before downloading, and gives the pull command
    something to check its result against.
    """
    entries = collect_entries(output_dir, task_dir)
    total = 0
    for _name, path in entries:
        try:
            total += os.path.getsize(path)
        except OSError:
            pass

    databases = []
    for database in DATABASES:
        path = os.path.join(task_dir, database)
        if os.path.isfile(path):
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            databases.append({"name": database, "bytes": size})
            total += size

    return {
        "files": len(entries) + len(databases),
        "bytes": total,
        "databases": databases,
        "excluded": sorted(EXCLUDED_NAMES),
    }


def build_archive(output_dir: str, task_dir: str, destination) -> Dict:
    """Write a gzipped tar of the collected data to an open binary file object.

    Returns a summary. Databases are snapshotted into a temporary directory
    first, so what lands in the archive is a consistent copy rather than a file
    being written to.
    """
    written: List[str] = []
    skipped: List[str] = []

    with tempfile.TemporaryDirectory(prefix="potato-archive-") as staging:
        snapshots = []
        for database in DATABASES:
            source = os.path.join(task_dir, database)
            target = os.path.join(staging, database)
            try:
                if snapshot_sqlite(source, target):
                    snapshots.append((database, target))
                else:
                    skipped.append(f"{database} (not present)")
            except sqlite3.Error as exc:
                # Report rather than raise: a locked database must not cost the
                # caller the annotation files, which are the larger loss.
                logger.error("Could not snapshot %s: %s", source, exc)
                skipped.append(f"{database} (snapshot failed: {exc})")

        with tarfile.open(fileobj=destination, mode="w|gz") as archive:
            for name, path in collect_entries(output_dir, task_dir):
                try:
                    archive.add(path, arcname=name)
                    written.append(name)
                except OSError as exc:
                    logger.warning("Skipping %s: %s", path, exc)
                    skipped.append(f"{name} ({exc})")
            for name, path in snapshots:
                archive.add(path, arcname=name)
                written.append(name)

    return {"files": len(written), "written": written, "skipped": skipped}


def stream_archive(output_dir: str, task_dir: str,
                   chunk_size: int = 1024 * 256) -> Iterator[bytes]:
    """Yield the archive in chunks.

    Built to a spooled temporary file rather than assembled in memory: a study
    with media or a long history produces an archive larger than a container's
    RAM allowance, and holding it would kill the very server being backed up.
    """
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    try:
        build_archive(output_dir, task_dir, spool)
        spool.seek(0)
        while True:
            chunk = spool.read(chunk_size)
            if not chunk:
                return
            yield chunk
    finally:
        spool.close()


def archive_filename(task_name: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in (task_name or "potato").lower())
    slug = "-".join(part for part in slug.split("-") if part) or "potato"
    return f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
