"""
Tests for the periodic-review and rule-review phase wiring (2026-07-23).

These phases had full routes/templates/dashboard buttons but nothing ever
transitioned into them (the "unreachable review phases" gap). This verifies the
new triggers:
- the periodic-review counter is incremented per LLM label (_handle_labeling_result)
- check_and_enter_periodic_review() enters PERIODIC_REVIEW when due + items exist
- check_and_enter_rule_review() enters RULE_REVIEW when categories are pending
- both step through ACTIVE_ANNOTATION when starting from PARALLEL_ANNOTATION
"""

from unittest.mock import MagicMock, patch

import pytest

from potato.solo_mode.manager import SoloModeManager, LLMPrediction
from potato.solo_mode.config import parse_solo_mode_config
from potato.solo_mode.phase_controller import SoloPhase


def _make_solo_config(**overrides):
    config_data = {
        'solo_mode': {'enabled': True, 'labeling_models': [], **overrides},
        'annotation_schemes': [
            {'name': 'sentiment', 'annotation_type': 'radio',
             'labels': ['positive', 'negative', 'neutral']},
        ],
    }
    return parse_solo_mode_config(config_data)


def _make_manager():
    app_config = {'annotation_schemes': [
        {'name': 'sentiment', 'annotation_type': 'radio',
         'labels': ['positive', 'negative', 'neutral']}]}
    mgr = SoloModeManager(_make_solo_config(), app_config)
    mgr.create_prompt_version("test prompt", "user")
    return mgr


def _pred(iid, label="positive", confidence=0.3):
    return LLMPrediction(
        instance_id=iid, schema_name="sentiment", predicted_label=label,
        confidence_score=confidence, uncertainty_score=1 - confidence,
        prompt_version=1, model_name='m', reasoning='r')


class TestPeriodicReviewCounter:
    def test_record_llm_label_triggers_after_interval(self):
        mgr = _make_manager()
        mgr.validation_tracker.periodic_review_interval = 3
        assert mgr.validation_tracker.should_trigger_periodic_review() is False
        for i in range(3):
            mgr.validation_tracker.record_llm_label(f"i{i}")
        assert mgr.validation_tracker.should_trigger_periodic_review() is True
        mgr.validation_tracker.reset_periodic_review_counter()
        assert mgr.validation_tracker.should_trigger_periodic_review() is False


class TestEnterPeriodicReview:
    def _due_manager(self, interval=3):
        mgr = _make_manager()
        # confidence_low defaults to 0.5, so conf 0.3 preds are review-eligible.
        mgr.validation_tracker.periodic_review_interval = interval
        return mgr

    def test_enters_when_due_with_low_conf_items(self):
        mgr = self._due_manager()
        mgr.phase_controller.transition_to(SoloPhase.PARALLEL_ANNOTATION, force=True)
        for i in range(3):
            mgr.set_llm_prediction(f"i{i}", "sentiment", _pred(f"i{i}", confidence=0.3))
            mgr.validation_tracker.record_llm_label(f"i{i}")
        assert mgr.check_and_enter_periodic_review() is True
        assert mgr.get_current_phase() == SoloPhase.PERIODIC_REVIEW

    def test_no_enter_when_not_due(self):
        mgr = self._due_manager(interval=10)
        mgr.phase_controller.transition_to(SoloPhase.ACTIVE_ANNOTATION, force=True)
        mgr.set_llm_prediction("i0", "sentiment", _pred("i0", confidence=0.3))
        assert mgr.check_and_enter_periodic_review() is False
        assert mgr.get_current_phase() == SoloPhase.ACTIVE_ANNOTATION

    def test_due_but_no_review_items_resets_counter(self):
        mgr = self._due_manager(interval=2)
        mgr.phase_controller.transition_to(SoloPhase.ACTIVE_ANNOTATION, force=True)
        # only high-confidence preds -> nothing review-eligible
        mgr.set_llm_prediction("i0", "sentiment", _pred("i0", confidence=0.95))
        for i in range(2):
            mgr.validation_tracker.record_llm_label(f"i{i}")
        assert mgr.check_and_enter_periodic_review() is False
        assert mgr.validation_tracker.should_trigger_periodic_review() is False
        assert mgr.get_current_phase() == SoloPhase.ACTIVE_ANNOTATION

    def test_not_triggered_outside_annotation_phases(self):
        mgr = self._due_manager(interval=1)
        mgr.phase_controller.transition_to(SoloPhase.SETUP, force=True)
        mgr.set_llm_prediction("i0", "sentiment", _pred("i0", confidence=0.3))
        mgr.validation_tracker.record_llm_label("i0")
        assert mgr.check_and_enter_periodic_review() is False


class TestEnterRuleReview:
    def test_enters_when_categories_pending(self):
        mgr = _make_manager()
        mgr.phase_controller.transition_to(SoloPhase.PARALLEL_ANNOTATION, force=True)
        with patch.object(mgr.edge_case_rule_manager, 'get_pending_categories',
                          return_value=[MagicMock()]):
            assert mgr.check_and_enter_rule_review() is True
            assert mgr.get_current_phase() == SoloPhase.RULE_REVIEW

    def test_no_enter_when_no_pending_categories(self):
        mgr = _make_manager()
        mgr.phase_controller.transition_to(SoloPhase.ACTIVE_ANNOTATION, force=True)
        with patch.object(mgr.edge_case_rule_manager, 'get_pending_categories',
                          return_value=[]):
            assert mgr.check_and_enter_rule_review() is False
            assert mgr.get_current_phase() == SoloPhase.ACTIVE_ANNOTATION

    def test_not_triggered_outside_annotation_phases(self):
        mgr = _make_manager()
        mgr.phase_controller.transition_to(SoloPhase.COMPLETED, force=True)
        with patch.object(mgr.edge_case_rule_manager, 'get_pending_categories',
                          return_value=[MagicMock()]):
            assert mgr.check_and_enter_rule_review() is False


class TestHandleLabelingResultIncrementsCounter:
    def test_labeling_result_advances_periodic_counter(self):
        mgr = _make_manager()
        mgr.validation_tracker.periodic_review_interval = 2
        result = MagicMock()
        result.error = None
        result.instance_id = "i1"
        result.schema_name = "sentiment"
        result.label = "positive"
        result.confidence = 0.9
        result.uncertainty = 0.1
        result.prompt_version = 1
        result.model_name = "m"
        result.reasoning = "r"
        result.is_edge_case = False
        before = mgr.validation_tracker._llm_labels_since_review
        mgr._handle_labeling_result(result)
        assert mgr.validation_tracker._llm_labels_since_review == before + 1
