"""
Unit tests for the Adjudication module.

Tests cover:
- AdjudicationConfig parsing and validation
- AdjudicationManager queue building
- Agreement computation
- Decision storage and serialization
- Final dataset generation
- Singleton management
"""

import json
import os
import pytest
import tempfile
import shutil
from unittest.mock import patch, MagicMock, PropertyMock
from collections import defaultdict

from potato.adjudication import (
    AdjudicationConfig,
    AdjudicationItem,
    AdjudicationDecision,
    AdjudicationManager,
    init_adjudication_manager,
    get_adjudication_manager,
    clear_adjudication_manager,
)


@pytest.fixture(autouse=True)
def cleanup():
    """Clear singleton between tests."""
    clear_adjudication_manager()
    yield
    clear_adjudication_manager()


@pytest.fixture
def base_config():
    """Base configuration with adjudication enabled."""
    return {
        "adjudication": {
            "enabled": True,
            "adjudicator_users": ["expert_1", "expert_2"],
            "min_annotations": 2,
            "agreement_threshold": 0.75,
            "show_all_items": False,
            "error_taxonomy": ["ambiguous_text", "guideline_gap", "annotator_error"],
        },
        "annotation_schemes": [
            {"name": "sentiment", "annotation_type": "radio", "labels": ["positive", "negative", "neutral"]},
        ],
        "output_annotation_dir": tempfile.mkdtemp(),
        "item_properties": {"id_key": "id", "text_key": "text"},
    }


@pytest.fixture
def disabled_config():
    """Configuration with adjudication disabled."""
    return {
        "adjudication": {"enabled": False},
        "annotation_schemes": [],
        "output_annotation_dir": tempfile.mkdtemp(),
    }


class TestAdjudicationConfig:
    """Tests for AdjudicationConfig parsing."""

    def test_parse_enabled_config(self, base_config):
        mgr = AdjudicationManager(base_config)
        assert mgr.adj_config.enabled is True
        assert mgr.adj_config.adjudicator_users == ["expert_1", "expert_2"]
        assert mgr.adj_config.min_annotations == 2
        assert mgr.adj_config.agreement_threshold == 0.75

    def test_parse_disabled_config(self, disabled_config):
        mgr = AdjudicationManager(disabled_config)
        assert mgr.adj_config.enabled is False

    def test_parse_missing_adjudication_section(self):
        mgr = AdjudicationManager({"output_annotation_dir": "/tmp/test"})
        assert mgr.adj_config.enabled is False

    def test_default_values(self, base_config):
        # Remove optional fields
        del base_config["adjudication"]["show_all_items"]
        mgr = AdjudicationManager(base_config)
        assert mgr.adj_config.show_all_items is False
        assert mgr.adj_config.show_annotator_names is True
        assert mgr.adj_config.show_timing_data is True
        assert mgr.adj_config.require_confidence is True
        assert mgr.adj_config.fast_decision_warning_ms == 2000

    def test_custom_error_taxonomy(self, base_config):
        base_config["adjudication"]["error_taxonomy"] = ["custom_1", "custom_2"]
        mgr = AdjudicationManager(base_config)
        assert mgr.adj_config.error_taxonomy == ["custom_1", "custom_2"]

    def test_similarity_config(self, base_config):
        base_config["adjudication"]["similarity"] = {
            "enabled": True,
            "model": "test-model",
            "top_k": 10,
        }
        mgr = AdjudicationManager(base_config)
        assert mgr.adj_config.similarity_enabled is True
        assert mgr.adj_config.similarity_model == "test-model"
        assert mgr.adj_config.similarity_top_k == 10


class TestAdjudicationManager:
    """Tests for AdjudicationManager core functionality."""

    def test_is_adjudicator(self, base_config):
        mgr = AdjudicationManager(base_config)
        assert mgr.is_adjudicator("expert_1") is True
        assert mgr.is_adjudicator("expert_2") is True
        assert mgr.is_adjudicator("random_user") is False

    def test_is_adjudicator_disabled(self, disabled_config):
        mgr = AdjudicationManager(disabled_config)
        assert mgr.is_adjudicator("expert_1") is False

    def test_singleton_init(self, base_config):
        mgr1 = init_adjudication_manager(base_config)
        mgr2 = get_adjudication_manager()
        assert mgr1 is mgr2

    def test_singleton_clear(self, base_config):
        init_adjudication_manager(base_config)
        assert get_adjudication_manager() is not None
        clear_adjudication_manager()
        assert get_adjudication_manager() is None


class TestAgreementComputation:
    """Tests for agreement score calculation."""

    def test_perfect_agreement(self, base_config):
        mgr = AdjudicationManager(base_config)
        annotations = {
            "user_1": {"sentiment": "positive"},
            "user_2": {"sentiment": "positive"},
            "user_3": {"sentiment": "positive"},
        }
        scores = mgr._compute_agreement(annotations, ["sentiment"])
        assert scores["sentiment"] == 1.0

    def test_no_agreement(self, base_config):
        mgr = AdjudicationManager(base_config)
        annotations = {
            "user_1": {"sentiment": "positive"},
            "user_2": {"sentiment": "negative"},
            "user_3": {"sentiment": "neutral"},
        }
        scores = mgr._compute_agreement(annotations, ["sentiment"])
        assert scores["sentiment"] == 0.0

    def test_partial_agreement(self, base_config):
        mgr = AdjudicationManager(base_config)
        annotations = {
            "user_1": {"sentiment": "positive"},
            "user_2": {"sentiment": "positive"},
            "user_3": {"sentiment": "negative"},
        }
        scores = mgr._compute_agreement(annotations, ["sentiment"])
        # 1 out of 3 pairs agree: 1/3
        assert abs(scores["sentiment"] - 1.0 / 3.0) < 0.01

    def test_overall_agreement(self, base_config):
        mgr = AdjudicationManager(base_config)
        scores = {"sentiment": 0.5, "topics": 1.0}
        overall = mgr._compute_overall_agreement(scores)
        assert overall == 0.75

    def test_overall_agreement_empty(self, base_config):
        mgr = AdjudicationManager(base_config)
        overall = mgr._compute_overall_agreement({})
        assert overall == 1.0

    def test_agreement_with_dict_values(self, base_config):
        """Test agreement with multiselect-style dict annotations."""
        mgr = AdjudicationManager(base_config)
        annotations = {
            "user_1": {"topics": {"food": True, "service": True}},
            "user_2": {"topics": {"food": True, "service": True}},
        }
        scores = mgr._compute_agreement(annotations, ["topics"])
        assert scores["topics"] == 1.0


class TestAdjudicationDecision:
    """Tests for AdjudicationDecision data class."""

    def test_to_dict(self):
        decision = AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="expert_1",
            timestamp="2026-02-05T10:00:00",
            label_decisions={"sentiment": "positive"},
            span_decisions=[],
            source={"sentiment": "annotator_user_1"},
            confidence="high",
            notes="Clear positive sentiment",
            error_taxonomy=["ambiguous_text"],
            time_spent_ms=15000,
        )
        d = decision.to_dict()
        assert d["instance_id"] == "item_001"
        assert d["adjudicator_id"] == "expert_1"
        assert d["label_decisions"] == {"sentiment": "positive"}
        assert d["confidence"] == "high"
        assert d["time_spent_ms"] == 15000

    def test_from_dict(self):
        data = {
            "instance_id": "item_002",
            "adjudicator_id": "expert_2",
            "timestamp": "2026-02-05T11:00:00",
            "label_decisions": {"sentiment": "negative"},
            "span_decisions": [],
            "source": {},
            "confidence": "low",
            "notes": "",
            "error_taxonomy": ["guideline_gap"],
        }
        decision = AdjudicationDecision.from_dict(data)
        assert decision.instance_id == "item_002"
        assert decision.confidence == "low"
        assert decision.error_taxonomy == ["guideline_gap"]

    def test_roundtrip(self):
        decision = AdjudicationDecision(
            instance_id="item_003",
            adjudicator_id="expert_1",
            timestamp="2026-02-05T12:00:00",
            label_decisions={"sentiment": "neutral"},
            span_decisions=[],
            source={"sentiment": "adjudicator"},
            confidence="medium",
            notes="Edge case",
            error_taxonomy=["edge_case"],
            guideline_update_flag=True,
            guideline_update_notes="Need clarification",
            time_spent_ms=8000,
        )
        d = decision.to_dict()
        restored = AdjudicationDecision.from_dict(d)
        assert restored.instance_id == decision.instance_id
        assert restored.confidence == decision.confidence
        assert restored.guideline_update_flag == decision.guideline_update_flag
        assert restored.time_spent_ms == decision.time_spent_ms


class TestAdjudicationItem:
    """Tests for AdjudicationItem data class."""

    def test_to_dict(self):
        item = AdjudicationItem(
            instance_id="item_001",
            annotations={"user_1": {"sentiment": "positive"}},
            span_annotations={},
            behavioral_data={"user_1": {"total_time_ms": 5000}},
            agreement_scores={"sentiment": 0.5},
            overall_agreement=0.5,
            num_annotators=2,
        )
        d = item.to_dict()
        assert d["instance_id"] == "item_001"
        assert d["num_annotators"] == 2
        assert d["status"] == "pending"
        assert d["overall_agreement"] == 0.5


class TestDecisionPersistence:
    """Tests for saving and loading decisions."""

    def test_save_and_load_decisions(self, base_config):
        mgr = AdjudicationManager(base_config)

        decision = AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="expert_1",
            timestamp="2026-02-05T10:00:00",
            label_decisions={"sentiment": "positive"},
            span_decisions=[],
            source={"sentiment": "adjudicator"},
            confidence="high",
            notes="Test",
            error_taxonomy=[],
            time_spent_ms=5000,
        )
        mgr.submit_decision(decision)

        # Create new manager to test loading
        mgr2 = AdjudicationManager(base_config)
        loaded = mgr2.get_decision("item_001")
        assert loaded is not None
        assert loaded.instance_id == "item_001"
        assert loaded.confidence == "high"

    def test_submit_updates_queue(self, base_config):
        mgr = AdjudicationManager(base_config)

        # Add item to queue manually
        item = AdjudicationItem(
            instance_id="item_001",
            annotations={},
            span_annotations={},
            behavioral_data={},
            agreement_scores={},
            overall_agreement=0.5,
            num_annotators=2,
        )
        mgr.queue["item_001"] = item

        decision = AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="expert_1",
            timestamp="2026-02-05T10:00:00",
            label_decisions={"sentiment": "positive"},
            span_decisions=[],
            source={},
            confidence="high",
            notes="",
            error_taxonomy=[],
            time_spent_ms=5000,
        )
        mgr.submit_decision(decision)

        assert mgr.queue["item_001"].status == "completed"
        assert mgr.queue["item_001"].assigned_adjudicator == "expert_1"


class TestStatistics:
    """Tests for adjudication statistics."""

    def test_stats_empty(self, base_config):
        mgr = AdjudicationManager(base_config)
        mgr._queue_built = True  # Prevent auto-build
        stats = mgr.get_stats()
        assert stats["total"] == 0
        assert stats["completed"] == 0
        assert stats["completion_rate"] == 0.0

    def test_stats_with_items(self, base_config):
        mgr = AdjudicationManager(base_config)
        mgr._queue_built = True

        mgr.queue["item_001"] = AdjudicationItem(
            instance_id="item_001", annotations={}, span_annotations={},
            behavioral_data={}, agreement_scores={}, overall_agreement=0.5,
            num_annotators=2, status="completed",
        )
        mgr.queue["item_002"] = AdjudicationItem(
            instance_id="item_002", annotations={}, span_annotations={},
            behavioral_data={}, agreement_scores={}, overall_agreement=0.3,
            num_annotators=3, status="pending",
        )
        mgr.queue["item_003"] = AdjudicationItem(
            instance_id="item_003", annotations={}, span_annotations={},
            behavioral_data={}, agreement_scores={}, overall_agreement=0.7,
            num_annotators=2, status="skipped",
        )

        stats = mgr.get_stats()
        assert stats["total"] == 3
        assert stats["completed"] == 1
        assert stats["pending"] == 1
        assert stats["skipped"] == 1
        assert abs(stats["completion_rate"] - 1.0 / 3.0) < 0.01

    def test_skip_item(self, base_config):
        mgr = AdjudicationManager(base_config)
        mgr.queue["item_001"] = AdjudicationItem(
            instance_id="item_001", annotations={}, span_annotations={},
            behavioral_data={}, agreement_scores={}, overall_agreement=0.5,
            num_annotators=2,
        )

        result = mgr.skip_item("item_001", "expert_1")
        assert result is True
        assert mgr.queue["item_001"].status == "skipped"

    def test_skip_nonexistent_item(self, base_config):
        mgr = AdjudicationManager(base_config)
        result = mgr.skip_item("nonexistent", "expert_1")
        assert result is False


class TestQueueFiltering:
    """Tests for queue filtering and sorting."""

    def test_get_queue_filter_pending(self, base_config):
        mgr = AdjudicationManager(base_config)
        mgr._queue_built = True

        mgr.queue["item_001"] = AdjudicationItem(
            instance_id="item_001", annotations={}, span_annotations={},
            behavioral_data={}, agreement_scores={}, overall_agreement=0.3,
            num_annotators=2, status="pending",
        )
        mgr.queue["item_002"] = AdjudicationItem(
            instance_id="item_002", annotations={}, span_annotations={},
            behavioral_data={}, agreement_scores={}, overall_agreement=0.5,
            num_annotators=2, status="completed",
        )

        pending = mgr.get_queue(filter_status="pending")
        assert len(pending) == 1
        assert pending[0].instance_id == "item_001"

    def test_get_queue_sorted_by_agreement(self, base_config):
        mgr = AdjudicationManager(base_config)
        mgr._queue_built = True

        mgr.queue["item_001"] = AdjudicationItem(
            instance_id="item_001", annotations={}, span_annotations={},
            behavioral_data={}, agreement_scores={}, overall_agreement=0.7,
            num_annotators=2, status="pending",
        )
        mgr.queue["item_002"] = AdjudicationItem(
            instance_id="item_002", annotations={}, span_annotations={},
            behavioral_data={}, agreement_scores={}, overall_agreement=0.2,
            num_annotators=2, status="pending",
        )

        items = mgr.get_queue(filter_status="pending")
        # Should be sorted by agreement (lowest first)
        assert items[0].instance_id == "item_002"
        assert items[1].instance_id == "item_001"

    def test_get_next_item(self, base_config):
        mgr = AdjudicationManager(base_config)
        mgr._queue_built = True

        mgr.queue["item_001"] = AdjudicationItem(
            instance_id="item_001", annotations={}, span_annotations={},
            behavioral_data={}, agreement_scores={}, overall_agreement=0.3,
            num_annotators=2, status="pending",
        )

        next_item = mgr.get_next_item("expert_1")
        assert next_item is not None
        assert next_item.instance_id == "item_001"

    def test_get_next_item_empty(self, base_config):
        mgr = AdjudicationManager(base_config)
        mgr._queue_built = True

        next_item = mgr.get_next_item("expert_1")
        assert next_item is None


class TestConfigValidation:
    """Tests for config_module adjudication validation."""

    def test_valid_config(self):
        from potato.server_utils.config_module import validate_adjudication_config
        config_data = {
            "adjudication": {
                "enabled": True,
                "adjudicator_users": ["user1"],
                "min_annotations": 2,
                "agreement_threshold": 0.75,
            }
        }
        # Should not raise
        validate_adjudication_config(config_data)

    def test_disabled_config_skips_validation(self):
        from potato.server_utils.config_module import validate_adjudication_config
        config_data = {"adjudication": {"enabled": False}}
        validate_adjudication_config(config_data)

    def test_missing_adjudicator_users(self):
        from potato.server_utils.config_module import (
            validate_adjudication_config, ConfigValidationError
        )
        config_data = {
            "adjudication": {
                "enabled": True,
                "adjudicator_users": [],
            }
        }
        with pytest.raises(ConfigValidationError, match="adjudicator_users"):
            validate_adjudication_config(config_data)

    def test_invalid_threshold(self):
        from potato.server_utils.config_module import (
            validate_adjudication_config, ConfigValidationError
        )
        config_data = {
            "adjudication": {
                "enabled": True,
                "adjudicator_users": ["user1"],
                "agreement_threshold": 1.5,
            }
        }
        with pytest.raises(ConfigValidationError, match="agreement_threshold"):
            validate_adjudication_config(config_data)

    def test_invalid_min_annotations(self):
        from potato.server_utils.config_module import (
            validate_adjudication_config, ConfigValidationError
        )
        config_data = {
            "adjudication": {
                "enabled": True,
                "adjudicator_users": ["user1"],
                "min_annotations": 0,
            }
        }
        with pytest.raises(ConfigValidationError, match="min_annotations"):
            validate_adjudication_config(config_data)

    def test_invalid_error_taxonomy_type(self):
        from potato.server_utils.config_module import (
            validate_adjudication_config, ConfigValidationError
        )
        config_data = {
            "adjudication": {
                "enabled": True,
                "adjudicator_users": ["user1"],
                "error_taxonomy": "not_a_list",
            }
        }
        with pytest.raises(ConfigValidationError, match="error_taxonomy"):
            validate_adjudication_config(config_data)
