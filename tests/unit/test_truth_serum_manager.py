"""Unit tests for Truth Serum scoring (potato/truth_serum/manager.py)."""

import os

import pytest

from potato.truth_serum.config import parse_truth_serum_config
from potato.truth_serum.manager import (
    TruthSerumManager,
    clear_truth_serum_manager,
    get_truth_serum_manager,
    init_truth_serum_manager,
)
from tests.helpers.test_utils import create_test_directory


def make_config(test_dir, **overrides):
    config = {
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "annotation_schemes": [{
            "annotation_type": "radio", "name": "capital",
            "labels": ["Yes", "No"],
        }],
        "truth_serum": {"enabled": True, "schema": "capital", "min_annotators": 3},
    }
    config["truth_serum"].update(overrides)
    return config


@pytest.fixture()
def manager():
    test_dir = create_test_directory("truth_serum_manager")
    mgr = TruthSerumManager(make_config(test_dir))
    yield mgr
    clear_truth_serum_manager()


class TestConfig:
    def test_disabled_by_default(self):
        assert parse_truth_serum_config({}).enabled is False

    def test_defaults_schema_to_first_radio(self):
        config = {
            "truth_serum": {"enabled": True},
            "annotation_schemes": [
                {"annotation_type": "span", "name": "spans"},
                {"annotation_type": "radio", "name": "sentiment"},
            ],
        }
        assert parse_truth_serum_config(config).schema == "sentiment"

    def test_min_annotators_floor(self):
        config = {"truth_serum": {"enabled": True, "min_annotators": 1}}
        assert parse_truth_serum_config(config).min_annotators == 2


class TestRecording:
    def test_record_and_get(self, manager):
        manager.record_prediction("alice", "i1", "Yes", 80)
        record = manager.get_prediction("alice", "i1")
        assert record["label"] == "Yes"
        assert record["predicted_pct"] == 80.0
        assert manager.get_prediction("bob", "i1") is None

    def test_latest_wins(self, manager):
        manager.record_prediction("alice", "i1", "Yes", 80)
        manager.record_prediction("alice", "i1", "No", 60)
        record = manager.get_prediction("alice", "i1")
        assert record["label"] == "No"
        assert record["predicted_pct"] == 60.0

    def test_out_of_range_rejected(self, manager):
        with pytest.raises(ValueError):
            manager.record_prediction("alice", "i1", "Yes", 130)
        with pytest.raises(ValueError):
            manager.record_prediction("alice", "i1", "Yes", -5)

    def test_reload_from_disk(self, manager):
        manager.record_prediction("alice", "i1", "Yes", 80)
        manager.record_prediction("alice", "i1", "No", 60)  # revision
        reloaded = TruthSerumManager(manager.app_config)
        record = reloaded.get_prediction("alice", "i1")
        assert record["label"] == "No"  # latest wins across reload too


class TestSurprisinglyPopular:
    def _seed_philadelphia(self, manager):
        """The canonical SP scenario: 'Is Philadelphia the capital of PA?'

        Majority wrongly says Yes and overpredicts agreement; the informed
        minority says No while correctly predicting most will say Yes (so
        their own-answer popularity prediction is LOW).
        """
        manager.record_prediction("u1", "i1", "Yes", 90)
        manager.record_prediction("u2", "i1", "Yes", 85)
        manager.record_prediction("u3", "i1", "Yes", 80)
        manager.record_prediction("u4", "i1", "No", 25)   # knows they're a minority
        manager.record_prediction("u5", "i1", "No", 30)

    def test_sp_beats_majority(self, manager):
        self._seed_philadelphia(manager)
        results = manager.compute_item_results()
        assert len(results) == 1
        r = results[0]
        assert r["majority_label"] == "Yes"
        # Yes: actual 60% vs predicted 85% (surprise -25)
        # No:  actual 40% vs predicted 27.5% (surprise +12.5)
        assert r["sp_label"] == "No"
        assert r["disagrees"] is True

    def test_no_verdict_below_min_annotators(self, manager):
        manager.record_prediction("u1", "i1", "Yes", 90)
        manager.record_prediction("u2", "i1", "No", 40)
        assert manager.compute_item_results() == []

    def test_unanimous_item_agrees_with_majority(self, manager):
        for user in ("u1", "u2", "u3"):
            manager.record_prediction(user, "i2", "Yes", 90)
        r = manager.compute_item_results()[0]
        assert r["majority_label"] == "Yes"
        assert r["sp_label"] == "Yes"
        assert r["disagrees"] is False

    def test_majority_tie_flagged(self, manager):
        manager.record_prediction("u1", "i3", "Yes", 50)
        manager.record_prediction("u2", "i3", "Yes", 50)
        manager.record_prediction("u3", "i3", "No", 50)
        manager.record_prediction("u4", "i3", "No", 50)
        r = manager.compute_item_results()[0]
        assert r["majority_tied"] is True


class TestAnnotatorScores:
    def test_calibration_and_alignment(self, manager):
        # u1..u3 say Yes; u4, u5 say No (SP verdict: No, as above)
        manager.record_prediction("u1", "i1", "Yes", 90)
        manager.record_prediction("u2", "i1", "Yes", 85)
        manager.record_prediction("u3", "i1", "Yes", 80)
        manager.record_prediction("u4", "i1", "No", 25)
        manager.record_prediction("u5", "i1", "No", 30)
        scores = manager.compute_annotator_scores()

        # u1: 2 of 4 others agreed -> actual 50; predicted 90 -> error 40
        assert scores["u1"]["calibration_error"] == 40.0
        # u4: 1 of 4 others agreed -> actual 25; predicted 25 -> error 0
        assert scores["u4"]["calibration_error"] == 0.0
        # SP verdict is No: u4/u5 aligned, u1..u3 not
        assert scores["u4"]["sp_alignment"] == 1.0
        assert scores["u1"]["sp_alignment"] == 0.0

    def test_unscored_items_still_counted_as_predictions(self, manager):
        manager.record_prediction("solo", "lonely", "Yes", 70)
        scores = manager.compute_annotator_scores()
        assert scores["solo"]["predictions"] == 1
        assert scores["solo"]["calibration_error"] is None
        assert scores["solo"]["sp_alignment"] is None


class TestStatsAndExport:
    def test_stats_shape(self, manager):
        for user, label, pct in (("u1", "Yes", 90), ("u2", "Yes", 85),
                                 ("u3", "No", 20)):
            manager.record_prediction(user, "i1", label, pct)
        stats = manager.get_stats()
        assert stats["totals"]["predictions"] == 3
        assert stats["totals"]["items_with_verdicts"] == 1
        assert stats["totals"]["annotators"] == 3
        assert len(stats["items"]) == 1
        assert stats["disagreements"] == [i for i in stats["items"] if i["disagrees"]]

    def test_export_includes_raw_predictions(self, manager):
        manager.record_prediction("u1", "i1", "Yes", 90)
        export = manager.export_records()
        assert export["schema"] == "capital"
        assert len(export["predictions"]) == 1
        assert export["predictions"][0]["username"] == "u1"


class TestSingleton:
    def test_init_requires_enabled(self):
        test_dir = create_test_directory("truth_serum_singleton")
        config = make_config(test_dir)
        config["truth_serum"]["enabled"] = False
        assert init_truth_serum_manager(config) is None
        assert get_truth_serum_manager() is None

    def test_init_and_clear(self):
        test_dir = create_test_directory("truth_serum_singleton2")
        mgr = init_truth_serum_manager(make_config(test_dir))
        assert mgr is not None
        assert get_truth_serum_manager() is mgr
        clear_truth_serum_manager()
        assert get_truth_serum_manager() is None
