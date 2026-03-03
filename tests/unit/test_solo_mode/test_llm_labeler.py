"""
Tests for LLM Labeler.

Tests LabelingResult, LLMLabelingThread (edge case rule parsing,
JSON parsing, queue management, label matching, stats).
"""

import pytest
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

from potato.solo_mode.llm_labeler import (
    LabelingResult,
    LLMLabelingThread,
)


class TestLabelingResult:
    """Tests for LabelingResult dataclass."""

    def test_creation(self):
        r = LabelingResult(
            instance_id="i1",
            schema_name="sentiment",
            label="positive",
            confidence=0.9,
            uncertainty=0.1,
            reasoning="Clear positive tone",
            prompt_version=1,
            model_name="test-model",
        )
        assert r.instance_id == "i1"
        assert r.label == "positive"
        assert r.is_edge_case is False
        assert r.edge_case_rule is None
        assert r.error is None

    def test_to_dict_basic(self):
        r = LabelingResult(
            instance_id="i1",
            schema_name="s",
            label="x",
            confidence=0.8,
            uncertainty=0.2,
            reasoning="r",
            prompt_version=1,
            model_name="m",
        )
        data = r.to_dict()
        assert data['instance_id'] == "i1"
        assert data['label'] == "x"
        assert data['confidence'] == 0.8
        assert 'is_edge_case' not in data  # Not included when False

    def test_to_dict_with_edge_case(self):
        r = LabelingResult(
            instance_id="i1",
            schema_name="s",
            label="x",
            confidence=0.4,
            uncertainty=0.6,
            reasoning="r",
            prompt_version=1,
            model_name="m",
            is_edge_case=True,
            edge_case_rule="When sarcasm -> negative",
            edge_case_condition="sarcasm",
            edge_case_action="negative",
        )
        data = r.to_dict()
        assert data['is_edge_case'] is True
        assert data['edge_case_rule'] == "When sarcasm -> negative"
        assert data['edge_case_condition'] == "sarcasm"

    def test_to_dict_with_error(self):
        r = LabelingResult(
            instance_id="i1",
            schema_name="s",
            label=None,
            confidence=0,
            uncertainty=1,
            reasoning="",
            prompt_version=0,
            model_name="",
            error="Connection failed",
        )
        data = r.to_dict()
        assert data['error'] == "Connection failed"
        assert data['label'] is None


class TestLLMLabelingThreadInit:
    """Tests for LLMLabelingThread initialization."""

    def _make_thread(self, **kwargs):
        defaults = {
            'config': {'annotation_schemes': []},
            'solo_config': MagicMock(),
            'prompt_getter': lambda: "Classify",
            'result_callback': lambda r: None,
        }
        defaults.update(kwargs)
        return LLMLabelingThread(**defaults)

    def test_creation(self):
        thread = self._make_thread()
        assert thread.daemon is True
        assert thread.name == "LLMLabelingThread"
        assert thread._labeled_count == 0
        assert thread._error_count == 0

    def test_queue_operations(self):
        thread = self._make_thread()
        assert thread.get_queue_size() == 0

        thread.enqueue("i1", "text one", "schema")
        assert thread.get_queue_size() == 1

        thread.enqueue("i2", "text two", "schema")
        assert thread.get_queue_size() == 2

    def test_enqueue_batch(self):
        thread = self._make_thread()
        instances = [
            {'instance_id': f'i{i}', 'text': f'text {i}'}
            for i in range(5)
        ]
        count = thread.enqueue_batch(instances, "schema")
        assert count == 5
        assert thread.get_queue_size() == 5

    def test_pause_resume(self):
        thread = self._make_thread()
        assert thread.is_paused() is False
        thread.pause()
        assert thread.is_paused() is True
        thread.resume()
        assert thread.is_paused() is False


class TestLLMLabelingThreadEdgeCaseParsing:
    """Tests for edge case rule parsing."""

    @pytest.fixture
    def thread(self):
        return LLMLabelingThread.__new__(LLMLabelingThread)

    def test_when_arrow_format(self, thread):
        cond, act = thread._parse_edge_case_rule(
            "When the text uses double negatives -> label as positive"
        )
        assert cond == "the text uses double negatives"
        assert act == "label as positive"

    def test_when_arrow_lowercase(self, thread):
        cond, act = thread._parse_edge_case_rule(
            "when mixed signals -> choose dominant"
        )
        assert cond == "mixed signals"
        assert act == "choose dominant"

    def test_if_then_format(self, thread):
        cond, act = thread._parse_edge_case_rule(
            "If the sentiment is mixed, then choose the dominant emotion"
        )
        assert cond == "the sentiment is mixed"
        assert act == "choose the dominant emotion"

    def test_if_then_no_comma(self, thread):
        cond, act = thread._parse_edge_case_rule(
            "If ambiguous then label neutral"
        )
        assert cond == "ambiguous"
        assert act == "label neutral"

    def test_fallback(self, thread):
        cond, act = thread._parse_edge_case_rule("Some unstructured rule text")
        assert cond == "Some unstructured rule text"
        assert act == ""

    def test_empty_string(self, thread):
        cond, act = thread._parse_edge_case_rule("")
        assert cond == ""
        assert act == ""

    def test_complex_condition(self, thread):
        cond, act = thread._parse_edge_case_rule(
            "When the text contains both positive and negative words -> check context"
        )
        assert "both positive and negative words" in cond
        assert act == "check context"


class TestLLMLabelingThreadJsonParsing:
    """Tests for JSON response parsing."""

    @pytest.fixture
    def thread(self):
        return LLMLabelingThread.__new__(LLMLabelingThread)

    def test_plain_json(self, thread):
        result = thread._parse_json_response('{"label": "positive", "confidence": 85}')
        assert result['label'] == "positive"
        assert result['confidence'] == 85

    def test_markdown_json(self, thread):
        result = thread._parse_json_response('```json\n{"label": "neg"}\n```')
        assert result['label'] == "neg"

    def test_markdown_no_lang(self, thread):
        result = thread._parse_json_response('```\n{"label": "x"}\n```')
        assert result['label'] == "x"

    def test_invalid_json(self, thread):
        result = thread._parse_json_response("positive")
        assert result == {"label": "positive"}

    def test_json_with_edge_case(self, thread):
        response = json.dumps({
            "label": "positive",
            "confidence": 40,
            "reasoning": "Ambiguous",
            "is_edge_case": True,
            "edge_case_rule": "When sarcasm -> negative"
        })
        result = thread._parse_json_response(response)
        assert result['is_edge_case'] is True
        assert result['edge_case_rule'] == "When sarcasm -> negative"


class TestLLMLabelingThreadLabelMatching:
    """Tests for label validation and fuzzy matching."""

    @pytest.fixture
    def thread(self):
        return LLMLabelingThread.__new__(LLMLabelingThread)

    def test_extract_labels_strings(self, thread):
        schema = {'labels': ['positive', 'negative', 'neutral']}
        result = thread._extract_labels(schema)
        assert result == "positive, negative, neutral"

    def test_extract_labels_dicts(self, thread):
        schema = {'labels': [
            {'name': 'pos', 'tooltip': 'positive'},
            {'name': 'neg'},
        ]}
        result = thread._extract_labels(schema)
        assert "pos" in result
        assert "neg" in result

    def test_extract_labels_empty(self, thread):
        assert thread._extract_labels({}) == ""
        assert thread._extract_labels({'labels': []}) == ""

    def test_get_valid_labels(self, thread):
        schema = {'labels': ['a', 'b', {'name': 'c'}]}
        result = thread._get_valid_labels(schema)
        assert result == ['a', 'b', 'c']

    def test_fuzzy_match_exact(self, thread):
        result = thread._fuzzy_match_label("positive", ["positive", "negative"])
        assert result == "positive"

    def test_fuzzy_match_case_insensitive(self, thread):
        result = thread._fuzzy_match_label("POSITIVE", ["positive", "negative"])
        assert result == "positive"

    def test_fuzzy_match_whitespace(self, thread):
        result = thread._fuzzy_match_label("  positive  ", ["positive", "negative"])
        assert result == "positive"

    def test_fuzzy_match_no_match(self, thread):
        result = thread._fuzzy_match_label("unknown", ["positive", "negative"])
        assert result is None


class TestLLMLabelingThreadStats:
    """Tests for labeling statistics."""

    def test_initial_stats(self):
        thread = LLMLabelingThread(
            config={},
            solo_config=MagicMock(),
            prompt_getter=lambda: "",
            result_callback=lambda r: None,
        )
        stats = thread.get_stats()
        assert stats['labeled_count'] == 0
        assert stats['error_count'] == 0
        assert stats['queue_size'] == 0
        assert stats['is_paused'] is False
        assert stats['last_error'] is None

    def test_stats_after_enqueue(self):
        thread = LLMLabelingThread(
            config={},
            solo_config=MagicMock(),
            prompt_getter=lambda: "",
            result_callback=lambda r: None,
        )
        thread.enqueue("i1", "text", "schema")
        stats = thread.get_stats()
        assert stats['queue_size'] == 1

    def test_stats_paused(self):
        thread = LLMLabelingThread(
            config={},
            solo_config=MagicMock(),
            prompt_getter=lambda: "",
            result_callback=lambda r: None,
        )
        thread.pause()
        stats = thread.get_stats()
        assert stats['is_paused'] is True


class TestLLMLabelingThreadStop:
    """Tests for thread stop mechanism."""

    def test_stop_sets_event(self):
        thread = LLMLabelingThread(
            config={},
            solo_config=MagicMock(),
            prompt_getter=lambda: "",
            result_callback=lambda r: None,
        )
        thread.stop()
        assert thread._stop_event.is_set()
        # Sentinel should be in queue
        assert thread.get_queue_size() == 1


class TestLLMLabelingThreadEndpointParam:
    """Tests for _label_instance with explicit endpoint parameter."""

    def _make_thread(self, **kwargs):
        defaults = {
            'config': {
                'annotation_schemes': [
                    {'name': 'sentiment', 'annotation_type': 'radio',
                     'labels': ['positive', 'negative', 'neutral']}
                ]
            },
            'solo_config': MagicMock(),
            'prompt_getter': lambda: "Classify the sentiment.",
            'result_callback': lambda r: None,
        }
        defaults.update(kwargs)
        return LLMLabelingThread(**defaults)

    def test_uses_provided_endpoint(self):
        """When endpoint is provided, uses it instead of _get_endpoint()."""
        thread = self._make_thread()
        mock_endpoint = MagicMock()

        # Make the endpoint return a valid response
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            'label': 'positive',
            'confidence': 90,
            'reasoning': 'Clear positive',
        }
        mock_endpoint.query.return_value = mock_response
        mock_endpoint.model = 'custom-model'

        # Ensure _get_endpoint is NOT called
        thread._get_endpoint = MagicMock(side_effect=AssertionError("Should not be called"))

        result = thread._label_instance("i1", "Great!", "sentiment", endpoint=mock_endpoint)
        assert result is not None
        assert result.label == "positive"
        assert result.model_name == "custom-model"
        mock_endpoint.query.assert_called_once()

    def test_falls_back_to_get_endpoint_when_none(self):
        """When endpoint=None, falls back to _get_endpoint()."""
        thread = self._make_thread()
        mock_endpoint = MagicMock()

        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            'label': 'negative',
            'confidence': 85,
            'reasoning': 'Negative tone',
        }
        mock_endpoint.query.return_value = mock_response
        mock_endpoint.model = 'default-model'

        thread._get_endpoint = MagicMock(return_value=mock_endpoint)

        result = thread._label_instance("i1", "Bad!", "sentiment", endpoint=None)
        assert result is not None
        assert result.label == "negative"
        thread._get_endpoint.assert_called_once()

    def test_backward_compatible_no_endpoint_arg(self):
        """Calling without endpoint arg works (backward compatible)."""
        thread = self._make_thread()
        mock_endpoint = MagicMock()

        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            'label': 'neutral',
            'confidence': 70,
            'reasoning': 'Ambiguous',
        }
        mock_endpoint.query.return_value = mock_response
        mock_endpoint.model = 'default-model'

        thread._get_endpoint = MagicMock(return_value=mock_endpoint)

        # Call without the endpoint parameter (old-style)
        result = thread._label_instance("i1", "Ok.", "sentiment")
        assert result is not None
        assert result.label == "neutral"


class TestCreateEndpointFromModelConfig:
    """Tests for create_endpoint_from_model_config static method."""

    @patch('potato.solo_mode.llm_labeler.AIEndpointFactory', create=True)
    def test_creates_endpoint(self, mock_factory_cls):
        """Creates endpoint with correct config structure."""
        # We need to patch the import inside the static method
        from potato.solo_mode.config import ModelConfig

        model_config = ModelConfig(
            endpoint_type='openai',
            model='gpt-4o-mini',
            max_tokens=500,
            temperature=0.2,
        )

        mock_endpoint = MagicMock()
        with patch('potato.ai.ai_endpoint.AIEndpointFactory') as mock_factory:
            mock_factory.create_endpoint.return_value = mock_endpoint
            result = LLMLabelingThread.create_endpoint_from_model_config(model_config)

        assert result == mock_endpoint
        call_args = mock_factory.create_endpoint.call_args[0][0]
        assert call_args['ai_support']['endpoint_type'] == 'openai'
        assert call_args['ai_support']['ai_config']['model'] == 'gpt-4o-mini'
        assert call_args['ai_support']['ai_config']['max_tokens'] == 500
        assert call_args['ai_support']['ai_config']['temperature'] == 0.2

    @patch('potato.ai.ai_endpoint.AIEndpointFactory')
    def test_includes_api_key(self, mock_factory):
        from potato.solo_mode.config import ModelConfig

        model_config = ModelConfig(
            endpoint_type='anthropic',
            model='claude-sonnet',
            api_key='sk-test-key',
        )

        mock_factory.create_endpoint.return_value = MagicMock()
        LLMLabelingThread.create_endpoint_from_model_config(model_config)

        call_args = mock_factory.create_endpoint.call_args[0][0]
        assert call_args['ai_support']['ai_config']['api_key'] == 'sk-test-key'

    @patch('potato.ai.ai_endpoint.AIEndpointFactory')
    def test_includes_base_url(self, mock_factory):
        from potato.solo_mode.config import ModelConfig

        model_config = ModelConfig(
            endpoint_type='openai',
            model='local-model',
            base_url='http://localhost:8080',
        )

        mock_factory.create_endpoint.return_value = MagicMock()
        LLMLabelingThread.create_endpoint_from_model_config(model_config)

        call_args = mock_factory.create_endpoint.call_args[0][0]
        assert call_args['ai_support']['ai_config']['base_url'] == 'http://localhost:8080'

    @patch('potato.ai.ai_endpoint.AIEndpointFactory')
    def test_omits_api_key_when_none(self, mock_factory):
        from potato.solo_mode.config import ModelConfig

        model_config = ModelConfig(
            endpoint_type='openai',
            model='gpt-4o-mini',
        )

        mock_factory.create_endpoint.return_value = MagicMock()
        LLMLabelingThread.create_endpoint_from_model_config(model_config)

        call_args = mock_factory.create_endpoint.call_args[0][0]
        assert 'api_key' not in call_args['ai_support']['ai_config']
        assert 'base_url' not in call_args['ai_support']['ai_config']


# Need json import for test data
import json
