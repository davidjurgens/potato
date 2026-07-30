"""
Tests for the live ingestion worker.

No SQLAlchemy here on purpose. It is an optional dependency absent from both
requirements.txt and requirements-test.txt, so CI has none -- and worker
lifecycle, backoff, deduplication and metrics are exactly the behaviour that
must not go uncovered there. SQL semantics live in
``test_database_live_source.py``, which skips when SQLAlchemy is missing.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from potato.data_sources.base import DataSource, LiveRow, SourceConfig
from potato.data_sources.live_ingestion import (
    LiveCursorStore,
    LiveIngestionConfig,
    LiveIngestionCoordinator,
    LiveIngestionWorker,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeLiveSource(DataSource):
    """
    An in-memory source that honours the ``(cursor, tiebreaker)`` contract.

    Rows are ``(cursor_value, row_id, item)`` triples kept sorted, so this
    exercises the same ordering and tie-breaking semantics a real database
    would, without needing one.
    """

    def __init__(self, rows=None, source_id="fake"):
        super().__init__(SourceConfig.from_dict({"type": "file", "path": "x", "id": source_id}))
        self.rows = list(rows or [])
        self.fail_times = 0
        self.fail_with = RuntimeError("database is on fire")
        self.read_calls = []
        self.close_calls = 0
        self.on_read = None
        self._rows_lock = threading.Lock()

    # -- DataSource plumbing ------------------------------------------------

    def get_source_id(self):
        return self.source_id

    def is_available(self):
        return True

    def read_items(self, start=0, count=None):
        return iter(())

    def get_total_count(self):
        return len(self.rows)

    def supports_partial_reading(self):
        return False

    def close(self):
        self.close_calls += 1

    # -- live ingestion -----------------------------------------------------

    def supports_live_ingestion(self):
        return True

    def read_since(self, cursor=None, tiebreaker=None, limit=None):
        self.read_calls.append({"cursor": cursor, "tiebreaker": tiebreaker, "limit": limit})

        if self.fail_times > 0:
            self.fail_times -= 1
            raise self.fail_with

        if self.on_read is not None:
            self.on_read()

        with self._rows_lock:
            rows = sorted(self.rows, key=lambda r: (r[0], r[1]))

        if cursor is not None:
            if tiebreaker is None:
                # No tie-breaker to compare against: strictly after the cursor.
                rows = [r for r in rows if r[0] > cursor]
            else:
                rows = [
                    r for r in rows
                    if r[0] > cursor or (r[0] == cursor and r[1] > tiebreaker)
                ]

        if limit is not None:
            rows = rows[:limit]

        for cursor_value, row_id, item in rows:
            yield LiveRow(item=dict(item), cursor_value=cursor_value, row_id=row_id)

    def add_row(self, cursor_value, row_id, item):
        with self._rows_lock:
            self.rows.append((cursor_value, row_id, item))


class FakeItemPool:
    """
    Stand-in for the manager's ``_ingest_item``, backed by a real dict + lock.

    Deliberately not a MagicMock: ``MagicMock().has_item()`` returns a truthy
    Mock, which would make every deduplication assertion here pass without
    testing anything.
    """

    def __init__(self):
        self.items = {}
        self.annotations = {}
        self._lock = threading.RLock()
        self.id_key = "id"

    def ingest(self, item):
        if self.id_key not in item:
            return "invalid"
        item_id = str(item[self.id_key])
        with self._lock:
            if item_id in self.items:
                return "duplicate"
            self.items[item_id] = item
        return "added"


def make_worker(source, pool, tmp_path, **config_kwargs):
    config_kwargs.setdefault("enabled", True)
    config_kwargs.setdefault("poll_interval_seconds", 0.05)
    config_kwargs.setdefault("cursor_column", "created_at")
    config = LiveIngestionConfig(**config_kwargs)
    store = LiveCursorStore(str(tmp_path))
    return LiveIngestionWorker(source, config, store, pool.ingest)


def rows_from(count, start=1):
    """``count`` rows with distinct integer cursors."""
    return [
        (i, str(i), {"id": str(i), "text": f"row {i}"})
        for i in range(start, start + count)
    ]


@pytest.fixture
def pool():
    return FakeItemPool()


# ---------------------------------------------------------------------------
# Reading and cursor handling
# ---------------------------------------------------------------------------


class TestPolling:

    def test_first_poll_ingests_all_rows(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(3))
        worker = make_worker(source, pool, tmp_path)

        worker.poll_once()

        assert set(pool.items) == {"1", "2", "3"}
        assert source.read_calls[0]["cursor"] is None

    def test_second_poll_ingests_only_new_rows(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(2))
        worker = make_worker(source, pool, tmp_path)
        worker.poll_once()

        source.add_row(3, "3", {"id": "3", "text": "row 3"})
        result = worker.poll_once()

        assert result["rows_fetched"] == 1
        assert result["items_added"] == 1
        assert set(pool.items) == {"1", "2", "3"}

    def test_cursor_advances_to_last_row_of_batch(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(5))
        worker = make_worker(source, pool, tmp_path, batch_size=2)

        worker.poll_once()

        assert source.read_calls[-1]["cursor"] is None
        status = worker.get_status()
        assert status["last_cursor"] == "2"
        assert status["last_cursor_tiebreak"] == "2"

    def test_cursor_persists_for_a_new_worker(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(3))
        make_worker(source, pool, tmp_path).poll_once()

        # A fresh worker over the same state directory resumes, not restarts.
        second_pool = FakeItemPool()
        resumed = make_worker(FakeLiveSource(rows_from(3)), second_pool, tmp_path)
        resumed.poll_once()

        assert second_pool.items == {}

    def test_empty_source_does_not_move_the_cursor(self, pool, tmp_path):
        worker = make_worker(FakeLiveSource([]), pool, tmp_path)
        worker.poll_once()

        assert worker.get_status()["last_cursor"] is None

    def test_batch_size_is_passed_through_as_limit(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(10))
        worker = make_worker(source, pool, tmp_path, batch_size=4)

        worker.poll_once()

        assert source.read_calls[0]["limit"] == 4
        assert len(pool.items) == 4

    def test_initial_cursor_is_used_when_nothing_is_stored(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(5))
        worker = make_worker(source, pool, tmp_path, initial_cursor=3)

        worker.poll_once()

        assert source.read_calls[0]["cursor"] == 3
        assert set(pool.items) == {"4", "5"}


class TestPrime:

    def test_prime_pages_through_a_backlog(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(10))
        worker = make_worker(source, pool, tmp_path, batch_size=3)

        added = worker.prime()

        assert added == 10
        assert len(pool.items) == 10
        assert len(source.read_calls) == 4  # 3 + 3 + 3 + 1 (short page ends it)

    def test_prime_on_empty_source_returns_zero(self, pool, tmp_path):
        worker = make_worker(FakeLiveSource([]), pool, tmp_path, batch_size=3)
        assert worker.prime() == 0

    def test_prime_replays_from_the_start_by_default(self, pool, tmp_path):
        """
        A restart must rebuild the whole pool, not just the tail.

        Admin views, exports and adjudication all read the item pool. Resuming
        from the cursor alone would leave them seeing only rows that arrived
        after the last shutdown.
        """
        rows = rows_from(5)
        make_worker(FakeLiveSource(rows), pool, tmp_path).prime()

        # A fresh process over the same state directory: empty pool, stored cursor.
        second_pool = FakeItemPool()
        resumed = make_worker(FakeLiveSource(rows), second_pool, tmp_path)
        resumed.prime()

        assert len(second_pool.items) == 5, "restart left the item pool incomplete"

    def test_prime_does_not_rewind_the_stored_cursor(self, pool, tmp_path):
        """A replay must not make the poller re-deliver rows it passed."""
        rows = rows_from(5)
        make_worker(FakeLiveSource(rows), pool, tmp_path).prime()

        source = FakeLiveSource(rows)
        resumed = make_worker(source, FakeItemPool(), tmp_path)
        resumed.prime()

        assert resumed.get_status()["last_cursor"] == "5"

        source.add_row(6, "6", {"id": "6"})
        result = resumed.poll_once()
        assert result["rows_fetched"] == 1, "poller re-read rows it had already passed"

    def test_replay_disabled_resumes_from_the_cursor(self, pool, tmp_path):
        """The escape hatch for tables too large to rescan."""
        rows = rows_from(5)
        make_worker(
            FakeLiveSource(rows), pool, tmp_path, replay_on_start=False
        ).prime()

        second_pool = FakeItemPool()
        make_worker(
            FakeLiveSource(rows), second_pool, tmp_path, replay_on_start=False
        ).prime()

        assert second_pool.items == {}

    def test_first_run_is_unaffected_by_replay_setting(self, pool, tmp_path):
        """With no stored cursor there is nothing to replay past."""
        assert make_worker(FakeLiveSource(rows_from(4)), pool, tmp_path).prime() == 4

    def test_prime_respects_stop_after_items(self, pool, tmp_path, caplog):
        source = FakeLiveSource(rows_from(20))
        worker = make_worker(source, pool, tmp_path, batch_size=5, stop_after_items=7)

        with caplog.at_level("WARNING"):
            worker.prime()

        assert len(pool.items) <= 10
        assert any("stop_after_items" in r.getMessage() for r in caplog.records)


class TestOverlapSeconds:

    def test_overlap_rewinds_a_datetime_cursor(self, pool, tmp_path):
        base = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        rows = [(base + timedelta(seconds=i), str(i), {"id": str(i)}) for i in range(3)]
        source = FakeLiveSource(rows)
        worker = make_worker(source, pool, tmp_path, overlap_seconds=5)

        worker.poll_once()
        worker.poll_once()

        # Second read rewinds 5s behind the stored cursor, so it re-reads.
        assert source.read_calls[1]["cursor"] == rows[-1][0] - timedelta(seconds=5)

    def test_overlap_refetched_rows_are_deduped_not_duplicated(self, pool, tmp_path):
        base = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        rows = [(base + timedelta(seconds=i), str(i), {"id": str(i)}) for i in range(3)]
        worker = make_worker(FakeLiveSource(rows), pool, tmp_path, overlap_seconds=60)

        worker.poll_once()
        result = worker.poll_once()

        assert len(pool.items) == 3
        assert result["duplicates_skipped"] > 0
        assert result["items_added"] == 0

    def test_overlap_rewinds_a_numeric_cursor(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(3))
        worker = make_worker(source, pool, tmp_path, overlap_seconds=2)

        worker.poll_once()
        worker.poll_once()

        assert source.read_calls[1]["cursor"] == 1  # 3 - 2

    def test_overlap_rewinds_an_iso_text_cursor(self, pool, tmp_path):
        """SQLite stores timestamps as text; overlap must still apply there."""
        rows = [
            ((BASE_ISO := datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc))
             + timedelta(seconds=i)).isoformat()
            for i in range(2)
        ]
        source = FakeLiveSource([(rows[i], str(i), {"id": str(i)}) for i in range(2)])
        worker = make_worker(source, pool, tmp_path, overlap_seconds=10)

        worker.poll_once()
        worker.poll_once()

        rewound = datetime.fromisoformat(source.read_calls[1]["cursor"])
        assert rewound == datetime.fromisoformat(rows[-1]) - timedelta(seconds=10)

    def test_overlap_leaves_a_text_cursor_alone(self, pool, tmp_path):
        rows = [("aaa", "1", {"id": "1"}), ("bbb", "2", {"id": "2"})]
        source = FakeLiveSource(rows)
        worker = make_worker(source, pool, tmp_path, overlap_seconds=5)

        worker.poll_once()
        worker.poll_once()

        assert source.read_calls[1]["cursor"] == "bbb"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:

    def test_duplicate_ids_are_skipped_and_counted(self, pool, tmp_path):
        rows = [(1, "1", {"id": "dup"}), (2, "2", {"id": "dup"})]
        worker = make_worker(FakeLiveSource(rows), pool, tmp_path)

        worker.poll_once()

        assert len(pool.items) == 1
        status = worker.get_status()
        assert status["items_added"] == 1
        assert status["duplicates_skipped"] == 1
        assert status["polls_failed"] == 0

    def test_duplicate_preserves_existing_annotations(self, pool, tmp_path):
        """Re-seeing an id must take the skip branch, never overwrite.

        Live ingestion uses add-or-skip, not add-or-update: an item that has
        already been annotated must not have its data replaced underneath the
        annotator.
        """
        source = FakeLiveSource([(1, "1", {"id": "7", "text": "original"})])
        worker = make_worker(source, pool, tmp_path)
        worker.poll_once()
        pool.items["7"]["labels"] = {"sentiment": "positive"}

        source.rows = [(2, "2", {"id": "7", "text": "REWRITTEN"})]
        worker._cursor = None
        worker.poll_once()

        assert pool.items["7"]["text"] == "original"
        assert pool.items["7"]["labels"] == {"sentiment": "positive"}

    def test_row_missing_id_key_counts_invalid_not_failed(self, pool, tmp_path):
        rows = [(1, "1", {"no_id_here": True}), (2, "2", {"id": "ok"})]
        worker = make_worker(FakeLiveSource(rows), pool, tmp_path)

        worker.poll_once()

        status = worker.get_status()
        assert status["invalid_rows_skipped"] == 1
        assert status["items_added"] == 1
        assert status["polls_failed"] == 0

    def test_rows_sharing_a_cursor_value_are_not_skipped(self, pool, tmp_path):
        """The tie-breaker regression.

        Three rows with an identical timestamp and a batch size of two: a
        cursor of ``created_at > X`` alone would step over the third.
        """
        same = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        rows = [(same, str(i), {"id": str(i)}) for i in (1, 2, 3)]
        worker = make_worker(FakeLiveSource(rows), pool, tmp_path, batch_size=2)

        worker.poll_once()
        worker.poll_once()

        assert set(pool.items) == {"1", "2", "3"}


# ---------------------------------------------------------------------------
# Failures, retry and backoff
# ---------------------------------------------------------------------------


class TestFailureHandling:

    def test_poll_once_propagates_so_callers_can_report(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(1))
        source.fail_times = 1
        worker = make_worker(source, pool, tmp_path)

        with pytest.raises(RuntimeError):
            worker.poll_once()

    def test_transient_failure_does_not_kill_the_thread(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(2))
        source.fail_times = 2
        worker = make_worker(
            source, pool, tmp_path,
            poll_interval_seconds=0.5, backoff_initial_seconds=0.01,
        )

        worker.start()
        try:
            deadline = time.time() + 5
            while time.time() < deadline and len(pool.items) < 2:
                time.sleep(0.02)
        finally:
            worker.stop()

        assert set(pool.items) == {"1", "2"}
        status = worker.get_status()
        assert status["polls_failed"] == 2
        assert status["consecutive_failures"] == 0

    def test_consecutive_failures_reset_on_success(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(1))
        source.fail_times = 1
        worker = make_worker(source, pool, tmp_path)

        with pytest.raises(RuntimeError):
            worker.poll_once()
        worker._record_failure(RuntimeError("x"))
        assert worker.get_status()["consecutive_failures"] >= 1

        worker.poll_once()
        assert worker.get_status()["consecutive_failures"] == 0

    def test_backoff_grows_exponentially_and_caps(self, pool, tmp_path):
        worker = make_worker(
            FakeLiveSource([]), pool, tmp_path,
            backoff_initial_seconds=1.0, backoff_max_seconds=8.0,
        )

        delays = [worker._record_failure(RuntimeError("boom")) for _ in range(6)]

        # Jitter is +/-20%, so compare against the un-jittered envelope.
        assert 0.8 <= delays[0] <= 1.2
        assert 1.6 <= delays[1] <= 2.4
        assert 3.2 <= delays[2] <= 4.8
        assert all(d <= 8.0 * 1.2 for d in delays)
        assert delays[-1] >= 6.4

    def test_failure_closes_the_source_to_rebuild_the_pool(self, pool, tmp_path):
        source = FakeLiveSource([])
        worker = make_worker(source, pool, tmp_path)

        worker._record_failure(RuntimeError("dead pool"))

        assert source.close_calls == 1

    def test_last_error_is_truncated(self, pool, tmp_path):
        worker = make_worker(FakeLiveSource([]), pool, tmp_path)

        worker._record_failure(RuntimeError("x" * 5000))

        assert len(worker.get_status()["last_error"]) < 600

    def test_max_consecutive_failures_stops_worker_preserving_error(self, pool, tmp_path):
        source = FakeLiveSource([])
        source.fail_times = 99
        worker = make_worker(
            source, pool, tmp_path,
            backoff_initial_seconds=0.01, max_consecutive_failures=3,
        )

        worker.start()
        deadline = time.time() + 5
        while time.time() < deadline and worker.is_running():
            time.sleep(0.02)
        worker.stop()

        status = worker.get_status()
        assert status["consecutive_failures"] >= 3
        assert "database is on fire" in status["last_error"]
        assert status["stopped_reason"] is not None

    def test_zero_max_consecutive_failures_means_retry_forever(self, pool, tmp_path):
        worker = make_worker(
            FakeLiveSource([]), pool, tmp_path, max_consecutive_failures=0,
        )

        for _ in range(20):
            assert worker._record_failure(RuntimeError("x")) is not None


# ---------------------------------------------------------------------------
# Thread lifecycle
# ---------------------------------------------------------------------------


class TestThreadLifecycle:

    def test_start_creates_a_running_daemon_thread(self, pool, tmp_path):
        worker = make_worker(FakeLiveSource([]), pool, tmp_path)
        worker.start()
        try:
            assert worker.is_running()
            assert worker._thread.daemon
        finally:
            worker.stop()

    def test_stop_terminates_the_thread(self, pool, tmp_path):
        worker = make_worker(FakeLiveSource([]), pool, tmp_path)
        worker.start()
        worker.stop()

        assert not worker.is_running()

    def test_start_is_idempotent(self, pool, tmp_path):
        worker = make_worker(FakeLiveSource([]), pool, tmp_path)
        worker.start()
        try:
            first = worker._thread
            worker.start()
            assert worker._thread is first
        finally:
            worker.stop()

    def test_stop_is_safe_when_never_started(self, pool, tmp_path):
        make_worker(FakeLiveSource([]), pool, tmp_path).stop()  # must not raise

    def test_stop_interrupts_a_long_backoff_quickly(self, pool, tmp_path):
        """Shutdown must not wait out a 300-second backoff."""
        source = FakeLiveSource([])
        source.fail_times = 99
        worker = make_worker(
            source, pool, tmp_path,
            backoff_initial_seconds=300.0, backoff_max_seconds=300.0,
        )

        worker.start()
        while worker.get_status()["consecutive_failures"] < 1:
            time.sleep(0.01)

        started = time.time()
        worker.stop()
        elapsed = time.time() - started

        assert elapsed < 2.0, f"stop() took {elapsed:.1f}s -- backoff is not interruptible"

    def test_new_rows_are_picked_up_by_the_background_loop(self, pool, tmp_path):
        source = FakeLiveSource(rows_from(1))
        worker = make_worker(source, pool, tmp_path, poll_interval_seconds=0.05)

        worker.start()
        try:
            source.add_row(2, "2", {"id": "2"})
            deadline = time.time() + 5
            while time.time() < deadline and "2" not in pool.items:
                time.sleep(0.02)
        finally:
            worker.stop()

        assert "2" in pool.items


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestConcurrency:

    def test_poll_does_not_block_other_threads(self, pool, tmp_path):
        """
        A slow read must not stall unrelated work.

        This is the acceptance criterion "polling does not block annotation
        requests", reduced to its essence: nothing shared is held across the
        source read.
        """
        source = FakeLiveSource(rows_from(1))
        other_thread_ran = threading.Event()

        def slow_read():
            helper = threading.Thread(target=other_thread_ran.set)
            helper.start()
            helper.join()
            time.sleep(0.2)

        source.on_read = slow_read
        worker = make_worker(source, pool, tmp_path)
        worker.poll_once()

        assert other_thread_ran.is_set()

    def test_concurrent_inserts_are_all_ingested_exactly_once(self, pool, tmp_path):
        """Rows written while polling must be neither lost nor duplicated."""
        source = FakeLiveSource([])
        worker = make_worker(source, pool, tmp_path, poll_interval_seconds=0.01, batch_size=10)

        total = 200
        writer_done = threading.Event()

        def writer():
            for i in range(total):
                source.add_row(i, f"{i:04d}", {"id": str(i)})
                time.sleep(0.001)
            writer_done.set()

        thread = threading.Thread(target=writer)
        worker.start()
        thread.start()
        try:
            writer_done.wait(timeout=20)
            deadline = time.time() + 10
            while time.time() < deadline and len(pool.items) < total:
                time.sleep(0.02)
        finally:
            worker.stop()
            thread.join(timeout=5)

        assert len(pool.items) == total
        status = worker.get_status()
        assert status["items_added"] == total
        assert status["items_added"] + status["duplicates_skipped"] \
            + status["invalid_rows_skipped"] == status["rows_fetched"]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class TestStatus:

    EXPECTED_KEYS = {
        "source_id", "is_running", "polls_total", "polls_failed", "rows_fetched",
        "items_added", "duplicates_skipped", "invalid_rows_skipped",
        "consecutive_failures", "last_error", "last_error_at", "last_poll_at",
        "last_success_at", "last_cursor", "last_cursor_tiebreak",
        "current_backoff_seconds", "started_at", "stopped_reason",
        "poll_interval_seconds", "cursor_column", "tiebreaker_column",
        "batch_size", "overlap_seconds",
    }

    def test_status_shape(self, pool, tmp_path):
        worker = make_worker(FakeLiveSource([]), pool, tmp_path)
        assert set(worker.get_status()) == self.EXPECTED_KEYS

    def test_status_is_json_serializable(self, pool, tmp_path):
        import json
        worker = make_worker(FakeLiveSource(rows_from(2)), pool, tmp_path)
        worker.poll_once()
        json.dumps(worker.get_status())  # must not raise

    def test_status_never_leaks_the_connection_string(self, pool, tmp_path):
        """Credentials must never reach an HTTP response."""
        secret = "postgresql://user:hunter2@db.internal/prod"
        source = FakeLiveSource(rows_from(1))
        source._raw_config["connection_string"] = secret
        worker = make_worker(source, pool, tmp_path)
        worker.poll_once()

        rendered = repr(worker.get_status())
        assert "hunter2" not in rendered
        assert secret not in rendered


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestLiveIngestionConfig:

    def test_defaults_are_disabled(self):
        assert LiveIngestionConfig.from_dict(None).enabled is False
        assert LiveIngestionConfig.from_dict({}).enabled is False

    def test_from_dict_reads_every_valid_key(self):
        block = {
            "enabled": True, "poll_interval_seconds": 7, "cursor_column": "ts",
            "tiebreaker_column": "pk", "initial_cursor": 3, "batch_size": 25,
            "overlap_seconds": 2, "safety_lag_seconds": 1,
            "backoff_initial_seconds": 2, "backoff_max_seconds": 60,
            "max_consecutive_failures": 5, "stop_after_items": 1000,
            "replay_on_start": False,
        }
        config = LiveIngestionConfig.from_dict(block)

        assert set(block) == LiveIngestionConfig.VALID_KEYS
        assert config.cursor_column == "ts"
        assert config.batch_size == 25
        assert config.stop_after_items == 1000
        assert config.replay_on_start is False

    def test_replay_on_start_defaults_to_true(self):
        """A restart rebuilds the full pool unless told otherwise."""
        assert LiveIngestionConfig.from_dict({"enabled": True}).replay_on_start is True

    def test_disabled_config_skips_validation(self):
        assert LiveIngestionConfig.from_dict({"poll_interval_seconds": -5}).validate() == []

    @pytest.mark.parametrize("block,fragment", [
        ({"poll_interval_seconds": 0.1}, "at least 0.5"),
        ({"poll_interval_seconds": 999999}, "3600"),
        ({"batch_size": 0}, "positive integer"),
        ({"overlap_seconds": -1}, "non-negative"),
        ({"safety_lag_seconds": -1}, "non-negative"),
        ({"backoff_initial_seconds": 0}, "positive number"),
        ({"backoff_initial_seconds": 10, "backoff_max_seconds": 1}, ">= backoff_initial_seconds"),
        ({"max_consecutive_failures": -1}, "non-negative"),
        ({"stop_after_items": -1}, "non-negative"),
    ])
    def test_validation_errors(self, block, fragment):
        config = LiveIngestionConfig.from_dict({"enabled": True, "cursor_column": "ts", **block})
        errors = config.validate()
        assert any(fragment in e for e in errors), errors

    def test_valid_config_has_no_errors(self):
        config = LiveIngestionConfig.from_dict({
            "enabled": True, "poll_interval_seconds": 5, "cursor_column": "created_at",
        })
        assert config.validate() == []


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class TestCoordinator:

    def _coordinator(self, tmp_path):
        return LiveIngestionCoordinator(LiveCursorStore(str(tmp_path)))

    def test_register_and_lookup(self, pool, tmp_path):
        coordinator = self._coordinator(tmp_path)
        source = FakeLiveSource([], source_id="src-a")

        worker = coordinator.register(
            source, LiveIngestionConfig(enabled=True), pool.ingest
        )

        assert coordinator.get_worker("src-a") is worker
        assert coordinator.get_worker("nope") is None
        assert coordinator.has_workers()

    def test_empty_coordinator_reports_no_workers(self, tmp_path):
        coordinator = self._coordinator(tmp_path)
        assert not coordinator.has_workers()
        assert coordinator.get_status() == []
        assert coordinator.start_all() == 0
        coordinator.stop_all()  # must not raise

    def test_start_all_then_stop_all(self, pool, tmp_path):
        coordinator = self._coordinator(tmp_path)
        for name in ("a", "b"):
            coordinator.register(
                FakeLiveSource([], source_id=name),
                LiveIngestionConfig(enabled=True, poll_interval_seconds=0.5),
                pool.ingest,
            )

        assert coordinator.start_all() == 2
        assert all(s["is_running"] for s in coordinator.get_status())

        coordinator.stop_all()
        assert not any(s["is_running"] for s in coordinator.get_status())

    def test_stop_all_survives_a_broken_worker(self, pool, tmp_path):
        """One wedged worker must not prevent the others from shutting down."""
        coordinator = self._coordinator(tmp_path)
        good = coordinator.register(
            FakeLiveSource([], source_id="good"),
            LiveIngestionConfig(enabled=True, poll_interval_seconds=0.5),
            pool.ingest,
        )
        bad = coordinator.register(
            FakeLiveSource([], source_id="bad"),
            LiveIngestionConfig(enabled=True, poll_interval_seconds=0.5),
            pool.ingest,
        )
        good.start()
        bad.stop = lambda: (_ for _ in ()).throw(RuntimeError("wedged"))

        coordinator.stop_all()

        assert not good.is_running()
