"""
SQL-level tests for cursor-based live ingestion.

These need a real database, so they use SQLAlchemy over a throwaway SQLite
file. SQLAlchemy is an optional dependency (it is in neither requirements.txt
nor requirements-test.txt), so the whole module skips when it is absent --
the SQLAlchemy-free behaviour is covered by test_live_ingestion_worker.py.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("sqlalchemy")

from potato.data_sources.base import SourceConfig  # noqa: E402
from potato.data_sources.live_ingestion import (  # noqa: E402
    LiveCursorStore,
    LiveIngestionConfig,
    LiveIngestionWorker,
)
from potato.data_sources.sources.database_source import DatabaseSource  # noqa: E402


BASE_TIME = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    """A SQLite file with an ``instances`` table holding three rows."""
    from sqlalchemy import create_engine, text

    path = tmp_path / "live.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE instances ("
            "  id INTEGER PRIMARY KEY,"
            "  text TEXT,"
            "  created_at TEXT"
            ")"
        ))
        for i in (1, 2, 3):
            conn.execute(
                text("INSERT INTO instances (id, text, created_at) VALUES (:i, :t, :c)"),
                {"i": i, "t": f"row {i}", "c": (BASE_TIME + timedelta(seconds=i)).isoformat()},
            )
    engine.dispose()
    return path


def insert_row(db_path, row_id, text_value, created_at):
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO instances (id, text, created_at) VALUES (:i, :t, :c)"),
            {"i": row_id, "t": text_value, "c": created_at},
        )
    engine.dispose()


def make_source(db_path, **live_overrides):
    live = {
        "enabled": True,
        "poll_interval_seconds": 1,
        "cursor_column": "created_at",
    }
    live.update(live_overrides)
    return DatabaseSource(SourceConfig.from_dict({
        "type": "database",
        "id": "live_instances",
        "connection_string": f"sqlite:///{db_path}",
        "query": "SELECT id, text, created_at FROM instances",
        "live_ingestion": live,
    }))


class Pool:
    """Minimal ingest target mirroring the manager's dedupe contract."""

    def __init__(self):
        self.items = {}

    def ingest(self, item):
        if "id" not in item:
            return "invalid"
        key = str(item["id"])
        if key in self.items:
            return "duplicate"
        self.items[key] = item
        return "added"


def make_worker(source, pool, tmp_path):
    return LiveIngestionWorker(
        source,
        source.live_config,
        LiveCursorStore(str(tmp_path / "state")),
        pool.ingest,
    )


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------


class TestQueryBuilding:

    def test_first_poll_omits_the_where_clause(self, db_path):
        """A NULL bind inside a comparison is a portability landmine."""
        source = make_source(db_path)
        sql = source._build_live_query(has_cursor=False, has_tiebreak=False, limit=10)

        assert "WHERE" not in sql
        assert ":cursor_value" not in sql
        assert "ORDER BY created_at, id" in sql
        assert "LIMIT 10" in sql

    def test_cursor_without_tiebreak_uses_a_simple_comparison(self, db_path):
        sql = make_source(db_path)._build_live_query(
            has_cursor=True, has_tiebreak=False, limit=5
        )
        assert "created_at > :cursor_value" in sql
        assert ":cursor_tiebreak" not in sql

    def test_cursor_with_tiebreak_uses_the_portable_or_form(self, db_path):
        """Not row-value syntax: SQL Server lacks it, old SQLite lacks it."""
        sql = make_source(db_path)._build_live_query(
            has_cursor=True, has_tiebreak=True, limit=5
        )

        assert "created_at > :cursor_value" in sql
        assert "created_at = :cursor_value AND id > :cursor_tiebreak" in sql
        assert "(created_at, id) >" not in sql

    def test_safety_lag_adds_an_upper_bound(self, db_path):
        sql = make_source(db_path, safety_lag_seconds=30)._build_live_query(
            has_cursor=True, has_tiebreak=True, limit=5
        )
        assert "created_at <= :safety_horizon" in sql

    def test_tiebreaker_defaults_to_the_id_column(self, db_path):
        assert make_source(db_path)._tiebreak_column() == "id"

    def test_explicit_tiebreaker_is_honoured(self, db_path):
        source = make_source(db_path, tiebreaker_column="text")
        assert "ORDER BY created_at, text" in source._build_live_query(False, False, 5)

    def test_cursor_column_is_identifier_validated(self, db_path):
        """Identifiers are interpolated, so they must be guarded."""
        source = make_source(db_path, cursor_column="created_at; DROP TABLE instances")

        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            source._build_live_query(has_cursor=True, has_tiebreak=False, limit=5)

    def test_bad_cursor_column_is_reported_by_validate_config(self, db_path):
        source = make_source(db_path, cursor_column="created_at; DROP TABLE x")
        errors = source.validate_config()
        assert any("not a valid SQL identifier" in e for e in errors)

    def test_missing_cursor_column_is_reported(self, db_path):
        source = make_source(db_path, cursor_column="")
        assert any("requires 'cursor_column'" in e for e in source.validate_config())


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


class TestReadSince:

    def test_first_read_returns_everything(self, db_path):
        rows = list(make_source(db_path).read_since())
        assert [r.row_id for r in rows] == ["1", "2", "3"]

    def test_read_since_a_cursor_returns_only_newer_rows(self, db_path):
        source = make_source(db_path)
        first = list(source.read_since())

        rest = list(source.read_since(
            cursor=first[0].cursor_value, tiebreaker=first[0].row_id
        ))

        assert [r.row_id for r in rest] == ["2", "3"]

    def test_limit_caps_the_batch(self, db_path):
        assert len(list(make_source(db_path).read_since(limit=2))) == 2

    def test_raw_cursor_is_not_isoformatted_twice(self, db_path):
        """
        The cursor must come off the raw row, not the converted item dict.

        ``_row_to_dict`` calls ``.isoformat()`` on datetimes; taking the
        cursor from there would already have lost the native type. SQLite
        stores text so both look alike here -- the assertion that matters is
        that the two are read independently.
        """
        row = next(iter(make_source(db_path).read_since()))

        assert row.cursor_value == row.item["created_at"]
        assert row.cursor_value is not None

    def test_cursor_value_is_bound_not_interpolated(self, db_path):
        """A cursor containing SQL must be data, never code."""
        from sqlalchemy import create_engine, text

        malicious = "'; DROP TABLE instances; --"
        insert_row(db_path, 99, "sneaky", malicious)

        source = make_source(db_path)
        rows = list(source.read_since(cursor=malicious, tiebreaker="0"))

        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            surviving = conn.execute(text("SELECT COUNT(*) FROM instances")).scalar()
        engine.dispose()

        assert surviving == 4, "the table was dropped -- the cursor was interpolated"
        assert isinstance(rows, list)

    def test_rows_sharing_a_timestamp_are_not_skipped(self, db_path):
        """
        The core tie-breaker regression.

        Three rows with an identical ``created_at`` and a batch size of two.
        A bare ``created_at > :cursor`` steps over the third one forever.
        """
        from sqlalchemy import create_engine, text

        engine = create_engine(f"sqlite:///{db_path}")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM instances"))
            same = BASE_TIME.isoformat()
            for i in (10, 11, 12):
                conn.execute(
                    text("INSERT INTO instances (id, text, created_at) VALUES (:i, :t, :c)"),
                    {"i": i, "t": f"row {i}", "c": same},
                )
        engine.dispose()

        source = make_source(db_path, batch_size=2)
        pool = Pool()
        worker = LiveIngestionWorker(
            source, source.live_config, LiveCursorStore(str(db_path.parent / "s1")), pool.ingest
        )

        worker.poll_once()
        worker.poll_once()

        assert set(pool.items) == {"10", "11", "12"}

    def test_cursor_column_missing_from_select_raises_clearly(self, db_path):
        source = DatabaseSource(SourceConfig.from_dict({
            "type": "database",
            "id": "bad",
            "connection_string": f"sqlite:///{db_path}",
            "query": "SELECT id, text FROM instances",
            "live_ingestion": {"enabled": True, "cursor_column": "created_at"},
        }))

        with pytest.raises(RuntimeError, match="not present in the query result columns"):
            list(source.read_since())

    def test_read_since_without_live_enabled_raises(self, db_path):
        source = DatabaseSource(SourceConfig.from_dict({
            "type": "database",
            "id": "static",
            "connection_string": f"sqlite:///{db_path}",
            "query": "SELECT id, text, created_at FROM instances",
        }))

        assert source.supports_live_ingestion() is False
        with pytest.raises(RuntimeError, match="does not have live_ingestion enabled"):
            list(source.read_since())

    def test_table_form_works_without_an_explicit_query(self, db_path):
        source = DatabaseSource(SourceConfig.from_dict({
            "type": "database",
            "id": "tbl",
            "connection_string": f"sqlite:///{db_path}",
            "table": "instances",
            "live_ingestion": {"enabled": True, "cursor_column": "created_at"},
        }))

        assert len(list(source.read_since())) == 3


class TestExplicitCursorMode:
    """Mode B -- the admin's query carries its own ``:cursor``."""

    def _source(self, db_path, **live_overrides):
        live = {
            "enabled": True,
            "cursor_column": "created_at",
            "initial_cursor": "1970-01-01T00:00:00+00:00",
        }
        live.update(live_overrides)
        return DatabaseSource(SourceConfig.from_dict({
            "type": "database",
            "id": "explicit",
            "connection_string": f"sqlite:///{db_path}",
            "query": (
                "SELECT id, text, created_at FROM instances "
                "WHERE created_at > :cursor ORDER BY created_at, id"
            ),
            "live_ingestion": live,
        }))

    def test_issue_example_config_reads_rows(self, db_path):
        """The exact shape from the issue must work end to end."""
        rows = list(self._source(db_path).read_since())
        assert [r.row_id for r in rows] == ["1", "2", "3"]

    def test_initial_cursor_is_required(self, db_path):
        source = self._source(db_path, initial_cursor=None)
        errors = source.validate_config()
        assert any("initial_cursor is required" in e for e in errors)

    def test_potato_only_appends_a_limit(self, db_path):
        sql = self._source(db_path)._build_explicit_cursor_query(7)
        assert sql.endswith("LIMIT 7")
        assert ":cursor" in sql

    def test_subsequent_reads_bind_the_stored_cursor(self, db_path):
        source = self._source(db_path)
        first = list(source.read_since(limit=1))

        rest = list(source.read_since(cursor=first[0].cursor_value))

        assert [r.row_id for r in rest] == ["2", "3"]


class TestCrashGuards:
    """
    Both of these crash on the issue's example config as shipped today.

    ``read_items`` and ``get_total_count`` execute the query with no
    parameters, so an unbound ``:cursor`` raises StatementError -- and
    ``get_total_count`` is reachable from GET /admin/api/data_sources, i.e.
    on a request thread.
    """

    def test_read_items_delegates_in_live_mode(self, db_path):
        items = list(make_source(db_path).read_items())
        assert [i["id"] for i in items] == [1, 2, 3]

    def test_read_items_does_not_raise_on_an_explicit_cursor_query(self, db_path):
        source = DatabaseSource(SourceConfig.from_dict({
            "type": "database",
            "id": "explicit",
            "connection_string": f"sqlite:///{db_path}",
            "query": "SELECT id, text, created_at FROM instances WHERE created_at > :cursor",
            "live_ingestion": {
                "enabled": True,
                "cursor_column": "created_at",
                "initial_cursor": "1970-01-01T00:00:00+00:00",
            },
        }))

        assert len(list(source.read_items())) == 3

    def test_get_total_count_returns_none_for_a_live_source(self, db_path):
        assert make_source(db_path).get_total_count() is None

    def test_get_total_count_still_works_for_a_static_source(self, db_path):
        source = DatabaseSource(SourceConfig.from_dict({
            "type": "database",
            "id": "static",
            "connection_string": f"sqlite:///{db_path}",
            "query": "SELECT id, text, created_at FROM instances",
        }))
        assert source.get_total_count() == 3

    def test_get_status_is_safe_on_a_live_source(self, db_path):
        """get_status() is on the admin request path and must never raise."""
        status = make_source(db_path).get_status()
        assert status["live_ingestion_enabled"] is True
        assert status["total_count"] is None


# ---------------------------------------------------------------------------
# Live behaviour against a real database
# ---------------------------------------------------------------------------


class TestLiveIngestionAgainstSqlite:

    def test_rows_inserted_after_the_first_poll_are_picked_up(self, db_path, tmp_path):
        source = make_source(db_path)
        pool = Pool()
        worker = make_worker(source, pool, tmp_path)

        worker.poll_once()
        assert set(pool.items) == {"1", "2", "3"}

        insert_row(db_path, 4, "row 4", (BASE_TIME + timedelta(seconds=4)).isoformat())
        worker.poll_once()

        assert set(pool.items) == {"1", "2", "3", "4"}

    def test_repeated_polls_do_not_duplicate(self, db_path, tmp_path):
        source = make_source(db_path)
        pool = Pool()
        worker = make_worker(source, pool, tmp_path)

        for _ in range(4):
            worker.poll_once()

        assert len(pool.items) == 3
        assert worker.get_status()["items_added"] == 3

    def test_cursor_survives_a_worker_restart(self, db_path, tmp_path):
        pool = Pool()
        make_worker(make_source(db_path), pool, tmp_path).poll_once()

        second_pool = Pool()
        resumed = make_worker(make_source(db_path), second_pool, tmp_path)
        resumed.poll_once()

        assert second_pool.items == {}, "resumed worker re-ingested existing rows"

    def test_prime_backfills_through_pages(self, db_path, tmp_path):
        source = make_source(db_path, batch_size=1)
        pool = Pool()

        added = make_worker(source, pool, tmp_path).prime()

        assert added == 3
        assert set(pool.items) == {"1", "2", "3"}

    def test_overlap_seconds_refetches_and_dedupes(self, db_path, tmp_path):
        source = make_source(db_path, overlap_seconds=3600)
        pool = Pool()
        worker = make_worker(source, pool, tmp_path)

        worker.poll_once()
        result = worker.poll_once()

        assert len(pool.items) == 3
        assert result["items_added"] == 0
        assert result["duplicates_skipped"] > 0

    def test_unreachable_database_does_not_kill_the_worker(self, tmp_path):
        """A dead source must back off, not crash the process."""
        source = DatabaseSource(SourceConfig.from_dict({
            "type": "database",
            "id": "dead",
            "connection_string": f"sqlite:///{tmp_path}/nope.db",
            "query": "SELECT id, text, created_at FROM does_not_exist",
            "live_ingestion": {
                "enabled": True,
                "poll_interval_seconds": 0.5,
                "cursor_column": "created_at",
                "backoff_initial_seconds": 0.01,
            },
        }))
        worker = make_worker(source, Pool(), tmp_path)

        worker.start()
        try:
            deadline = time.time() + 5
            while time.time() < deadline and worker.get_status()["polls_failed"] < 2:
                time.sleep(0.02)
        finally:
            worker.stop()

        status = worker.get_status()
        assert status["polls_failed"] >= 2
        assert status["last_error"] is not None

    def test_concurrent_inserts_are_ingested_exactly_once(self, db_path, tmp_path):
        """Rows written while the poller runs: none lost, none duplicated."""
        source = make_source(db_path, poll_interval_seconds=0.5, batch_size=25)
        pool = Pool()
        worker = LiveIngestionWorker(
            source,
            LiveIngestionConfig.from_dict({
                "enabled": True,
                "poll_interval_seconds": 0.02,
                "cursor_column": "created_at",
                "batch_size": 25,
            }),
            LiveCursorStore(str(tmp_path / "conc")),
            pool.ingest,
        )

        total = 200
        done = threading.Event()

        def writer():
            for i in range(100, 100 + total):
                insert_row(
                    db_path, i, f"row {i}",
                    (BASE_TIME + timedelta(seconds=i)).isoformat(),
                )
            done.set()

        thread = threading.Thread(target=writer)
        worker.start()
        thread.start()
        try:
            done.wait(timeout=60)
            deadline = time.time() + 20
            while time.time() < deadline and len(pool.items) < total + 3:
                time.sleep(0.05)
        finally:
            worker.stop()
            thread.join(timeout=10)

        assert len(pool.items) == total + 3, "rows were lost during concurrent inserts"
        status = worker.get_status()
        assert status["items_added"] == total + 3
        assert (
            status["items_added"]
            + status["duplicates_skipped"]
            + status["invalid_rows_skipped"]
            == status["rows_fetched"]
        )


class TestManagerIntegration:
    """The coordinator wired into a real DataSourceManager."""

    @pytest.fixture
    def manager(self, db_path, tmp_path):
        from potato.data_sources.manager import DataSourceManager, clear_data_source_manager
        import potato.data_sources.sources  # noqa: F401  registers source types

        from potato.item_state_management import (
            clear_item_state_manager,
            get_item_state_manager,
            init_item_state_manager,
        )

        clear_item_state_manager()
        config = {
            "output_annotation_dir": str(tmp_path / "out"),
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_sources": [{
                "type": "database",
                "id": "live_instances",
                "connection_string": f"sqlite:///{db_path}",
                "query": "SELECT id, text, created_at FROM instances",
                "live_ingestion": {
                    # 0.5s is the configured floor -- see LiveIngestionConfig.validate.
                    "enabled": True,
                    "poll_interval_seconds": 0.5,
                    "cursor_column": "created_at",
                },
            }],
        }
        init_item_state_manager(config)
        mgr = DataSourceManager(config, get_item_state_manager())

        yield mgr, get_item_state_manager()

        mgr.close()
        clear_data_source_manager()
        clear_item_state_manager()

    def test_live_worker_is_registered(self, manager):
        mgr, _ = manager
        assert mgr.has_live_sources()
        assert mgr.get_live_ingestion_status("live_instances") is not None
        assert mgr.get_live_ingestion_status("nope") is None

    def test_initial_load_goes_through_the_cursor_path(self, manager):
        mgr, ism = manager

        loaded = mgr.load_initial_data()

        assert loaded == 3
        assert ism.has_item("1")
        # The cursor was seeded by the catch-up read, not left at the start.
        assert mgr.get_live_ingestion_status("live_instances")["last_cursor"] is not None

    def test_ingested_items_have_displayed_text(self, manager):
        """Runtime items must not depend on the startup render pass."""
        mgr, ism = manager
        mgr.load_initial_data()

        assert "displayed_text" in ism.get_item("1").get_data()

    def test_ingested_items_are_immediately_assignable(self, manager):
        """The acceptance criterion: stored is not enough, it must be servable."""
        mgr, ism = manager
        mgr.load_initial_data()

        assert "1" in list(ism.remaining_instance_ids)

    def test_row_added_after_startup_is_picked_up(self, manager, db_path):
        mgr, ism = manager
        mgr.load_initial_data()
        assert not ism.has_item("42")

        insert_row(db_path, 42, "late arrival",
                   (BASE_TIME + timedelta(seconds=99)).isoformat())
        result = mgr.poll_source_now("live_instances")

        assert result["items_added"] == 1
        assert ism.has_item("42")
        assert "42" in list(ism.remaining_instance_ids)

    def test_poll_unknown_source_raises_valueerror(self, manager):
        mgr, _ = manager
        with pytest.raises(ValueError, match="no live ingestion worker"):
            mgr.poll_source_now("does-not-exist")

    def test_list_sources_carries_live_state(self, manager):
        mgr, _ = manager
        mgr.load_initial_data()

        sources = mgr.list_sources()
        live = sources[0]["live_ingestion"]

        assert live["source_id"] == "live_instances"
        assert live["items_added"] == 3
        assert "hunter2" not in repr(sources)

    def test_get_stats_includes_live_ingestion(self, manager):
        mgr, _ = manager
        assert "live_ingestion" in mgr.get_stats()

    def test_start_then_close_stops_the_threads(self, manager):
        mgr, ism = manager
        mgr.load_initial_data()

        assert mgr.start_live_ingestion() == 1
        assert mgr.get_live_ingestion_status("live_instances")["is_running"]

        mgr.close()

        assert not mgr.get_live_ingestion_status("live_instances")["is_running"]

    def test_background_loop_picks_up_a_new_row(self, manager, db_path):
        """End to end: insert while running, no restart, item becomes servable."""
        mgr, ism = manager
        mgr.load_initial_data()
        mgr.start_live_ingestion()
        try:
            insert_row(db_path, 77, "live row",
                       (BASE_TIME + timedelta(seconds=77)).isoformat())

            deadline = time.time() + 10
            while time.time() < deadline and not ism.has_item("77"):
                time.sleep(0.05)
        finally:
            mgr.stop_live_ingestion()

        assert ism.has_item("77")
        assert "77" in list(ism.remaining_instance_ids)


class TestEnvVarSubstitution:
    """
    ``${VAR}`` inside ``live_ingestion`` resolves.

    It does, because CredentialManager.process_config recurses into nested
    dicts -- but nothing pinned that, and the recursion is easy to lose.
    """

    def test_env_vars_resolve_inside_the_live_block(self, monkeypatch):
        from potato.data_sources.credentials import CredentialManager

        monkeypatch.setenv("POTATO_TEST_SINCE", "2026-01-01T00:00:00")

        processed = CredentialManager().process_config({
            "type": "database",
            "connection_string": "sqlite:///x.db",
            "query": "SELECT * FROM t WHERE created_at > :cursor",
            "live_ingestion": {
                "enabled": True,
                "cursor_column": "created_at",
                "initial_cursor": "${POTATO_TEST_SINCE}",
            },
        })

        assert processed["live_ingestion"]["initial_cursor"] == "2026-01-01T00:00:00"
