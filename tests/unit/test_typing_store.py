"""
Unit tests for potato.typing_store.

Covers the migration, the round trip through the packed event blob, the
fidelity contract (``summary`` must persist no raw stream), and the aggregation
the admin dashboard depends on.
"""

import os

import pytest

from potato.persistence import clear_db_cache, clear_migrations
from potato.typing_dynamics import TypingEvent, summarize
from potato import typing_store

from tests.unit.test_typing_dynamics import natural_trace, paste_trace


@pytest.fixture
def task_dir(tmp_path):
    """A fresh project directory with an isolated SQLite database.

    Both registries are process-global, so they are cleared before and after or
    a previous test's connection leaks into this one.
    """
    clear_db_cache()
    d = str(tmp_path / "project")
    os.makedirs(d, exist_ok=True)
    yield d
    clear_db_cache()


def _record(task_dir, *, user="alice", instance="i1", schema="notes",
            label="body", events=None, **kwargs):
    events = events if events is not None else natural_trace(120)
    summary = summarize(events, schema_name=schema, label_name=label)
    return typing_store.record_session(
        task_dir, project="demo", user_id=user, instance_id=instance,
        schema_name=schema, label_name=label, summary=summary,
        events=events, **kwargs)


class TestMigration:
    def test_tables_created_on_first_use(self, task_dir):
        typing_store.count_sessions(task_dir, "demo")
        conn = typing_store._db(task_dir)
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "typing_sessions" in names
        assert "typing_calibration" in names

    def test_survives_a_cleared_migration_registry(self, task_dir):
        """A test helper may wipe the global registry before this store's first
        get_db(); the _db() helper re-registers to cover that."""
        clear_migrations()
        clear_db_cache()
        session_id = _record(task_dir)
        assert typing_store.get_session(task_dir, session_id) is not None

    def test_database_lands_in_the_task_dir(self, task_dir):
        _record(task_dir)
        assert os.path.exists(os.path.join(task_dir, "project.sqlite"))


class TestRecordAndRead:
    def test_roundtrip(self, task_dir):
        events = natural_trace(120)
        session_id = _record(task_dir, events=events)
        row = typing_store.get_session(task_dir, session_id)
        assert row["user_id"] == "alice"
        assert row["schema_name"] == "notes"
        assert row["summary"]["keystrokes"] > 0
        assert len(typing_store.load_events(task_dir, session_id)) == len(events)

    def test_denormalized_columns_match_the_summary(self, task_dir):
        session_id = _record(task_dir, events=paste_trace())
        row = typing_store.get_session(task_dir, session_id)
        for column in ("keystrokes", "final_chars", "paste_events",
                       "pasted_fraction", "silent_insert_ratio"):
            assert row[column] == pytest.approx(row["summary"][column])

    def test_pause_columns_extracted(self, task_dir):
        session_id = _record(task_dir)
        row = typing_store.get_session(task_dir, session_id)
        assert row["pause_2s"] == row["summary"]["pause_counts"]["2000"]
        assert row["pause_10s"] == row["summary"]["pause_counts"]["10000"]

    def test_flags_stored_and_parsed(self, task_dir):
        session_id = _record(task_dir, flags={"level": "suspect",
                                              "flag_names": ["paste_dominant"]})
        row = typing_store.get_session(task_dir, session_id)
        assert row["flags"]["level"] == "suspect"
        assert row["flags"]["flag_names"] == ["paste_dominant"]

    def test_absent_flags_read_as_none(self, task_dir):
        assert typing_store.get_session(
            task_dir, _record(task_dir))["flags"] is None

    def test_listing_does_not_decode_the_event_blob(self, task_dir):
        """Listing many sessions must stay cheap; streams are fetched by id."""
        _record(task_dir)
        rows = typing_store.sessions_for_instance(task_dir, "demo", "i1")
        assert rows and "events" not in rows[0]

    def test_missing_session_returns_none(self, task_dir):
        assert typing_store.get_session(task_dir, "nope") is None
        assert typing_store.load_events(task_dir, "nope") == []


class TestFidelityContract:
    def test_summary_fidelity_stores_no_raw_stream(self, task_dir):
        session_id = _record(task_dir, fidelity="summary")
        assert typing_store.load_events(task_dir, session_id) == []
        # ...but the features survive.
        assert typing_store.get_session(task_dir, session_id)["summary"]["keystrokes"] > 0

    def test_events_fidelity_stores_the_stream(self, task_dir):
        session_id = _record(task_dir, fidelity="events")
        assert typing_store.load_events(task_dir, session_id)

    def test_no_events_supplied_is_tolerated(self, task_dir):
        summary = summarize(natural_trace(50))
        session_id = typing_store.record_session(
            task_dir, project="demo", user_id="alice", instance_id="i1",
            schema_name="notes", label_name="body", summary=summary, events=None)
        assert typing_store.load_events(task_dir, session_id) == []


class TestQueries:
    def test_scoped_by_project(self, task_dir):
        _record(task_dir)
        typing_store.record_session(
            task_dir, project="other", user_id="alice", instance_id="i1",
            schema_name="notes", label_name="body",
            summary=summarize(natural_trace(20)), events=natural_trace(20))
        assert typing_store.count_sessions(task_dir, "demo") == 1
        assert typing_store.count_sessions(task_dir, "other") == 1

    def test_sessions_for_instance_optionally_filters_user(self, task_dir):
        _record(task_dir, user="alice")
        _record(task_dir, user="bob")
        assert len(typing_store.sessions_for_instance(task_dir, "demo", "i1")) == 2
        assert len(typing_store.sessions_for_instance(
            task_dir, "demo", "i1", user_id="bob")) == 1

    def test_aggregate_by_user(self, task_dir):
        _record(task_dir, user="alice", instance="i1")
        _record(task_dir, user="alice", instance="i2")
        _record(task_dir, user="bob", instance="i1", events=paste_trace())
        agg = {r["user_id"]: r for r in typing_store.aggregate_by_user(task_dir, "demo")}
        assert agg["alice"]["sessions"] == 2
        assert agg["alice"]["instances"] == 2
        assert agg["bob"]["paste_events"] == 1
        assert agg["bob"]["pasted_char_fraction"] > 0.5

    def test_aggregate_normalizes_pauses_per_100_chars(self, task_dir):
        _record(task_dir)
        row = typing_store.aggregate_by_user(task_dir, "demo")[0]
        assert row["pause_2s_per_100_chars"] == pytest.approx(
            row["pause_2s"] * 100.0 / row["chars"])

    def test_aggregate_on_empty_project(self, task_dir):
        typing_store.count_sessions(task_dir, "demo")
        assert typing_store.aggregate_by_user(task_dir, "demo") == []

    def test_feature_matrix_shape(self, task_dir):
        _record(task_dir)
        _record(task_dir, user="bob")
        rows = typing_store.feature_matrix(task_dir, "demo")
        assert len(rows) == 2
        for key in ("id", "user_id", "iki_log_cv", "final_chars", "virtual_keyboard"):
            assert key in rows[0]

    def test_delete_for_user(self, task_dir):
        _record(task_dir, user="alice")
        _record(task_dir, user="bob")
        assert typing_store.delete_for_user(task_dir, "demo", "alice") == 1
        assert typing_store.count_sessions(task_dir, "demo") == 1
        assert typing_store.sessions_for_user(task_dir, "demo", "alice") == []


class TestCalibrationStorage:
    def test_save_and_load(self, task_dir):
        typing_store.save_calibration(
            task_dir, "demo", {"transcription_rhythm.iki_log_cv": 0.08}, 42)
        assert typing_store.load_calibration(task_dir, "demo") == {
            "transcription_rhythm.iki_log_cv": 0.08}

    def test_refit_replaces_rather_than_duplicates(self, task_dir):
        typing_store.save_calibration(task_dir, "demo", {"a.b": 1.0}, 10)
        typing_store.save_calibration(task_dir, "demo", {"a.b": 2.0}, 20)
        assert typing_store.load_calibration(task_dir, "demo") == {"a.b": 2.0}

    def test_scoped_by_project(self, task_dir):
        typing_store.save_calibration(task_dir, "demo", {"a.b": 1.0}, 10)
        assert typing_store.load_calibration(task_dir, "other") == {}

    def test_empty_when_never_calibrated(self, task_dir):
        typing_store.count_sessions(task_dir, "demo")
        assert typing_store.load_calibration(task_dir, "demo") == {}
