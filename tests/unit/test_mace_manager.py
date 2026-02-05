"""Tests for the MACE manager integration layer."""

import json
import os
import tempfile

import pytest
from unittest.mock import MagicMock

from potato.mace_manager import (
    MACEConfig,
    MACEManager,
    MACEResult,
    init_mace_manager,
    get_mace_manager,
    clear_mace_manager,
)


class FakeLabel:
    """Minimal Label stand-in for testing."""

    def __init__(self, schema, name):
        self.schema = schema
        self.name = name

    def get_schema(self):
        return self.schema

    def get_name(self):
        return self.name

    def __repr__(self):
        return f"FakeLabel({self.schema}, {self.name})"


class FakeUserState:
    """Minimal UserState stand-in for testing."""

    def __init__(self, user_id, label_data=None):
        self.user_id = user_id
        self.instance_id_to_label_to_value = label_data or {}


class TestMACEConfig:
    """Test MACEConfig dataclass."""

    def test_defaults(self):
        cfg = MACEConfig()
        assert cfg.enabled is False
        assert cfg.trigger_every_n == 10
        assert cfg.min_annotations_per_item == 3
        assert cfg.min_items == 5
        assert cfg.num_restarts == 10
        assert cfg.num_iters == 50
        assert cfg.alpha == 0.5
        assert cfg.beta == 0.5
        assert cfg.output_subdir == "mace"
        assert cfg.cache_results is True

    def test_from_dict(self):
        cfg = MACEConfig.from_dict({
            "enabled": True,
            "trigger_every_n": 20,
            "min_annotations_per_item": 5,
            "unknown_key": "ignored",
        })
        assert cfg.enabled is True
        assert cfg.trigger_every_n == 20
        assert cfg.min_annotations_per_item == 5
        # Defaults for unspecified
        assert cfg.min_items == 5

    def test_from_empty_dict(self):
        cfg = MACEConfig.from_dict({})
        assert cfg.enabled is False


class TestMACEResult:
    """Test MACEResult serialization."""

    def test_round_trip(self):
        result = MACEResult(
            schema_name="sentiment",
            competence_scores={"user1": 0.9, "user2": 0.3},
            predicted_labels={"item1": "positive", "item2": "negative"},
            label_entropy={"item1": 0.1, "item2": 0.5},
            label_mapping={0: "negative", 1: "positive"},
            num_annotators=2,
            num_instances=2,
            timestamp="2025-01-01T00:00:00",
            log_likelihood=-10.5,
            option_name=None,
        )
        d = result.to_dict()
        restored = MACEResult.from_dict(d)
        assert restored.schema_name == "sentiment"
        assert restored.competence_scores["user1"] == 0.9
        assert restored.predicted_labels["item1"] == "positive"
        assert restored.option_name is None

    def test_with_option_name(self):
        result = MACEResult(
            schema_name="topics",
            competence_scores={"u1": 0.8},
            predicted_labels={"i1": "1"},
            label_entropy={"i1": 0.2},
            label_mapping={0: "0", 1: "1"},
            num_annotators=1,
            num_instances=1,
            timestamp="2025-01-01",
            log_likelihood=-5.0,
            option_name="food",
        )
        d = result.to_dict()
        assert d["option_name"] == "food"


def _make_radio_config(schema_name="sentiment", labels=None):
    """Create a minimal config with a radio schema for testing."""
    if labels is None:
        labels = ["positive", "negative"]
    return {
        "mace": {
            "enabled": True,
            "trigger_every_n": 5,
            "min_annotations_per_item": 2,
            "min_items": 2,
            "num_restarts": 3,
            "num_iters": 20,
            "cache_results": False,
        },
        "annotation_schemes": [
            {
                "annotation_type": "radio",
                "name": schema_name,
                "labels": labels,
            }
        ],
        "output_annotation_dir": tempfile.mkdtemp(),
    }


def _make_multiselect_config(schema_name="topics", labels=None):
    """Create a minimal config with a multiselect schema."""
    if labels is None:
        labels = ["food", "service", "price"]
    return {
        "mace": {
            "enabled": True,
            "trigger_every_n": 5,
            "min_annotations_per_item": 2,
            "min_items": 2,
            "num_restarts": 3,
            "num_iters": 20,
            "cache_results": False,
        },
        "annotation_schemes": [
            {
                "annotation_type": "multiselect",
                "name": schema_name,
                "labels": labels,
            }
        ],
        "output_annotation_dir": tempfile.mkdtemp(),
    }


def _make_mock_usm(users_dict):
    """Create a mock UserStateManager from a dict of user_id -> FakeUserState."""
    mock_usm = MagicMock()
    mock_usm.get_user_ids.return_value = list(users_dict.keys())
    mock_usm.get_user_state.side_effect = lambda uid: users_dict.get(uid)
    return mock_usm


def _make_mock_ism():
    """Create a minimal mock ItemStateManager."""
    return MagicMock()


def _build_user_states_radio(schema="sentiment"):
    """Build 3 users annotating 4 items with a radio schema.

    Users 1&2 agree on everything, user3 is a spammer (always "negative").
    """
    users = {}

    # User 1: correct annotations
    users["user1"] = FakeUserState("user1", {
        "item1": {FakeLabel(schema, "positive"): "true", FakeLabel(schema, "negative"): "false"},
        "item2": {FakeLabel(schema, "positive"): "false", FakeLabel(schema, "negative"): "true"},
        "item3": {FakeLabel(schema, "positive"): "true", FakeLabel(schema, "negative"): "false"},
        "item4": {FakeLabel(schema, "positive"): "false", FakeLabel(schema, "negative"): "true"},
    })

    # User 2: agrees with user1
    users["user2"] = FakeUserState("user2", {
        "item1": {FakeLabel(schema, "positive"): "true", FakeLabel(schema, "negative"): "false"},
        "item2": {FakeLabel(schema, "positive"): "false", FakeLabel(schema, "negative"): "true"},
        "item3": {FakeLabel(schema, "positive"): "true", FakeLabel(schema, "negative"): "false"},
        "item4": {FakeLabel(schema, "positive"): "false", FakeLabel(schema, "negative"): "true"},
    })

    # User 3: spammer, always picks "negative"
    users["user3"] = FakeUserState("user3", {
        "item1": {FakeLabel(schema, "positive"): "false", FakeLabel(schema, "negative"): "true"},
        "item2": {FakeLabel(schema, "positive"): "false", FakeLabel(schema, "negative"): "true"},
        "item3": {FakeLabel(schema, "positive"): "false", FakeLabel(schema, "negative"): "true"},
        "item4": {FakeLabel(schema, "positive"): "false", FakeLabel(schema, "negative"): "true"},
    })

    return users


def _build_user_states_multiselect(schema="topics"):
    """Build 3 users annotating 3 items with multiselect (per-option binary)."""
    users = {}

    # User 1
    users["user1"] = FakeUserState("user1", {
        "item1": {
            FakeLabel(schema, "food"): True,
            FakeLabel(schema, "service"): False,
            FakeLabel(schema, "price"): True,
        },
        "item2": {
            FakeLabel(schema, "food"): False,
            FakeLabel(schema, "service"): True,
            FakeLabel(schema, "price"): False,
        },
        "item3": {
            FakeLabel(schema, "food"): True,
            FakeLabel(schema, "service"): True,
            FakeLabel(schema, "price"): False,
        },
    })

    # User 2: agrees mostly with user 1
    users["user2"] = FakeUserState("user2", {
        "item1": {
            FakeLabel(schema, "food"): True,
            FakeLabel(schema, "service"): False,
            FakeLabel(schema, "price"): True,
        },
        "item2": {
            FakeLabel(schema, "food"): False,
            FakeLabel(schema, "service"): True,
            FakeLabel(schema, "price"): False,
        },
        "item3": {
            FakeLabel(schema, "food"): True,
            FakeLabel(schema, "service"): True,
            FakeLabel(schema, "price"): False,
        },
    })

    # User 3: disagrees on some
    users["user3"] = FakeUserState("user3", {
        "item1": {
            FakeLabel(schema, "food"): False,
            FakeLabel(schema, "service"): True,
            FakeLabel(schema, "price"): True,
        },
        "item2": {
            FakeLabel(schema, "food"): True,
            FakeLabel(schema, "service"): False,
            FakeLabel(schema, "price"): True,
        },
        "item3": {
            FakeLabel(schema, "food"): True,
            FakeLabel(schema, "service"): False,
            FakeLabel(schema, "price"): True,
        },
    })

    return users


class TestMACEManager:
    """Test MACEManager with mocked state managers."""

    def setup_method(self):
        clear_mace_manager()

    def teardown_method(self):
        clear_mace_manager()

    def test_run_radio_schema(self):
        """Run MACE on a radio schema and verify results."""
        users = _build_user_states_radio()
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = _make_radio_config()
        mgr = MACEManager(config)
        results = mgr.run_all_schemas(_usm=usm, _ism=ism)

        assert "sentiment" in results
        result = results["sentiment"]
        assert result.num_annotators == 3
        assert result.num_instances == 4

        # Good annotators should have higher competence than spammer
        avg_good = (result.competence_scores["user1"] + result.competence_scores["user2"]) / 2
        spammer = result.competence_scores["user3"]
        assert spammer < avg_good

        # Predictions should follow majority (users 1&2)
        assert result.predicted_labels["item1"] == "positive"
        assert result.predicted_labels["item2"] == "negative"

    def test_run_multiselect_per_option(self):
        """Run MACE on a multiselect schema — should produce per-option results."""
        users = _build_user_states_multiselect()
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = _make_multiselect_config()
        mgr = MACEManager(config)
        results = mgr.run_all_schemas(_usm=usm, _ism=ism)

        # Should have one result per option
        assert "topics::food" in results
        assert "topics::service" in results
        assert "topics::price" in results

        # Each should be binary (2 labels)
        for key, result in results.items():
            assert set(result.label_mapping.values()) == {"0", "1"}
            assert result.num_annotators == 3

    def test_check_and_run_triggers(self):
        """check_and_run should trigger at the right threshold."""
        users = _build_user_states_radio()
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = _make_radio_config()
        config["mace"]["trigger_every_n"] = 5
        mgr = MACEManager(config)

        # Monkey-patch run_all_schemas to track calls without needing real managers
        original_run = mgr.run_all_schemas
        mgr.run_all_schemas = lambda: original_run(_usm=usm, _ism=ism)

        # Below threshold — no run
        assert mgr.check_and_run(3) is False
        assert len(mgr.results) == 0

        # At threshold — should run
        assert mgr.check_and_run(5) is True
        assert len(mgr.results) > 0

    def test_check_and_run_incremental(self):
        """check_and_run should trigger again after another N annotations."""
        users = _build_user_states_radio()
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = _make_radio_config()
        config["mace"]["trigger_every_n"] = 5
        mgr = MACEManager(config)

        original_run = mgr.run_all_schemas
        mgr.run_all_schemas = lambda: original_run(_usm=usm, _ism=ism)

        # First trigger at 5
        assert mgr.check_and_run(5) is True

        # Not again at 7
        assert mgr.check_and_run(7) is False

        # Again at 10
        assert mgr.check_and_run(10) is True

    def test_insufficient_items_skipped(self):
        """Schema with too few eligible items should be skipped."""
        # Only 1 item annotated by 2 users (needs min_items=2)
        users = {
            "user1": FakeUserState("user1", {
                "item1": {FakeLabel("sentiment", "positive"): "true"},
            }),
            "user2": FakeUserState("user2", {
                "item1": {FakeLabel("sentiment", "positive"): "true"},
            }),
        }
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = _make_radio_config()
        mgr = MACEManager(config)
        results = mgr.run_all_schemas(_usm=usm, _ism=ism)
        assert len(results) == 0

    def test_get_competence(self):
        """get_competence returns scores for a specific user."""
        users = _build_user_states_radio()
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = _make_radio_config()
        mgr = MACEManager(config)
        mgr.run_all_schemas(_usm=usm, _ism=ism)

        scores = mgr.get_competence("user1")
        assert "sentiment" in scores
        assert 0.0 <= scores["sentiment"] <= 1.0

        # Non-existent user
        assert mgr.get_competence("nobody") == {}

    def test_get_prediction(self):
        """get_prediction returns the predicted label for an instance."""
        users = _build_user_states_radio()
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = _make_radio_config()
        mgr = MACEManager(config)
        mgr.run_all_schemas(_usm=usm, _ism=ism)

        pred = mgr.get_prediction("item1", "sentiment")
        assert pred in ("positive", "negative")

        # Non-existent
        assert mgr.get_prediction("nonexistent", "sentiment") is None
        assert mgr.get_prediction("item1", "nonexistent") is None

    def test_results_summary(self):
        """get_results_summary returns structured overview."""
        users = _build_user_states_radio()
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = _make_radio_config()
        mgr = MACEManager(config)
        mgr.run_all_schemas(_usm=usm, _ism=ism)

        summary = mgr.get_results_summary()
        assert summary["enabled"] is True
        assert summary["has_results"] is True
        assert len(summary["schemas"]) == 1
        assert "user1" in summary["annotator_competence"]

    def test_results_summary_empty(self):
        """get_results_summary works when no results exist."""
        config = _make_radio_config()
        mgr = MACEManager(config)

        summary = mgr.get_results_summary()
        assert summary["has_results"] is False
        assert summary["schemas"] == []

    def test_cache_save_and_load(self):
        """Results should survive save/load round-trip."""
        users = _build_user_states_radio()
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = _make_radio_config()
        config["mace"]["cache_results"] = True
        mgr = MACEManager(config)
        mgr.run_all_schemas(_usm=usm, _ism=ism)
        mgr._save_cache()

        # Create a new manager that should load from cache
        mgr2 = MACEManager(config)
        assert "sentiment" in mgr2.results
        assert mgr2.results["sentiment"].num_annotators == 3

    def test_non_categorical_schemas_skipped(self):
        """Non-categorical schemas (span, text, slider) should be skipped."""
        users = _build_user_states_radio()
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = _make_radio_config()
        # Change annotation type to non-categorical
        config["annotation_schemes"][0]["annotation_type"] = "span"
        mgr = MACEManager(config)
        results = mgr.run_all_schemas(_usm=usm, _ism=ism)
        assert len(results) == 0

    def test_likert_schema(self):
        """Likert annotations should work like radio (label name = rating value)."""
        schema = "quality"
        users = {
            "user1": FakeUserState("user1", {
                "item1": {FakeLabel(schema, "3"): "true", FakeLabel(schema, "1"): "false", FakeLabel(schema, "2"): "false"},
                "item2": {FakeLabel(schema, "1"): "true", FakeLabel(schema, "2"): "false", FakeLabel(schema, "3"): "false"},
            }),
            "user2": FakeUserState("user2", {
                "item1": {FakeLabel(schema, "3"): "true", FakeLabel(schema, "1"): "false", FakeLabel(schema, "2"): "false"},
                "item2": {FakeLabel(schema, "1"): "true", FakeLabel(schema, "2"): "false", FakeLabel(schema, "3"): "false"},
            }),
        }
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = {
            "mace": {
                "enabled": True,
                "min_annotations_per_item": 2,
                "min_items": 2,
                "num_restarts": 3,
                "num_iters": 20,
                "cache_results": False,
            },
            "annotation_schemes": [
                {"annotation_type": "likert", "name": schema, "labels": ["1", "2", "3"]},
            ],
            "output_annotation_dir": tempfile.mkdtemp(),
        }
        mgr = MACEManager(config)
        results = mgr.run_all_schemas(_usm=usm, _ism=ism)

        assert schema in results
        assert results[schema].predicted_labels["item1"] == "3"
        assert results[schema].predicted_labels["item2"] == "1"

    def test_predictions_for_schema(self):
        """get_predictions_for_schema returns filtered predictions."""
        users = _build_user_states_radio()
        usm = _make_mock_usm(users)
        ism = _make_mock_ism()

        config = _make_radio_config()
        mgr = MACEManager(config)
        mgr.run_all_schemas(_usm=usm, _ism=ism)

        # All predictions
        preds = mgr.get_predictions_for_schema("sentiment")
        assert "predicted_labels" in preds
        assert len(preds["predicted_labels"]) == 4

        # Specific instance
        single = mgr.get_predictions_for_schema("sentiment", instance_id="item1")
        assert "predicted_label" in single
        assert "entropy" in single

        # Non-existent schema
        err = mgr.get_predictions_for_schema("nonexistent")
        assert "error" in err


class TestMACEManagerSingleton:
    """Test singleton init/get/clear pattern."""

    def setup_method(self):
        clear_mace_manager()

    def teardown_method(self):
        clear_mace_manager()

    def test_get_before_init_returns_none(self):
        assert get_mace_manager() is None

    def test_init_when_enabled(self):
        config = _make_radio_config()
        mgr = init_mace_manager(config)
        assert mgr is not None
        assert get_mace_manager() is mgr

    def test_init_when_disabled(self):
        config = {"mace": {"enabled": False}}
        mgr = init_mace_manager(config)
        assert mgr is None
        assert get_mace_manager() is None

    def test_clear(self):
        config = _make_radio_config()
        init_mace_manager(config)
        assert get_mace_manager() is not None
        clear_mace_manager()
        assert get_mace_manager() is None

    def test_init_idempotent(self):
        config = _make_radio_config()
        mgr1 = init_mace_manager(config)
        mgr2 = init_mace_manager(config)
        assert mgr1 is mgr2
