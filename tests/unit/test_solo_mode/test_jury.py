"""Tests for the labeling jury (solo_mode.jury)."""

import json
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from potato.ai import cost
from potato.solo_mode.config import parse_solo_mode_config
from potato.solo_mode.jury import aggregate, decided, run_jury
from potato.solo_mode.manager import SoloModeManager


def _r(label, confidence=0.8, model='m', error=None):
    return SimpleNamespace(label=label, confidence=confidence, model_name=model,
                           error=error)


class TestAggregate:

    def test_plurality_wins_with_vote_share_confidence(self):
        out = aggregate([_r('a'), _r('b'), _r('a')], 'radio')
        assert out['label'] == 'a'
        assert out['confidence'] == pytest.approx(2 / 3)

    def test_tie_goes_to_the_more_confident_label(self):
        out = aggregate([_r('a', 0.6), _r('b', 0.9)], 'radio')
        assert out['label'] == 'b'

    def test_full_tie_goes_to_the_first_vote(self):
        out = aggregate([_r('b', 0.7), _r('a', 0.7)], 'radio')
        assert out['label'] == 'b'

    def test_failed_jurors_do_not_vote(self):
        out = aggregate([_r('a'), _r(None, error='boom'), None, _r('b'), _r('b')],
                        'radio')
        assert (out['label'], out['n_valid']) == ('b', 3)

    def test_no_valid_vote(self):
        assert aggregate([None, _r(None, error='x')], 'radio')['label'] is None

    def test_multiselect_keeps_majority_labels(self):
        out = aggregate([_r('["a", "b"]'), _r(['a']), _r('["a", "c"]')], 'multiselect')
        assert json.loads(out['label']) == ['a']
        assert out['confidence'] == pytest.approx(1.0)


class TestEarlyStop:

    def test_decided(self):
        assert decided(Counter({'a': 2}), remaining=1)
        assert not decided(Counter({'a': 1, 'b': 1}), remaining=1)
        assert not decided(Counter(), remaining=3)

    def test_two_agreeing_of_three_skip_the_third(self):
        calls = []
        out = run_jury(['x', 'y', 'z'],
                       lambda ep: calls.append(ep) or _r('a', model=ep), 'radio')
        assert calls == ['x', 'y']
        assert out['calls'] == {0: 1, 1: 1}
        assert out['label'] == 'a'

    def test_split_jury_asks_everyone(self):
        labels = iter(['a', 'b', 'a'])
        out = run_jury(['x', 'y', 'z'], lambda ep: _r(next(labels)), 'radio')
        assert out['calls'] == {0: 1, 1: 1, 2: 1}

    def test_early_stop_off_asks_everyone(self):
        out = run_jury(['x', 'y', 'z'], lambda ep: _r('a'), 'radio', early_stop=False)
        assert len(out['calls']) == 3

    def test_a_raising_juror_counts_as_no_vote(self):
        def label(ep):
            if ep == 'y':
                raise RuntimeError('down')
            return _r('a')
        out = run_jury(['x', 'y', 'z'], label, 'radio')
        assert out['label'] == 'a' and out['n_valid'] == 2


SCHEMES = [{'name': 'sentiment', 'annotation_type': 'radio',
            'labels': ['positive', 'negative']}]
JURORS = [{'endpoint_type': 'openai', 'model': 'juror-a'},
          {'endpoint_type': 'openai', 'model': 'juror-b'},
          {'endpoint_type': 'openai', 'model': 'juror-c'}]


def _cfg(**jury):
    return parse_solo_mode_config({'solo_mode': {
        'enabled': True, 'labeling_models': [JURORS[0]],
        'jury': {'enabled': True, 'models': JURORS, **jury},
    }, 'annotation_schemes': SCHEMES})


class TestConfig:

    def test_parses(self):
        cfg = _cfg(early_stop=False)
        assert [m.model for m in cfg.jury.models] == ['juror-a', 'juror-b', 'juror-c']
        assert cfg.jury.early_stop is False
        assert cfg.validate(SCHEMES) == []

    def test_needs_two_models(self):
        cfg = _cfg(models=JURORS[:1])
        assert any('at least two' in e for e in cfg.validate(SCHEMES))

    def test_not_with_confidence_routing(self):
        cfg = _cfg()
        cfg.confidence_routing.enabled = True
        assert any('enable one of them' in e for e in cfg.validate(SCHEMES))

    def test_span_is_refused(self):
        spans = [{'name': 'ner', 'annotation_type': 'span', 'labels': ['X']}]
        assert any('jury aggregates' in e for e in _cfg().validate(spans))


class TestManagerJury:

    def test_items_are_labelled_by_vote_and_each_juror_charged(self, tmp_path):
        app = {'annotation_schemes': SCHEMES, 'task_dir': str(tmp_path),
               'annotation_task_name': 'jury', 'ai_budget': {'prices': {'juror': [1, 1]}}}
        mgr = SoloModeManager(_cfg(), app)
        endpoints = [SimpleNamespace(model=m['model']) for m in JURORS]
        mgr._jury_endpoint_cache = list(zip(mgr.config.jury.models, endpoints))
        mgr._get_instances_for_labeling = lambda n: [
            {'instance_id': f'i{k}', 'text': 'good', 'schema_name': 'sentiment'}
            for k in range(2)]
        # juror-a and juror-b agree, so juror-c is never asked.
        votes = {'juror-a': 'positive', 'juror-b': 'positive', 'juror-c': 'negative'}

        def label(iid, text, schema, endpoint=None):
            return SimpleNamespace(label=votes[endpoint.model], confidence=0.9,
                                   model_name=endpoint.model, error=None)
        handled = []
        with patch.object(SoloModeManager, 'llm_labeling_thread',
                          SimpleNamespace(_label_instance=label)), \
                patch.object(mgr, '_handle_labeling_result', side_effect=handled.append):
            assert mgr._label_batch(2) == 2
        assert [h.label for h in handled] == ['positive', 'positive']
        assert handled[0].model_name == 'jury:juror-a,juror-b,juror-c'
        assert 'juror-a: positive' in handled[0].reasoning
        runs = {r['model']: r['n_items'] for r in cost.total_spend(app)['runs']}
        assert runs == {'juror-a': 2, 'juror-b': 2}
