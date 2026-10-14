"""
Tests for the labeling call's response schema and the decision-model branch.

The response schema is what guided decoding (vLLM, OpenAI, Gemini, Ollama)
enforces. It used to name only label/confidence/reasoning, so the edge-case
fields the prompt asked for never came back. Decision models (systemone,
laya) label in one forward pass and carry their own calibrated confidence.
"""

from unittest.mock import MagicMock

import pytest

from potato.ai.decision_endpoint import DecisionAnswer
from potato.server_utils.config_module import (
    ConfigValidationError, validate_solo_mode_config,
)
from potato.solo_mode.config import parse_solo_mode_config
from potato.solo_mode.llm_labeler import LLMLabelingThread


def _labeler(schemes, edge_case=False):
    solo = parse_solo_mode_config({'solo_mode': {
        'enabled': True,
        'labeling_models': [{'endpoint_type': 'openai', 'model': 'm'}],
        'edge_case_rules': {'enabled': edge_case, 'auto_extract_on_labeling': edge_case},
        'uncertainty': {'strategy': 'direct_confidence'},
    }, 'annotation_schemes': schemes})
    t = LLMLabelingThread(
        {'annotation_schemes': schemes}, solo,
        prompt_getter=lambda: 'Classify the sentiment.', result_callback=lambda r: None)
    t._get_uncertainty_estimator = lambda: None
    return t


RADIO = [{'name': 'sentiment', 'annotation_type': 'radio',
          'labels': ['positive', {'name': 'negative'}, 'neutral']}]


class TestResponseSchema:

    def _schema(self, schemes, edge):
        return _labeler(schemes)._response_model(schemes[0], edge).model_json_schema()

    def test_radio_labels_are_an_enum(self):
        schema = self._schema(RADIO, edge=False)
        assert schema['properties']['label']['enum'] == ['positive', 'negative', 'neutral']
        assert set(schema['required']) == {'label', 'confidence', 'reasoning'}

    def test_edge_case_fields_are_required_when_asked_for(self):
        schema = self._schema(RADIO, edge=True)
        assert {'is_edge_case', 'edge_case_rule'} <= set(schema['required'])
        assert schema['properties']['is_edge_case']['type'] == 'boolean'
        # The edge-case prompt allows -1 for "unclassifiable".
        assert '-1' in schema['properties']['label']['enum']

    def test_multiselect_is_a_list_of_labels(self):
        schemes = [{'name': 'topics', 'annotation_type': 'multiselect',
                    'labels': ['a', 'b']}]
        label = self._schema(schemes, edge=False)['properties']['label']
        assert label['type'] == 'array'
        assert label['items']['enum'] == ['a', 'b']

    def test_span_items_name_their_labels(self):
        schemes = [{'name': 'ner', 'annotation_type': 'span',
                    'labels': ['PER', 'ORG']}]
        schema = self._schema(schemes, edge=False)
        item = schema['$defs']['SpanResponse']
        assert item['properties']['label']['enum'] == ['PER', 'ORG']
        assert set(item['required']) == {'text', 'label'}

    def test_likert_scale_points(self):
        schemes = [{'name': 'r', 'annotation_type': 'likert', 'size': 4}]
        label = self._schema(schemes, edge=False)['properties']['label']
        assert label['enum'] == ['1', '2', '3', '4']

    def test_free_text_stays_a_string(self):
        schemes = [{'name': 't', 'annotation_type': 'textbox'}]
        label = self._schema(schemes, edge=False)['properties']['label']
        assert label['type'] == 'string' and 'enum' not in label

    def test_edge_case_reply_reaches_the_result(self):
        t = _labeler(RADIO, edge_case=True)
        endpoint = MagicMock()
        endpoint.is_decision_model = False
        endpoint.model = 'm'
        endpoint.query.return_value = {
            'label': 'neutral', 'confidence': 40, 'reasoning': 'hedged',
            'is_edge_case': True,
            'edge_case_rule': 'When praise is hedged -> neutral'}
        result = t._label_instance('i1', 'it was okay i guess', 'sentiment', endpoint)
        assert result.error is None
        assert result.is_edge_case
        assert result.edge_case_condition == 'praise is hedged'
        # The schema object sent to the endpoint carries the edge-case fields.
        sent = endpoint.query.call_args[0][1].model_json_schema()
        assert 'is_edge_case' in sent['required']


class _FakeDecisionEndpoint:
    is_decision_model = True
    model = 'laya-test'

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def decide(self, state, questions):
        self.calls.append((state, questions))
        return [self.answer]


class TestDecisionBranch:

    def test_radio_is_labelled_in_one_call(self):
        endpoint = _FakeDecisionEndpoint(DecisionAnswer(
            id='sentiment', value='negative', confidence=0.83,
            probabilities={'positive': 0.07, 'negative': 0.83, 'neutral': 0.10}))
        result = _labeler(RADIO)._label_instance('i1', 'awful', 'sentiment', endpoint)
        assert result.error is None
        assert (result.label, result.model_name) == ('negative', 'laya-test')
        assert result.confidence == pytest.approx(0.83)
        assert result.uncertainty == pytest.approx(0.17)
        assert 'negative 0.83' in result.reasoning
        state, questions = endpoint.calls[0]
        assert state == 'awful'
        assert questions[0].kind == 'choice'
        assert questions[0].options == ['positive', 'negative', 'neutral']
        # The study's prompt is the question's instructions.
        assert 'Classify the sentiment.' in questions[0].text

    def test_uncertainty_estimator_is_not_run(self):
        t = _labeler(RADIO)
        estimator = MagicMock()
        t._get_uncertainty_estimator = lambda: estimator
        endpoint = _FakeDecisionEndpoint(DecisionAnswer(
            id='sentiment', value='positive', confidence=0.9,
            probabilities={'positive': 0.9, 'negative': 0.05, 'neutral': 0.05}))
        t._label_instance('i1', 'great', 'sentiment', endpoint)
        estimator.estimate_uncertainty.assert_not_called()

    def test_likert_score_is_labelled(self):
        schemes = [{'name': 'r', 'annotation_type': 'likert', 'size': 5}]
        endpoint = _FakeDecisionEndpoint(DecisionAnswer(
            id='r', value='4', confidence=0.6,
            probabilities={str(k): (0.6 if k == 4 else 0.1) for k in range(1, 6)}))
        result = _labeler(schemes)._label_instance('i1', 'good', 'r', endpoint)
        assert result.label == '4'
        assert endpoint.calls[0][1][0].kind == 'score'

    def test_unsupported_scheme_is_an_error_result(self):
        schemes = [{'name': 'topics', 'annotation_type': 'multiselect',
                    'labels': ['a', 'b']}]
        endpoint = _FakeDecisionEndpoint(None)
        result = _labeler(schemes)._label_instance('i1', 'x', 'topics', endpoint)
        assert result.label is None and 'multiselect' in result.error
        assert endpoint.calls == []


def _config(labeling, revision=None, scheme_type='radio', tiers=None):
    sm = {'enabled': True, 'labeling_models': labeling}
    if revision is not None:
        sm['revision_models'] = revision
    if tiers:
        sm['confidence_routing'] = {'enabled': True, 'tiers': tiers}
    scheme = {'name': 's', 'annotation_type': scheme_type, 'labels': ['a', 'b']}
    if scheme_type == 'likert':
        scheme = {'name': 's', 'annotation_type': 'likert', 'size': 5}
    return {'solo_mode': sm, 'annotation_schemes': [scheme]}


LAYA = {'endpoint_type': 'laya', 'model': 'convaiinnovations/laya'}
GEN = {'endpoint_type': 'vllm', 'model': 'gemma', 'base_url': 'http://x/v1'}


class TestDecisionConfigValidation:

    def test_decision_model_with_generative_reviser_is_valid(self):
        validate_solo_mode_config(_config([LAYA], revision=[GEN]))

    def test_decision_model_as_its_own_reviser_is_refused(self):
        # revision_models defaults to labeling_models.
        with pytest.raises(ConfigValidationError, match='revision_models'):
            validate_solo_mode_config(_config([LAYA]))

    @pytest.mark.parametrize('scheme_type', ['multiselect', 'span', 'textbox'])
    def test_decision_model_on_an_open_scheme_is_refused(self, scheme_type):
        with pytest.raises(ConfigValidationError, match='decision model'):
            validate_solo_mode_config(_config([LAYA], [GEN], scheme_type))

    def test_likert_is_allowed(self):
        validate_solo_mode_config(_config([LAYA], [GEN], 'likert'))

    def test_decision_tier_is_checked_too(self):
        tiers = [{'name': 'fast', 'confidence_threshold': 0.9, 'model': LAYA},
                 {'name': 'strong', 'confidence_threshold': 0.5, 'model': GEN}]
        with pytest.raises(ConfigValidationError, match='decision model'):
            validate_solo_mode_config(_config([GEN], [GEN], 'span', tiers))
        validate_solo_mode_config(_config([GEN], [GEN], 'radio', tiers))

    def test_invalid_solo_block_refuses_to_start(self):
        cfg = _config([GEN], [GEN])
        cfg['solo_mode']['suggestions'] = {'display': 'nope'}
        with pytest.raises(ConfigValidationError, match='suggestions.display'):
            validate_solo_mode_config(cfg)

    def test_disabled_solo_block_is_not_checked(self):
        validate_solo_mode_config({'solo_mode': {'enabled': False,
                                                 'suggestions': {'display': 'nope'}}})

    def test_ai_support_refuses_decision_models(self):
        from potato.server_utils.config_module import validate_ai_support_config
        with pytest.raises(ConfigValidationError, match='cannot write text'):
            validate_ai_support_config({'ai_support': {
                'enabled': True, 'endpoint_type': 'laya', 'ai_config': {}}})


class TestEndpointOptionsPassThrough:
    """device/batch_size/max_options/state_key reach the endpoint's ai_config.

    They used to be dropped by _parse_model_config, so `device: cuda` on a
    laya model silently ran on the endpoint's default.
    """

    def test_known_options_pass_and_unknown_keys_do_not(self):
        cfg = parse_solo_mode_config({'solo_mode': {'enabled': True, 'labeling_models': [
            {'endpoint_type': 'laya', 'model': 'convaiinnovations/laya',
             'device': 'cuda', 'batch_size': 8, 'max_options': 40,
             'state_key': '', 'not_an_option': 1}]}})
        ai = cfg.labeling_models[0].to_endpoint_config()['ai_support']['ai_config']
        assert (ai['device'], ai['batch_size'], ai['max_options'], ai['state_key']) == (
            'cuda', 8, 40, '')
        assert 'not_an_option' not in ai

    def test_options_never_override_core_keys(self):
        from potato.solo_mode.config import ModelConfig
        m = ModelConfig(endpoint_type='laya', model='a', options={'model': 'b'})
        assert m.to_endpoint_config()['ai_support']['ai_config']['model'] == 'a'
