"""
Tests for curriculum ordering in Solo Mode instance selection.

The curriculum shows the human the items the LLM found easiest first, ramps the
target difficulty up over ``ramp_items`` labels, then hands back to the
weighted pools.
"""

from unittest.mock import MagicMock, patch

import pytest

from potato.solo_mode.config import CurriculumConfig, parse_solo_mode_config
from potato.solo_mode.instance_selector import InstanceSelector, SelectionWeights
from potato.solo_mode.manager import LLMPrediction, SoloModeManager


SCHEMES = [{'name': 'sentiment', 'annotation_type': 'radio',
            'labels': ['positive', 'negative', 'neutral']}]


def _preds(confidences, labels=None):
    """instance_id -> {schema: prediction dict} from {iid: confidence}."""
    labels = labels or {}
    return {
        iid: {'sentiment': {'confidence_score': conf,
                            'predicted_label': labels.get(iid, 'positive')}}
        for iid, conf in confidences.items()
    }


def _selector(seed=0, **curriculum):
    selector = InstanceSelector(SelectionWeights(
        low_confidence=0.0, diverse=0.0, random=1.0, disagreement=0.0))
    selector.random.seed(seed)
    selector.configure_curriculum(CurriculumConfig(enabled=True, **curriculum))
    return selector


def _refresh(selector, available, predictions, labeled=0, **kwargs):
    with patch.object(selector, '_build_diverse_pool', return_value=[]):
        selector.refresh_pools(
            available_ids=set(available),
            llm_predictions=predictions,
            human_labeled_count=labeled,
            **kwargs,
        )


def _run(selector, confidences, labels=None, steps=None, labeled_start=0,
         **kwargs):
    """Label items one at a time, as the manager does, and return the order."""
    remaining = set(confidences)
    order = []
    for step in range(steps or len(confidences)):
        _refresh(selector, remaining, _preds(confidences, labels),
                 labeled=labeled_start + step, **kwargs)
        chosen = selector.select_next(remaining)
        order.append(chosen)
        remaining.discard(chosen)
    return order


class TestWarmup:

    def test_warmup_shows_easiest_items_first(self):
        confidences = {'hard': 0.3, 'mid': 0.6, 'easy': 0.99, 'easier': 0.999}
        selector = _selector(warmup_items=4, ramp_items=0, window=1)
        assert _run(selector, confidences) == ['easier', 'easy', 'mid', 'hard']

    def test_warmup_picks_are_recorded_under_the_curriculum_pool(self):
        selector = _selector(warmup_items=2, ramp_items=0, window=1)
        _run(selector, {'a': 0.9, 'b': 0.5}, steps=1)
        assert selector.get_selection_stats()['by_pool'] == {'curriculum': 1}

    def test_warmup_rotates_predicted_labels(self):
        # Ten very easy positives and one slightly less easy negative. Without
        # rotation the first two picks would both be positive.
        confidences = {f'p{i}': 0.99 for i in range(10)}
        confidences['n0'] = 0.95
        labels = {'n0': 'negative'}
        selector = _selector(warmup_items=10, ramp_items=0, window=11)
        order = _run(selector, confidences, labels, steps=2)
        assert 'n0' in order

    def test_window_of_one_does_not_rotate(self):
        confidences = {f'p{i}': 0.99 for i in range(10)}
        confidences['n0'] = 0.5
        selector = _selector(warmup_items=10, ramp_items=0, window=1)
        order = _run(selector, confidences, {'n0': 'negative'}, steps=5)
        assert 'n0' not in order


class TestRamp:

    def test_target_rises_across_the_ramp(self):
        selector = _selector(warmup_items=2, ramp_items=4)
        targets = []
        for labeled in range(8):
            selector._human_labeled_count = labeled
            targets.append(selector.curriculum_target())
        assert targets == [0.0, 0.0, 0.0, 0.25, 0.5, 0.75, None, None]

    def test_mid_ramp_pick_is_mid_difficulty(self):
        confidences = {f'i{k}': 1.0 - k / 10 for k in range(11)}  # i10 hardest
        selector = _selector(warmup_items=0, ramp_items=2, window=1)
        _refresh(selector, confidences, _preds(confidences), labeled=1)
        assert selector.curriculum_target() == 0.5
        assert selector.select_next(set(confidences)) == 'i5'

    def test_after_the_ramp_the_weighted_pools_decide(self):
        confidences = {'a': 0.9, 'b': 0.5, 'c': 0.2}
        selector = _selector(warmup_items=1, ramp_items=1)
        _refresh(selector, confidences, _preds(confidences), labeled=2)
        selector.select_next(set(confidences))
        assert 'curriculum' not in selector.get_selection_stats()['by_pool']
        assert selector.get_curriculum_status()['stage'] == 'done'


class TestFallbacks:

    def test_disabled_curriculum_never_selects(self):
        selector = InstanceSelector()
        selector.configure_curriculum(CurriculumConfig(enabled=False))
        assert selector.curriculum is None
        _refresh(selector, {'a'}, _preds({'a': 0.9}))
        selector.select_next({'a'})
        assert 'curriculum' not in selector.get_selection_stats()['by_pool']
        assert selector.get_curriculum_status() == {'enabled': False}

    def test_cold_start_without_predictions_falls_back(self):
        selector = _selector(warmup_items=5)
        _refresh(selector, {'a', 'b'}, {})
        assert selector.select_next({'a', 'b'}) in {'a', 'b'}
        assert 'curriculum' not in selector.get_selection_stats()['by_pool']

    def test_unpredicted_items_wait_while_predicted_ones_remain(self):
        selector = _selector(warmup_items=5)
        _refresh(selector, {'a', 'b', 'c'}, _preds({'a': 0.4}))
        assert selector.select_next({'a', 'b', 'c'}) == 'a'

    def test_disagreement_revisit_keeps_its_turn(self):
        selector = InstanceSelector(SelectionWeights(
            low_confidence=0.0, diverse=0.0, random=0.0, disagreement=1.0))
        selector.configure_curriculum(CurriculumConfig(enabled=True))
        _refresh(selector, {'fresh'}, _preds({'fresh': 0.99, 'old': 0.4}),
                 revisit_ids={'old'})
        assert selector.select_next({'fresh', 'old'}) == 'old'

    def test_excluded_items_are_never_picked(self):
        selector = _selector(warmup_items=5, window=1)
        confidences = {'easy': 0.99, 'hard': 0.2}
        _refresh(selector, confidences, _preds(confidences))
        assert selector.select_next(set(confidences), exclude_ids={'easy'}) == 'hard'


class TestDifficultySignals:

    def test_confidence_uses_the_least_confident_schema(self):
        selector = _selector(warmup_items=5)
        selector._predictions_cache = {'a': {
            's1': {'confidence_score': 0.9}, 's2': {'confidence_score': 0.3}}}
        assert selector._difficulty('a') == pytest.approx(0.7)

    def test_cartography_orders_by_variability(self):
        selector = _selector(warmup_items=5, difficulty_signal='cartography',
                             window=1)
        confidences = {'stable': 0.5, 'wobbly': 0.99}
        _refresh(selector, confidences, _preds(confidences),
                 cartography_scores={'stable': 0.01, 'wobbly': 0.4})
        # Confidence alone would pick 'wobbly'; variability says it is harder.
        assert selector.select_next(set(confidences)) == 'stable'

    def test_combined_averages_both_signals(self):
        selector = _selector(warmup_items=5, difficulty_signal='combined')
        _refresh(selector, {'a', 'b'}, _preds({'a': 0.8, 'b': 0.8}),
                 cartography_scores={'a': 0.2, 'b': 0.1})
        assert selector._difficulty('a') == pytest.approx((0.2 + 1.0) / 2)
        assert selector._difficulty('b') == pytest.approx((0.2 + 0.5) / 2)


class TestConfig:

    def _parse(self, curriculum):
        return parse_solo_mode_config({'solo_mode': {
            'enabled': True,
            'labeling_models': [{'endpoint_type': 'openai', 'model': 'm'}],
            'instance_selection': {'curriculum': curriculum},
        }, 'annotation_schemes': SCHEMES})

    def test_defaults(self):
        c = self._parse({}).instance_selection.curriculum
        assert (c.enabled, c.warmup_items, c.ramp_items,
                c.difficulty_signal, c.window) == (False, 20, 30, 'confidence', 5)

    def test_parses_yaml_values(self):
        cfg = self._parse({'enabled': True, 'warmup_items': 8, 'ramp_items': 0,
                           'difficulty_signal': 'combined', 'window': 3})
        c = cfg.instance_selection.curriculum
        assert (c.enabled, c.warmup_items, c.ramp_items,
                c.difficulty_signal, c.window) == (True, 8, 0, 'combined', 3)
        assert cfg.validate() == []

    @pytest.mark.parametrize('curriculum, fragment', [
        ({'difficulty_signal': 'vibes'}, 'difficulty_signal'),
        ({'warmup_items': 'twenty'}, 'warmup_items must be an integer'),
        ({'ramp_items': -1}, 'must be 0 or more'),
        ({'window': 0}, 'window must be at least 1'),
        ({'enabled': 'yes'}, 'enabled must be true or false'),
        ({'window': True}, 'window must be an integer'),
    ])
    def test_invalid_values_are_reported(self, curriculum, fragment):
        errors = self._parse(curriculum).validate()
        assert any(fragment in e for e in errors), errors

    def test_type_and_signal_errors_are_both_reported(self):
        errors = self._parse({'warmup_items': 'x', 'difficulty_signal': 'v'}).validate()
        assert len([e for e in errors if 'curriculum' in e]) == 2


class TestManagerWiring:

    def _manager(self, **curriculum):
        cfg = parse_solo_mode_config({'solo_mode': {
            'enabled': True, 'labeling_models': [],
            'instance_selection': {
                'low_confidence_weight': 0.0, 'diversity_weight': 0.0,
                'random_weight': 1.0, 'disagreement_weight': 0.0,
                'curriculum': {'enabled': True, **curriculum}},
        }, 'annotation_schemes': SCHEMES})
        return SoloModeManager(cfg, {'annotation_schemes': SCHEMES})

    def _predict(self, mgr, iid, conf):
        mgr.set_llm_prediction(iid, 'sentiment', LLMPrediction(
            instance_id=iid, schema_name='sentiment', predicted_label='positive',
            confidence_score=conf, uncertainty_score=1 - conf,
            prompt_version=1, model_name='m'))

    def test_human_sees_the_easiest_items_first(self):
        mgr = self._manager(warmup_items=3, ramp_items=0, window=1)
        for iid, conf in {'i1': 0.4, 'i2': 0.95, 'i3': 0.7}.items():
            self._predict(mgr, iid, conf)
        ism = MagicMock()
        ism.instance_id_ordering = ['i1', 'i2', 'i3']
        order = []
        with patch('potato.item_state_management.get_item_state_manager',
                   return_value=ism):
            for _ in range(3):
                chosen = mgr.get_next_instance_for_human('u')
                order.append(chosen)
                mgr.human_labeled_ids.add(chosen)
        assert order == ['i2', 'i3', 'i1']

    def test_status_reports_the_stage(self):
        mgr = self._manager(warmup_items=2, ramp_items=2)
        assert mgr.get_status()['curriculum']['stage'] == 'warmup'
        mgr.human_labeled_ids.update({'a', 'b', 'c'})
        status = mgr.get_status()['curriculum']
        assert (status['stage'], status['target_difficulty']) == ('ramp', 0.5)
        mgr.human_labeled_ids.add('d')
        assert mgr.get_status()['curriculum']['stage'] == 'done'

    def test_status_when_off(self):
        mgr = self._manager()
        mgr.config.instance_selection.curriculum.enabled = False
        mgr._instance_selector = None
        assert mgr.get_status()['curriculum'] == {'enabled': False}


class TestRoutingDifficulty:
    """An item escalated past the first routing tier is not ranked easy."""

    def test_escalated_item_ranks_by_its_lowest_tier_confidence(self):
        selector = _selector(warmup_items=5, window=1)
        preds = {
            'escalated': {'s': {'confidence_score': 1.0, 'routing_min_confidence': 0.6}},
            'accepted': {'s': {'confidence_score': 0.95}},
        }
        _refresh(selector, set(preds), preds)
        assert selector.select_next(set(preds)) == 'accepted'

    def test_manager_passes_the_lowest_tier_confidence(self):
        from types import SimpleNamespace
        mgr = TestManagerWiring()._manager(warmup_items=3, ramp_items=0, window=1)
        TestManagerWiring()._predict(mgr, 'i1', 1.0)   # accepted by tier 1 after escalation
        TestManagerWiring()._predict(mgr, 'i2', 0.95)  # accepted at tier 0
        mgr._routing_min_confidence['i1'] = 0.55
        ism = SimpleNamespace(instance_id_ordering=['i1', 'i2'])
        with patch('potato.item_state_management.get_item_state_manager',
                   return_value=ism):
            assert mgr.get_next_instance_for_human('u') == 'i2'
