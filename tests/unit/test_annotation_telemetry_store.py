"""
Unit tests for potato.annotation_telemetry_store.

Covers the migration, the round trip through the packed event blob, the
fidelity contract (``summary`` must persist no raw stream), and the aggregation
the admin dashboard depends on.
"""

import os

import pytest

from potato import annotation_telemetry_store as store
from potato.annotation_telemetry import (
    TelemetryEvent,
    evaluate,
    summarize,
)
from potato.persistence import clear_db_cache


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


def drawing_trace(shapes=5, interval=4_000, vertices=4):
    """A steady, unremarkable drawing session."""
    events = [TelemetryEvent(t_ms=0, action="tool", meta={"tool": "bbox"})]
    for i in range(shapes):
        events.append(TelemetryEvent(
            t_ms=1_000 + i * interval, action="shape_add",
            shape="bbox", value=vertices))
    return events


def rubber_stamp_trace(accepts=8, latency=180):
    events = []
    for i in range(accepts):
        t = i * 500
        events.append(TelemetryEvent(t_ms=t, action="ai_suggest",
                                     shape="bbox", meta={"sid": f"s{i}"}))
        events.append(TelemetryEvent(t_ms=t + latency, action="ai_accept",
                                     shape="bbox", meta={"sid": f"s{i}"}))
    return events


def _record(task_dir, *, user="alice", instance="i1", schema="objects",
            events=None, **kwargs):
    events = events if events is not None else drawing_trace()
    summary = summarize(events, schema_name=schema, instance_id=instance)
    return store.record_session(
        task_dir, project="demo", user_id=user, instance_id=instance,
        schema_name=schema, summary=summary, events=events, **kwargs)


class TestMigration:
    def test_tables_created_on_first_use(self, task_dir):
        store.count_sessions(task_dir, "demo")
        conn = store._db(task_dir)
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "annotation_telemetry" in names
        assert "annotation_telemetry_calibration" in names

    def test_every_denormalized_column_exists_in_the_schema(self, task_dir):
        """The insert names columns explicitly, so a typo is a hard error —
        but only if something actually inserts. This asserts the two lists
        agree before any row is written."""
        store.count_sessions(task_dir, "demo")
        conn = store._db(task_dir)
        columns = {r["name"] for r in conn.execute(
            "PRAGMA table_info(annotation_telemetry)")}
        for column in store._SUMMARY_COLUMNS:
            assert column in columns, f"{column} is inserted but not declared"

    def test_summary_columns_all_exist_on_the_summary_object(self, task_dir):
        """A column with no matching attribute would silently store NULL."""
        summary = summarize(drawing_trace())
        keys = summary.to_dict()
        for column in store._SUMMARY_COLUMNS:
            assert column in keys, f"{column} has no TelemetrySummary field"


class TestRoundTrip:
    def test_session_and_events_survive_storage(self, task_dir):
        events = drawing_trace(shapes=6)
        session_id = _record(task_dir, events=events)

        row = store.get_session(task_dir, session_id)
        assert row["user_id"] == "alice"
        assert row["schema_name"] == "objects"
        assert row["shapes_added"] == 6

        restored = store.load_events(task_dir, session_id)
        assert len(restored) == len(events)
        assert [e.action for e in restored] == [e.action for e in events]

    def test_denormalized_columns_match_the_stored_summary(self, task_dir):
        """The columns exist only as a query shortcut; if they disagree with the
        JSON, the dashboard and the export tell different stories."""
        session_id = _record(task_dir, events=rubber_stamp_trace())
        row = store.get_session(task_dir, session_id)
        for column in store._SUMMARY_COLUMNS:
            stored = row[column]
            in_json = row["summary"][column]
            if isinstance(stored, float) or isinstance(in_json, float):
                assert stored == pytest.approx(in_json), column
            else:
                assert stored == in_json, column

    def test_listing_sessions_does_not_decode_the_blob(self, task_dir):
        """Listing many sessions must stay cheap."""
        _record(task_dir)
        rows = store.sessions_for_user(task_dir, "demo", "alice")
        assert rows and "events_blob" not in rows[0]

    def test_flags_round_trip_as_json(self, task_dir):
        events = rubber_stamp_trace()
        verdict = evaluate(summarize(events))
        assert verdict.flags
        session_id = _record(task_dir, events=events,
                             flags=verdict.to_dict())
        row = store.get_session(task_dir, session_id)
        assert row["flags"]["flags"] == verdict.flags


class TestFidelity:
    def test_summary_fidelity_stores_no_raw_stream(self, task_dir):
        """That is the entire point of the setting."""
        session_id = _record(task_dir, fidelity="summary")
        assert store.load_events(task_dir, session_id) == []
        assert store.get_session(task_dir, session_id)["shapes_added"] == 5

    def test_passing_no_events_stores_no_stream(self, task_dir):
        summary = summarize(drawing_trace())
        session_id = store.record_session(
            task_dir, project="demo", user_id="alice", instance_id="i1",
            schema_name="objects", summary=summary, events=None)
        assert store.load_events(task_dir, session_id) == []


class TestQueries:
    def test_sessions_for_instance_can_filter_by_user(self, task_dir):
        _record(task_dir, user="alice", instance="i1")
        _record(task_dir, user="bob", instance="i1")
        _record(task_dir, user="alice", instance="i2")

        both = store.sessions_for_instance(task_dir, "demo", "i1")
        assert len(both) == 2
        just_alice = store.sessions_for_instance(
            task_dir, "demo", "i1", user_id="alice")
        assert len(just_alice) == 1
        assert just_alice[0]["user_id"] == "alice"

    def test_projects_are_isolated(self, task_dir):
        _record(task_dir)
        store.record_session(
            task_dir, project="other", user_id="alice", instance_id="i1",
            schema_name="objects", summary=summarize(drawing_trace()))
        assert store.count_sessions(task_dir, "demo") == 1
        assert store.count_sessions(task_dir, "other") == 1

    def test_feature_matrix_returns_one_row_per_session(self, task_dir):
        _record(task_dir, instance="i1")
        _record(task_dir, instance="i2")
        rows = store.feature_matrix(task_dir, "demo")
        assert len(rows) == 2
        assert {"user_id", "shapes_added", "ai_accept_latency_median_ms"} <= set(rows[0])

    def test_delete_for_user_removes_only_that_user(self, task_dir):
        _record(task_dir, user="alice")
        _record(task_dir, user="bob")
        assert store.delete_for_user(task_dir, "demo", "alice") == 1
        remaining = store.feature_matrix(task_dir, "demo")
        assert {r["user_id"] for r in remaining} == {"bob"}


class TestAggregation:
    def test_rollup_counts_per_user(self, task_dir):
        _record(task_dir, user="alice", instance="i1")
        _record(task_dir, user="alice", instance="i2")
        _record(task_dir, user="bob", instance="i1")

        rollup = {r["user_id"]: r for r in
                  store.aggregate_by_user(task_dir, "demo")}
        assert rollup["alice"]["sessions"] == 2
        assert rollup["alice"]["instances"] == 2
        assert rollup["alice"]["shapes"] == 10
        assert rollup["bob"]["sessions"] == 1

    def test_annotators_who_never_used_ai_sort_last(self, task_dir):
        """Ordering on a NULL latency would otherwise put the people with no
        signal at all above the ones worth looking at."""
        _record(task_dir, user="never_used_ai", events=drawing_trace())
        _record(task_dir, user="fast_accepter", events=rubber_stamp_trace())

        order = [r["user_id"] for r in store.aggregate_by_user(task_dir, "demo")]
        assert order[0] == "fast_accepter"
        assert order[-1] == "never_used_ai"

    def test_the_rollup_splits_drawn_from_accepted(self, task_dir):
        """Pace is measured over drawn shapes, so the dashboard has to show
        which is which — otherwise "8 shapes, 500ms apart" reads as hasty when
        it was eight carefully reviewed accepts."""
        events = []
        t = 0
        for i in range(6):
            events.append(TelemetryEvent(t, "ai_suggest", "bbox",
                                         meta={"sid": f"s{i}"}))
            events.append(TelemetryEvent(t + 4_000, "ai_accept", "bbox",
                                         meta={"sid": f"s{i}"}))
            events.append(TelemetryEvent(t + 4_010, "shape_add", "bbox", 4))
            t += 4_200
        _record(task_dir, user="reviewer", events=events)

        row = [r for r in store.aggregate_by_user(task_dir, "demo")
               if r["user_id"] == "reviewer"][0]
        assert row["shapes"] == 6
        assert row["shapes_from_ai"] == 6
        assert row["shapes_drawn"] == 0

    def test_active_time_is_normalized_per_shape(self, task_dir):
        """A few busy images must be comparable to many sparse ones."""
        _record(task_dir, user="alice",
                events=drawing_trace(shapes=10, interval=2_000))
        rollup = {r["user_id"]: r for r in
                  store.aggregate_by_user(task_dir, "demo")}
        row = rollup["alice"]
        assert row["active_ms_per_shape"] == pytest.approx(
            row["active_ms"] / row["shapes"])

    def test_accept_rates_are_recomputed_from_totals(self, task_dir):
        _record(task_dir, user="alice", events=rubber_stamp_trace(accepts=8))
        row = store.aggregate_by_user(task_dir, "demo")[0]
        assert row["ai_suggested"] == 8
        assert row["ai_accepted"] == 8
        assert row["ai_accept_rate"] == pytest.approx(1.0)
        assert row["ai_accept_edited_rate"] == pytest.approx(0.0)

    def test_empty_project_aggregates_to_nothing_not_an_error(self, task_dir):
        assert store.aggregate_by_user(task_dir, "demo") == []


class TestCalibration:
    def test_thresholds_persist_and_reload(self, task_dir):
        store.save_calibration(task_dir, "demo",
                               {"ai_accept_latency_ms": 240.0}, n_sessions=120)
        assert store.load_calibration(task_dir, "demo") == {
            "ai_accept_latency_ms": 240.0}

    def test_refitting_replaces_rather_than_duplicating(self, task_dir):
        store.save_calibration(task_dir, "demo", {"ai_accept_latency_ms": 100.0}, 50)
        store.save_calibration(task_dir, "demo", {"ai_accept_latency_ms": 300.0}, 90)
        assert store.load_calibration(task_dir, "demo")["ai_accept_latency_ms"] == 300.0

    def test_calibrate_needs_enough_sessions_before_it_fits_anything(self, task_dir):
        for i in range(5):
            _record(task_dir, instance=f"i{i}", events=rubber_stamp_trace())
        assert store.calibrate(task_dir, "demo") == {}
        assert store.load_calibration(task_dir, "demo") == {}

    def test_calibrate_fits_from_the_projects_own_distribution(self, task_dir):
        for i in range(40):
            _record(task_dir, instance=f"i{i}",
                    events=rubber_stamp_trace(latency=100 + i * 50))
        fitted = store.calibrate(task_dir, "demo", percentile=10.0)
        assert "ai_accept_latency_ms" in fitted
        # The 10th percentile of latencies running 100..2050 is near the bottom.
        assert 100 <= fitted["ai_accept_latency_ms"] <= 400
        assert store.load_calibration(task_dir, "demo") == fitted

    def test_unfitted_project_reports_no_thresholds(self, task_dir):
        assert store.load_calibration(task_dir, "demo") == {}


class TestStandalone:
    def test_the_store_never_reaches_back_into_flask(self):
        """Same property typing_store has: it must be usable from a script."""
        import pathlib
        source = pathlib.Path("potato/annotation_telemetry_store.py").read_text()
        assert "from flask" not in source
        assert "import flask" not in source
