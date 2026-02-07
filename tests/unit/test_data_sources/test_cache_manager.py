"""Tests for CacheManager."""

import os
import time
import tempfile
import pytest
from potato.data_sources.cache_manager import CacheManager, CacheEntry


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_is_expired_no_expiration(self):
        """Test that entry with no expiration is not expired."""
        entry = CacheEntry(
            source_id="test",
            source_url="http://example.com",
            cache_path="/tmp/test",
            expires_at=None
        )
        assert entry.is_expired() is False

    def test_is_expired_future_expiration(self):
        """Test that entry with future expiration is not expired."""
        entry = CacheEntry(
            source_id="test",
            source_url="http://example.com",
            cache_path="/tmp/test",
            expires_at=time.time() + 3600
        )
        assert entry.is_expired() is False

    def test_is_expired_past_expiration(self):
        """Test that entry with past expiration is expired."""
        entry = CacheEntry(
            source_id="test",
            source_url="http://example.com",
            cache_path="/tmp/test",
            expires_at=time.time() - 1
        )
        assert entry.is_expired() is True

    def test_to_dict_and_from_dict(self):
        """Test serialization round-trip."""
        entry = CacheEntry(
            source_id="test_source",
            source_url="http://example.com/data.json",
            cache_path="/tmp/cached_file",
            etag="abc123",
            last_modified="Wed, 01 Jan 2020 00:00:00 GMT",
            file_size=1024,
            content_type="application/json",
            metadata={"key": "value"},
        )

        data = entry.to_dict()
        restored = CacheEntry.from_dict(data)

        assert restored.source_id == entry.source_id
        assert restored.source_url == entry.source_url
        assert restored.etag == entry.etag
        assert restored.metadata == entry.metadata


class TestCacheManager:
    """Tests for CacheManager."""

    @pytest.fixture
    def cache_dir(self, tmp_path):
        """Create a temporary cache directory."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        return str(cache_dir)

    @pytest.fixture
    def cache_manager(self, cache_dir):
        """Create a CacheManager with a temporary directory."""
        return CacheManager(cache_dir=cache_dir, ttl_seconds=3600)

    def test_init_creates_directory(self, tmp_path):
        """Test that init creates the cache directory."""
        cache_dir = str(tmp_path / "new_cache")
        manager = CacheManager(cache_dir=cache_dir)

        assert os.path.isdir(cache_dir)

    def test_put_and_get(self, cache_manager):
        """Test storing and retrieving cached data."""
        source_id = "test_source"
        source_url = "http://example.com/data.json"
        data = b'{"items": []}'

        entry = cache_manager.put(
            source_id=source_id,
            source_url=source_url,
            data=data,
            content_type="application/json"
        )

        # Verify entry was created
        assert entry.source_id == source_id
        assert entry.file_size == len(data)

        # Retrieve and verify
        retrieved = cache_manager.get(source_id)
        assert retrieved is not None
        assert retrieved.source_id == source_id

    def test_get_missing_returns_none(self, cache_manager):
        """Test that getting missing entry returns None."""
        result = cache_manager.get("nonexistent_source")
        assert result is None

    def test_get_expired_returns_none(self, cache_manager, cache_dir):
        """Test that expired entries are not returned."""
        # Create a manager with very short TTL
        short_ttl_manager = CacheManager(cache_dir=cache_dir, ttl_seconds=1)

        source_id = "expiring_source"
        # Set expires_at to a time in the past by using a tiny ttl
        entry = short_ttl_manager.put(
            source_id=source_id,
            source_url="http://example.com/data.json",
            data=b"test",
            ttl_seconds=1  # Short TTL
        )

        # Manually expire the entry by modifying expires_at
        short_ttl_manager._entries[source_id].expires_at = time.time() - 1

        result = short_ttl_manager.get(source_id)
        assert result is None

    def test_invalidate(self, cache_manager):
        """Test invalidating a cache entry."""
        source_id = "invalidate_test"

        cache_manager.put(
            source_id=source_id,
            source_url="http://example.com/data.json",
            data=b"test data"
        )

        # Verify it exists
        assert cache_manager.get(source_id) is not None

        # Invalidate
        result = cache_manager.invalidate(source_id)
        assert result is True

        # Verify it's gone
        assert cache_manager.get(source_id) is None

    def test_invalidate_nonexistent(self, cache_manager):
        """Test invalidating nonexistent entry returns False."""
        result = cache_manager.invalidate("nonexistent")
        assert result is False

    def test_clear(self, cache_manager):
        """Test clearing all cache entries."""
        # Add multiple entries
        for i in range(3):
            cache_manager.put(
                source_id=f"source_{i}",
                source_url=f"http://example.com/data{i}.json",
                data=f"data{i}".encode()
            )

        # Clear all
        count = cache_manager.clear()

        assert count == 3
        assert cache_manager.get("source_0") is None
        assert cache_manager.get("source_1") is None
        assert cache_manager.get("source_2") is None

    def test_cleanup_expired(self, cache_manager, cache_dir):
        """Test cleaning up expired entries."""
        # Create manager with short TTL
        short_ttl_manager = CacheManager(cache_dir=cache_dir, ttl_seconds=1)

        # Add entries
        for i in range(2):
            short_ttl_manager.put(
                source_id=f"expiring_{i}",
                source_url=f"http://example.com/data{i}.json",
                data=b"test",
                ttl_seconds=1
            )

        # Manually expire the entries
        for i in range(2):
            short_ttl_manager._entries[f"expiring_{i}"].expires_at = time.time() - 1

        # Cleanup
        count = short_ttl_manager.cleanup_expired()
        assert count == 2

    def test_get_stats(self, cache_manager):
        """Test getting cache statistics."""
        # Add some entries
        cache_manager.put(
            source_id="stats_test",
            source_url="http://example.com/data.json",
            data=b"x" * 1000  # 1000 bytes
        )

        stats = cache_manager.get_stats()

        assert stats["entry_count"] == 1
        assert stats["total_size_bytes"] == 1000
        assert stats["ttl_seconds"] == 3600
        assert "cache_dir" in stats

    def test_etag_validation(self, cache_manager):
        """Test ETag-based cache validation."""
        source_id = "etag_test"

        cache_manager.put(
            source_id=source_id,
            source_url="http://example.com/data.json",
            data=b"test",
            etag="etag123"
        )

        # Same ETag should return entry
        result = cache_manager.get_if_valid(source_id, etag="etag123")
        assert result is not None

        # Different ETag should return None
        result = cache_manager.get_if_valid(source_id, etag="different_etag")
        assert result is None

    def test_persistence_across_restarts(self, cache_dir):
        """Test that cache index persists across manager instances."""
        source_id = "persist_test"
        source_url = "http://example.com/data.json"

        # Create first manager and add entry
        manager1 = CacheManager(cache_dir=cache_dir)
        manager1.put(
            source_id=source_id,
            source_url=source_url,
            data=b"persistent data"
        )

        # Create second manager (simulating restart)
        manager2 = CacheManager(cache_dir=cache_dir)

        # Entry should still be accessible
        entry = manager2.get(source_id)
        assert entry is not None
        assert entry.source_id == source_id
