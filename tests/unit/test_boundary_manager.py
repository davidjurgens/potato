"""Unit tests for Boundary Lab state management (potato/boundary/manager.py)."""

import json
import os

import pytest

from potato.boundary.manager import (
    BoundaryManager,
    clear_boundary_manager,
    get_boundary_manager,
    init_boundary_manager,
)
from tests.helpers.test_utils import create_test_directory


ITEM_DATA = {"counterfactuals": [
    {"text": "Send the report.", "kind": "flip", "edit_hint": "removed please"},
    {"text": "Please send over the report.", "kind": "invariance"},
]}


def make_config(test_dir, **overrides):
    config = {
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "annotation_schemes": [{
            "annotation_type": "radio", "name": "politeness",
            "labels": ["Polite", "Impolite"],
        }],
        "boundary_probing": {
            "enabled": True,
            "schema": "politeness",
            # Budget of 2 (1 flip + 1 invariance) so the two precomputed
            # counterfactuals in ITEM_DATA fill it exactly and the rules
            # tier contributes nothing.
            "probes_per_item": 2,
            "sources": ["precomputed", "rules"],
        },
    }
    config["boundary_probing"].update(overrides)
    return config


@pytest.fixture()
def manager():
    test_dir = create_test_directory("boundary_manager")
    mgr = BoundaryManager(make_config(test_dir))
    yield mgr
    clear_boundary_manager()


class TestProbeCache:
    def test_generates_and_caches(self, manager):
        first = manager.get_or_generate_probes(
            "i1", "politeness", "Polite", ["Polite", "Impolite"],
            "Please send the report.", item_data=ITEM_DATA)
        second = manager.get_or_generate_probes(
            "i1", "politeness", "Polite", ["Polite", "Impolite"],
            "Please send the report.", item_data=ITEM_DATA)
        assert first == second
        assert len(first) == 2

    def test_probes_persist_to_disk(self, manager):
        manager.get_or_generate_probes(
            "i1", "politeness", "Polite", ["Polite", "Impolite"],
            "Please send the report.", item_data=ITEM_DATA)
        path = manager._probes_path()
        assert os.path.exists(path)
        with open(path) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert len(lines) == 2
        assert {l["kind"] for l in lines} == {"flip", "invariance"}

    def test_different_labels_get_distinct_probe_sets(self, manager):
        a = manager.get_or_generate_probes(
            "i1", "politeness", "Polite", ["Polite", "Impolite"],
            "Please send the report.", item_data=ITEM_DATA)
        b = manager.get_or_generate_probes(
            "i1", "politeness", "Impolite", ["Polite", "Impolite"],
            "Please send the report.", item_data=ITEM_DATA)
        assert {p["probe_id"] for p in a}.isdisjoint({p["probe_id"] for p in b})


class TestResponses:
    def _probe_ids(self, manager):
        probes = manager.get_or_generate_probes(
            "i1", "politeness", "Polite", ["Polite", "Impolite"],
            "Please send the report.", item_data=ITEM_DATA)
        return {p["kind"]: p["probe_id"] for p in probes}

    def test_record_and_fetch(self, manager):
        ids = self._probe_ids(manager)
        manager.record_response("alice", ids["flip"], "flips",
                                new_label="Impolite", rationale="lost the please")
        responses = manager.get_user_responses("alice", "i1", "politeness", "Polite")
        assert responses[ids["flip"]]["verdict"] == "flips"
        assert responses[ids["flip"]]["new_label"] == "Impolite"
        # Other users see none
        assert manager.get_user_responses("bob", "i1", "politeness", "Polite") == {}

    def test_invalid_verdict_rejected(self, manager):
        ids = self._probe_ids(manager)
        with pytest.raises(ValueError):
            manager.record_response("alice", ids["flip"], "maybe")

    def test_unknown_probe_rejected(self, manager):
        with pytest.raises(KeyError):
            manager.record_response("alice", "nonexistent", "holds")

    def test_new_label_only_kept_on_flips(self, manager):
        ids = self._probe_ids(manager)
        record = manager.record_response("alice", ids["invariance"], "holds",
                                         new_label="Impolite")
        assert record["new_label"] is None

    def test_reload_from_disk(self, manager):
        ids = self._probe_ids(manager)
        manager.record_response("alice", ids["flip"], "flips", new_label="Impolite")
        # Fresh manager over the same storage dir
        reloaded = BoundaryManager(manager.app_config)
        responses = reloaded.get_user_responses("alice", "i1", "politeness", "Polite")
        assert responses[ids["flip"]]["verdict"] == "flips"


class TestStatsAndExport:
    def _seed(self, manager):
        ids = {p["kind"]: p["probe_id"] for p in manager.get_or_generate_probes(
            "i1", "politeness", "Polite", ["Polite", "Impolite"],
            "Please send the report.", item_data=ITEM_DATA)}
        manager.record_response("alice", ids["flip"], "flips",
                                new_label="Impolite", rationale="lost the please")
        manager.record_response("alice", ids["invariance"], "holds")
        manager.record_response("bob", ids["flip"], "holds")
        manager.record_response("bob", ids["invariance"], "flips", new_label="Impolite")
        return ids

    def test_stats_totals(self, manager):
        self._seed(manager)
        stats = manager.get_stats()
        totals = stats["totals"]
        assert totals["contrast_pairs"] == 4
        assert totals["flips"] == 2
        assert totals["holds"] == 2
        assert totals["annotators"] == 2
        assert totals["rationales"] == 1

    def test_label_sensitivity(self, manager):
        self._seed(manager)
        sens = manager.get_stats()["label_sensitivity"]["Polite"]
        # flip-kind probes: alice flipped, bob held
        assert sens["flips"] == 1
        assert sens["holds"] == 1
        assert sens["flip_rate"] == 0.5

    def test_invariance_consistency_flags_bob(self, manager):
        self._seed(manager)
        annotators = manager.get_stats()["annotators"]
        assert annotators["alice"]["invariance_consistency"] == 1.0
        assert annotators["bob"]["invariance_consistency"] == 0.0

    def test_export_contrast_set(self, manager):
        self._seed(manager)
        records = manager.export_contrast_set()
        assert len(records) == 4
        flipped = [r for r in records if r["flipped"]]
        held = [r for r in records if not r["flipped"]]
        assert all(r["counterfactual_label"] == "Impolite" for r in flipped)
        assert all(r["counterfactual_label"] == r["original_label"] for r in held)
        required_keys = {"instance_id", "original_text", "original_label",
                         "counterfactual_text", "counterfactual_label", "kind",
                         "flipped", "rationale", "annotator", "probe_source"}
        assert required_keys <= set(records[0].keys())

    def test_latest_response_wins(self, manager):
        ids = self._seed(manager)
        manager.record_response("alice", ids["flip"], "holds")
        stats = manager.get_stats()
        assert stats["totals"]["flips"] == 1  # only bob's invariance flip remains


class TestSingleton:
    def test_init_requires_enabled(self):
        test_dir = create_test_directory("boundary_singleton")
        config = make_config(test_dir)
        config["boundary_probing"]["enabled"] = False
        assert init_boundary_manager(config) is None
        assert get_boundary_manager() is None

    def test_init_and_clear(self):
        test_dir = create_test_directory("boundary_singleton2")
        mgr = init_boundary_manager(make_config(test_dir))
        assert mgr is not None
        assert get_boundary_manager() is mgr
        clear_boundary_manager()
        assert get_boundary_manager() is None
