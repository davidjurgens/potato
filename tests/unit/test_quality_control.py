"""
Unit tests for Quality Control module.

Tests attention checks, gold standards, pre-annotation support,
and response validation logic.
"""

import pytest
import json
import tempfile
import os
from datetime import datetime
from unittest.mock import Mock, patch

from potato.quality_control import (
    QualityControlManager,
    QualityControlConfig,
    AttentionCheckResult,
    GoldStandardResult,
    init_quality_control_manager,
    get_quality_control_manager,
    clear_quality_control_manager
)


class TestQualityControlConfig:
    """Tests for QualityControlConfig parsing."""

    def test_empty_config(self):
        """Test that empty config results in all features disabled."""
        manager = QualityControlManager({}, "/tmp")
        assert not manager.qc_config.attention_checks_enabled
        assert not manager.qc_config.gold_standards_enabled
        assert not manager.qc_config.pre_annotation_enabled

    def test_attention_checks_config(self):
        """Test attention checks configuration parsing."""
        config = {
            "attention_checks": {
                "enabled": True,
                "items_file": "attention.json",
                "frequency": 10,
                "min_response_time": 3.0,
                "failure_handling": {
                    "warn_threshold": 2,
                    "warn_message": "Please be careful!",
                    "block_threshold": 5,
                    "block_message": "You are blocked."
                }
            }
        }
        manager = QualityControlManager(config, "/tmp")

        assert manager.qc_config.attention_checks_enabled
        assert manager.qc_config.attention_items_file == "attention.json"
        assert manager.qc_config.attention_frequency == 10
        assert manager.qc_config.attention_min_response_time == 3.0
        assert manager.qc_config.attention_warn_threshold == 2
        assert manager.qc_config.attention_warn_message == "Please be careful!"
        assert manager.qc_config.attention_block_threshold == 5
        assert manager.qc_config.attention_block_message == "You are blocked."

    def test_gold_standards_config(self):
        """Test gold standards configuration parsing."""
        config = {
            "gold_standards": {
                "enabled": True,
                "items_file": "gold.json",
                "mode": "mixed",
                "frequency": 20,
                "accuracy": {
                    "min_threshold": 0.8,
                    "evaluation_count": 5
                },
                "feedback": {
                    "show_correct_answer": True,
                    "show_explanation": False
                }
            }
        }
        manager = QualityControlManager(config, "/tmp")

        assert manager.qc_config.gold_standards_enabled
        assert manager.qc_config.gold_items_file == "gold.json"
        assert manager.qc_config.gold_mode == "mixed"
        assert manager.qc_config.gold_frequency == 20
        assert manager.qc_config.gold_min_accuracy == 0.8
        assert manager.qc_config.gold_evaluation_count == 5
        assert manager.qc_config.gold_show_correct_answer is True
        assert manager.qc_config.gold_show_explanation is False

    def test_pre_annotation_config(self):
        """Test pre-annotation configuration parsing."""
        config = {
            "pre_annotation": {
                "enabled": True,
                "field": "model_predictions",
                "allow_modification": False,
                "show_confidence": True,
                "highlight_low_confidence": 0.5
            }
        }
        manager = QualityControlManager(config, "/tmp")

        assert manager.qc_config.pre_annotation_enabled
        assert manager.qc_config.pre_annotation_field == "model_predictions"
        assert manager.qc_config.pre_annotation_allow_modification is False
        assert manager.qc_config.pre_annotation_show_confidence is True
        assert manager.qc_config.pre_annotation_highlight_threshold == 0.5


class TestAttentionChecks:
    """Tests for attention check functionality."""

    @pytest.fixture
    def attention_check_items(self, tmp_path):
        """Create temporary attention check items file."""
        items = [
            {
                "id": "attn_001",
                "text": "Select positive for this item.",
                "expected_answer": {"sentiment": "positive"}
            },
            {
                "id": "attn_002",
                "text": "Select negative for this item.",
                "expected_answer": {"sentiment": "negative"}
            }
        ]
        file_path = tmp_path / "attention.json"
        file_path.write_text(json.dumps(items))
        return str(file_path), items

    @pytest.fixture
    def manager_with_attention(self, attention_check_items):
        """Create manager with attention checks enabled."""
        file_path, items = attention_check_items
        config = {
            "attention_checks": {
                "enabled": True,
                "items_file": os.path.basename(file_path),
                "frequency": 5,
                "failure_handling": {
                    "warn_threshold": 2,
                    "block_threshold": 4
                }
            }
        }
        return QualityControlManager(config, os.path.dirname(file_path))

    def test_load_attention_items(self, manager_with_attention):
        """Test that attention check items are loaded correctly."""
        assert len(manager_with_attention.attention_items) == 2
        assert "attn_001" in manager_with_attention.attention_expected
        assert "attn_002" in manager_with_attention.attention_expected

    def test_is_attention_check(self, manager_with_attention):
        """Test attention check identification."""
        assert manager_with_attention.is_attention_check("attn_001")
        assert manager_with_attention.is_attention_check("attn_002")
        assert not manager_with_attention.is_attention_check("regular_item")

    def test_should_inject_frequency(self, manager_with_attention):
        """Test frequency-based injection."""
        # Initially should not inject
        assert not manager_with_attention.should_inject_attention_check("user1")

        # Record items until threshold
        for i in range(5):
            manager_with_attention.record_regular_item("user1")

        # Now should inject
        assert manager_with_attention.should_inject_attention_check("user1")

    def test_validate_correct_response(self, manager_with_attention):
        """Test validation of correct attention check response."""
        response = {"sentiment": "positive"}
        result = manager_with_attention.validate_attention_response(
            "user1", "attn_001", response
        )

        assert result is not None
        assert result["passed"] is True
        assert "warning" not in result
        assert "blocked" not in result

    def test_validate_incorrect_response(self, manager_with_attention):
        """Test validation of incorrect attention check response."""
        response = {"sentiment": "negative"}  # Wrong answer for attn_001
        result = manager_with_attention.validate_attention_response(
            "user1", "attn_001", response
        )

        assert result is not None
        assert result["passed"] is False

    def test_warning_threshold(self, manager_with_attention):
        """Test that warning is triggered at threshold."""
        # Fail twice to trigger warning
        for i in range(2):
            result = manager_with_attention.validate_attention_response(
                "user1", "attn_001", {"sentiment": "wrong"}
            )

        assert result["passed"] is False
        assert result.get("warning") is True
        assert "message" in result

    def test_block_threshold(self, manager_with_attention):
        """Test that blocking is triggered at threshold."""
        # Fail 4 times to trigger block
        for i in range(4):
            result = manager_with_attention.validate_attention_response(
                "user1", "attn_001", {"sentiment": "wrong"}
            )

        assert result["passed"] is False
        assert result.get("blocked") is True
        assert "message" in result

    def test_get_stats(self, manager_with_attention):
        """Test getting attention check statistics."""
        # Pass one, fail one
        manager_with_attention.validate_attention_response(
            "user1", "attn_001", {"sentiment": "positive"}
        )
        manager_with_attention.validate_attention_response(
            "user1", "attn_002", {"sentiment": "wrong"}
        )

        stats = manager_with_attention.get_attention_check_stats("user1")
        assert stats["total"] == 2
        assert stats["passed"] == 1
        assert stats["failed"] == 1
        assert stats["pass_rate"] == 0.5


class TestGoldStandards:
    """Tests for gold standard functionality."""

    @pytest.fixture
    def gold_standard_items(self, tmp_path):
        """Create temporary gold standard items file."""
        items = [
            {
                "id": "gold_001",
                "text": "I love this product!",
                "gold_label": {"sentiment": "positive"},
                "explanation": "Strong positive language."
            },
            {
                "id": "gold_002",
                "text": "This is terrible.",
                "gold_label": {"sentiment": "negative"},
                "explanation": "Clear negative sentiment."
            }
        ]
        file_path = tmp_path / "gold.json"
        file_path.write_text(json.dumps(items))
        return str(file_path), items

    @pytest.fixture
    def manager_with_gold(self, gold_standard_items):
        """Create manager with gold standards enabled."""
        file_path, items = gold_standard_items
        config = {
            "gold_standards": {
                "enabled": True,
                "items_file": os.path.basename(file_path),
                "mode": "mixed",
                "frequency": 10,
                "accuracy": {
                    "min_threshold": 0.7,
                    "evaluation_count": 3
                },
                "feedback": {
                    "show_correct_answer": True,
                    "show_explanation": True
                }
            }
        }
        return QualityControlManager(config, os.path.dirname(file_path))

    def test_load_gold_items(self, manager_with_gold):
        """Test that gold standard items are loaded correctly."""
        assert len(manager_with_gold.gold_items) == 2
        assert "gold_001" in manager_with_gold.gold_labels
        assert "gold_002" in manager_with_gold.gold_labels
        assert "gold_001" in manager_with_gold.gold_explanations

    def test_is_gold_standard(self, manager_with_gold):
        """Test gold standard identification."""
        assert manager_with_gold.is_gold_standard("gold_001")
        assert manager_with_gold.is_gold_standard("gold_002")
        assert not manager_with_gold.is_gold_standard("regular_item")

    def test_validate_correct_response(self, manager_with_gold):
        """Test validation of correct gold standard response."""
        response = {"sentiment": "positive"}
        result = manager_with_gold.validate_gold_response(
            "user1", "gold_001", response
        )

        assert result is not None
        assert result["correct"] is True
        assert result["gold_label"] == {"sentiment": "positive"}
        assert result["explanation"] == "Strong positive language."

    def test_validate_incorrect_response(self, manager_with_gold):
        """Test validation of incorrect gold standard response."""
        response = {"sentiment": "negative"}  # Wrong answer for gold_001
        result = manager_with_gold.validate_gold_response(
            "user1", "gold_001", response
        )

        assert result is not None
        assert result["correct"] is False
        assert result["gold_label"] == {"sentiment": "positive"}

    def test_accuracy_warning(self, manager_with_gold):
        """Test that accuracy warning is triggered below threshold."""
        # Answer 3 gold standards (2 wrong, 1 right = 33% accuracy)
        manager_with_gold.validate_gold_response(
            "user1", "gold_001", {"sentiment": "wrong"}
        )
        manager_with_gold.validate_gold_response(
            "user1", "gold_002", {"sentiment": "wrong"}
        )
        result = manager_with_gold.validate_gold_response(
            "user1", "gold_001", {"sentiment": "positive"}
        )

        assert result.get("accuracy_warning") is True
        assert result["current_accuracy"] < 0.7
        assert result["required_accuracy"] == 0.7

    def test_get_accuracy(self, manager_with_gold):
        """Test getting gold standard accuracy."""
        # 2 correct, 1 incorrect
        manager_with_gold.validate_gold_response(
            "user1", "gold_001", {"sentiment": "positive"}
        )
        manager_with_gold.validate_gold_response(
            "user1", "gold_002", {"sentiment": "negative"}
        )
        manager_with_gold.validate_gold_response(
            "user1", "gold_001", {"sentiment": "wrong"}
        )

        accuracy = manager_with_gold.get_gold_accuracy("user1")
        assert accuracy["total"] == 3
        assert accuracy["correct"] == 2
        assert abs(accuracy["accuracy"] - 2/3) < 0.01


class TestPreAnnotation:
    """Tests for pre-annotation functionality."""

    @pytest.fixture
    def manager_with_preannotation(self):
        """Create manager with pre-annotation enabled."""
        config = {
            "pre_annotation": {
                "enabled": True,
                "field": "predictions",
                "allow_modification": True,
                "show_confidence": True,
                "highlight_low_confidence": 0.7
            }
        }
        return QualityControlManager(config, "/tmp")

    def test_extract_pre_annotations(self, manager_with_preannotation):
        """Test extracting pre-annotations from item data."""
        item_data = {
            "text": "Some text",
            "predictions": {
                "sentiment": "positive",
                "confidence": 0.85
            }
        }

        result = manager_with_preannotation.extract_pre_annotations("item_001", item_data)

        assert result is not None
        assert result["sentiment"] == "positive"
        assert result["confidence"] == 0.85

    def test_extract_no_predictions(self, manager_with_preannotation):
        """Test extracting pre-annotations when field is missing."""
        item_data = {
            "text": "Some text"
        }

        result = manager_with_preannotation.extract_pre_annotations("item_001", item_data)
        assert result is None

    def test_get_pre_annotation_config(self, manager_with_preannotation):
        """Test getting pre-annotation configuration for frontend."""
        config = manager_with_preannotation.get_pre_annotation_config()

        assert config["enabled"] is True
        assert config["allow_modification"] is True
        assert config["show_confidence"] is True
        assert config["highlight_threshold"] == 0.7

    def test_disabled_returns_empty(self):
        """Test that disabled pre-annotation returns empty config."""
        manager = QualityControlManager({}, "/tmp")
        config = manager.get_pre_annotation_config()

        assert config["enabled"] is False


class TestResponseComparison:
    """Tests for response comparison logic."""

    @pytest.fixture
    def manager(self):
        """Create a basic manager for testing."""
        return QualityControlManager({}, "/tmp")

    def test_simple_match(self, manager):
        """Test simple string value comparison."""
        expected = {"sentiment": "positive"}
        actual = {"sentiment": "positive"}
        assert manager._compare_responses(expected, actual) is True

    def test_simple_mismatch(self, manager):
        """Test simple string value mismatch."""
        expected = {"sentiment": "positive"}
        actual = {"sentiment": "negative"}
        assert manager._compare_responses(expected, actual) is False

    def test_case_insensitive(self, manager):
        """Test case-insensitive comparison."""
        expected = {"sentiment": "Positive"}
        actual = {"sentiment": "positive"}
        assert manager._compare_responses(expected, actual) is True

    def test_list_match(self, manager):
        """Test list value comparison (multiselect)."""
        expected = {"topics": ["sports", "news"]}
        actual = {"topics": ["news", "sports"]}
        assert manager._compare_responses(expected, actual) is True

    def test_list_mismatch(self, manager):
        """Test list value mismatch."""
        expected = {"topics": ["sports", "news"]}
        actual = {"topics": ["sports"]}
        assert manager._compare_responses(expected, actual) is False

    def test_partial_key_match(self, manager):
        """Test matching with schema:label format keys."""
        expected = {"sentiment": "positive"}
        actual = {"sentiment:label_1": "positive"}
        # Should still match since we check for prefix
        assert manager._compare_responses(expected, actual) is True


class TestQualityMetrics:
    """Tests for quality metrics aggregation."""

    @pytest.fixture
    def manager_with_data(self, tmp_path):
        """Create manager with test data."""
        attention_items = [
            {"id": "attn_001", "text": "Test", "expected_answer": {"s": "a"}}
        ]
        gold_items = [
            {"id": "gold_001", "text": "Test", "gold_label": {"s": "a"}}
        ]

        attn_file = tmp_path / "attention.json"
        attn_file.write_text(json.dumps(attention_items))
        gold_file = tmp_path / "gold.json"
        gold_file.write_text(json.dumps(gold_items))

        config = {
            "attention_checks": {
                "enabled": True,
                "items_file": "attention.json",
                "frequency": 10
            },
            "gold_standards": {
                "enabled": True,
                "items_file": "gold.json"
            },
            "pre_annotation": {
                "enabled": True,
                "field": "predictions"
            }
        }
        manager = QualityControlManager(config, str(tmp_path))

        # Add some results
        manager.validate_attention_response("user1", "attn_001", {"s": "a"})
        manager.validate_attention_response("user2", "attn_001", {"s": "wrong"})
        manager.validate_gold_response("user1", "gold_001", {"s": "a"})
        manager.validate_gold_response("user2", "gold_001", {"s": "wrong"})

        return manager

    def test_get_quality_metrics(self, manager_with_data):
        """Test getting comprehensive quality metrics."""
        metrics = manager_with_data.get_quality_metrics()

        # Attention checks
        attn = metrics["attention_checks"]
        assert attn["enabled"] is True
        assert attn["total_checks"] == 2
        assert attn["total_passed"] == 1
        assert attn["total_failed"] == 1
        assert "user1" in attn["by_user"]
        assert "user2" in attn["by_user"]

        # Gold standards
        gold = metrics["gold_standards"]
        assert gold["enabled"] is True
        assert gold["total_evaluations"] == 2
        assert gold["total_correct"] == 1
        assert gold["total_incorrect"] == 1

        # Pre-annotation
        pre = metrics["pre_annotation"]
        assert pre["enabled"] is True


class TestAutoPromotion:
    """Tests for gold standard auto-promotion functionality."""

    @pytest.fixture
    def manager_with_auto_promote(self):
        """Create manager with auto-promotion enabled."""
        config = {
            "gold_standards": {
                "enabled": True,
                "auto_promote": {
                    "enabled": True,
                    "min_annotators": 3,
                    "agreement_threshold": 1.0
                }
            }
        }
        return QualityControlManager(config, "/tmp")

    def test_auto_promote_config(self, manager_with_auto_promote):
        """Test auto-promotion config parsing."""
        assert manager_with_auto_promote.qc_config.gold_auto_promote_enabled
        assert manager_with_auto_promote.qc_config.gold_auto_promote_min_annotators == 3
        assert manager_with_auto_promote.qc_config.gold_auto_promote_agreement == 1.0

    def test_record_annotation_insufficient_annotators(self, manager_with_auto_promote):
        """Test that items aren't promoted with too few annotators."""
        # Only 2 annotators - shouldn't promote yet
        result1 = manager_with_auto_promote.record_item_annotation(
            "item_001", "user1", {"sentiment": "positive"}
        )
        result2 = manager_with_auto_promote.record_item_annotation(
            "item_001", "user2", {"sentiment": "positive"}
        )

        assert result1 is None
        assert result2 is None
        assert not manager_with_auto_promote.is_gold_standard("item_001")

    def test_record_annotation_unanimous_agreement(self, manager_with_auto_promote):
        """Test promotion when all annotators agree."""
        manager_with_auto_promote.record_item_annotation(
            "item_001", "user1", {"sentiment": "positive"}
        )
        manager_with_auto_promote.record_item_annotation(
            "item_001", "user2", {"sentiment": "positive"}
        )
        result = manager_with_auto_promote.record_item_annotation(
            "item_001", "user3", {"sentiment": "positive"}
        )

        assert result is not None
        assert result["promoted"] is True
        assert result["item_id"] == "item_001"
        assert result["consensus_label"]["sentiment"] == "positive"
        assert manager_with_auto_promote.is_gold_standard("item_001")

    def test_record_annotation_no_agreement(self, manager_with_auto_promote):
        """Test that items aren't promoted when annotators disagree."""
        manager_with_auto_promote.record_item_annotation(
            "item_002", "user1", {"sentiment": "positive"}
        )
        manager_with_auto_promote.record_item_annotation(
            "item_002", "user2", {"sentiment": "negative"}
        )
        result = manager_with_auto_promote.record_item_annotation(
            "item_002", "user3", {"sentiment": "positive"}
        )

        # 2/3 agree, but threshold is 1.0 (unanimous)
        assert result is None
        assert not manager_with_auto_promote.is_gold_standard("item_002")

    def test_partial_agreement_threshold(self):
        """Test promotion with partial agreement threshold."""
        config = {
            "gold_standards": {
                "enabled": True,
                "auto_promote": {
                    "enabled": True,
                    "min_annotators": 3,
                    "agreement_threshold": 0.66  # 2/3 (0.666...) must agree
                }
            }
        }
        manager = QualityControlManager(config, "/tmp")

        manager.record_item_annotation("item_001", "user1", {"sentiment": "positive"})
        manager.record_item_annotation("item_001", "user2", {"sentiment": "negative"})
        result = manager.record_item_annotation("item_001", "user3", {"sentiment": "positive"})

        # 2/3 agree (0.666...), threshold is 0.66
        assert result is not None
        assert result["promoted"] is True

    def test_get_promoted_gold_standards(self, manager_with_auto_promote):
        """Test retrieving promoted gold standards."""
        # Promote an item
        manager_with_auto_promote.record_item_annotation(
            "item_001", "user1", {"sentiment": "positive"}
        )
        manager_with_auto_promote.record_item_annotation(
            "item_001", "user2", {"sentiment": "positive"}
        )
        manager_with_auto_promote.record_item_annotation(
            "item_001", "user3", {"sentiment": "positive"}
        )

        promoted = manager_with_auto_promote.get_promoted_gold_standards()
        assert len(promoted) == 1
        assert promoted[0]["id"] == "item_001"
        assert promoted[0]["auto_promoted"] is True
        assert promoted[0]["annotator_count"] == 3

    def test_get_promotion_candidates(self, manager_with_auto_promote):
        """Test retrieving promotion candidates."""
        # Add some annotations but not enough to promote
        manager_with_auto_promote.record_item_annotation(
            "item_001", "user1", {"sentiment": "positive"}
        )
        manager_with_auto_promote.record_item_annotation(
            "item_001", "user2", {"sentiment": "positive"}
        )

        candidates = manager_with_auto_promote.get_promotion_candidates()
        assert len(candidates) == 1
        assert candidates[0]["item_id"] == "item_001"
        assert candidates[0]["annotator_count"] == 2
        assert candidates[0]["needed_annotators"] == 3


class TestSingleton:
    """Tests for singleton pattern."""

    def teardown_method(self):
        """Clean up singleton after each test."""
        clear_quality_control_manager()

    def test_init_and_get(self):
        """Test singleton initialization and retrieval."""
        config = {"attention_checks": {"enabled": False}}
        manager = init_quality_control_manager(config, "/tmp")
        retrieved = get_quality_control_manager()

        assert manager is retrieved

    def test_clear(self):
        """Test singleton clearing."""
        config = {"attention_checks": {"enabled": False}}
        init_quality_control_manager(config, "/tmp")
        clear_quality_control_manager()

        assert get_quality_control_manager() is None
