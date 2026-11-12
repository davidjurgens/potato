"""
Agreement over time, and the re-calibration trigger.

The IAA package had fourteen metric modules and no time dimension, so it could
say what agreement *is* and never whether it is falling. That matters because
a single whole-project number averages early and late work together: a team
whose recent agreement has collapsed still shows an acceptable figure, and the
advice that produces large agreement gains -- calibration sessions -- only
holds if the calibration is repeated as guidelines drift.

Three things these tests hold down, each of which is a way the feature could
look right and be wrong:

* the timestamp used is when the answer was *finalised*, not when the item was
  first opened
* an item enters the window containing its LAST annotator's finish, because
  that is when the item became measurable
* the baseline and a window are only compared when they are the same metric
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from potato.server_utils.iaa import drift


class FakeChange:
    def __init__(self, schema_name, timestamp):
        self.schema_name = schema_name
        self.timestamp = timestamp


class FakeBehaviour:
    def __init__(self, changes=(), session_start=None, session_end=None):
        self.annotation_changes = list(changes)
        self.session_start = session_start
        self.session_end = session_end


class FakeUserState:
    def __init__(self, behaviour):
        self.instance_id_to_behavioral_data = behaviour


# ------------------------------------------------------------- timestamps


class TestWhichTimestamp:
    def test_the_last_change_for_the_schema_wins(self):
        """
        session_start is when the item was OPENED. For a queue skimmed once
        and answered later, that is nowhere near when the answer was given --
        and the answer is what agreement is computed over.
        """
        state = FakeUserState({"a": FakeBehaviour(
            changes=[FakeChange("tone", 100.0), FakeChange("tone", 300.0)],
            session_start=10.0, session_end=400.0)})
        assert drift.annotation_timestamp(state, "a", "tone") == 300.0

    def test_changes_to_other_schemas_are_ignored(self):
        state = FakeUserState({"a": FakeBehaviour(
            changes=[FakeChange("tone", 100.0), FakeChange("topic", 900.0)])})
        assert drift.annotation_timestamp(state, "a", "tone") == 100.0

    def test_no_schema_filter_takes_any_change(self):
        state = FakeUserState({"a": FakeBehaviour(
            changes=[FakeChange("tone", 100.0), FakeChange("topic", 900.0)])})
        assert drift.annotation_timestamp(state, "a") == 900.0

    def test_falls_back_to_session_end_then_start(self):
        end_only = FakeUserState({"a": FakeBehaviour(session_end=50.0,
                                                     session_start=10.0)})
        assert drift.annotation_timestamp(end_only, "a") == 50.0
        start_only = FakeUserState({"a": FakeBehaviour(session_start=10.0)})
        assert drift.annotation_timestamp(start_only, "a") == 10.0

    def test_no_behavioural_data_is_none_not_now(self):
        """
        Defaulting to the current time would pile every migrated annotation
        into the newest window and invent a cliff that is not there.
        """
        assert drift.annotation_timestamp(FakeUserState({}), "a") is None
        assert drift.annotation_timestamp(SimpleNamespace(), "a") is None

    def test_dict_shaped_behavioural_data_works_too(self):
        """user_state.json round-trips these as plain dicts."""
        state = FakeUserState({"a": {
            "annotation_changes": [{"schema_name": "tone", "timestamp": 7.0}],
            "session_end": 99.0,
        }})
        assert drift.annotation_timestamp(state, "a", "tone") == 7.0


class TestItemCompletionTimes:
    def test_an_item_is_placed_by_its_last_annotator(self):
        """
        Agreement is a property of the item across annotators, so the item
        becomes measurable only when the last of them finishes.
        """
        states = {
            "alice": FakeUserState({"x": FakeBehaviour(session_end=100.0)}),
            "bob": FakeUserState({"x": FakeBehaviour(session_end=500.0)}),
        }
        assert drift.item_completion_times(None, states, ["x"]) == {"x": 500.0}

    def test_an_item_nobody_timed_is_absent_rather_than_defaulted(self):
        states = {"alice": FakeUserState({"x": FakeBehaviour()})}
        assert drift.item_completion_times(None, states, ["x"]) == {}


# ---------------------------------------------------------------- windows


class TestSplitWindows:
    def test_equal_count_windows_are_balanced_and_ordered(self):
        times = {f"i{n}": float(n) for n in range(12)}
        windows = drift.split_windows(times, n_windows=3)
        assert [w.n_items for w in windows] == [4, 4, 4]
        assert windows[0].instance_ids == ["i0", "i1", "i2", "i3"]
        assert windows[-1].instance_ids[-1] == "i11"

    def test_windows_never_outnumber_the_items(self):
        """Six windows over five items would leave five of them empty, and an
        empty window's agreement is not a low number -- it is no number."""
        windows = drift.split_windows({"a": 1.0, "b": 2.0}, n_windows=6)
        assert len(windows) == 2

    def test_equal_time_windows_use_duration(self):
        times = {"a": 0.0, "b": 1.0, "c": 100.0}
        windows = drift.split_windows(times, n_windows=2, by="time")
        assert windows[0].instance_ids == ["a", "b"]
        assert windows[1].instance_ids == ["c"]

    def test_all_items_at_one_instant_collapse_to_one_window(self):
        windows = drift.split_windows({"a": 5.0, "b": 5.0}, n_windows=4, by="time")
        assert len(windows) == 1
        assert sorted(windows[0].instance_ids) == ["a", "b"]

    def test_nothing_in_gives_nothing_out(self):
        assert drift.split_windows({}, n_windows=3) == []

    def test_a_small_window_is_flagged_sparse_not_hidden(self):
        windows = drift.split_windows({f"i{n}": float(n) for n in range(4)},
                                      n_windows=2)
        assert all(w.sparse for w in windows)
        assert sum(w.n_items for w in windows) == 4, (
            "sparse windows must still be reported; hiding them makes a small "
            "project look like it has no history")


# --------------------------------------------------------------- headline


class TestHeadlineMetric:
    def test_a_chance_corrected_metric_beats_percent_agreement(self):
        """
        Percent agreement rises with class imbalance alone, so a timeline
        drawn from it can trend upward while annotators agree less than chance
        would predict.
        """
        name, value = drift.headline_metric(
            {"percent_agreement": 0.95, "alpha_nominal": 0.20})
        assert name == "alpha_nominal"
        assert value == pytest.approx(0.20)

    def test_nested_groups_are_reachable(self):
        name, value = drift.headline_metric({"outcome": {"outcome_alpha": 0.5}})
        assert name == "outcome.outcome_alpha"
        assert value == pytest.approx(0.5)

    def test_nan_and_none_are_skipped_for_the_next_candidate(self):
        name, value = drift.headline_metric(
            {"alpha_nominal": float("nan"), "fleiss_kappa": None,
             "cohen_kappa": 0.4})
        assert name == "cohen_kappa"
        assert value == pytest.approx(0.4)

    def test_a_bool_is_not_a_metric(self):
        """`True` is an int in Python, and 1.0 agreement is a strong claim."""
        assert drift.headline_metric({"percent_agreement": True}) == (None, None)

    def test_nothing_usable_returns_nothing(self):
        assert drift.headline_metric({}) == (None, None)
        assert drift.headline_metric({"n_items": 4}) == (None, None)
        assert drift.headline_metric("not a dict") == (None, None)


# ---------------------------------------------------------------- triggers


def series(baseline, values, metric="alpha_nominal", n_items=20):
    return {"tone": {
        "metric": metric,
        "baseline": baseline,
        "points": [{"window": i, "value": v, "n_items": n_items,
                    "sparse": n_items < drift.MIN_ITEMS_PER_WINDOW}
                   for i, v in enumerate(values)],
    }}


class TestDropDetection:
    def test_a_fall_past_the_threshold_fires(self):
        triggers = drift._find_drops(series(0.80, [0.80, 0.60]), [], 0.15)
        assert len(triggers) == 1
        assert triggers[0]["schema"] == "tone"
        assert triggers[0]["relative_drop"] == pytest.approx(0.25)

    def test_a_fall_short_of_the_threshold_does_not(self):
        assert drift._find_drops(series(0.80, [0.80, 0.75]), [], 0.15) == []

    def test_only_the_latest_window_is_judged(self):
        """
        A dip the team already recovered from is history, not a call to
        action, and firing on it trains people to ignore the prompt.
        """
        assert drift._find_drops(series(0.80, [0.80, 0.30, 0.82]), [], 0.15) == []

    def test_a_sparse_latest_window_falls_through_to_a_real_one(self):
        entry = series(0.80, [0.80, 0.30])
        entry["tone"]["points"].append(
            {"window": 2, "value": 0.05, "n_items": 1, "sparse": True})
        triggers = drift._find_drops(entry, [], 0.15)
        assert len(triggers) == 1
        assert triggers[0]["window"] == 1, (
            "the one-item window must not be what fires the prompt")

    def test_a_baseline_at_or_below_zero_is_not_a_relative_drop(self):
        """
        Agreement already at chance is a problem the whole-project number
        reports. A percentage fall from zero is arithmetic, not a finding.
        """
        assert drift._find_drops(series(0.0, [0.0, -0.4]), [], 0.15) == []
        assert drift._find_drops(series(-0.2, [-0.2, -0.9]), [], 0.15) == []

    def test_windows_with_no_value_are_skipped(self):
        assert drift._find_drops(series(0.80, [0.80, None]), [], 0.15) == []

    def test_the_worst_drop_is_reported_first(self):
        entries = series(0.80, [0.80, 0.60])
        entries["topic"] = {
            "metric": "alpha_nominal", "baseline": 0.90,
            "points": [{"window": 0, "value": 0.90, "n_items": 20,
                        "sparse": False},
                       {"window": 1, "value": 0.20, "n_items": 20,
                        "sparse": False}],
        }
        triggers = drift._find_drops(entries, [], 0.15)
        assert [t["schema"] for t in triggers] == ["topic", "tone"]


class TestSeriesComparability:
    def test_a_window_scored_with_a_different_metric_is_not_compared(self):
        """
        A window too small for alpha may still produce percent_agreement.
        Plotting that against an alpha baseline compares two different
        measures and would read as a collapse.
        """
        windows = [drift.Window(index=0, start=0, end=1, instance_ids=["a"]),
                   drift.Window(index=1, start=2, end=3, instance_ids=["b"])]
        windows[0].schemas = {"tone": {"metrics": {"alpha_nominal": 0.8}}}
        windows[1].schemas = {"tone": {"metrics": {"percent_agreement": 0.95}}}
        built = drift._build_series(
            windows, {"tone": {"metrics": {"alpha_nominal": 0.8}}})
        assert built["tone"]["metric"] == "alpha_nominal"
        assert built["tone"]["points"][0]["value"] == pytest.approx(0.8)
        assert built["tone"]["points"][1]["value"] is None

    def test_the_baseline_is_the_project_figure_not_the_first_window(self):
        """
        A first window that happens to be unusually good would set the bar for
        the whole study -- and the first window is exactly where an
        uncalibrated team's numbers are least stable.
        """
        windows = [drift.Window(index=0, start=0, end=1, instance_ids=["a"])]
        windows[0].schemas = {"tone": {"metrics": {"alpha_nominal": 0.99}}}
        built = drift._build_series(
            windows, {"tone": {"metrics": {"alpha_nominal": 0.55}}})
        assert built["tone"]["baseline"] == pytest.approx(0.55)


# ----------------------------------------------------------------- report


class FakeISM:
    def __init__(self, instance_annotators):
        self.instance_annotators = instance_annotators

    def iter_items(self):
        return [(iid, object()) for iid in self.instance_annotators]

    def _get_annotator_cap_for_item(self, iid):
        return 2

    def find_item(self, iid):
        return None


class FakeUSM:
    def __init__(self, states):
        self._states = states

    def get_user_state(self, uid):
        return self._states.get(uid)


class TestEmptyStatesExplainThemselves:
    def test_no_overlap_items_says_so(self):
        report = drift.compute_agreement_over_time(
            FakeISM({}), FakeUSM({}), {"annotation_schemes": [
                {"annotation_type": "radio", "name": "tone",
                 "description": "d", "labels": ["a", "b"]}]})
        assert report["windows"] == []
        assert "annotator cap" in report["reason"]

    def test_untimed_items_say_so(self, monkeypatch):
        """
        A project migrated in from another tool has annotations and no
        timestamps. The admin page must be able to say why the chart is
        missing rather than drawing an empty one.
        """
        monkeypatch.setattr(
            drift, "compute_overlap_iaa",
            lambda *a, **k: {"schemas": {}, "items": {"x": {}}, "n_overlap_items": 1})
        report = drift.compute_agreement_over_time(
            FakeISM({"x": {"alice"}}), FakeUSM({"alice": FakeUserState({})}), {})
        assert "timestamp" in report["reason"]
        assert report["windows"] == []

    def test_one_window_is_not_a_trend(self):
        completion = {"x": 1.0}
        assert len(drift.split_windows(completion, n_windows=6)) == 1


class TestMarkers:
    def test_a_missing_codebook_database_yields_no_markers(self, tmp_path):
        """An admin page must not 500 because a project has no codebook."""
        assert drift.codebook_markers(str(tmp_path), "nonexistent") == []

    def test_recorded_bumps_are_exact_and_inferred_ones_are_flagged(self, tmp_path):
        from potato.codebook import revision as rev

        rev.bump_revision(str(tmp_path), "proj")   # -> revision 1, recorded
        markers = drift.codebook_markers(str(tmp_path), "proj")
        assert [m["revision"] for m in markers] == [1]
        assert markers[0]["inferred"] is False

        # A revision that only shows up on an annotation is a lower bound.
        conn = rev._db(str(tmp_path))
        conn.execute(
            """INSERT INTO annotation_provenance
                   (project, instance_id, username, revision, updated_at)
               VALUES ('proj', 'i1', 'alice', 7, 1000.0)""")
        conn.commit()
        markers = drift.codebook_markers(str(tmp_path), "proj")
        by_revision = {m["revision"]: m for m in markers}
        assert by_revision[7]["inferred"] is True
        assert by_revision[7]["created_at"] == pytest.approx(1000.0)

    def test_markers_are_ordered_by_time(self, tmp_path):
        from potato.codebook import revision as rev

        rev.bump_revision(str(tmp_path), "proj")
        rev.bump_revision(str(tmp_path), "proj")
        markers = drift.codebook_markers(str(tmp_path), "proj")
        stamps = [m["created_at"] for m in markers]
        assert stamps == sorted(stamps)
