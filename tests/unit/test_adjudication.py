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


class TestSpanAnnotationHandling:
    """Phase 2: Tests for span annotation data in adjudication."""

    def test_serialize_spans_with_span_objects(self, base_config):
        """Test _serialize_spans with mock SpanAnnotation objects."""
        mgr = AdjudicationManager(base_config)

        class MockSpan:
            def __init__(self, schema, name, title, start, end, span_id, target_field=None):
                self._schema = schema
                self._name = name
                self._title = title
                self._start = start
                self._end = end
                self._id = span_id
                self._target_field = target_field

            def get_schema(self): return self._schema
            def get_name(self): return self._name
            def get_title(self): return self._title
            def get_start(self): return self._start
            def get_end(self): return self._end
            def get_id(self): return self._id
            def get_target_field(self): return self._target_field

        mock_span = MockSpan("entity", "PERSON", "John", 0, 4, "span_1")
        span_data = {mock_span: True}
        result = mgr._serialize_spans(span_data)

        assert len(result) == 1
        assert result[0]["schema"] == "entity"
        assert result[0]["name"] == "PERSON"
        assert result[0]["title"] == "John"
        assert result[0]["start"] == 0
        assert result[0]["end"] == 4
        assert result[0]["id"] == "span_1"

    def test_serialize_spans_with_dicts(self, base_config):
        """Test _serialize_spans with already-serialized dict data."""
        mgr = AdjudicationManager(base_config)

        span_dict = {
            "key": {
                "schema": "entity",
                "name": "LOC",
                "start": 10,
                "end": 15,
            }
        }
        result = mgr._serialize_spans(span_dict)
        assert len(result) == 1
        assert result[0]["schema"] == "entity"

    def test_item_to_dict_includes_span_annotations(self):
        """AdjudicationItem.to_dict() includes span_annotations."""
        item = AdjudicationItem(
            instance_id="test_001",
            annotations={"user1": {"sentiment": "positive"}},
            span_annotations={
                "user1": [
                    {"schema": "entity", "name": "PERSON", "start": 0, "end": 5, "title": "Hello"}
                ],
                "user2": [
                    {"schema": "entity", "name": "LOC", "start": 10, "end": 15, "title": "World"}
                ]
            },
            behavioral_data={},
            agreement_scores={"sentiment": 0.5},
            overall_agreement=0.5,
            num_annotators=2,
        )
        d = item.to_dict()
        assert "span_annotations" in d
        assert "user1" in d["span_annotations"]
        assert len(d["span_annotations"]["user1"]) == 1
        assert d["span_annotations"]["user1"][0]["name"] == "PERSON"

    def test_decision_with_span_decisions(self):
        """AdjudicationDecision supports span_decisions."""
        decision = AdjudicationDecision(
            instance_id="test_001",
            adjudicator_id="expert_1",
            timestamp="2026-02-05T10:00:00",
            label_decisions={"sentiment": "positive"},
            span_decisions=[
                {"schema": "entity", "name": "PERSON", "start": 0, "end": 5},
                {"schema": "entity", "name": "LOC", "start": 10, "end": 15},
            ],
            source={"sentiment": "adjudicator", "entity": "annotator_user1"},
            confidence="high",
            notes="",
            error_taxonomy=[],
        )
        d = decision.to_dict()
        assert len(d["span_decisions"]) == 2
        assert d["span_decisions"][0]["name"] == "PERSON"

        # Roundtrip
        restored = AdjudicationDecision.from_dict(d)
        assert len(restored.span_decisions) == 2
        assert restored.span_decisions[1]["name"] == "LOC"


class TestComplexAnnotationTypes:
    """Phase 2: Tests for image, audio, video annotation data in adjudication."""

    def test_image_annotation_in_item(self):
        """Image annotation data stored as label annotations is preserved."""
        image_data = [
            {"type": "bbox", "label": "car", "coordinates": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}},
            {"type": "bbox", "label": "tree", "coordinates": {"x": 0.5, "y": 0.6, "width": 0.2, "height": 0.3}},
        ]
        item = AdjudicationItem(
            instance_id="img_001",
            annotations={
                "user1": {"image_labels": json.dumps(image_data)},
                "user2": {"image_labels": json.dumps(image_data[:1])},
            },
            span_annotations={},
            behavioral_data={},
            agreement_scores={},
            overall_agreement=0.5,
            num_annotators=2,
        )
        d = item.to_dict()
        user1_data = json.loads(d["annotations"]["user1"]["image_labels"])
        assert len(user1_data) == 2
        assert user1_data[0]["label"] == "car"

    def test_audio_annotation_in_item(self):
        """Audio annotation data stored as label annotations is preserved."""
        audio_data = {
            "segments": [
                {"id": "seg_1", "start_time": 1.5, "end_time": 5.2, "label": "speech"},
                {"id": "seg_2", "start_time": 8.0, "end_time": 12.0, "label": "music"},
            ]
        }
        item = AdjudicationItem(
            instance_id="audio_001",
            annotations={
                "user1": {"audio_labels": json.dumps(audio_data)},
            },
            span_annotations={},
            behavioral_data={},
            agreement_scores={},
            overall_agreement=1.0,
            num_annotators=1,
        )
        d = item.to_dict()
        parsed = json.loads(d["annotations"]["user1"]["audio_labels"])
        assert len(parsed["segments"]) == 2

    def test_video_annotation_in_item(self):
        """Video annotation data with segments and keyframes is preserved."""
        video_data = {
            "segments": [
                {"id": "seg_1", "startTime": 0.0, "endTime": 3.5, "label": "action"},
            ],
            "keyframes": [
                {"id": "kf_1", "frame": 30, "time": 1.0, "label": "key_moment"},
            ]
        }
        item = AdjudicationItem(
            instance_id="video_001",
            annotations={
                "user1": {"video_labels": json.dumps(video_data)},
            },
            span_annotations={},
            behavioral_data={},
            agreement_scores={},
            overall_agreement=1.0,
            num_annotators=1,
        )
        d = item.to_dict()
        parsed = json.loads(d["annotations"]["user1"]["video_labels"])
        assert len(parsed["segments"]) == 1
        assert len(parsed["keyframes"]) == 1

    def test_mixed_schema_types_in_item(self):
        """An item can contain both label and span annotations simultaneously."""
        item = AdjudicationItem(
            instance_id="mixed_001",
            annotations={
                "user1": {"sentiment": {"positive": True}},
                "user2": {"sentiment": {"negative": True}},
            },
            span_annotations={
                "user1": [{"schema": "entity", "name": "PERSON", "start": 0, "end": 5, "title": "Alice"}],
                "user2": [{"schema": "entity", "name": "ORG", "start": 10, "end": 20, "title": "Company"}],
            },
            behavioral_data={
                "user1": {"total_time_ms": 30000},
                "user2": {"total_time_ms": 25000},
            },
            agreement_scores={"sentiment": 0.0},
            overall_agreement=0.0,
            num_annotators=2,
        )
        d = item.to_dict()
        assert len(d["annotations"]) == 2
        assert len(d["span_annotations"]) == 2
        assert d["span_annotations"]["user1"][0]["name"] == "PERSON"
        assert d["span_annotations"]["user2"][0]["name"] == "ORG"

    def test_decision_with_complex_adopted_annotations(self):
        """Decisions can include adopted complex annotations in label_decisions."""
        decision = AdjudicationDecision(
            instance_id="img_001",
            adjudicator_id="expert_1",
            timestamp="2026-02-05T12:00:00",
            label_decisions={
                "image_labels": {
                    "adopted_annotations": [
                        {"annotator": "user1", "idx": "0", "type": "image"},
                        {"annotator": "user2", "idx": "1", "type": "image"},
                    ]
                }
            },
            span_decisions=[],
            source={"image_labels": "adjudicator"},
            confidence="high",
            notes="Adopted boxes from both annotators",
            error_taxonomy=[],
        )
        d = decision.to_dict()
        adopted = d["label_decisions"]["image_labels"]["adopted_annotations"]
        assert len(adopted) == 2
        assert adopted[0]["annotator"] == "user1"

        restored = AdjudicationDecision.from_dict(d)
        assert len(restored.label_decisions["image_labels"]["adopted_annotations"]) == 2


class TestDecisionOutputFormat:
    """Tests that adjudication decisions save correctly and resolved labels
    can be extracted from the on-disk decisions.json file."""

    def _make_multiselect_config(self):
        """Config with both radio and multiselect schemas."""
        return {
            "adjudication": {
                "enabled": True,
                "adjudicator_users": ["adjudicator"],
                "min_annotations": 2,
                "agreement_threshold": 0.75,
                "show_all_items": True,
                "error_taxonomy": ["ambiguous_text", "annotator_error"],
            },
            "annotation_schemes": [
                {"name": "sentiment", "annotation_type": "radio",
                 "labels": ["positive", "negative", "neutral", "mixed"]},
                {"name": "topics", "annotation_type": "multiselect",
                 "labels": ["food", "service", "price", "ambiance"]},
            ],
            "output_annotation_dir": tempfile.mkdtemp(),
            "item_properties": {"id_key": "id", "text_key": "text"},
        }

    def test_decisions_json_file_structure(self):
        """The decisions.json file has the expected top-level structure."""
        cfg = self._make_multiselect_config()
        mgr = AdjudicationManager(cfg)

        decision = AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="adjudicator",
            timestamp="2026-02-05T10:00:00",
            label_decisions={"sentiment": "positive"},
            span_decisions=[],
            source={"sentiment": "adjudicator"},
            confidence="high",
            notes="",
            error_taxonomy=[],
            time_spent_ms=5000,
        )
        mgr.submit_decision(decision)

        decisions_file = os.path.join(
            cfg["output_annotation_dir"], "adjudication", "decisions.json"
        )
        assert os.path.exists(decisions_file)

        with open(decisions_file) as f:
            data = json.load(f)

        assert "decisions" in data
        assert "last_updated" in data
        assert isinstance(data["decisions"], list)
        assert len(data["decisions"]) == 1

    def test_radio_schema_saves_single_string_label(self):
        """Radio schema decisions save as a single string value."""
        cfg = self._make_multiselect_config()
        mgr = AdjudicationManager(cfg)

        mgr.submit_decision(AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="adjudicator",
            timestamp="2026-02-05T10:00:00",
            label_decisions={"sentiment": "negative"},
            span_decisions=[],
            source={"sentiment": "adjudicator"},
            confidence="medium",
            notes="",
            error_taxonomy=[],
            time_spent_ms=3000,
        ))

        decisions_file = os.path.join(
            cfg["output_annotation_dir"], "adjudication", "decisions.json"
        )
        with open(decisions_file) as f:
            data = json.load(f)

        label = data["decisions"][0]["label_decisions"]["sentiment"]
        assert isinstance(label, str)
        assert label == "negative"

    def test_multiselect_schema_saves_dict_labels(self):
        """Multiselect schema decisions save as a dict of {label: true}."""
        cfg = self._make_multiselect_config()
        mgr = AdjudicationManager(cfg)

        mgr.submit_decision(AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="adjudicator",
            timestamp="2026-02-05T10:00:00",
            label_decisions={
                "sentiment": "mixed",
                "topics": {"food": True, "service": True},
            },
            span_decisions=[],
            source={"sentiment": "adjudicator", "topics": "adjudicator"},
            confidence="medium",
            notes="",
            error_taxonomy=[],
            time_spent_ms=4000,
        ))

        decisions_file = os.path.join(
            cfg["output_annotation_dir"], "adjudication", "decisions.json"
        )
        with open(decisions_file) as f:
            data = json.load(f)

        topics = data["decisions"][0]["label_decisions"]["topics"]
        assert isinstance(topics, dict)
        assert topics["food"] is True
        assert topics["service"] is True

    def test_extract_resolved_labels_from_file(self):
        """Resolved labels can be extracted from decisions.json for all items."""
        cfg = self._make_multiselect_config()
        mgr = AdjudicationManager(cfg)

        # Submit decisions for multiple items
        mgr.submit_decision(AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="adjudicator",
            timestamp="2026-02-05T10:00:00",
            label_decisions={
                "sentiment": "negative",
                "topics": {"service": True},
            },
            span_decisions=[],
            source={"sentiment": "adjudicator", "topics": "adjudicator"},
            confidence="medium", notes="", error_taxonomy=[],
            time_spent_ms=3000,
        ))
        mgr.submit_decision(AdjudicationDecision(
            instance_id="item_002",
            adjudicator_id="adjudicator",
            timestamp="2026-02-05T10:01:00",
            label_decisions={
                "sentiment": "positive",
                "topics": {"food": True, "ambiance": True},
            },
            span_decisions=[],
            source={"sentiment": "user_1", "topics": "adjudicator"},
            confidence="high", notes="", error_taxonomy=[],
            time_spent_ms=5000,
        ))

        # Read file back and extract resolved labels
        decisions_file = os.path.join(
            cfg["output_annotation_dir"], "adjudication", "decisions.json"
        )
        with open(decisions_file) as f:
            data = json.load(f)

        resolved = {}
        for d in data["decisions"]:
            item_id = d["instance_id"]
            labels = {}
            for schema, val in d["label_decisions"].items():
                if isinstance(val, str):
                    labels[schema] = val
                elif isinstance(val, dict):
                    labels[schema] = sorted(k for k, v in val.items() if v)
            resolved[item_id] = labels

        assert resolved["item_001"]["sentiment"] == "negative"
        assert resolved["item_001"]["topics"] == ["service"]
        assert resolved["item_002"]["sentiment"] == "positive"
        assert resolved["item_002"]["topics"] == ["ambiance", "food"]

    def test_decisions_persist_across_manager_reload(self):
        """Decisions survive creating a new AdjudicationManager instance."""
        cfg = self._make_multiselect_config()
        mgr = AdjudicationManager(cfg)

        mgr.submit_decision(AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="adjudicator",
            timestamp="2026-02-05T10:00:00",
            label_decisions={
                "sentiment": "neutral",
                "topics": {"price": True},
            },
            span_decisions=[],
            source={"sentiment": "adjudicator", "topics": "user_2"},
            confidence="low", notes="tricky item", error_taxonomy=["edge_case"],
            time_spent_ms=8000,
        ))

        # Simulate server restart by creating a new manager with same config
        mgr2 = AdjudicationManager(cfg)
        decision = mgr2.get_decision("item_001")

        assert decision is not None
        assert decision.label_decisions["sentiment"] == "neutral"
        assert decision.label_decisions["topics"] == {"price": True}
        assert decision.confidence == "low"
        assert decision.notes == "tricky item"
        assert decision.error_taxonomy == ["edge_case"]
        assert decision.source == {"sentiment": "adjudicator", "topics": "user_2"}

    def test_multiple_decisions_all_retrievable(self):
        """All submitted decisions can be individually retrieved by item ID."""
        cfg = self._make_multiselect_config()
        mgr = AdjudicationManager(cfg)

        items = {
            "item_001": {"sentiment": "positive", "topics": {"food": True}},
            "item_002": {"sentiment": "negative", "topics": {"service": True}},
            "item_003": {"sentiment": "mixed", "topics": {"food": True, "price": True}},
        }

        for item_id, labels in items.items():
            mgr.submit_decision(AdjudicationDecision(
                instance_id=item_id,
                adjudicator_id="adjudicator",
                timestamp="2026-02-05T10:00:00",
                label_decisions=labels,
                span_decisions=[],
                source={s: "adjudicator" for s in labels},
                confidence="medium", notes="", error_taxonomy=[],
                time_spent_ms=3000,
            ))

        for item_id, expected_labels in items.items():
            decision = mgr.get_decision(item_id)
            assert decision is not None, f"Decision missing for {item_id}"
            assert decision.label_decisions == expected_labels

    def test_decision_source_tracks_label_origin(self):
        """The source field correctly records where each label came from."""
        cfg = self._make_multiselect_config()
        mgr = AdjudicationManager(cfg)

        mgr.submit_decision(AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="adjudicator",
            timestamp="2026-02-05T10:00:00",
            label_decisions={
                "sentiment": "positive",
                "topics": {"food": True},
            },
            span_decisions=[],
            source={"sentiment": "user_1", "topics": "adjudicator"},
            confidence="high", notes="", error_taxonomy=[],
            time_spent_ms=2000,
        ))

        decision = mgr.get_decision("item_001")
        assert decision.source["sentiment"] == "user_1"
        assert decision.source["topics"] == "adjudicator"

    def test_decision_metadata_preserved(self):
        """Confidence, notes, error_taxonomy, and timing are all preserved."""
        cfg = self._make_multiselect_config()
        mgr = AdjudicationManager(cfg)

        mgr.submit_decision(AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="adjudicator",
            timestamp="2026-02-05T10:00:00",
            label_decisions={"sentiment": "negative"},
            span_decisions=[],
            source={"sentiment": "adjudicator"},
            confidence="low",
            notes="Very ambiguous text",
            error_taxonomy=["ambiguous_text", "annotator_error"],
            guideline_update_flag=True,
            guideline_update_notes="Need examples for sarcasm",
            time_spent_ms=12000,
        ))

        # Reload and check all metadata
        mgr2 = AdjudicationManager(cfg)
        d = mgr2.get_decision("item_001")

        assert d.confidence == "low"
        assert d.notes == "Very ambiguous text"
        assert d.error_taxonomy == ["ambiguous_text", "annotator_error"]
        assert d.guideline_update_flag is True
        assert d.guideline_update_notes == "Need examples for sarcasm"
        assert d.time_spent_ms == 12000
        assert d.adjudicator_id == "adjudicator"

    def test_undecided_items_return_none(self):
        """get_decision returns None for items without a decision."""
        cfg = self._make_multiselect_config()
        mgr = AdjudicationManager(cfg)

        assert mgr.get_decision("nonexistent_item") is None

    def test_decision_overwrites_previous(self):
        """Submitting a new decision for the same item overwrites the old one."""
        cfg = self._make_multiselect_config()
        mgr = AdjudicationManager(cfg)

        # Add item to queue so submit_decision can update its status
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

        mgr.submit_decision(AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="adjudicator",
            timestamp="2026-02-05T10:00:00",
            label_decisions={"sentiment": "positive"},
            span_decisions=[],
            source={"sentiment": "adjudicator"},
            confidence="high", notes="", error_taxonomy=[],
            time_spent_ms=3000,
        ))
        assert mgr.get_decision("item_001").label_decisions["sentiment"] == "positive"

        mgr.submit_decision(AdjudicationDecision(
            instance_id="item_001",
            adjudicator_id="adjudicator",
            timestamp="2026-02-05T10:05:00",
            label_decisions={"sentiment": "negative"},
            span_decisions=[],
            source={"sentiment": "adjudicator"},
            confidence="low", notes="Changed my mind", error_taxonomy=[],
            time_spent_ms=6000,
        ))
        assert mgr.get_decision("item_001").label_decisions["sentiment"] == "negative"
        assert mgr.get_decision("item_001").notes == "Changed my mind"
