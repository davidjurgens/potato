"""
Content-addressed cache for transcoded media.

Transcoding a 200MB TIFF stack takes seconds; doing it on every page load makes
the project unusable. The cache key is derived from the source path, its size,
its mtime **and** the transcode parameters, so:

* editing the source file produces a new key and the stale render is never
  served — the failure mode of a path-only key, where a corrected image keeps
  showing the old pixels and looks like a browser cache problem;
* changing the window on a 16-bit image produces a different key, so two
  windows of the same scan coexist rather than fighting over one entry.

Entries live under ``<output_dir>/.media_cache/``. The directory is disposable:
deleting it costs a re-render and nothing else, which is the property that makes
it safe to tell people to delete it.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CACHE_DIRNAME = ".media_cache"

#: Beyond this the cache prunes least-recently-used entries. Transcoded WebP is
#: small, but a video proxy is not, and an unbounded cache on a shared research
#: machine eventually fills the disk for everyone on it.
DEFAULT_MAX_BYTES = 2 * 1024 ** 3  # 2 GiB


def cache_key(source: Path, suffix: str, **params: Any) -> str:
    """
    A key that changes when the source or the transcode parameters change.

    Includes size and mtime, not the file's contents: hashing a multi-gigabyte
    video to decide whether to transcode it would cost more than the transcode.
    """
    try:
        stat = source.stat()
        fingerprint = f"{stat.st_size}:{int(stat.st_mtime)}"
    except OSError:
        fingerprint = "missing"

    parts = [str(source.resolve()), fingerprint, suffix]
    parts.extend(f"{k}={params[k]!r}" for k in sorted(params))
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


def cache_path_for(cache_dir: Path, source: Path, suffix: str,
                   **params: Any) -> Path:
    """Where a given transcode of a given source would live."""
    return Path(cache_dir) / f"{cache_key(source, suffix, **params)}{suffix}"


class MediaCache:
    """A size-bounded directory of transcoded files."""

    def __init__(self, root: str, max_bytes: int = DEFAULT_MAX_BYTES):
        # ABSOLUTE, always. Flask's send_file resolves a relative path against
        # app.root_path, not the process cwd, so a relative cache root made
        # every transcode 404 at serve time under a doubled path -- the file
        # was written where the code expected and looked for somewhere else.
        self.root = (Path(root) / CACHE_DIRNAME).resolve()
        self.max_bytes = max_bytes
        # Two requests for the same uncached image arrive together on the first
        # page load. Without this they both transcode, and on a large file the
        # second write can land on top of a half-written first.
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def ensure_dir(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def path_for(self, source: Path, suffix: str, **params: Any) -> Path:
        return cache_path_for(self.root, Path(source), suffix, **params)

    def lock_for(self, path: Path) -> threading.Lock:
        """One lock per cache entry, so unrelated transcodes stay parallel."""
        key = str(path)
        with self._locks_guard:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    def get(self, source: Path, suffix: str, **params: Any) -> Optional[Path]:
        path = self.path_for(source, suffix, **params)
        if path.exists() and path.stat().st_size > 0:
            # Touch so the LRU prune keeps what is actually being used.
            try:
                os.utime(path, None)
            except OSError:
                pass
            return path
        return None

    def total_bytes(self) -> int:
        if not self.root.exists():
            return 0
        return sum(p.stat().st_size for p in self.root.iterdir() if p.is_file())

    def prune(self) -> int:
        """
        Drop least-recently-used entries until under the size limit.

        Returns the number of files removed. An entry can always be
        regenerated, so eviction is never data loss.
        """
        if not self.root.exists():
            return 0
        files = [p for p in self.root.iterdir() if p.is_file()]
        total = sum(p.stat().st_size for p in files)
        if total <= self.max_bytes:
            return 0

        files.sort(key=lambda p: p.stat().st_atime)
        removed = 0
        for path in files:
            if total <= self.max_bytes:
                break
            try:
                size = path.stat().st_size
                path.unlink()
                total -= size
                removed += 1
            except OSError:
                continue
        if removed:
            logger.info("Media cache pruned %d file(s) to stay under %d bytes",
                        removed, self.max_bytes)
        return removed

    def clear(self) -> int:
        if not self.root.exists():
            return 0
        removed = 0
        for path in self.root.iterdir():
            if path.is_file():
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
        return removed


_cache: Optional[MediaCache] = None
_cache_guard = threading.Lock()


def get_media_cache(output_dir: Optional[str] = None,
                    max_bytes: int = DEFAULT_MAX_BYTES) -> MediaCache:
    """
    The process-wide cache, created on first use.

    Follows the singleton pattern the state managers use, so the cache location
    is decided once from config rather than being re-derived per request.
    """
    global _cache
    with _cache_guard:
        if _cache is None or (output_dir and str(_cache.root.parent) != output_dir):
            _cache = MediaCache(output_dir or ".", max_bytes=max_bytes)
        return _cache


def clear_media_cache() -> None:
    """Drop the singleton. For tests."""
    global _cache
    with _cache_guard:
        _cache = None
