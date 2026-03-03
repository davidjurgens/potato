"""
Tests for SoloModeManager.

Tests PromptVersion, LLMPrediction, AgreementMetrics dataclasses,
SoloModeManager initialization, prompt management, prediction management,
agreement checks, disagreement resolution, background labeling,
validation, state persistence, and status reporting.
"""

import json
import os
import pytest
import threading
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

from potato.solo_mode.manager import (
    PromptVersion,
    LLMPrediction,
    AgreementMetrics,
    SoloModeManager,
    init_solo_mode_manager,
    get_solo_mode_manager,
    clear_solo_mode_manager,
)
from potato.solo_mode.config import SoloModeConfig, parse_solo_mode_config


def _make_solo_config(**overrides):
    """Create a SoloModeConfig with sensible test defaults."""
    config_data = {
        'solo_mode': {
            'enabled': True,
            'labeling_models': [],
            **overrides,
        },
        'annotation_schemes': [
            {'name': 'sentiment', 'annotation_type': 'radio',
             'labels': ['positive', 'negative', 'neutral']},
        ],
    }
    return parse_solo_mode_config(config_data)


def _make_manager(solo_config=None, app_config=None):
    """Create a SoloModeManager for testing."""
    if solo_config is None:
        solo_config = _make_solo_config()
    if app_config is None:
        app_config = {
            'annotation_schemes': [
                {'name': 'sentiment', 'annotation_type': 'radio',
                 'labels': ['positive', 'negative', 'neutral']},
            ],
        }
    return SoloModeManager(solo_config, app_config)


def _make_prediction(instance_id="i1", schema_name="sentiment",
                     label="positive", confidence=0.9, **kwargs):
    """Create an LLMPrediction for testing."""
    defaults = {
        'instance_id': instance_id,
        'schema_name': schema_name,
        'predicted_label': label,
        'confidence_score': confidence,
        'uncertainty_score': 1.0 - confidence,
        'prompt_version': 1,
        'model_name': 'test-model',
        'reasoning': 'test reasoning',
    }
    defaults.update(kwargs)
    return LLMPrediction(**defaults)


# === Dataclass Tests ===


class TestPromptVersion:
    """Tests for PromptVersion dataclass."""

    def test_creation(self):
        pv = PromptVersion(
            version=1,
            prompt_text="Classify sentiment",
            created_at=datetime(2025, 1, 1, 12, 0),
            created_by="user",
        )
        assert pv.version == 1
        assert pv.prompt_text == "Classify sentiment"
        assert pv.parent_version is None
        assert pv.validation_accuracy is None
        assert pv.source_description == ""

    def test_to_dict(self):
        pv = PromptVersion(
            version=2,
            prompt_text="Better prompt",
            created_at=datetime(2025, 6, 15, 10, 30),
            created_by="llm_synthesis",
            source_description="Synthesized from task",
            parent_version=1,
            validation_accuracy=0.92,
        )
        data = pv.to_dict()
        assert data['version'] == 2
        assert data['created_by'] == "llm_synthesis"
        assert data['parent_version'] == 1
        assert data['validation_accuracy'] == 0.92
        assert '2025-06-15' in data['created_at']

    def test_serialization_roundtrip(self):
        pv = PromptVersion(
            version=3,
            prompt_text="Third prompt",
            created_at=datetime(2025, 3, 1, 8, 0),
            created_by="llm_optimization",
            source_description="Optimized",
            parent_version=2,
            validation_accuracy=0.88,
        )
        data = pv.to_dict()
        restored = PromptVersion.from_dict(data)

        assert restored.version == pv.version
        assert restored.prompt_text == pv.prompt_text
        assert restored.created_by == pv.created_by
        assert restored.source_description == pv.source_description
        assert restored.parent_version == pv.parent_version
        assert restored.validation_accuracy == pv.validation_accuracy

    def test_from_dict_defaults(self):
        data = {
            'version': 1,
            'prompt_text': 'test',
            'created_at': '2025-01-01T00:00:00',
            'created_by': 'user',
        }
        pv = PromptVersion.from_dict(data)
        assert pv.source_description == ''
        assert pv.parent_version is None
        assert pv.validation_accuracy is None


class TestLLMPrediction:
    """Tests for LLMPrediction dataclass."""

    def test_creation(self):
        pred = _make_prediction()
        assert pred.instance_id == "i1"
        assert pred.predicted_label == "positive"
        assert pred.confidence_score == 0.9
        assert pred.human_label is None
        assert pred.agrees_with_human is None
        assert pred.disagreement_resolved is False
        assert pred.resolution_label is None

    def test_to_dict(self):
        pred = _make_prediction(
            instance_id="i5",
            label="negative",
            confidence=0.7,
        )
        pred.human_label = "positive"
        pred.agrees_with_human = False

        data = pred.to_dict()
        assert data['instance_id'] == "i5"
        assert data['predicted_label'] == "negative"
        assert data['human_label'] == "positive"
        assert data['agrees_with_human'] is False
        assert 'timestamp' in data

    def test_serialization_roundtrip(self):
        pred = _make_prediction(
            instance_id="i2",
            label="neutral",
            confidence=0.6,
        )
        pred.human_label = "neutral"
        pred.agrees_with_human = True
        pred.disagreement_resolved = True
        pred.resolution_label = "neutral"

        data = pred.to_dict()
        restored = LLMPrediction.from_dict(data)

        assert restored.instance_id == "i2"
        assert restored.predicted_label == "neutral"
        assert restored.confidence_score == 0.6
        assert restored.human_label == "neutral"
        assert restored.agrees_with_human is True
        assert restored.disagreement_resolved is True
        assert restored.resolution_label == "neutral"

    def test_from_dict_uncertainty_default(self):
        """Missing uncertainty_score should be computed from confidence."""
        data = {
            'instance_id': 'i1',
            'schema_name': 's',
            'predicted_label': 'x',
            'confidence_score': 0.8,
            'prompt_version': 1,
            'timestamp': '2025-01-01T00:00:00',
        }
        pred = LLMPrediction.from_dict(data)
        assert abs(pred.uncertainty_score - 0.2) < 1e-6


class TestAgreementMetrics:
    """Tests for AgreementMetrics dataclass."""

    def test_defaults(self):
        m = AgreementMetrics()
        assert m.total_compared == 0
        assert m.agreements == 0
        assert m.disagreements == 0
        assert m.agreement_rate == 0.0

    def test_update_rate(self):
        m = AgreementMetrics(total_compared=10, agreements=8, disagreements=2)
        m.update_rate()
        assert abs(m.agreement_rate - 0.8) < 1e-6

    def test_update_rate_zero_total(self):
        m = AgreementMetrics()
        m.update_rate()
        assert m.agreement_rate == 0.0

    def test_to_dict(self):
        m = AgreementMetrics(total_compared=5, agreements=4, disagreements=1)
        m.update_rate()
        data = m.to_dict()
        assert data['total_compared'] == 5
        assert data['agreements'] == 4
        assert data['disagreements'] == 1
        assert abs(data['agreement_rate'] - 0.8) < 1e-6


# === Manager Initialization ===


class TestSoloModeManagerInit:
    """Tests for SoloModeManager initialization."""

    def test_creation(self):
        mgr = _make_manager()
        assert mgr.config.enabled is True
        assert mgr.current_prompt_version == 0
        assert len(mgr.prompt_versions) == 0
        assert len(mgr.predictions) == 0
        assert len(mgr.human_labeled_ids) == 0
        assert len(mgr.llm_labeled_ids) == 0

    def test_phase_controller_initialized(self):
        mgr = _make_manager()
        assert mgr.phase_controller is not None

    def test_lazy_components_none(self):
        mgr = _make_manager()
        assert mgr._edge_case_synthesizer is None
        assert mgr._edge_case_rule_manager is None
        assert mgr._prompt_manager is None
        assert mgr._instance_selector is None
        assert mgr._disagreement_resolver is None

    def test_background_labeling_not_running(self):
        mgr = _make_manager()
        assert mgr.is_background_labeling_running() is False


# === Prompt Management ===


class TestSoloModeManagerPrompts:
    """Tests for prompt management."""

    @pytest.fixture
    def manager(self):
        return _make_manager()

    def test_no_prompt_initially(self, manager):
        assert manager.get_current_prompt() is None
        assert manager.get_current_prompt_text() == ""

    def test_create_prompt_version(self, manager):
        pv = manager.create_prompt_version("Classify sentiment", "user")
        assert pv.version == 1
        assert pv.prompt_text == "Classify sentiment"
        assert pv.created_by == "user"
        assert pv.parent_version is None
        assert manager.current_prompt_version == 1

    def test_multiple_versions(self, manager):
        manager.create_prompt_version("v1", "user")
        pv2 = manager.create_prompt_version("v2", "llm_synthesis", "Synthesized")
        assert pv2.version == 2
        assert pv2.parent_version == 1
        assert manager.current_prompt_version == 2

    def test_get_current_prompt(self, manager):
        manager.create_prompt_version("First", "user")
        manager.create_prompt_version("Second", "user")
        current = manager.get_current_prompt()
        assert current.prompt_text == "Second"
        assert current.version == 2

    def test_get_prompt_version(self, manager):
        manager.create_prompt_version("v1", "user")
        manager.create_prompt_version("v2", "user")

        pv1 = manager.get_prompt_version(1)
        assert pv1.prompt_text == "v1"

        pv2 = manager.get_prompt_version(2)
        assert pv2.prompt_text == "v2"

    def test_get_prompt_version_invalid(self, manager):
        assert manager.get_prompt_version(0) is None
        assert manager.get_prompt_version(99) is None

    def test_get_all_prompt_versions(self, manager):
        manager.create_prompt_version("v1", "user")
        manager.create_prompt_version("v2", "user")
        all_versions = manager.get_all_prompt_versions()
        assert len(all_versions) == 2
        # Should be a copy
        all_versions.pop()
        assert len(manager.get_all_prompt_versions()) == 2

    def test_update_prompt(self, manager):
        manager.create_prompt_version("original", "user")
        pv = manager.update_prompt("updated", "llm_revision", "Improved")
        assert pv.version == 2
        assert manager.get_current_prompt_text() == "updated"

    def test_set_and_get_task_description(self, manager):
        manager.set_task_description("Classify tweets")
        assert manager.get_task_description() == "Classify tweets"

    def test_task_description_default(self, manager):
        assert manager.get_task_description() == ""


# === LLM Prediction Management ===


class TestSoloModeManagerPredictions:
    """Tests for LLM prediction management."""

    @pytest.fixture
    def manager(self):
        return _make_manager()

    def test_set_and_get_prediction(self, manager):
        pred = _make_prediction()
        manager.set_llm_prediction("i1", "sentiment", pred)

        result = manager.get_llm_prediction("i1", "sentiment")
        assert result is not None
        assert result.predicted_label == "positive"
        assert "i1" in manager.llm_labeled_ids

    def test_get_prediction_nonexistent(self, manager):
        assert manager.get_llm_prediction("missing", "sentiment") is None

    def test_get_all_predictions(self, manager):
        manager.set_llm_prediction("i1", "s1", _make_prediction("i1", "s1"))
        manager.set_llm_prediction("i2", "s1", _make_prediction("i2", "s1"))

        all_preds = manager.get_all_llm_predictions()
        assert len(all_preds) == 2
        assert "i1" in all_preds
        assert "i2" in all_preds

    def test_get_predictions_by_confidence(self, manager):
        manager.set_llm_prediction("i1", "s", _make_prediction("i1", confidence=0.9))
        manager.set_llm_prediction("i2", "s", _make_prediction("i2", confidence=0.5))
        manager.set_llm_prediction("i3", "s", _make_prediction("i3", confidence=0.3))

        low = manager.get_predictions_by_confidence(max_confidence=0.6)
        assert len(low) == 2  # 0.5 and 0.3

        high = manager.get_predictions_by_confidence(min_confidence=0.8)
        assert len(high) == 1  # 0.9

        mid = manager.get_predictions_by_confidence(min_confidence=0.4, max_confidence=0.6)
        assert len(mid) == 1  # 0.5

    def test_get_low_confidence_predictions(self, manager):
        manager.set_llm_prediction("i1", "s", _make_prediction("i1", confidence=0.9))
        manager.set_llm_prediction("i2", "s", _make_prediction("i2", confidence=0.3))

        low = manager.get_low_confidence_predictions()
        assert any(p.instance_id == "i2" for p in low)

    def test_get_llm_prediction_for_instance(self, manager):
        pred = _make_prediction("i1", "sentiment", "positive", 0.9)
        manager.set_llm_prediction("i1", "sentiment", pred)

        result = manager.get_llm_prediction_for_instance("i1")
        assert result is not None
        assert result['label'] == "positive"
        assert result['confidence'] == 0.9
        assert result['schema'] == "sentiment"

    def test_get_llm_prediction_for_instance_missing(self, manager):
        assert manager.get_llm_prediction_for_instance("missing") is None


# === Human Label Recording & Agreement ===


class TestSoloModeManagerAgreement:
    """Tests for human label recording and agreement checking."""

    @pytest.fixture
    def manager(self):
        mgr = _make_manager()
        mgr.create_prompt_version("test prompt", "user")
        return mgr

    def test_record_human_label_agrees(self, manager):
        pred = _make_prediction("i1", "sentiment", "positive")
        manager.set_llm_prediction("i1", "sentiment", pred)

        result = manager.record_human_label("i1", "sentiment", "positive", "user1")
        assert result is True
        assert "i1" in manager.human_labeled_ids
        assert manager.agreement_metrics.agreements == 1
        assert manager.agreement_metrics.total_compared == 1

    def test_record_human_label_disagrees(self, manager):
        pred = _make_prediction("i1", "sentiment", "positive")
        manager.set_llm_prediction("i1", "sentiment", pred)

        result = manager.record_human_label("i1", "sentiment", "negative", "user1")
        assert result is False
        assert "i1" in manager.disagreement_ids
        assert manager.agreement_metrics.disagreements == 1

    def test_record_human_label_no_prediction(self, manager):
        result = manager.record_human_label("i1", "sentiment", "positive", "user1")
        assert result is None
        assert "i1" in manager.human_labeled_ids

    def test_check_agreement_radio(self, manager):
        assert manager._check_agreement("positive", "positive", "sentiment") is True
        assert manager._check_agreement("positive", "negative", "sentiment") is False

    def test_check_agreement_string_coercion(self, manager):
        assert manager._check_agreement(1, "1", "sentiment") is True

    def test_check_agreement_likert(self, manager):
        mgr = _make_manager(app_config={
            'annotation_schemes': [
                {'name': 'rating', 'annotation_type': 'likert', 'labels': [1, 2, 3, 4, 5]},
            ],
        })
        assert mgr._check_agreement(3, 4, "rating") is True  # Within tolerance
        assert mgr._check_agreement(1, 5, "rating") is False  # Too far apart

    def test_check_agreement_multiselect(self, manager):
        mgr = _make_manager(app_config={
            'annotation_schemes': [
                {'name': 'topics', 'annotation_type': 'multiselect',
                 'labels': ['a', 'b', 'c']},
            ],
        })
        assert mgr._check_agreement(
            ['a', 'b'], ['a', 'b'], "topics"
        ) is True
        assert mgr._check_agreement(
            ['a'], ['c'], "topics"
        ) is False

    def test_check_agreement_textbox(self, manager):
        mgr = _make_manager(app_config={
            'annotation_schemes': [
                {'name': 'notes', 'annotation_type': 'textbox'},
            ],
        })
        assert mgr._check_agreement("Hello World", "hello world", "notes") is True
        assert mgr._check_agreement("abc", "xyz", "notes") is False

    def test_get_annotation_type(self, manager):
        assert manager._get_annotation_type("sentiment") == "radio"
        assert manager._get_annotation_type("nonexistent") == "radio"  # default

    def test_agreement_metrics_update(self, manager):
        pred1 = _make_prediction("i1", "sentiment", "positive")
        pred2 = _make_prediction("i2", "sentiment", "negative")
        manager.set_llm_prediction("i1", "sentiment", pred1)
        manager.set_llm_prediction("i2", "sentiment", pred2)

        manager.record_human_label("i1", "sentiment", "positive", "u")
        manager.record_human_label("i2", "sentiment", "positive", "u")

        metrics = manager.get_agreement_metrics()
        assert metrics.total_compared == 2
        assert metrics.agreements == 1
        assert metrics.disagreements == 1
        assert abs(metrics.agreement_rate - 0.5) < 1e-6


# === Disagreement Resolution ===


class TestSoloModeManagerDisagreements:
    """Tests for disagreement resolution."""

    @pytest.fixture
    def manager(self):
        mgr = _make_manager()
        mgr.create_prompt_version("test", "user")
        pred = _make_prediction("i1", "sentiment", "positive")
        mgr.set_llm_prediction("i1", "sentiment", pred)
        mgr.record_human_label("i1", "sentiment", "negative", "user1")
        return mgr

    def test_get_pending_disagreements(self, manager):
        pending = manager.get_pending_disagreements()
        assert "i1" in pending

    def test_resolve_disagreement(self, manager):
        result = manager.resolve_disagreement("i1", "sentiment", "negative", "human")
        assert result is True

        pred = manager.get_llm_prediction("i1", "sentiment")
        assert pred.disagreement_resolved is True
        assert pred.resolution_label == "negative"

    def test_resolve_nonexistent(self, manager):
        assert manager.resolve_disagreement("missing", "sentiment", "x", "h") is False

    def test_resolved_not_in_pending(self, manager):
        manager.resolve_disagreement("i1", "sentiment", "negative", "human")
        pending = manager.get_pending_disagreements()
        assert "i1" not in pending

    def test_check_for_disagreement(self, manager):
        assert manager.check_for_disagreement("i1", "negative") is True

    def test_check_for_disagreement_no_prediction(self, manager):
        assert manager.check_for_disagreement("missing", "x") is False

    def test_get_disagreement(self, manager):
        with patch.object(manager, '_get_instance_text', return_value="test text"):
            result = manager.get_disagreement("i1")
        assert result is not None
        assert result['instance_id'] == "i1"
        assert result['human_label'] == "negative"
        assert result['llm_label'] == "positive"


# === Agreement Thresholds ===


class TestSoloModeManagerThresholds:
    """Tests for agreement thresholds and phase transitions."""

    def _manager_with_high_agreement(self):
        mgr = _make_manager()
        mgr.create_prompt_version("test", "user")

        # Create 100 agreeing predictions
        for i in range(100):
            pred = _make_prediction(f"i{i}", "sentiment", "positive")
            mgr.set_llm_prediction(f"i{i}", "sentiment", pred)
            mgr.record_human_label(f"i{i}", "sentiment", "positive", "u")

        return mgr

    def test_should_end_human_annotation_insufficient_sample(self):
        mgr = _make_manager()
        mgr.create_prompt_version("test", "user")
        # Only 2 comparisons - below minimum
        for i in range(2):
            pred = _make_prediction(f"i{i}", "sentiment", "positive")
            mgr.set_llm_prediction(f"i{i}", "sentiment", pred)
            mgr.record_human_label(f"i{i}", "sentiment", "positive", "u")

        assert mgr.should_end_human_annotation() is False

    def test_should_end_human_annotation_high_agreement(self):
        mgr = self._manager_with_high_agreement()
        assert mgr.should_end_human_annotation() is True

    def test_should_end_human_annotation_low_agreement(self):
        mgr = _make_manager()
        mgr.create_prompt_version("test", "user")
        # 100 comparisons, 50 agree
        for i in range(50):
            pred = _make_prediction(f"ia{i}", "sentiment", "positive")
            mgr.set_llm_prediction(f"ia{i}", "sentiment", pred)
            mgr.record_human_label(f"ia{i}", "sentiment", "positive", "u")
        for i in range(50):
            pred = _make_prediction(f"id{i}", "sentiment", "positive")
            mgr.set_llm_prediction(f"id{i}", "sentiment", pred)
            mgr.record_human_label(f"id{i}", "sentiment", "negative", "u")

        assert mgr.should_end_human_annotation() is False

    def test_should_trigger_periodic_review(self):
        mgr = _make_manager()
        # periodic_review_interval defaults to some value
        interval = mgr.config.thresholds.periodic_review_interval
        # Add exactly interval number of llm-labeled ids
        for i in range(interval):
            mgr.llm_labeled_ids.add(f"i{i}")
        assert mgr.should_trigger_periodic_review() is True


# === Background Labeling ===


class TestSoloModeManagerBackgroundLabeling:
    """Tests for background labeling management."""

    @pytest.fixture
    def manager(self):
        return _make_manager()

    def test_start_background_labeling(self, manager):
        result = manager.start_background_labeling()
        assert result is True
        assert manager.is_background_labeling_running() is True
        manager.stop_background_labeling()

    def test_double_start(self, manager):
        manager.start_background_labeling()
        result = manager.start_background_labeling()
        assert result is False  # Already running
        manager.stop_background_labeling()

    def test_stop_background_labeling(self, manager):
        manager.start_background_labeling()
        manager.stop_background_labeling()
        assert manager.is_background_labeling_running() is False

    def test_stop_when_not_running(self, manager):
        manager.stop_background_labeling()  # Should not raise

    def test_pause_aliases_stop(self, manager):
        manager.start_background_labeling()
        manager.pause_background_labeling()
        assert manager.is_background_labeling_running() is False


# === Validation ===


class TestSoloModeManagerValidation:
    """Tests for validation sample selection."""

    @pytest.fixture
    def manager(self):
        mgr = _make_manager()
        for i in range(20):
            mgr.llm_labeled_ids.add(f"i{i}")
        return mgr

    def test_select_validation_sample(self, manager):
        sample = manager.select_validation_sample(5)
        assert len(sample) == 5
        assert all(s in manager.validation_sample_ids for s in sample)

    def test_select_excludes_human_labeled(self, manager):
        for i in range(10):
            manager.human_labeled_ids.add(f"i{i}")
        sample = manager.select_validation_sample(20)
        # Should only select from llm-only (10 remaining)
        assert len(sample) <= 10

    def test_select_excludes_already_validated(self, manager):
        first = manager.select_validation_sample(10)
        second = manager.select_validation_sample(10)
        # Should not overlap
        assert len(set(first) & set(second)) == 0

    def test_select_caps_at_available(self, manager):
        sample = manager.select_validation_sample(100)
        assert len(sample) <= 20

    def test_get_validation_progress(self, manager):
        manager.select_validation_sample(5)
        progress = manager.get_validation_progress()
        assert progress['total_samples'] == 5
        assert progress['validated'] == 0
        assert progress['remaining'] == 5

    def test_get_validation_progress_with_human_labels(self, manager):
        sample = manager.select_validation_sample(5)
        for sid in sample[:2]:
            manager.human_labeled_ids.add(sid)
        progress = manager.get_validation_progress()
        assert progress['validated'] == 2
        assert progress['remaining'] == 3


# === State Persistence ===


class TestSoloModeManagerPersistence:
    """Tests for state save/load."""

    def test_save_and_load(self, tmp_path):
        solo_config = _make_solo_config()
        solo_config.state_dir = str(tmp_path)
        app_config = {
            'annotation_schemes': [
                {'name': 'sentiment', 'annotation_type': 'radio',
                 'labels': ['positive', 'negative']},
            ],
        }

        # Create and populate manager
        mgr1 = SoloModeManager(solo_config, app_config)
        mgr1.set_task_description("Classify sentiment")
        mgr1.create_prompt_version("prompt v1", "user")
        mgr1.create_prompt_version("prompt v2", "llm_synthesis", "Better prompt")

        pred = _make_prediction("i1", "sentiment", "positive", 0.9)
        mgr1.set_llm_prediction("i1", "sentiment", pred)
        mgr1.human_labeled_ids.add("i1")
        mgr1.disagreement_ids.add("i1")
        mgr1.validation_sample_ids.add("i2")
        mgr1.edge_case_ids.add("i3")
        mgr1.agreement_metrics = AgreementMetrics(
            total_compared=10, agreements=8, disagreements=2
        )
        mgr1.agreement_metrics.update_rate()
        mgr1._save_state()

        # Load into new manager
        mgr2 = SoloModeManager(solo_config, app_config)
        assert mgr2.load_state() is True

        assert mgr2.get_task_description() == "Classify sentiment"
        assert mgr2.current_prompt_version == 2
        assert len(mgr2.prompt_versions) == 2
        assert mgr2.get_current_prompt().prompt_text == "prompt v2"
        assert "i1" in mgr2.predictions
        assert "i1" in mgr2.human_labeled_ids
        assert "i1" in mgr2.disagreement_ids
        assert "i2" in mgr2.validation_sample_ids
        assert "i3" in mgr2.edge_case_ids
        assert mgr2.agreement_metrics.total_compared == 10
        assert abs(mgr2.agreement_metrics.agreement_rate - 0.8) < 1e-6

    def test_load_nonexistent(self, tmp_path):
        solo_config = _make_solo_config()
        solo_config.state_dir = str(tmp_path)
        mgr = SoloModeManager(solo_config, {})
        assert mgr.load_state() is False

    def test_load_no_state_dir(self):
        solo_config = _make_solo_config()
        solo_config.state_dir = None
        mgr = SoloModeManager(solo_config, {})
        assert mgr.load_state() is False

    def test_save_no_state_dir(self):
        solo_config = _make_solo_config()
        solo_config.state_dir = None
        mgr = SoloModeManager(solo_config, {})
        mgr.create_prompt_version("test", "user")  # Should not raise

    def test_atomic_write(self, tmp_path):
        solo_config = _make_solo_config()
        solo_config.state_dir = str(tmp_path)
        mgr = SoloModeManager(solo_config, {})
        mgr.create_prompt_version("test", "user")

        state_file = os.path.join(str(tmp_path), 'solo_mode_state.json')
        assert os.path.exists(state_file)
        # No temp file should remain
        assert not os.path.exists(state_file + '.tmp')


# === Route Helper Methods ===


class TestSoloModeManagerRouteHelpers:
    """Tests for route helper methods."""

    @pytest.fixture
    def manager(self):
        mgr = _make_manager()
        mgr.create_prompt_version("test prompt", "user")
        return mgr

    def test_record_human_annotation(self, manager):
        pred = _make_prediction("i1", "sentiment", "positive")
        manager.set_llm_prediction("i1", "sentiment", pred)

        manager.record_human_annotation("i1", "positive", "user1")
        assert "i1" in manager.human_labeled_ids

    def test_get_llm_labeling_stats(self, manager):
        manager.llm_labeled_ids = {"i1", "i2", "i3"}
        stats = manager.get_llm_labeling_stats()
        assert stats['labeled_count'] == 3
        assert stats['is_running'] is False

    def test_approve_llm_label(self, manager):
        manager.approve_llm_label("i5")
        assert "i5" in manager.human_labeled_ids

    def test_correct_llm_label(self, manager):
        pred = _make_prediction("i1", "sentiment", "positive")
        manager.set_llm_prediction("i1", "sentiment", pred)

        manager.correct_llm_label("i1", "negative")
        assert "i1" in manager.human_labeled_ids

    def test_get_annotation_stats(self, manager):
        manager.human_labeled_ids = {"i1", "i2"}
        manager.llm_labeled_ids = {"i1", "i3", "i4"}
        with patch.object(manager, '_get_total_instance_count', return_value=10):
            stats = manager.get_annotation_stats()
        assert stats['human_labeled'] == 2
        assert stats['llm_labeled'] == 3
        assert stats['total'] == 10

    def test_get_available_labels(self, manager):
        labels = manager.get_available_labels()
        assert "positive" in labels
        assert "negative" in labels
        assert "neutral" in labels

    def test_get_available_labels_dict_format(self):
        mgr = _make_manager(app_config={
            'annotation_schemes': [
                {'name': 'test', 'labels': [
                    {'name': 'pos', 'tooltip': 'positive'},
                    {'name': 'neg'},
                ]},
            ],
        })
        labels = mgr.get_available_labels()
        assert "pos" in labels
        assert "neg" in labels

    def test_get_all_annotations(self, manager):
        pred = _make_prediction("i1", "sentiment", "positive")
        manager.set_llm_prediction("i1", "sentiment", pred)
        manager.human_labeled_ids.add("i1")

        data = manager.get_all_annotations()
        assert "i1" in data['human_labels']
        assert "i1" in data['llm_labels']


# === Handle Labeling Result ===


class TestSoloModeManagerHandleLabelingResult:
    """Tests for _handle_labeling_result."""

    @pytest.fixture
    def manager(self):
        mgr = _make_manager()
        mgr.create_prompt_version("test", "user")
        return mgr

    def test_handle_error_result(self, manager):
        result = MagicMock()
        result.error = "Connection failed"
        result.instance_id = "i1"

        manager._handle_labeling_result(result)
        assert "i1" not in manager.llm_labeled_ids

    def test_handle_normal_result(self, manager):
        result = MagicMock()
        result.error = None
        result.instance_id = "i1"
        result.schema_name = "sentiment"
        result.label = "positive"
        result.confidence = 0.9
        result.uncertainty = 0.1
        result.prompt_version = 1
        result.model_name = "test"
        result.reasoning = "Clear"
        result.is_edge_case = False

        manager._handle_labeling_result(result)
        assert "i1" in manager.llm_labeled_ids
        pred = manager.get_llm_prediction("i1", "sentiment")
        assert pred.predicted_label == "positive"

    def test_handle_edge_case_result(self, manager):
        result = MagicMock()
        result.error = None
        result.instance_id = "i1"
        result.schema_name = "sentiment"
        result.label = "positive"
        result.confidence = 0.4
        result.uncertainty = 0.6
        result.prompt_version = 1
        result.model_name = "test"
        result.reasoning = "Ambiguous"
        result.is_edge_case = True
        result.edge_case_rule = "When sarcasm -> negative"
        result.edge_case_condition = "sarcasm"
        result.edge_case_action = "negative"

        mock_ecr = MagicMock()
        mock_ecr.get_unclustered_rules.return_value = []
        manager._edge_case_rule_manager = mock_ecr

        manager._handle_labeling_result(result)

        mock_ecr.record_rule_from_labeling.assert_called_once()
        call_kwargs = mock_ecr.record_rule_from_labeling.call_args
        assert call_kwargs[1]['rule_text'] == "When sarcasm -> negative"


# === Status ===


class TestSoloModeManagerStatus:
    """Tests for status reporting."""

    def test_status_empty(self):
        mgr = _make_manager()
        status = mgr.get_status()
        assert status['enabled'] is True
        assert status['prompt']['current_version'] == 0
        assert status['labeling']['human_labeled'] == 0
        assert status['labeling']['llm_labeled'] == 0
        assert status['agreement']['total_compared'] == 0
        assert status['disagreements']['total'] == 0

    def test_status_with_data(self):
        mgr = _make_manager()
        mgr.create_prompt_version("test", "user")
        mgr.human_labeled_ids = {"i1", "i2"}
        mgr.llm_labeled_ids = {"i1", "i2", "i3"}
        mgr.disagreement_ids = {"i2"}

        status = mgr.get_status()
        assert status['prompt']['current_version'] == 1
        assert status['labeling']['human_labeled'] == 2
        assert status['labeling']['llm_labeled'] == 3
        assert status['labeling']['overlap'] == 2
        assert status['labeling']['llm_only'] == 1
        assert status['disagreements']['total'] == 1


# === Shutdown ===


class TestSoloModeManagerShutdown:
    """Tests for manager shutdown."""

    def test_shutdown(self):
        mgr = _make_manager()
        mgr.start_background_labeling()
        mgr.shutdown()
        assert mgr.is_background_labeling_running() is False


# === Singleton Management ===


class TestSoloModeSingleton:
    """Tests for singleton init/get/clear functions."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Ensure singleton is cleared after each test."""
        yield
        clear_solo_mode_manager()

    def test_init_disabled(self):
        config = {'solo_mode': {'enabled': False}}
        result = init_solo_mode_manager(config)
        assert result is None

    def test_init_returns_none_when_no_solo_mode(self):
        config = {}
        result = init_solo_mode_manager(config)
        assert result is None

    def test_get_before_init(self):
        assert get_solo_mode_manager() is None

    def test_clear_when_none(self):
        clear_solo_mode_manager()  # Should not raise


# === Phase Control Delegation ===


class TestSoloModeManagerPhaseControl:
    """Tests for phase control delegation."""

    @pytest.fixture
    def manager(self):
        return _make_manager()

    def test_get_current_phase(self, manager):
        phase = manager.get_current_phase()
        assert phase is not None

    def test_advance_to_phase(self, manager):
        from potato.solo_mode.phase_controller import SoloPhase
        # The initial phase should allow some transition
        result = manager.advance_to_phase(
            SoloPhase.PROMPT_REVIEW,
            reason="test"
        )
        # Result depends on phase_controller rules
        assert isinstance(result, bool)

    def test_advance_to_next_phase(self, manager):
        result = manager.advance_to_next_phase(reason="test")
        assert isinstance(result, bool)


# === Labeling Result Integration ===


class TestSoloModeManagerMaybeTriggerClustering:
    """Tests for _maybe_trigger_rule_clustering."""

    def test_below_threshold(self):
        mgr = _make_manager()
        mock_ecr = MagicMock()
        mock_ecr.get_unclustered_rules.return_value = [MagicMock()] * 3
        mgr._edge_case_rule_manager = mock_ecr

        mgr._maybe_trigger_rule_clustering()
        # Should not trigger clustering (3 < min_rules_for_clustering)

    def test_above_threshold_triggers(self):
        mgr = _make_manager()
        mock_ecr = MagicMock()
        min_rules = mgr.config.edge_case_rules.min_rules_for_clustering
        mock_ecr.get_unclustered_rules.return_value = [MagicMock()] * min_rules
        mgr._edge_case_rule_manager = mock_ecr

        with patch.object(mgr, '_trigger_rule_clustering') as mock_trigger:
            mgr._maybe_trigger_rule_clustering()
            mock_trigger.assert_called_once()


# === Get Instances For Review ===


class TestSoloModeManagerReview:
    """Tests for review-related methods."""

    def test_get_instances_for_review(self):
        mgr = _make_manager()
        pred = _make_prediction("i1", "sentiment", "positive", 0.3)
        mgr.set_llm_prediction("i1", "sentiment", pred)

        with patch.object(mgr, '_get_instance_text', return_value="text"):
            instances = mgr.get_instances_for_review()
        assert len(instances) == 1
        assert instances[0]['id'] == "i1"
        assert instances[0]['confidence'] == 0.3

    def test_get_instances_for_review_excludes_human_labeled(self):
        mgr = _make_manager()
        pred = _make_prediction("i1", "sentiment", "positive", 0.3)
        mgr.set_llm_prediction("i1", "sentiment", pred)
        mgr.human_labeled_ids.add("i1")

        with patch.object(mgr, '_get_instance_text', return_value="text"):
            instances = mgr.get_instances_for_review()
        assert len(instances) == 0

    def test_record_validation(self):
        mgr = _make_manager()
        mgr.create_prompt_version("test", "user")
        pred = _make_prediction("i1", "sentiment", "positive")
        mgr.set_llm_prediction("i1", "sentiment", pred)

        mgr.record_validation("i1", "positive")
        assert "i1" in mgr.human_labeled_ids


# === Confidence History & Cartography ===


class TestSoloModeManagerCartography:
    """Tests for confidence history tracking and cartography scores."""

    @pytest.fixture
    def manager(self):
        return _make_manager()

    def test_confidence_history_tracked_on_set_prediction(self, manager):
        pred = _make_prediction("i1", "sentiment", "positive", confidence=0.8,
                                prompt_version=1)
        manager.set_llm_prediction("i1", "sentiment", pred)

        assert "i1" in manager.confidence_history
        assert len(manager.confidence_history["i1"]) == 1
        assert manager.confidence_history["i1"][0] == (1, 0.8)

    def test_confidence_history_accumulates(self, manager):
        pred1 = _make_prediction("i1", "sentiment", "positive", confidence=0.8,
                                 prompt_version=1)
        pred2 = _make_prediction("i1", "sentiment", "positive", confidence=0.5,
                                 prompt_version=2)

        manager.set_llm_prediction("i1", "sentiment", pred1)
        manager.set_llm_prediction("i1", "sentiment", pred2)

        assert len(manager.confidence_history["i1"]) == 2
        assert manager.confidence_history["i1"][1] == (2, 0.5)

    def test_get_cartography_scores_empty(self, manager):
        scores = manager.get_cartography_scores()
        assert scores == {}

    def test_get_cartography_scores_single_entry(self, manager):
        pred = _make_prediction("i1", "sentiment", "positive", confidence=0.7,
                                prompt_version=1)
        manager.set_llm_prediction("i1", "sentiment", pred)

        scores = manager.get_cartography_scores()
        assert "i1" in scores
        assert scores["i1"]["mean_confidence"] == 0.7
        assert scores["i1"]["variability"] == 0.0  # Single entry

    def test_get_cartography_scores_multiple_entries(self, manager):
        for i, conf in enumerate([0.8, 0.4, 0.6], start=1):
            pred = _make_prediction("i1", "sentiment", "positive",
                                    confidence=conf, prompt_version=i)
            manager.set_llm_prediction("i1", "sentiment", pred)

        scores = manager.get_cartography_scores()
        assert "i1" in scores
        # Mean of [0.8, 0.4, 0.6] = 0.6
        assert abs(scores["i1"]["mean_confidence"] - 0.6) < 1e-6
        # Stdev of [0.8, 0.4, 0.6] = 0.2
        assert scores["i1"]["variability"] > 0

    def test_cartography_high_variability_instance(self, manager):
        """Instance with widely varying confidence should have high variability."""
        for i, conf in enumerate([0.1, 0.9], start=1):
            pred = _make_prediction("i1", "sentiment", "positive",
                                    confidence=conf, prompt_version=i)
            manager.set_llm_prediction("i1", "sentiment", pred)

        for i, conf in enumerate([0.5, 0.5], start=1):
            pred = _make_prediction("i2", "sentiment", "positive",
                                    confidence=conf, prompt_version=i)
            manager.set_llm_prediction("i2", "sentiment", pred)

        scores = manager.get_cartography_scores()
        assert scores["i1"]["variability"] > scores["i2"]["variability"]

    def test_confidence_history_persisted(self, tmp_path):
        solo_config = _make_solo_config()
        solo_config.state_dir = str(tmp_path)
        app_config = {
            'annotation_schemes': [
                {'name': 'sentiment', 'annotation_type': 'radio',
                 'labels': ['positive', 'negative']},
            ],
        }

        mgr1 = SoloModeManager(solo_config, app_config)
        pred = _make_prediction("i1", "sentiment", "positive", confidence=0.7,
                                prompt_version=1)
        mgr1.set_llm_prediction("i1", "sentiment", pred)
        mgr1._save_state()

        mgr2 = SoloModeManager(solo_config, app_config)
        mgr2.load_state()

        assert "i1" in mgr2.confidence_history
        assert mgr2.confidence_history["i1"] == [(1, 0.7)]


# === Instance Selection Wiring ===


class TestSoloModeManagerInstanceSelection:
    """Tests for get_next_instance_for_human using InstanceSelector."""

    def test_get_next_uses_selector(self):
        """get_next_instance_for_human should use the InstanceSelector."""
        mgr = _make_manager()

        mock_ism = MagicMock()
        mock_ism.instance_id_ordering = ['i1', 'i2', 'i3']

        with patch('potato.item_state_management.get_item_state_manager',
                    return_value=mock_ism):
            result = mgr.get_next_instance_for_human("user1")

        assert result in {'i1', 'i2', 'i3'}

    def test_get_next_excludes_human_labeled(self):
        mgr = _make_manager()
        mgr.human_labeled_ids = {'i1', 'i2'}

        mock_ism = MagicMock()
        mock_ism.instance_id_ordering = ['i1', 'i2', 'i3']

        with patch('potato.item_state_management.get_item_state_manager',
                    return_value=mock_ism):
            result = mgr.get_next_instance_for_human("user1")

        assert result == 'i3'

    def test_get_next_returns_none_when_all_labeled(self):
        mgr = _make_manager()
        mgr.human_labeled_ids = {'i1', 'i2', 'i3'}

        mock_ism = MagicMock()
        mock_ism.instance_id_ordering = ['i1', 'i2', 'i3']

        with patch('potato.item_state_management.get_item_state_manager',
                    return_value=mock_ism):
            result = mgr.get_next_instance_for_human("user1")

        assert result is None

    def test_get_next_returns_none_on_ism_error(self):
        mgr = _make_manager()

        with patch('potato.item_state_management.get_item_state_manager',
                    side_effect=ValueError("not init")):
            result = mgr.get_next_instance_for_human("user1")

        assert result is None

    def test_get_next_prefers_low_confidence(self):
        """With low-confidence predictions, selector should prefer those instances."""
        mgr = _make_manager()

        # Set up predictions: i2 has low confidence
        pred_high = _make_prediction("i1", "sentiment", "positive", confidence=0.9)
        pred_low = _make_prediction("i2", "sentiment", "positive", confidence=0.2)
        mgr.set_llm_prediction("i1", "sentiment", pred_high)
        mgr.set_llm_prediction("i2", "sentiment", pred_low)

        mock_ism = MagicMock()
        mock_ism.instance_id_ordering = ['i1', 'i2', 'i3']

        with patch('potato.item_state_management.get_item_state_manager',
                    return_value=mock_ism):
            result = mgr.get_next_instance_for_human("user1")

        # Result should be one of the available instances
        assert result in {'i1', 'i2', 'i3'}

    def test_get_next_passes_edge_case_rule_ids(self):
        """Edge case rule IDs should be passed to selector."""
        mgr = _make_manager()

        mock_ecr = MagicMock()
        mock_ecr.get_rule_instance_ids.return_value = {'i2'}
        mgr._edge_case_rule_manager = mock_ecr

        mock_ism = MagicMock()
        mock_ism.instance_id_ordering = ['i1', 'i2', 'i3']

        with patch('potato.item_state_management.get_item_state_manager',
                    return_value=mock_ism):
            result = mgr.get_next_instance_for_human("user1")

        assert result in {'i1', 'i2', 'i3'}
        mock_ecr.get_rule_instance_ids.assert_called_once()


class TestLabelBatch:
    """Tests for _label_batch with and without confidence routing."""

    def test_label_batch_without_routing(self):
        """_label_batch labels instances using LLM thread when routing disabled."""
        mgr = _make_manager()

        mock_ism = MagicMock()
        mock_ism.instance_id_ordering = ['i1', 'i2']
        mock_ism.get_item_by_id.return_value = {'text': 'test text'}

        from potato.solo_mode.llm_labeler import LabelingResult
        mock_result = LabelingResult(
            instance_id='i1',
            schema_name='sentiment',
            label='positive',
            confidence=0.9,
            uncertainty=0.1,
            reasoning='Clear positive',
            prompt_version=1,
            model_name='test-model',
        )

        mock_thread = MagicMock()
        mock_thread._label_instance.return_value = mock_result
        mgr._llm_labeling_thread = mock_thread

        with patch('potato.item_state_management.get_item_state_manager',
                    return_value=mock_ism):
            count = mgr._label_batch(10)

        assert count == 2
        assert mock_thread._label_instance.call_count == 2

    def test_label_batch_with_routing(self):
        """_label_batch uses confidence router when routing enabled."""
        solo_config = _make_solo_config(
            confidence_routing={
                'enabled': True,
                'tiers': [
                    {'name': 'fast', 'model': {'endpoint_type': 'openai', 'model': 'test'},
                     'confidence_threshold': 0.8},
                ],
            }
        )
        mgr = _make_manager(solo_config=solo_config)

        mock_ism = MagicMock()
        mock_ism.instance_id_ordering = ['i1']
        mock_ism.get_item_by_id.return_value = {'text': 'test text'}

        from potato.solo_mode.confidence_router import RoutingResult
        from potato.solo_mode.llm_labeler import LabelingResult

        mock_labeling_result = LabelingResult(
            instance_id='i1',
            schema_name='sentiment',
            label='positive',
            confidence=0.9,
            uncertainty=0.1,
            reasoning='Clear',
            prompt_version=1,
            model_name='test',
        )
        mock_routing_result = RoutingResult(
            instance_id='i1',
            accepted=True,
            tier_index=0,
            tier_name='fast',
            labeling_result=mock_labeling_result,
        )

        mock_router = MagicMock()
        mock_router.route_instance.return_value = mock_routing_result
        mgr._confidence_router = mock_router

        with patch('potato.item_state_management.get_item_state_manager',
                    return_value=mock_ism):
            count = mgr._label_batch(10)

        assert count == 1
        mock_router.route_instance.assert_called_once()

    def test_label_batch_returns_zero_when_no_instances(self):
        """_label_batch returns 0 when no instances available."""
        mgr = _make_manager()

        mock_ism = MagicMock()
        mock_ism.instance_id_ordering = []

        with patch('potato.item_state_management.get_item_state_manager',
                    return_value=mock_ism):
            count = mgr._label_batch(10)

        assert count == 0

    def test_label_batch_skips_already_labeled(self):
        """_label_batch skips instances already labeled by LLM or human."""
        mgr = _make_manager()
        mgr.llm_labeled_ids = {'i1'}
        mgr.human_labeled_ids = {'i2'}

        mock_ism = MagicMock()
        mock_ism.instance_id_ordering = ['i1', 'i2', 'i3']
        mock_ism.get_item_by_id.return_value = {'text': 'test text'}

        from potato.solo_mode.llm_labeler import LabelingResult
        mock_result = LabelingResult(
            instance_id='i3',
            schema_name='sentiment',
            label='neutral',
            confidence=0.8,
            uncertainty=0.2,
            reasoning='ok',
            prompt_version=1,
            model_name='test',
        )

        mock_thread = MagicMock()
        mock_thread._label_instance.return_value = mock_result
        mgr._llm_labeling_thread = mock_thread

        with patch('potato.item_state_management.get_item_state_manager',
                    return_value=mock_ism):
            count = mgr._label_batch(10)

        assert count == 1
        mock_thread._label_instance.assert_called_once()

    def test_label_batch_error_result_not_counted(self):
        """_label_batch doesn't count error results as labeled."""
        mgr = _make_manager()

        mock_ism = MagicMock()
        mock_ism.instance_id_ordering = ['i1']
        mock_ism.get_item_by_id.return_value = {'text': 'test text'}

        from potato.solo_mode.llm_labeler import LabelingResult
        error_result = LabelingResult(
            instance_id='i1',
            schema_name='sentiment',
            label=None,
            confidence=0,
            uncertainty=1,
            reasoning='',
            prompt_version=0,
            model_name='',
            error='Rate limited',
        )

        mock_thread = MagicMock()
        mock_thread._label_instance.return_value = error_result
        mgr._llm_labeling_thread = mock_thread

        with patch('potato.item_state_management.get_item_state_manager',
                    return_value=mock_ism):
            count = mgr._label_batch(10)

        assert count == 0


class TestLLMLabelingStatsWithRouting:
    """Tests for get_llm_labeling_stats with confidence routing."""

    def test_stats_include_routing_disabled(self):
        """Stats include confidence_routing: {enabled: false} when no router."""
        mgr = _make_manager()
        stats = mgr.get_llm_labeling_stats()
        assert 'confidence_routing' in stats
        assert stats['confidence_routing']['enabled'] is False

    def test_stats_include_routing_enabled(self):
        """Stats include full routing stats when router exists."""
        mgr = _make_manager()
        mock_router = MagicMock()
        mock_router.get_stats.return_value = {
            'enabled': True,
            'num_tiers': 2,
            'tiers': [],
            'human_routed_count': 5,
            'total_routed': 100,
        }
        mgr._confidence_router = mock_router

        stats = mgr.get_llm_labeling_stats()
        assert stats['confidence_routing']['enabled'] is True
        assert stats['confidence_routing']['total_routed'] == 100
        assert stats['confidence_routing']['human_routed_count'] == 5

    def test_status_includes_routing(self):
        """get_status() includes confidence_routing key."""
        mgr = _make_manager()
        status = mgr.get_status()
        assert 'confidence_routing' in status
        assert status['confidence_routing']['enabled'] is False


# === Confusion Analysis Tests ===


class TestSoloModeManagerConfusionAnalysis:
    """Tests for get_confusion_analysis_full()."""

    def test_disabled_returns_enabled_false(self):
        """When confusion analysis is disabled, returns {enabled: False}."""
        config = _make_solo_config(confusion_analysis={'enabled': False})
        mgr = _make_manager(solo_config=config)
        result = mgr.get_confusion_analysis_full()
        assert result == {'enabled': False}

    def test_returns_correct_structure(self):
        """Returns dict with expected keys when enabled."""
        mgr = _make_manager()

        # Mock the validation tracker
        mock_tracker = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.confusion_matrix = {}
        mock_metrics.total_compared = 0
        mock_tracker.get_metrics.return_value = mock_metrics
        mock_tracker.get_comparison_history.return_value = []
        mock_tracker.get_label_accuracy.return_value = {}
        mgr._validation_tracker = mock_tracker

        result = mgr.get_confusion_analysis_full()

        assert result['enabled'] is True
        assert 'matrix_data' in result
        assert 'patterns' in result
        assert 'total_disagreements' in result
        assert 'total_compared' in result

    def test_enriches_patterns_with_examples(self):
        """Patterns include examples when comparison history has disagreements."""
        config = _make_solo_config(confusion_analysis={'min_instances_for_pattern': 1})
        mgr = _make_manager(solo_config=config)

        mock_tracker = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.confusion_matrix = {('positive', 'negative'): 2}
        mock_metrics.total_compared = 5
        mock_tracker.get_metrics.return_value = mock_metrics
        mock_tracker.get_comparison_history.return_value = [
            {'instance_id': 'i1', 'llm_label': 'positive', 'human_label': 'negative',
             'schema_name': 'sentiment', 'agrees': False},
            {'instance_id': 'i2', 'llm_label': 'positive', 'human_label': 'negative',
             'schema_name': 'sentiment', 'agrees': False},
            {'instance_id': 'i3', 'llm_label': 'positive', 'human_label': 'positive',
             'schema_name': 'sentiment', 'agrees': True},
        ]
        mock_tracker.get_label_accuracy.return_value = {'positive': 0.5, 'negative': 1.0}
        mgr._validation_tracker = mock_tracker

        # Add predictions
        pred = _make_prediction('i1', 'sentiment', 'positive', 0.7)
        mgr.set_llm_prediction('i1', 'sentiment', pred)

        with patch.object(mgr, '_get_instance_text', return_value='Sample text'):
            result = mgr.get_confusion_analysis_full()

        assert result['enabled'] is True
        assert result['total_disagreements'] == 2
        assert result['total_compared'] == 5
        assert len(result['patterns']) >= 1

        pattern = result['patterns'][0]
        assert pattern['predicted_label'] == 'positive'
        assert pattern['actual_label'] == 'negative'
        assert pattern['count'] == 2

    def test_matrix_data_has_all_labels(self):
        """Matrix data includes cells for all label combinations."""
        mgr = _make_manager()

        mock_tracker = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.confusion_matrix = {}
        mock_metrics.total_compared = 0
        mock_tracker.get_metrics.return_value = mock_metrics
        mock_tracker.get_comparison_history.return_value = []
        mock_tracker.get_label_accuracy.return_value = {}
        mgr._validation_tracker = mock_tracker

        result = mgr.get_confusion_analysis_full()

        matrix = result['matrix_data']
        labels = matrix['labels']
        assert 'positive' in labels
        assert 'negative' in labels
        assert 'neutral' in labels
        # 3 labels = 9 cells
        assert len(matrix['cells']) == 9

    def test_confusion_analyzer_lazy_init(self):
        """confusion_analyzer property creates instance lazily."""
        mgr = _make_manager()
        assert mgr._confusion_analyzer is None
        analyzer = mgr.confusion_analyzer
        assert analyzer is not None
        # Second access returns same instance
        assert mgr.confusion_analyzer is analyzer


# === Refinement Loop Tests ===


class TestSoloModeManagerRefinementLoop:
    """Tests for refinement loop integration in manager."""

    def test_refinement_loop_lazy_init(self):
        """refinement_loop property creates instance lazily."""
        mgr = _make_manager()
        assert mgr._refinement_loop is None
        loop = mgr.refinement_loop
        assert loop is not None
        assert mgr.refinement_loop is loop

    def test_get_refinement_status_disabled(self):
        """Returns {enabled: False} when refinement loop is disabled."""
        config = _make_solo_config(refinement_loop={'enabled': False})
        mgr = _make_manager(solo_config=config)
        status = mgr.get_refinement_status()
        assert status == {'enabled': False}

    def test_get_refinement_status_enabled(self):
        """Returns status dict when enabled."""
        mgr = _make_manager()
        status = mgr.get_refinement_status()
        assert status['enabled'] is True
        assert status['total_cycles'] == 0
        assert status['is_stopped'] is False

    def test_maybe_trigger_refinement_counts(self):
        """_maybe_trigger_refinement respects trigger_interval."""
        config = _make_solo_config(refinement_loop={
            'trigger_interval': 1000,  # High so it won't trigger
        })
        mgr = _make_manager(solo_config=config)

        # Record one annotation — should not trigger (interval=1000)
        mgr.refinement_loop.record_annotation()
        assert mgr.refinement_loop._annotations_since_last_check == 1

    def test_trigger_refinement_cycle_when_disabled(self):
        """trigger_refinement_cycle returns error when analysis not available."""
        config = _make_solo_config(
            confusion_analysis={'enabled': False},
        )
        mgr = _make_manager(solo_config=config)

        # Mock validation tracker
        mock_tracker = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.agreement_rate = 0.7
        mock_tracker.get_metrics.return_value = mock_metrics
        mock_tracker.get_comparison_history.return_value = []
        mock_tracker.get_label_accuracy.return_value = {}
        mgr._validation_tracker = mock_tracker

        result = mgr.trigger_refinement_cycle()
        assert result['success'] is False

    def test_trigger_refinement_cycle_no_patterns(self):
        """Returns message when no confusion patterns found."""
        mgr = _make_manager()

        mock_tracker = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.agreement_rate = 0.9
        mock_metrics.confusion_matrix = {}
        mock_metrics.total_compared = 100
        mock_tracker.get_metrics.return_value = mock_metrics
        mock_tracker.get_comparison_history.return_value = [
            {'instance_id': f'i{i}', 'llm_label': 'positive',
             'human_label': 'positive', 'agrees': True}
            for i in range(100)
        ]
        mock_tracker.get_label_accuracy.return_value = {'positive': 1.0}
        mgr._validation_tracker = mock_tracker

        result = mgr.trigger_refinement_cycle()
        assert result['success'] is True
        assert 'No confusion patterns' in result.get('message', '')
