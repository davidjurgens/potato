"""
Tests for Solo Mode's AI spend estimate, cap and running total.

The cap (ai_budget.cap_usd) refuses background labeling before it starts and
before each batch; each batch's calls are recorded, per tier under confidence
routing.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from potato.ai import cost
from potato.solo_mode import spend
from potato.solo_mode.config import parse_solo_mode_config
from potato.solo_mode.manager import SoloModeManager


SCHEMES = [{'name': 'sentiment', 'annotation_type': 'radio',
            'labels': ['positive', 'negative']}]
#: USD per million tokens. Priced through ai_budget.prices so the test does
#: not depend on PRICE_TABLE rows, which go stale by design.
PRICES = {'pricey-model': [1000.0, 1000.0], 'cheap-model': [1.0, 1.0]}


def _manager(tmp_path, cap=None, routing=False, **solo):
    sm = {
        'enabled': True,
        'labeling_models': [{'endpoint_type': 'openai', 'model': 'pricey-model',
                             'max_tokens': 50}],
        **solo,
    }
    if routing:
        sm['confidence_routing'] = {'enabled': True, 'tiers': [
            {'name': 'fast', 'confidence_threshold': 0.9,
             'model': {'endpoint_type': 'openai', 'model': 'cheap-model',
                       'max_tokens': 50}},
            {'name': 'strong', 'confidence_threshold': 0.5,
             'model': {'endpoint_type': 'openai', 'model': 'pricey-model',
                       'max_tokens': 50}},
        ]}
    app = {'annotation_schemes': SCHEMES, 'task_dir': str(tmp_path),
           'annotation_task_name': f'spend-{tmp_path.name}',
           'ai_budget': {'prices': PRICES, **({'cap_usd': cap} if cap is not None else {})}}
    cfg = parse_solo_mode_config({'solo_mode': sm, 'annotation_schemes': SCHEMES})
    mgr = SoloModeManager(cfg, app)
    mgr._get_instances_for_labeling = lambda n: [
        {'instance_id': f'i{k}', 'text': 'x' * 400, 'schema_name': 'sentiment'}
        for k in range(min(n, 10))]
    mgr._get_total_instance_count = lambda: 10
    return mgr, app


class TestCallsPerItem:

    def test_default_estimator_asks_twice(self):
        cfg = parse_solo_mode_config({'solo_mode': {'enabled': True}})
        assert spend.calls_per_item(cfg) == 2

    def test_sampling_diversity_counts_its_samples(self):
        cfg = parse_solo_mode_config({'solo_mode': {'enabled': True, 'uncertainty': {
            'strategy': 'sampling_diversity', 'sampling_diversity': {'num_samples': 4}}}})
        assert spend.calls_per_item(cfg) == 5


class TestCapAtStart:

    def test_no_cap_never_reads_the_texts(self, tmp_path):
        mgr, _ = _manager(tmp_path)
        mgr._get_instances_for_labeling = MagicMock(side_effect=AssertionError)
        with patch('threading.Thread'):
            assert mgr.start_background_labeling()

    def test_cap_refuses_before_starting(self, tmp_path):
        mgr, _ = _manager(tmp_path, cap=0.01)
        with patch('threading.Thread') as thread:
            assert mgr.start_background_labeling() is False
        thread.assert_not_called()
        assert 'cap of $0.01' in mgr.get_spend_refusal()
        assert 'Nothing has been run' in mgr.get_spend_refusal()

    def test_generous_cap_starts_and_clears_an_old_refusal(self, tmp_path):
        mgr, _ = _manager(tmp_path, cap=10_000)
        mgr._spend_refusal = 'old'
        with patch('threading.Thread'):
            assert mgr.start_background_labeling()
        assert mgr.get_spend_refusal() is None

    def test_unpriced_model_does_not_block(self, tmp_path):
        mgr, _ = _manager(tmp_path, cap=0.0001, labeling_models=[
            {'endpoint_type': 'openai', 'model': 'never-heard-of-it'}])
        with patch('threading.Thread'):
            assert mgr.start_background_labeling()

    def test_self_hosted_model_is_free(self, tmp_path):
        mgr, _ = _manager(tmp_path, cap=0.0001, labeling_models=[
            {'endpoint_type': 'vllm', 'model': 'pricey-model'}])
        est = mgr.estimate_remaining_labeling_cost()
        assert est.local and est.cost_usd == 0.0
        with patch('threading.Thread'):
            assert mgr.start_background_labeling()


def _labeling_result(iid):
    return SimpleNamespace(instance_id=iid, schema_name='sentiment',
                           label='positive', confidence=0.9, uncertainty=0.1,
                           reasoning='', prompt_version=0, model_name='m',
                           error=None)


class TestBatchRecording:

    def test_batch_spend_is_recorded(self, tmp_path):
        mgr, app = _manager(tmp_path)
        labeler = MagicMock()
        labeler._label_instance.side_effect = lambda iid, text, schema: _labeling_result(iid)
        with patch.object(SoloModeManager, 'llm_labeling_thread', labeler), \
                patch.object(mgr, '_handle_labeling_result'):
            assert mgr._label_batch(3) == 3
        total = cost.total_spend(app)
        assert total['n_runs'] == 1
        assert total['runs'][0]['n_items'] == 3
        assert total['runs'][0]['model'] == 'pricey-model'
        assert total['cost_usd'] > 0

    def test_a_batch_that_dies_partway_is_charged_for_what_ran(self, tmp_path):
        mgr, app = _manager(tmp_path)
        calls = []

        def label(iid, text, schema):
            calls.append(iid)
            if len(calls) == 2:
                raise RuntimeError('boom')
            return _labeling_result(iid)

        labeler = MagicMock()
        labeler._label_instance.side_effect = label
        with patch.object(SoloModeManager, 'llm_labeling_thread', labeler), \
                patch.object(mgr, '_handle_labeling_result'), \
                pytest.raises(RuntimeError):
            mgr._label_batch(5)
        assert cost.total_spend(app)['runs'][0]['n_items'] == 2

    def test_routing_charges_each_tier_for_its_own_attempts(self, tmp_path):
        mgr, app = _manager(tmp_path, routing=True)
        router = MagicMock()

        def route(iid, text, schema):
            # i0 accepted at tier 0; the rest escalate to tier 1.
            attempts = [{'tier_index': 0}]
            if iid != 'i0':
                attempts.append({'tier_index': 1})
            return SimpleNamespace(accepted=True, attempts=attempts,
                                   labeling_result=_labeling_result(iid))
        router.route_instance.side_effect = route
        mgr._confidence_router = router
        with patch.object(mgr, '_handle_labeling_result'):
            mgr._label_batch(3)
        runs = {r['model']: r['n_items'] for r in cost.total_spend(app)['runs']}
        assert runs == {'cheap-model': 3, 'pricey-model': 2}

    def test_unbuilt_tier_is_not_charged(self, tmp_path):
        mgr, app = _manager(tmp_path, routing=True)
        router = MagicMock()
        router.route_instance.side_effect = lambda iid, text, schema: SimpleNamespace(
            accepted=True, labeling_result=_labeling_result(iid), attempts=[
                {'tier_index': 0, 'error': 'Failed to create endpoint'},
                {'tier_index': 1}])
        mgr._confidence_router = router
        with patch.object(mgr, '_handle_labeling_result'):
            mgr._label_batch(2)
        runs = {r['model']: r['n_items'] for r in cost.total_spend(app)['runs']}
        assert runs == {'pricey-model': 2}

    def test_cap_refuses_a_batch_and_pauses(self, tmp_path):
        mgr, app = _manager(tmp_path, cap=0.01)
        labeler = MagicMock()
        with patch.object(SoloModeManager, 'llm_labeling_thread', labeler), \
                patch.object(mgr, 'pause_background_labeling') as pause:
            assert mgr._label_batch(3) == 0
        labeler._label_instance.assert_not_called()
        pause.assert_called_once()
        assert mgr.get_spend_refusal()
        assert cost.total_spend(app)['n_runs'] == 0


class TestSummary:

    def test_summary_reports_cap_estimate_and_refusal(self, tmp_path):
        mgr, _ = _manager(tmp_path, cap=5)
        mgr._spend_refusal = 'refused'
        s = mgr.get_spend_summary()
        assert s['cap_usd'] == 5.0
        assert s['refusal'] == 'refused'
        assert s['remaining_estimate']['n_items'] == 10
        assert 'item(s)' in s['remaining_summary']

    def test_estimate_is_reused_until_labels_change(self, tmp_path):
        mgr, _ = _manager(tmp_path)
        with patch.object(mgr, 'estimate_remaining_labeling_cost',
                          wraps=mgr.estimate_remaining_labeling_cost) as est:
            mgr.get_spend_summary()
            mgr.get_spend_summary()
            assert est.call_count == 1
            mgr.llm_labeled_ids.add('i0')
            mgr.get_spend_summary()
            assert est.call_count == 2


class TestDecisionModelEstimate:

    def test_one_call_and_no_output_tokens(self, tmp_path):
        mgr, _ = _manager(tmp_path, labeling_models=[
            {'endpoint_type': 'laya', 'model': 'convaiinnovations/laya', 'max_tokens': 1000}],
            revision_models=[{'endpoint_type': 'vllm', 'model': 'g'}])
        est = mgr.estimate_remaining_labeling_cost()
        assert est.output_tokens == 0
        assert est.local and est.cost_usd == 0.0
        # Ten 400-char items plus prompt scaffolding, read once each.
        gen, _ = _manager(tmp_path)
        assert est.input_tokens * 2 == gen.estimate_remaining_labeling_cost().input_tokens
