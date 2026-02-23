"""
Unit tests for the DirectoryWatcher module.

Covers:
- File parsing (JSONL, JSON, CSV, TSV)
- Background thread lifecycle (start, stop, idempotent start)
- Deduplication: existing instances are updated, not duplicated
- Singleton lifecycle (init, get, clear)
- Stats reporting
- Missing id_key / text_key handling
"""

import json
import os
import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from tests.helpers.test_utils import create_test_directory, cleanup_test_directory


# ---------------------------------------------------------------------------
# Fixture: create a DirectoryWatcher with a mock ItemStateManager
# ---------------------------------------------------------------------------

@pytest.fixture
def watcher_env(tmp_path):
    """Set up a DirectoryWatcher pointing at a temporary directory.

    Yields a dict with keys: watcher, ism (mock), data_dir, config.
    Cleans up the watcher on teardown.
    """
    data_dir = str(tmp_path / "incoming")
    os.makedirs(data_dir, exist_ok=True)

    ism = MagicMock()
    ism.has_item.return_value = False
    ism.add_item.return_value = None

    config = {
        "data_directory": data_dir,
        "watch_poll_interval": 0.2,
        "item_properties": {"id_key": "id", "text_key": "text"},
    }

    from potato.directory_watcher import DirectoryWatcher
    watcher = DirectoryWatcher(config, ism)

    yield {"watcher": watcher, "ism": ism, "data_dir": data_dir, "config": config}

    watcher.stop()


# ---------------------------------------------------------------------------
# Initialisation validation
# ---------------------------------------------------------------------------


class TestDirectoryWatcherInit:
    """Test constructor validation."""

    def test_missing_data_directory_raises(self, tmp_path):
        from potato.directory_watcher import DirectoryWatcher
        ism = MagicMock()
        with pytest.raises(ValueError, match="data_directory must be configured"):
            DirectoryWatcher({"item_properties": {"id_key": "id", "text_key": "text"}}, ism)

    def test_nonexistent_data_directory_raises(self, tmp_path):
        from potato.directory_watcher import DirectoryWatcher
        ism = MagicMock()
        with pytest.raises(ValueError, match="does not exist"):
            DirectoryWatcher({
                "data_directory": str(tmp_path / "nope"),
                "item_properties": {"id_key": "id", "text_key": "text"},
            }, ism)

    def test_relative_path_resolved_via_task_dir(self, tmp_path):
        """Relative data_directory is resolved against task_dir."""
        data_dir = tmp_path / "incoming"
        data_dir.mkdir()
        from potato.directory_watcher import DirectoryWatcher
        ism = MagicMock()
        w = DirectoryWatcher({
            "data_directory": "incoming",
            "task_dir": str(tmp_path),
            "item_properties": {"id_key": "id", "text_key": "text"},
        }, ism)
        assert os.path.isabs(w.data_directory)
        assert w.data_directory.endswith("incoming")


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------


class TestFileLoading:
    """Test that various file formats are parsed correctly."""

    def test_load_jsonl_file(self, watcher_env):
        w = watcher_env["watcher"]
        ism = watcher_env["ism"]
        path = os.path.join(watcher_env["data_dir"], "items.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"id": "j1", "text": "hello"}) + "\n")
            f.write(json.dumps({"id": "j2", "text": "world"}) + "\n")

        count = w.load_directory()
        assert count == 2
        assert ism.add_item.call_count == 2

    def test_load_json_array(self, watcher_env):
        """A .json file containing a JSON array on a single line."""
        w = watcher_env["watcher"]
        ism = watcher_env["ism"]
        path = os.path.join(watcher_env["data_dir"], "items.json")
        with open(path, "w") as f:
            data = [{"id": "a1", "text": "alpha"}, {"id": "a2", "text": "beta"}]
            f.write(json.dumps(data) + "\n")

        count = w.load_directory()
        assert count == 2

    def test_load_csv_file(self, watcher_env):
        """Load instances from a CSV file."""
        w = watcher_env["watcher"]
        ism = watcher_env["ism"]
        path = os.path.join(watcher_env["data_dir"], "items.csv")
        with open(path, "w") as f:
            f.write("id,text\n")
            f.write("c1,hello csv\n")
            f.write("c2,world csv\n")

        count = w.load_directory()
        assert count == 2

    def test_load_tsv_file(self, watcher_env):
        """Load instances from a TSV file."""
        w = watcher_env["watcher"]
        ism = watcher_env["ism"]
        path = os.path.join(watcher_env["data_dir"], "items.tsv")
        with open(path, "w") as f:
            f.write("id\ttext\n")
            f.write("t1\thello tsv\n")

        count = w.load_directory()
        assert count == 1

    def test_unsupported_extension_ignored(self, watcher_env):
        """Files with unsupported extensions should be silently ignored."""
        w = watcher_env["watcher"]
        ism = watcher_env["ism"]
        path = os.path.join(watcher_env["data_dir"], "notes.txt")
        with open(path, "w") as f:
            f.write("just a text file\n")

        count = w.load_directory()
        assert count == 0
        ism.add_item.assert_not_called()

    def test_empty_lines_skipped(self, watcher_env):
        """Blank lines in JSONL files should be skipped."""
        w = watcher_env["watcher"]
        path = os.path.join(watcher_env["data_dir"], "items.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"id": "e1", "text": "a"}) + "\n")
            f.write("\n")
            f.write("   \n")
            f.write(json.dumps({"id": "e2", "text": "b"}) + "\n")

        count = w.load_directory()
        assert count == 2

    def test_missing_id_key_skipped(self, watcher_env):
        """Instances without the id_key should be skipped with a warning."""
        w = watcher_env["watcher"]
        ism = watcher_env["ism"]
        path = os.path.join(watcher_env["data_dir"], "items.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"id": "ok1", "text": "fine"}) + "\n")
            f.write(json.dumps({"no_id": "bad", "text": "missing"}) + "\n")

        count = w.load_directory()
        # Only one should be added
        assert count == 1
        assert ism.add_item.call_count == 1


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Existing instances should be updated, not duplicated."""

    def test_existing_instance_updated(self, watcher_env):
        """If has_item returns True, update_item should be called instead of add_item."""
        w = watcher_env["watcher"]
        ism = watcher_env["ism"]

        # First item is new, second already exists
        ism.has_item.side_effect = lambda iid: iid == "dup1"
        ism.update_item.return_value = True

        path = os.path.join(watcher_env["data_dir"], "items.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"id": "dup1", "text": "updated"}) + "\n")
            f.write(json.dumps({"id": "new1", "text": "fresh"}) + "\n")

        w.load_directory()

        ism.update_item.assert_called_once()
        assert ism.update_item.call_args[0][0] == "dup1"
        ism.add_item.assert_called_once()
        assert ism.add_item.call_args[0][0] == "new1"


# ---------------------------------------------------------------------------
# Background thread lifecycle
# ---------------------------------------------------------------------------


class TestWatchThread:
    """Test start/stop of the background watching thread."""

    def test_start_creates_thread(self, watcher_env):
        w = watcher_env["watcher"]
        w.start_watching()
        try:
            assert w._watch_thread is not None
            assert w._watch_thread.is_alive()
        finally:
            w.stop()

    def test_stop_terminates_thread(self, watcher_env):
        w = watcher_env["watcher"]
        w.start_watching()
        w.stop()
        assert w._watch_thread is None or not w._watch_thread.is_alive()

    def test_start_is_idempotent(self, watcher_env):
        """Calling start_watching twice should not create a second thread."""
        w = watcher_env["watcher"]
        w.start_watching()
        thread1 = w._watch_thread
        w.start_watching()
        thread2 = w._watch_thread
        assert thread1 is thread2
        w.stop()

    def test_stop_is_safe_when_not_started(self, watcher_env):
        """Calling stop without start should not raise."""
        w = watcher_env["watcher"]
        w.stop()  # Should not raise

    def test_new_file_detected_during_watch(self, watcher_env):
        """A file added while watching should be picked up."""
        w = watcher_env["watcher"]
        ism = watcher_env["ism"]
        w.start_watching()

        try:
            # Add a file after watching started
            time.sleep(0.1)
            path = os.path.join(watcher_env["data_dir"], "new_during_watch.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps({"id": "dw1", "text": "dynamic"}) + "\n")

            # Wait for at least one poll cycle
            time.sleep(watcher_env["config"]["watch_poll_interval"] * 3)

            # The instance should have been added
            assert ism.add_item.called
            added_ids = [call[0][0] for call in ism.add_item.call_args_list]
            assert "dw1" in added_ids
        finally:
            w.stop()


# ---------------------------------------------------------------------------
# force_rescan
# ---------------------------------------------------------------------------


class TestForceRescan:
    """Test the force_rescan method."""

    def test_force_rescan_picks_up_new_file(self, watcher_env):
        w = watcher_env["watcher"]
        ism = watcher_env["ism"]

        # Initial load: empty
        w.load_directory()
        assert ism.add_item.call_count == 0

        # Add a file
        path = os.path.join(watcher_env["data_dir"], "late.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"id": "late1", "text": "arrived"}) + "\n")

        added, updated = w.force_rescan()
        assert added == 1
        assert updated == 0

    def test_force_rescan_detects_modification(self, watcher_env):
        w = watcher_env["watcher"]
        ism = watcher_env["ism"]

        # Create initial file
        path = os.path.join(watcher_env["data_dir"], "evolve.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"id": "ev1", "text": "v1"}) + "\n")

        w.load_directory()
        initial_calls = ism.add_item.call_count

        # Modify the file — add another instance
        time.sleep(0.05)  # Ensure mtime changes
        with open(path, "w") as f:
            f.write(json.dumps({"id": "ev1", "text": "v2"}) + "\n")
            f.write(json.dumps({"id": "ev2", "text": "new"}) + "\n")

        ism.has_item.side_effect = lambda iid: iid == "ev1"
        ism.update_item.return_value = True

        added, updated = w.force_rescan()
        # ev1 should be updated, ev2 should be added
        assert added == 1
        assert updated == 1


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStats:
    """Test get_stats reporting."""

    def test_stats_before_loading(self, watcher_env):
        w = watcher_env["watcher"]
        stats = w.get_stats()
        assert stats["files_tracked"] == 0
        assert stats["total_instances"] == 0
        assert stats["is_watching"] is False

    def test_stats_after_loading(self, watcher_env):
        w = watcher_env["watcher"]
        path = os.path.join(watcher_env["data_dir"], "stats.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"id": "s1", "text": "a"}) + "\n")
            f.write(json.dumps({"id": "s2", "text": "b"}) + "\n")

        w.load_directory()
        stats = w.get_stats()
        assert stats["files_tracked"] == 1
        assert stats["total_instances"] == 2
        assert len(stats["files"]) == 1
        assert stats["files"][0]["instance_count"] == 2


# ---------------------------------------------------------------------------
# Singleton lifecycle
# ---------------------------------------------------------------------------


class TestSingletonLifecycle:
    """Test init/get/clear for the module-level singleton."""

    def test_get_returns_none_before_init(self):
        from potato.directory_watcher import get_directory_watcher, clear_directory_watcher
        clear_directory_watcher()
        assert get_directory_watcher() is None

    def test_clear_sets_to_none(self):
        from potato.directory_watcher import get_directory_watcher, clear_directory_watcher
        clear_directory_watcher()
        assert get_directory_watcher() is None

    def test_init_without_data_directory_returns_none(self):
        from potato.directory_watcher import init_directory_watcher, clear_directory_watcher
        clear_directory_watcher()
        result = init_directory_watcher({"item_properties": {"id_key": "id", "text_key": "text"}})
        assert result is None
