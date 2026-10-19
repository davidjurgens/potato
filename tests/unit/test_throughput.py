"""
Throughput per annotator: active time, items per active hour, median time per
item, per day, and first-pass approval / rework from the review workflow.
Every expected number below is worked out by hand from the events.
"""

from datetime import datetime, timezone

import pytest

from potato.throughput import compute_throughput, review_outcomes

DAY1 = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc).timestamp()
DAY2 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc).timestamp()


def visit(iid, *offsets, start=DAY1):
    """A behavioral record with one click at each offset (seconds)."""
    return {"instance_id": iid, "interactions": [
        {"event_type": "click", "timestamp": start + o, "target": "label:x", "instance_id": iid}
        for o in offsets]}


BEHAVIOR = {
    "a": {"i1": visit("i1", 0, 30, 60),            # 60 s
          "i2": visit("i2", 0, 90, start=DAY2),     # 90 s, on the second day
          "i3": visit("i3", 0, 500)},               # opened, never saved
    "b": {"i1": visit("i1", 0, 1000)},              # one 1000 s gap, capped at 300 s
}
SAVED = {"a": ["i1", "i2"], "b": ["i1"], "c": ["i9"]}  # c's answer has no events


def row(report, who):
    return next(r for r in report["annotators"] if r["annotator"] == who)


class TestRates:
    def test_per_annotator(self):
        report = compute_throughput(BEHAVIOR, SAVED)
        a, b = row(report, "a"), row(report, "b")
        # a: 2 items in 150 s -> 2 / (150/3600) = 48 per hour; median of 60, 90.
        assert (a["items"], a["items_timed"], a["items_per_active_hour"], a["median_active_seconds"]) == (
            2, 2, 48.0, 75.0)
        assert a["active_hours"] == pytest.approx(150 / 3600, abs=1e-3)
        # b: the idle gap is capped at 300 s -> 12 per hour.
        assert (b["items_per_active_hour"], b["median_active_seconds"]) == (12.0, 300.0)

    def test_the_project_and_untimed_items(self):
        report = compute_throughput(BEHAVIOR, SAVED)
        project = report["project"]
        # 3 timed items in 450 s -> 24 per hour; median of 60, 90, 300.
        assert (project["items"], project["items_timed"]) == (4, 3)
        assert (project["items_per_active_hour"], project["median_active_seconds"]) == (24.0, 90.0)
        assert "1 saved item(s) have no interaction events" in report["note"]
        c = row(report, "c")
        assert (c["items"], c["items_per_active_hour"], c["median_active_seconds"]) == (1, None, None)

    def test_by_day(self):
        a = row(compute_throughput(BEHAVIOR, SAVED), "a")
        assert [(d["day"], d["items"], d["items_per_active_hour"]) for d in a["by_day"]] == [
            ("2026-10-19", 1, 60.0), ("2026-10-20", 1, 40.0)]
        project_days = compute_throughput(BEHAVIOR, SAVED)["project"]["by_day"]
        assert [d["day"] for d in project_days] == ["2026-10-19", "2026-10-20", "no events"]

    def test_short_work_keeps_its_seconds(self):
        """Found in Chrome: 1.7 s of work, rounded to hours, displayed as 0s."""
        quick = {"q": {"i1": visit("i1", 0, 1.7)}}
        q = row(compute_throughput(quick, {"q": ["i1"]}), "q")
        assert q["active_seconds"] == 1.7
        assert q["active_hours"] == 0.0  # why the page must not format this one

    def test_attention_and_gold_items_are_counted_apart(self):
        """Suggested by the potato-skill agent: check items are not work on
        the data and inflated the rate of a heavily checked study."""
        behavior = {"a": {**BEHAVIOR["a"], "check1": visit("check1", 0, 5)}}
        report = compute_throughput(behavior, {"a": ["i1", "i2", "check1"]}, qc_items={"check1"})
        a = row(report, "a")
        assert (a["items"], a["qc_items"], a["items_per_active_hour"]) == (2, 1, 48.0)
        assert report["project"]["qc_items"] == 1

    def test_time_on_an_item_never_saved_counts_for_nothing(self):
        a = row(compute_throughput(BEHAVIOR, SAVED), "a")
        assert a["active_hours"] == pytest.approx(150 / 3600, abs=1e-3)  # i3's 300 s left out

    def test_stored_records_and_live_objects_agree(self):
        from potato.interaction_tracking import BehavioralData
        live = {u: {i: BehavioralData.from_dict(d) for i, d in items.items()}
                for u, items in BEHAVIOR.items()}
        assert compute_throughput(live, SAVED) == compute_throughput(BEHAVIOR, SAVED)


class TestReview:
    TRANSITIONS = [
        {"instance_id": "i1", "from_state": None, "to_state": "pending", "at": 1},
        {"instance_id": "i1", "from_state": "pending", "to_state": "in_review", "at": 2},
        {"instance_id": "i1", "from_state": "in_review", "to_state": "done", "at": 3},
        {"instance_id": "i2", "from_state": None, "to_state": "pending", "at": 1},
        {"instance_id": "i2", "from_state": "pending", "to_state": "in_review", "at": 2},
        {"instance_id": "i2", "from_state": "in_review", "to_state": "pending", "at": 3},
        {"instance_id": "i2", "from_state": "pending", "to_state": "in_review", "at": 4},
        {"instance_id": "i2", "from_state": "in_review", "to_state": "done", "at": 5},
    ]

    def test_outcomes(self):
        assert review_outcomes(self.TRANSITIONS) == {
            "i1": {"done": True, "sent_back": False},
            "i2": {"done": True, "sent_back": True}}

    def test_first_pass_approval_and_rework(self):
        report = compute_throughput(BEHAVIOR, SAVED, self.TRANSITIONS)
        a, b = row(report, "a"), row(report, "b")
        assert (a["reviewed_items"], a["first_pass_approval"], a["rework_rate"]) == (2, 0.5, 0.5)
        assert (b["first_pass_approval"], b["rework_rate"]) == (1.0, 0.0)
        assert row(report, "c")["first_pass_approval"] is None
        assert report["review_enabled"] is True

    def test_without_review_the_fields_are_absent(self):
        report = compute_throughput(BEHAVIOR, SAVED)
        assert report["review_enabled"] is False
        assert "first_pass_approval" not in row(report, "a")
