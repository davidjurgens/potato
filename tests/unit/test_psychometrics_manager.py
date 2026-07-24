"""Unit tests for the psychometrics manager (config, refits, routing)."""

import pytest

from potato.psychometrics.config import parse_psychometrics_config
from potato.psychometrics.manager import (
    PsychometricsManager,
    clear_psychometrics_manager,
    get_psychometrics_manager,
    init_psychometrics_manager,
)
from tests.unit.test_psychometrics_irt import synthetic_observations


def make_config(**overrides):
    config = {
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "sarcasm",
             "labels": ["Sarcastic", "Sincere"]},
        ],
        "psychometrics": {"enabled": True, "min_observations": 10,
                          "refit_interval": 5},
    }
    config["psychometrics"].update(overrides.pop("psychometrics", {}))
    config.update(overrides)
    return config


def make_manager(observations, **overrides):
    manager = PsychometricsManager(make_config(**overrides))
    manager.collect_observations = lambda: list(observations)
    return manager


class TestConfigParsing:
    def test_defaults_and_schema_autopick(self):
        ps = parse_psychometrics_config(make_config())
        assert ps.enabled
        assert ps.schema == "sarcasm"
        assert ps.refit_interval == 5
        assert ps.confidence_threshold == 0.95

    def test_explicit_schema_wins(self):
        ps = parse_psychometrics_config(
            make_config(psychometrics={"schema": "other"})
        )
        assert ps.schema == "other"

    def test_bad_threshold_falls_back(self):
        ps = parse_psychometrics_config(
            make_config(psychometrics={"confidence_threshold": 3.0})
        )
        assert ps.confidence_threshold == 0.95

    def test_disabled_by_default(self):
        assert not parse_psychometrics_config({}).enabled


class TestSingleton:
    def test_init_get_clear(self):
        init_psychometrics_manager(make_config())
        assert get_psychometrics_manager() is not None
        clear_psychometrics_manager()
        assert get_psychometrics_manager() is None

    def test_disabled_config_leaves_none(self):
        init_psychometrics_manager({"psychometrics": {"enabled": False}})
        assert get_psychometrics_manager() is None


class TestRefitCaching:
    def test_model_cached_until_interval(self):
        observations, _, _ = synthetic_observations(n_items=20)
        store = list(observations)
        manager = make_manager(store)
        m1 = manager.get_model()
        assert m1.fitted
        # Fewer new labels than refit_interval: same snapshot object.
        store.append(("item000", "newbie", "neg"))
        manager.collect_observations = lambda: list(store)
        assert manager.get_model() is m1
        # force always refits
        m2 = manager.get_model(force=True)
        assert m2 is not m1

    def test_refits_after_interval_new_labels(self):
        observations, _, _ = synthetic_observations(n_items=20)
        store = list(observations)
        manager = make_manager(store)
        m1 = manager.get_model()
        for i in range(5):  # refit_interval == 5
            store.append((f"item{i:03d}", "newbie", "neg"))
        manager.collect_observations = lambda: list(store)
        m2 = manager.get_model()
        assert m2 is not m1
        assert m2.num_observations == m1.num_observations + 5


class TestRouting:
    def test_cold_start_returns_none(self):
        observations, _, _ = synthetic_observations(n_items=20)
        manager = make_manager(
            observations[:5], psychometrics={"min_observations": 50}
        )
        assert manager.rank_items("anyone", ["item000", "item001"]) is None

    def test_resolved_items_are_excluded(self):
        observations, _, _ = synthetic_observations()
        manager = make_manager(
            observations,
            psychometrics={"min_observations": 10,
                           "confidence_threshold": 0.9,
                           "min_annotators_per_item": 2},
        )
        model = manager.get_model()
        candidates = model.item_ids()
        ranked = manager.rank_items("expert1", candidates)
        assert ranked is not None

        reports = {i: model.item_report(i) for i in candidates}
        resolved = {i for i, r in reports.items()
                    if r.prob >= 0.9 and r.n_annotators >= 2}
        unresolved = set(candidates) - resolved
        assert resolved, "synthetic data should resolve some items at 0.9"
        assert unresolved, "synthetic data should leave some items uncertain"
        # The early stop: resolved items never come back from rank_items.
        assert set(ranked) == unresolved

    def test_all_resolved_returns_empty_list_not_none(self):
        # Distinction matters: None = cold-start fallback (assign randomly),
        # [] = everything is measured (assign nothing, save the budget).
        observations, _, _ = synthetic_observations()
        manager = make_manager(
            observations,
            psychometrics={"min_observations": 10,
                           "confidence_threshold": 0.5,
                           "min_annotators_per_item": 1},
        )
        model = manager.get_model()
        resolved = [i for i in model.item_ids()
                    if model.item_report(i).prob >= 0.5]
        assert manager.rank_items("expert1", resolved) == []

    def test_ranking_is_deterministic(self):
        observations, _, _ = synthetic_observations()
        manager = make_manager(observations)
        candidates = manager.get_model().item_ids()
        assert manager.rank_items("ok1", candidates) == manager.rank_items(
            "ok1", candidates
        )

    def test_unknown_items_still_ranked(self):
        observations, _, _ = synthetic_observations()
        manager = make_manager(observations)
        model = manager.get_model()
        # Pair a brand-new item with the most uncertain known item (a known
        # RESOLVED item would rightly be excluded by the early stop).
        uncertain = max(model.item_ids(),
                        key=lambda i: model.item_report(i).entropy)
        ranked = manager.rank_items("ok1", ["never_seen_1", uncertain])
        assert ranked is not None
        assert set(ranked) == {"never_seen_1", uncertain}


class TestStatsPayload:
    def test_stats_shape_when_fitted(self):
        observations, _, _ = synthetic_observations()
        manager = make_manager(
            observations, num_annotators_per_item=6,
            psychometrics={"cost_per_judgment": 0.08},
        )
        stats = manager.get_stats()
        assert stats["fitted"]
        assert stats["n_annotators"] == 5
        assert len(stats["annotators"]) == 5
        assert stats["annotators"][0]["theta"] >= stats["annotators"][-1]["theta"]
        assert len(stats["items"]) == 60
        row = stats["items"][0]
        for key in ("instance_id", "map_label", "prob", "prob_lo", "prob_hi",
                    "entropy", "difficulty", "n_annotators", "resolved"):
            assert key in row
        # Items are sorted most-uncertain first.
        entropies = [r["entropy"] for r in stats["items"]]
        assert entropies == sorted(entropies, reverse=True)
        assert stats["summary"]["target_annotators_per_item"] == 6
        assert "saved_cost" in stats["summary"]

    def test_stats_degenerate_when_empty(self):
        manager = make_manager([])
        stats = manager.get_stats()
        assert not stats["fitted"]
        assert stats["n_observations"] == 0
        assert stats["items"] == []

    def test_export_shape(self):
        observations, _, _ = synthetic_observations(n_items=10)
        manager = make_manager(observations)
        export = manager.export_records()
        assert export["fitted"]
        assert len(export["items"]) == 10
        item = export["items"][0]
        assert abs(sum(item["posterior"].values()) - 1.0) < 1e-6
        assert item["prob_lo"] <= item["prob"] <= item["prob_hi"] + 1e-9
        assert len(export["annotators"]) == 5
