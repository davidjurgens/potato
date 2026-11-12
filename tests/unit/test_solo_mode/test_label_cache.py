"""Tests for the Solo Mode labeling response cache (solo_mode.cache)."""

from unittest.mock import MagicMock

from pydantic import BaseModel

from potato.solo_mode.config import parse_solo_mode_config
from potato.solo_mode.label_cache import CachingEndpoint, LabelCache, cache_key
from potato.solo_mode.llm_labeler import LLMLabelingThread


class Reply(BaseModel):
    label: str


def _endpoint(model='m', temperature=0.1, base_url='http://a', replies=None):
    ep = MagicMock()
    ep.model = model
    ep.temperature = temperature
    ep.ai_config = {'model': model, 'base_url': base_url}
    ep.query.side_effect = replies or (lambda p, f=None: {'label': 'positive'})
    return ep


class TestKey:

    def test_same_call_same_key(self):
        assert cache_key(_endpoint(), 'p', Reply) == cache_key(_endpoint(), 'p', Reply)

    def test_everything_that_changes_the_reply_changes_the_key(self):
        base = cache_key(_endpoint(), 'p', Reply)

        class Other(BaseModel):
            label: int

        assert cache_key(_endpoint(model='n'), 'p', Reply) != base
        assert cache_key(_endpoint(temperature=0.7), 'p', Reply) != base
        assert cache_key(_endpoint(base_url='http://b'), 'p', Reply) != base
        assert cache_key(_endpoint(), 'q', Reply) != base
        assert cache_key(_endpoint(), 'p', Other) != base


class TestCachingEndpoint:

    def test_second_identical_call_is_not_sent(self):
        ep = _endpoint()
        cached = CachingEndpoint(ep, LabelCache())
        assert cached.query('p', Reply) == {'label': 'positive'}
        assert cached.query('p', Reply) == {'label': 'positive'}
        assert ep.query.call_count == 1

    def test_unparsed_reply_is_not_kept(self):
        ep = _endpoint(replies=['\n\n\n\n', '{"label": "negative"}'])
        cache = LabelCache()
        cached = CachingEndpoint(ep, cache)
        cached.query('p', Reply)
        assert cached.query('p', Reply) == '{"label": "negative"}'
        assert ep.query.call_count == 2
        # Now it parsed, so the third call comes from the cache.
        assert cached.query('p', Reply) == {'label': 'negative'}
        assert ep.query.call_count == 2

    def test_error_message_is_not_kept(self):
        ep = _endpoint(replies=['Unable to generate suggestion - timeout',
                                {'label': 'positive'}])
        cached = CachingEndpoint(ep, LabelCache())
        cached.query('p', Reply)
        cached.query('p', Reply)
        assert ep.query.call_count == 2

    def test_pydantic_reply_is_stored_as_a_dict(self):
        ep = _endpoint(replies=[Reply(label='neutral')])
        cached = CachingEndpoint(ep, LabelCache())
        cached.query('p', Reply)
        assert cached.query('p', Reply) == {'label': 'neutral'}

    def test_other_attributes_pass_through(self):
        ep = _endpoint()
        assert CachingEndpoint(ep, LabelCache()).model == 'm'

    def test_cache_survives_a_restart(self, tmp_path):
        ep = _endpoint()
        CachingEndpoint(ep, LabelCache(str(tmp_path))).query('p', Reply)
        fresh = LabelCache(str(tmp_path))
        assert CachingEndpoint(ep, fresh).query('p', Reply) == {'label': 'positive'}
        assert ep.query.call_count == 1
        assert fresh.stats()['hits'] == 1 and fresh.stats()['persistent']


SCHEMES = [{'name': 'sentiment', 'annotation_type': 'radio',
            'labels': ['positive', 'negative']}]


def _labeler(strategy='direct_confidence', cache=True):
    solo = parse_solo_mode_config({'solo_mode': {
        'enabled': True, 'labeling_models': [{'endpoint_type': 'openai', 'model': 'm'}],
        'uncertainty': {'strategy': strategy}, 'cache': {'enabled': cache},
    }, 'annotation_schemes': SCHEMES})
    t = LLMLabelingThread({'annotation_schemes': SCHEMES}, solo,
                          prompt_getter=lambda: 'Classify.',
                          result_callback=lambda r: None)
    t.label_cache = LabelCache() if cache else None
    return t


class TestLabelerUsesTheCache:

    def test_relabeling_the_same_item_makes_no_new_call(self):
        t = _labeler()
        t._get_uncertainty_estimator = lambda: None
        ep = _endpoint(replies=lambda p, f=None: {'label': 'positive', 'confidence': 90})
        ep.is_decision_model = False
        a = t._label_instance('i1', 'great', 'sentiment', ep)
        b = t._label_instance('i1', 'great', 'sentiment', ep)
        assert a.label == b.label == 'positive'
        assert ep.query.call_count == 1

    def test_direct_confidence_estimate_is_cached_too(self):
        t = _labeler('direct_confidence')
        estimator = MagicMock()
        estimator.estimate_uncertainty.return_value = MagicMock(
            uncertainty_score=0.1, confidence_score=0.9, method='direct_confidence')
        t._get_uncertainty_estimator = lambda: estimator
        ep = _endpoint()
        ep.is_decision_model = False
        t._label_instance('i1', 'great', 'sentiment', ep)
        assert isinstance(
            estimator.estimate_uncertainty.call_args.kwargs['endpoint'], CachingEndpoint)

    def test_sampling_diversity_gets_the_raw_endpoint(self):
        t = _labeler('sampling_diversity')
        estimator = MagicMock()
        estimator.estimate_uncertainty.return_value = MagicMock(
            uncertainty_score=0.1, confidence_score=0.9, method='sampling')
        t._get_uncertainty_estimator = lambda: estimator
        ep = _endpoint()
        ep.is_decision_model = False
        t._label_instance('i1', 'great', 'sentiment', ep)
        assert estimator.estimate_uncertainty.call_args.kwargs['endpoint'] is ep

    def test_cache_off_sends_every_call(self):
        t = _labeler(cache=False)
        t._get_uncertainty_estimator = lambda: None
        ep = _endpoint()
        ep.is_decision_model = False
        t._label_instance('i1', 'great', 'sentiment', ep)
        t._label_instance('i1', 'great', 'sentiment', ep)
        assert ep.query.call_count == 2
