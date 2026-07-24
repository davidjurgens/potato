"""
Regression tests for solo-mode bugs found during browser testing on 2026-07-23.

Covers the backend fixes (the UI-layer fixes in the templates are exercised by
the Selenium suite):
- BUG #5: double-submit must not double-count agreement metrics / confusion matrix
- BUG #6: agreement handoff PARALLEL_ANNOTATION -> AUTONOMOUS_LABELING must not
          raise an invalid-transition ValueError
- BUG #7: autonomous labeling completion must advance to FINAL_VALIDATION
"""

from unittest.mock import patch

import pytest

from potato.solo_mode.manager import (
    LLMPrediction,
    SoloModeManager,
)
from potato.solo_mode.config import parse_solo_mode_config
from potato.solo_mode.phase_controller import SoloPhase


def _make_solo_config(**overrides):
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


def _make_manager(solo_config=None):
    if solo_config is None:
        solo_config = _make_solo_config()
    app_config = {
        'annotation_schemes': [
            {'name': 'sentiment', 'annotation_type': 'radio',
             'labels': ['positive', 'negative', 'neutral']},
        ],
    }
    mgr = SoloModeManager(solo_config, app_config)
    mgr.create_prompt_version("test prompt", "user")
    return mgr


def _make_prediction(instance_id="i1", label="positive", confidence=0.9):
    return LLMPrediction(
        instance_id=instance_id,
        schema_name="sentiment",
        predicted_label=label,
        confidence_score=confidence,
        uncertainty_score=1.0 - confidence,
        prompt_version=1,
        model_name='test-model',
        reasoning='test reasoning',
    )


class TestDoubleSubmitIdempotency:
    """BUG #5: re-submitting the same instance must not double-count."""

    def test_repeated_record_counts_once(self):
        mgr = _make_manager()
        mgr.set_llm_prediction("i1", "sentiment", _make_prediction("i1", "positive"))

        mgr.record_human_label("i1", "sentiment", "positive", "u")
        mgr.record_human_label("i1", "sentiment", "positive", "u")
        mgr.record_human_label("i1", "sentiment", "positive", "u")

        assert mgr.agreement_metrics.total_compared == 1
        assert mgr.agreement_metrics.agreements == 1
        assert mgr.agreement_metrics.disagreements == 0

    def test_repeated_disagreement_counts_once(self):
        mgr = _make_manager()
        mgr.set_llm_prediction("i1", "sentiment", _make_prediction("i1", "positive"))

        mgr.record_human_label("i1", "sentiment", "negative", "u")
        mgr.record_human_label("i1", "sentiment", "negative", "u")

        assert mgr.agreement_metrics.total_compared == 1
        assert mgr.agreement_metrics.disagreements == 1
        assert "i1" in mgr.disagreement_ids

    def test_distinct_instances_still_counted_separately(self):
        mgr = _make_manager()
        mgr.set_llm_prediction("i1", "sentiment", _make_prediction("i1", "positive"))
        mgr.set_llm_prediction("i2", "sentiment", _make_prediction("i2", "negative"))

        mgr.record_human_label("i1", "sentiment", "positive", "u")
        mgr.record_human_label("i2", "sentiment", "negative", "u")

        assert mgr.agreement_metrics.total_compared == 2
        assert mgr.agreement_metrics.agreements == 2


class TestAgreementHandoffTransition:
    """BUG #6: PARALLEL_ANNOTATION -> AUTONOMOUS_LABELING must not raise."""

    def test_handoff_from_parallel_does_not_raise_and_advances(self):
        mgr = _make_manager(_make_solo_config(thresholds={
            'end_human_annotation_agreement': 0.5,
            'minimum_validation_sample': 2,
        }))
        mgr.phase_controller.transition_to(SoloPhase.PARALLEL_ANNOTATION, force=True)

        # High agreement, enough samples.
        mgr.agreement_metrics.total_compared = 5
        mgr.agreement_metrics.agreements = 5
        mgr.agreement_metrics.update_rate()

        advanced = mgr.check_and_advance_to_autonomous()

        assert advanced is True
        assert mgr.get_current_phase() == SoloPhase.AUTONOMOUS_LABELING

    def test_handoff_below_threshold_stays_put(self):
        mgr = _make_manager(_make_solo_config(thresholds={
            'end_human_annotation_agreement': 0.9,
            'minimum_validation_sample': 2,
        }))
        mgr.phase_controller.transition_to(SoloPhase.PARALLEL_ANNOTATION, force=True)
        mgr.agreement_metrics.total_compared = 5
        mgr.agreement_metrics.agreements = 2  # 40% < 90%
        mgr.agreement_metrics.update_rate()

        assert mgr.check_and_advance_to_autonomous() is False
        assert mgr.get_current_phase() == SoloPhase.PARALLEL_ANNOTATION


class TestLikertLabelDerivation:
    """BUG #12: likert schemes (size/min_label/max_label, no labels list) must
    still yield selectable labels for the solo UI + LLM labeler."""

    def _likert_manager(self):
        config_data = {
            'solo_mode': {'enabled': True, 'labeling_models': []},
            'annotation_schemes': [{
                'name': 'positivity', 'annotation_type': 'likert',
                'description': 'tone', 'size': 5,
                'min_label': 'Very negative', 'max_label': 'Very positive',
            }],
        }
        solo_config = parse_solo_mode_config(config_data)
        app_config = {'annotation_schemes': config_data['annotation_schemes']}
        return SoloModeManager(solo_config, app_config)

    def test_get_available_labels_derives_scale_points(self):
        mgr = self._likert_manager()
        assert mgr.get_available_labels() == ['1', '2', '3', '4', '5']

    def test_labeler_valid_labels_for_likert(self):
        from potato.solo_mode.llm_labeler import LLMLabelingThread
        scheme = {'name': 'positivity', 'annotation_type': 'likert', 'size': 5,
                  'min_label': 'Very negative', 'max_label': 'Very positive'}
        # These helpers only use schema_info (+ self._get_valid_labels); an
        # uninitialized instance is enough to exercise them.
        labeler = object.__new__(LLMLabelingThread)
        assert labeler._get_valid_labels(scheme) == ['1', '2', '3', '4', '5']
        extracted = labeler._extract_labels(scheme)
        assert '1' in extracted and '5' in extracted
        assert 'Very negative' in extracted and 'Very positive' in extracted


class TestAnnotationTypeUIs:
    """Textbox (text) + multiselect wiring for solo mode."""

    def _mgr(self, atype, labels=None):
        scheme = {'name': 's', 'annotation_type': atype, 'description': 'd'}
        if labels is not None:
            scheme['labels'] = labels
        config_data = {'solo_mode': {'enabled': True, 'labeling_models': []},
                       'annotation_schemes': [scheme]}
        return SoloModeManager(parse_solo_mode_config(config_data),
                               {'annotation_schemes': [scheme]})

    def test_get_annotation_type(self):
        assert self._mgr('multiselect', ['a', 'b']).get_annotation_type() == 'multiselect'
        assert self._mgr('text').get_annotation_type() == 'text'

    def test_to_label_set_parses_all_forms(self):
        f = SoloModeManager._to_label_set
        assert f('["joy","gratitude"]') == {'joy', 'gratitude'}   # JSON array string
        assert f('joy, gratitude') == {'joy', 'gratitude'}         # comma string
        assert f(['joy', 'gratitude']) == {'joy', 'gratitude'}     # list
        assert f('joy') == {'joy'}                                 # single
        assert f('') == set() and f(None) == set()                 # empty
        # never a char-set:
        assert f('joy') != set('joy')

    def test_multiselect_agreement_jaccard(self):
        mgr = self._mgr('multiselect', ['joy', 'sadness', 'gratitude'])
        mgr.create_prompt_version('p', 'u')
        # exact set match -> agree
        assert mgr._check_agreement('["joy"]', '["joy"]', 's') is True
        # half overlap == threshold 0.5 -> agree
        assert mgr._check_agreement('["joy"]', '["joy","sadness"]', 's') is True
        # no overlap -> disagree
        assert mgr._check_agreement('["joy"]', '["sadness"]', 's') is False

    def test_text_agreement_case_insensitive(self):
        mgr = self._mgr('text')
        mgr.create_prompt_version('p', 'u')
        assert mgr._check_agreement('Happiness', 'happiness', 's') is True
        assert mgr._check_agreement('Happiness', 'sadness', 's') is False

    def test_parse_spans_forms(self):
        f = SoloModeManager._parse_spans
        assert f('[{"start":0,"end":5,"label":"a"}]') == [{'start': 0, 'end': 5, 'label': 'a'}]
        assert f([{'start': 2, 'end': 4, 'label': 'b'}]) == [{'start': 2, 'end': 4, 'label': 'b'}]
        assert f('') == [] and f('not json') == [] and f(None) == []
        # entries lacking start/end are dropped
        assert f('[{"label":"x"}]') == []

    def test_span_agreement_overlap(self):
        mgr = self._mgr('span', ['pos', 'neg'])
        mgr.create_prompt_version('p', 'u')
        thr = mgr.config.thresholds.span_overlap_threshold  # default 0.5
        llm = '[{"start":10,"end":30,"label":"pos"}]'
        # exact same span -> full overlap -> agree
        assert mgr._check_agreement(llm, '[{"start":10,"end":30,"label":"pos"}]', 's') is True
        # same offsets, different label -> no same-label overlap -> disagree
        assert mgr._check_agreement(llm, '[{"start":10,"end":30,"label":"neg"}]', 's') is False
        # no overlap -> disagree
        assert mgr._check_agreement(llm, '[{"start":40,"end":50,"label":"pos"}]', 's') is False
        # partial overlap >= threshold (human 10-30 len20, overlap 10-25 =15 -> 0.75) -> agree
        assert mgr._check_agreement(llm, '[{"start":10,"end":25,"label":"pos"}]', 's') is True
        # both empty -> agree
        assert mgr._check_agreement('[]', '[]', 's') is True
        # one empty -> disagree
        assert mgr._check_agreement(llm, '[]', 's') is False

    def test_labeler_multiselect_prompt_hint(self):
        from potato.solo_mode.llm_labeler import LLMLabelingThread
        labeler = object.__new__(LLMLabelingThread)
        ms = {'name': 's', 'annotation_type': 'multiselect', 'labels': ['a', 'b']}
        rad = {'name': 's', 'annotation_type': 'radio', 'labels': ['a', 'b']}
        # helper reflects type: multiselect asks for a list
        assert labeler._get_valid_labels(ms) == ['a', 'b']
        assert labeler._get_valid_labels(rad) == ['a', 'b']


class TestAutonomousToValidation:
    """BUG #7: autonomous completion advances to FINAL_VALIDATION."""

    def test_advances_when_dataset_fully_covered(self):
        mgr = _make_manager()
        mgr.phase_controller.transition_to(SoloPhase.AUTONOMOUS_LABELING, force=True)
        mgr.human_labeled_ids = {f"i{i}" for i in range(10)}

        with patch.object(mgr, '_get_total_instance_count', return_value=10):
            mgr._maybe_advance_autonomous_to_validation()

        assert mgr.get_current_phase() == SoloPhase.FINAL_VALIDATION

    def test_does_not_advance_when_work_remains(self):
        mgr = _make_manager()
        mgr.phase_controller.transition_to(SoloPhase.AUTONOMOUS_LABELING, force=True)
        mgr.human_labeled_ids = {f"i{i}" for i in range(3)}

        with patch.object(mgr, '_get_total_instance_count', return_value=10):
            mgr._maybe_advance_autonomous_to_validation()

        assert mgr.get_current_phase() == SoloPhase.AUTONOMOUS_LABELING

    def test_no_op_when_not_in_autonomous(self):
        mgr = _make_manager()
        mgr.phase_controller.transition_to(SoloPhase.PARALLEL_ANNOTATION, force=True)
        with patch.object(mgr, '_get_total_instance_count', return_value=0):
            mgr._maybe_advance_autonomous_to_validation()
        assert mgr.get_current_phase() == SoloPhase.PARALLEL_ANNOTATION
