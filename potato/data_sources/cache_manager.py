"""
Cache manager for remote data sources.

This module provides caching functionality for downloaded remote files,
including TTL-based expiration, ETag support for HTTP caching, and
thread-safe operations.
"""

import hashlib
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """
    Represents a cached file entry.

    Attributes:
        source_id: Identifier of the data source
        source_url: Original URL or path
        cache_path: Local path to cached file
        etag: HTTP ETag for cache validation (optional)
        last_modified: HTTP Last-Modified header value (optional)
        created_at: Unix timestamp when cached
        expires_at: Unix timestamp when cache expires
        file_size: Size of cached file in bytes
        content_type: MIME type of cached content
        metadata: Additional metadata about the cached content
    """
    source_id: str
    source_url: str
    cache_path: str
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    file_size: int = 0
    content_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def is_valid(self) -> bool:
        """Check if the cached file exists and hasn't expired."""
        if not os.path.exists(self.cache_path):
            return False
        if self.is_expired():
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "cache_path": self.cache_path,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "file_size": self.file_size,
            "content_type": self.content_type,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheEntry":
        """Create from dictionary."""
        return cls(
            source_id=data["source_id"],
            source_url=data["source_url"],
            cache_path=data["cache_path"],
            etag=data.get("etag"),
            last_modified=data.get("last_modified"),
            created_at=data.get("created_at", time.time()),
            expires_at=data.get("expires_at"),
            file_size=data.get("file_size", 0),
            content_type=data.get("content_type"),
            metadata=data.get("metadata", {}),
        )


class CacheManager:
    """
    Manages a local file cache for remote data sources.

    This class provides thread-safe caching of downloaded files with:
    - TTL-based expiration
    - ETag and Last-Modified support for conditional requests
    - Automatic cache directory management
    - Persistent cache index for restart recovery

    Attributes:
        cache_dir: Path to the cache directory
        ttl_seconds: Default time-to-live for cached files
        max_size_mb: Maximum total cache size in megabytes
    """

    DEFAULT_TTL = 3600  # 1 hour
    DEFAULT_MAX_SIZE_MB = 500
    INDEX_FILENAME = "_cache_index.json"

    def __init__(
        self,
        cache_dir: str,
        ttl_seconds: int = DEFAULT_TTL,
        max_size_mb: int = DEFAULT_MAX_SIZE_MB
    ):
        """
        Initialize the cache manager.

        Args:
            cache_dir: Directory to store cached files
            ttl_seconds: Default TTL for cached entries
            max_size_mb: Maximum total cache size
        """
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self.max_size_bytes = max_size_mb * 1024 * 1024

        self._entries: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()

        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Load existing cache index
        self._load_index()

        logger.info(
            f"CacheManager initialized: dir={cache_dir}, "
            f"ttl={ttl_seconds}s, max_size={max_size_mb}MB"
        )

    def _load_index(self) -> None:
        """Load the cache index from disk."""
        index_path = self.cache_dir / self.INDEX_FILENAME
        if not index_path.exists():
            return

        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for entry_data in data.get("entries", []):
                entry = CacheEntry.from_dict(entry_data)
                # Only load if cached file still exists
                if os.path.exists(entry.cache_path):
                    self._entries[entry.source_id] = entry
                else:
                    logger.debug(f"Cached file missing, skipping: {entry.cache_path}")

            logger.debug(f"Loaded {len(self._entries)} cache entries from index")

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load cache index: {e}")
            self._entries = {}

    def _save_index(self) -> None:
        """Save the cache index to disk."""
        index_path = self.cache_dir / self.INDEX_FILENAME

        data = {
            "version": 1,
            "entries": [entry.to_dict() for entry in self._entries.values()]
        }

        try:
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save cache index: {e}")

    def _generate_cache_key(self, source_id: str, url: str) -> str:
        """Generate a unique cache key for a source."""
        hash_input = f"{source_id}:{url}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:32]

    def _generate_cache_path(self, source_id: str, url: str, extension: str = "") -> Path:
        """Generate the cache file path for a source."""
        cache_key = self._generate_cache_key(source_id, url)
        filename = f"{cache_key}{extension}"
        return self.cache_dir / filename

    def get(self, source_id: str) -> Optional[CacheEntry]:
        """
        Get a cache entry by source ID.

        Args:
            source_id: The source identifier

        Returns:
            CacheEntry if found and valid, None otherwise
        """
        with self._lock:
            entry = self._entries.get(source_id)
            if entry and entry.is_valid():
                return entry
            return None

    def get_if_valid(
        self,
        source_id: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None
    ) -> Optional[CacheEntry]:
        """
        Get a cache entry if it's still valid.

        For HTTP sources, this checks ETag and Last-Modified headers
        for cache validation.

        Args:
            source_id: The source identifier
            etag: Current ETag from server (for validation)
            last_modified: Current Last-Modified from server

        Returns:
            CacheEntry if cache hit, None if miss or stale
        """
        with self._lock:
            entry = self._entries.get(source_id)
            if not entry:
                return None

            # Check if file exists
            if not os.path.exists(entry.cache_path):
                del self._entries[source_id]
                self._save_index()
                return None

            # Check TTL expiration
            if entry.is_expired():
                return None

            # If ETag provided, validate it matches
            if etag and entry.etag and entry.etag != etag:
                return None

            # If Last-Modified provided, validate it
            if last_modified and entry.last_modified and entry.last_modified != last_modified:
                return None

            return entry

    def put(
        self,
        source_id: str,
        source_url: str,
        data: bytes,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        content_type: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> CacheEntry:
        """
        Store data in the cache.

        Args:
            source_id: Unique identifier for this source
            source_url: Original URL of the data
            data: The data to cache
            etag: HTTP ETag header value
            last_modified: HTTP Last-Modified header value
            content_type: MIME type of the content
            ttl_seconds: Time-to-live (uses default if not specified)
            metadata: Additional metadata to store

        Returns:
            The created CacheEntry
        """
        # Determine file extension from content type
        extension = self._extension_from_content_type(content_type, source_url)
        cache_path = self._generate_cache_path(source_id, source_url, extension)

        with self._lock:
            # Write data to cache file
            try:
                with open(cache_path, 'wb') as f:
                    f.write(data)
            except IOError as e:
                logger.error(f"Failed to write cache file: {e}")
                raise

            # Create cache entry
            ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
            entry = CacheEntry(
                source_id=source_id,
                source_url=source_url,
                cache_path=str(cache_path),
                etag=etag,
                last_modified=last_modified,
                created_at=time.time(),
                expires_at=time.time() + ttl if ttl > 0 else None,
                file_size=len(data),
                content_type=content_type,
                metadata=metadata or {},
            )

            self._entries[source_id] = entry
            self._save_index()

            # Check cache size and cleanup if needed
            self._enforce_size_limit()

            logger.debug(f"Cached {len(data)} bytes for {source_id}")
            return entry

    def put_file(
        self,
        source_id: str,
        source_url: str,
        file_path: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        content_type: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        move: bool = False
    ) -> CacheEntry:
        """
        Store a file in the cache.

        Args:
            source_id: Unique identifier for this source
            source_url: Original URL of the data
            file_path: Path to the file to cache
            etag: HTTP ETag header value
            last_modified: HTTP Last-Modified header value
            content_type: MIME type of the content
            ttl_seconds: Time-to-live
            metadata: Additional metadata
            move: If True, move the file instead of copying

        Returns:
            The created CacheEntry
        """
        extension = self._extension_from_content_type(content_type, source_url)
        cache_path = self._generate_cache_path(source_id, source_url, extension)

        with self._lock:
            try:
                if move:
                    shutil.move(file_path, cache_path)
                else:
                    shutil.copy2(file_path, cache_path)
            except IOError as e:
                logger.error(f"Failed to cache file: {e}")
                raise

            file_size = os.path.getsize(cache_path)

            ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
            entry = CacheEntry(
                source_id=source_id,
                source_url=source_url,
                cache_path=str(cache_path),
                etag=etag,
                last_modified=last_modified,
                created_at=time.time(),
                expires_at=time.time() + ttl if ttl > 0 else None,
                file_size=file_size,
                content_type=content_type,
                metadata=metadata or {},
            )

            self._entries[source_id] = entry
            self._save_index()
            self._enforce_size_limit()

            return entry

    def invalidate(self, source_id: str) -> bool:
        """
        Invalidate (remove) a cache entry.

        Args:
            source_id: The source identifier

        Returns:
            True if entry was removed, False if not found
        """
        with self._lock:
            entry = self._entries.pop(source_id, None)
            if entry:
                try:
                    if os.path.exists(entry.cache_path):
                        os.remove(entry.cache_path)
                except IOError as e:
                    logger.warning(f"Failed to remove cache file: {e}")

                self._save_index()
                return True
            return False

    def clear(self) -> int:
        """
        Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._entries)

            for entry in self._entries.values():
                try:
                    if os.path.exists(entry.cache_path):
                        os.remove(entry.cache_path)
                except IOError as e:
                    logger.warning(f"Failed to remove cache file: {e}")

            self._entries.clear()
            self._save_index()

            logger.info(f"Cleared {count} cache entries")
            return count

    def cleanup_expired(self) -> int:
        """
        Remove all expired cache entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            expired = [
                source_id
                for source_id, entry in self._entries.items()
                if entry.is_expired()
            ]

            for source_id in expired:
                self.invalidate(source_id)

            if expired:
                logger.debug(f"Cleaned up {len(expired)} expired cache entries")

            return len(expired)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            total_size = sum(e.file_size for e in self._entries.values())
            expired_count = sum(1 for e in self._entries.values() if e.is_expired())

            return {
                "cache_dir": str(self.cache_dir),
                "entry_count": len(self._entries),
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "max_size_mb": self.max_size_bytes // (1024 * 1024),
                "expired_count": expired_count,
                "ttl_seconds": self.ttl_seconds,
            }

    def _enforce_size_limit(self) -> None:
        """Remove oldest entries if cache exceeds size limit."""
        total_size = sum(e.file_size for e in self._entries.values())

        if total_size <= self.max_size_bytes:
            return

        # Sort by creation time (oldest first)
        sorted_entries = sorted(
            self._entries.items(),
            key=lambda x: x[1].created_at
        )

        removed = 0
        for source_id, entry in sorted_entries:
            if total_size <= self.max_size_bytes:
                break

            total_size -= entry.file_size
            self.invalidate(source_id)
            removed += 1

        if removed:
            logger.info(f"Removed {removed} cache entries to enforce size limit")

    def _extension_from_content_type(
        self,
        content_type: Optional[str],
        url: str
    ) -> str:
        """Determine file extension from content type or URL."""
        # Try content type first
        if content_type:
            type_to_ext = {
                "application/json": ".json",
                "text/csv": ".csv",
                "text/tab-separated-values": ".tsv",
                "text/plain": ".txt",
            }
            for mime, ext in type_to_ext.items():
                if content_type.startswith(mime):
                    return ext

        # Fall back to URL extension
        url_path = url.split('?')[0]  # Remove query string
        if '.' in url_path.split('/')[-1]:
            return '.' + url_path.split('.')[-1]

        return ""  # No extension
