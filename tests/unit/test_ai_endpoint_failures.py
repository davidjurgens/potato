"""
Unit tests for AI endpoint failure paths and graceful degradation.

Existing AI tests (`test_ai_endpoints.py`, `test_ai_cache.py`) cover
happy paths. This file plugs the error-path gap:

- AIEndpointFactory config validation (missing type, unknown type,
  ai_support disabled)
- OpenAI endpoint init failures (missing API key)
- Query failures wrap exceptions as AIEndpointRequestError
- get_ai() returns graceful fallback strings instead of raising
- parseStringToJson() handles empty / malformed / markdown-wrapped JSON
- chat_query() default flattening for non-multiturn-native endpoints
- health_check() returns False on failure (never raises)

All tests are offline — external SDK calls are mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

from potato.ai.ai_endpoint import (
    AIEndpointFactory,
    AIEndpointConfigError,
    AIEndpointRequestError,
    BaseAIEndpoint,
    AnnotationInput,
    Annotation_Type,
)


# =====================================================================
# A minimal test endpoint that we can fully control
# =====================================================================


class _FakeEndpoint(BaseAIEndpoint):
    """Controllable test endpoint — lets tests inject query failures."""

    def __init__(self, config, query_raises=None, query_returns=None):
        self._query_raises = query_raises
        self._query_returns = query_returns
        super().__init__(config)

    def _initialize_client(self):
        self.client = MagicMock()

    def _get_default_model(self):
        return "fake-model-v1"

    def query(self, prompt, output_format=None):
        if self._query_raises is not None:
            raise self._query_raises
        return self._query_returns


def _make_fake(**kwargs):
    return _FakeEndpoint({"ai_config": {}}, **kwargs)


# =====================================================================
# TestFactoryConfigValidation
# =====================================================================


class TestFactoryConfigValidation:
    def test_disabled_ai_support_returns_none(self):
        """When ai_support.enabled is False (or absent), factory returns None."""
        assert AIEndpointFactory.create_endpoint({}) is None
        assert (
            AIEndpointFactory.create_endpoint({"ai_support": {"enabled": False}})
            is None
        )

    def test_missing_endpoint_type_raises_config_error(self):
        with pytest.raises(AIEndpointConfigError, match="endpoint_type"):
            AIEndpointFactory.create_endpoint(
                {"ai_support": {"enabled": True, "ai_config": {}}}
            )

    def test_unknown_endpoint_type_raises_config_error(self):
        with pytest.raises(AIEndpointConfigError, match="Unknown endpoint type"):
            AIEndpointFactory.create_endpoint(
                {
                    "ai_support": {
                        "enabled": True,
                        "endpoint_type": "nonexistent_provider",
                        "ai_config": {},
                    }
                }
            )

    def test_endpoint_init_failure_wrapped_as_config_error(self):
        """If an endpoint's __init__ raises, factory wraps it."""

        class _BrokenEndpoint(BaseAIEndpoint):
            def _initialize_client(self):
                raise RuntimeError("upstream service unreachable")

            def _get_default_model(self):
                return "broken"

            def query(self, prompt, output_format=None):
                return ""

        AIEndpointFactory.register_endpoint("broken_for_test", _BrokenEndpoint)
        try:
            with pytest.raises(AIEndpointConfigError, match="Failed to create"):
                AIEndpointFactory.create_endpoint(
                    {
                        "ai_support": {
                            "enabled": True,
                            "endpoint_type": "broken_for_test",
                            "ai_config": {},
                        }
                    }
                )
        finally:
            # Clean up the test registration
            AIEndpointFactory._endpoints.pop("broken_for_test", None)


# =====================================================================
# TestOpenAIInitFailures
# =====================================================================


class TestOpenAIInitFailures:
    """OpenAIEndpoint should fail fast on missing API key."""

    def test_missing_api_key_raises_request_error(self):
        from potato.ai.openai_endpoint import OpenAIEndpoint

        with pytest.raises(AIEndpointRequestError, match="API key is required"):
            OpenAIEndpoint({"ai_config": {}})

    def test_empty_api_key_raises_request_error(self):
        from potato.ai.openai_endpoint import OpenAIEndpoint

        with pytest.raises(AIEndpointRequestError, match="API key is required"):
            OpenAIEndpoint({"ai_config": {"api_key": ""}})

    @patch("potato.ai.openai_endpoint.OpenAI")
    def test_query_wraps_sdk_exceptions(self, mock_openai):
        """Any SDK exception in query() should surface as AIEndpointRequestError."""
        from potato.ai.openai_endpoint import OpenAIEndpoint

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("simulated 429")
        mock_openai.return_value = mock_client

        endpoint = OpenAIEndpoint({"ai_config": {"api_key": "test-key"}})
        with pytest.raises(AIEndpointRequestError, match="OpenAI request failed"):
            endpoint.query("prompt", MagicMock())

    @patch("potato.ai.openai_endpoint.OpenAI")
    def test_chat_query_wraps_sdk_exceptions(self, mock_openai):
        from potato.ai.openai_endpoint import OpenAIEndpoint

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("timeout")
        mock_openai.return_value = mock_client

        endpoint = OpenAIEndpoint({"ai_config": {"api_key": "test-key"}})
        with pytest.raises(AIEndpointRequestError, match="chat request failed"):
            endpoint.chat_query([{"role": "user", "content": "hi"}])


# =====================================================================
# TestGetAIGracefulDegradation
# =====================================================================


class TestGetAIGracefulDegradation:
    """get_ai() should NEVER raise — it should return a fallback string.

    This is the critical guarantee for the UI: an AI suggestion failure
    must not crash the annotation page.
    """

    def test_invalid_annotation_type_returns_fallback(self):
        endpoint = _make_fake(query_returns="irrelevant")
        data = AnnotationInput(
            ai_assistant="hint",
            annotation_type="totally_invalid_type",  # not in Annotation_Type
            text="some text",
            description="some description",
        )
        result = endpoint.get_ai(data, MagicMock())
        assert "Unable to generate suggestion" in result
        assert "annotation type not configured" in result

    def test_query_exception_returns_fallback(self):
        endpoint = _make_fake(
            query_raises=AIEndpointRequestError("rate limited 429")
        )
        data = AnnotationInput(
            ai_assistant="hint",
            annotation_type=Annotation_Type.RADIO.value,
            text="test",
            description="test",
            labels=["a", "b"],
        )
        # Must not propagate — returns fallback string
        result = endpoint.get_ai(data, MagicMock())
        assert "Unable to generate hint" in result

    def test_unknown_ai_assistant_returns_fallback(self):
        """An unknown ai_assistant name should yield a fallback, not crash."""
        endpoint = _make_fake(query_returns="irrelevant")
        data = AnnotationInput(
            ai_assistant="totally_fake_assistant_name",
            annotation_type=Annotation_Type.RADIO.value,
            text="test",
            description="test",
            labels=["a", "b"],
        )
        result = endpoint.get_ai(data, MagicMock())
        assert "Unable to generate" in result


# =====================================================================
# TestParseStringToJson
# =====================================================================


class TestParseStringToJson:
    """parseStringToJson handles markdown wrapping, empty content,
    and malformed input without silent corruption."""

    @pytest.fixture
    def endpoint(self):
        return _make_fake(query_returns="")

    def test_empty_string_raises(self, endpoint):
        with pytest.raises(ValueError, match="Empty response content"):
            endpoint.parseStringToJson("")

    def test_none_raises(self, endpoint):
        with pytest.raises(ValueError, match="Empty response content"):
            endpoint.parseStringToJson(None)

    def test_whitespace_only_raises(self, endpoint):
        with pytest.raises(ValueError, match="Empty response content"):
            endpoint.parseStringToJson("   \n\t  ")

    def test_valid_json_parsed(self, endpoint):
        result = endpoint.parseStringToJson('{"label": "positive", "confidence": 0.9}')
        assert result == {"label": "positive", "confidence": 0.9}

    def test_markdown_json_fence_stripped(self, endpoint):
        content = '```json\n{"label": "negative"}\n```'
        result = endpoint.parseStringToJson(content)
        assert result == {"label": "negative"}

    def test_generic_markdown_fence_stripped(self, endpoint):
        content = '```\n{"label": "neutral"}\n```'
        result = endpoint.parseStringToJson(content)
        assert result == {"label": "neutral"}

    def test_malformed_json_raises_value_error(self, endpoint):
        with pytest.raises(ValueError, match="Failed to parse JSON"):
            endpoint.parseStringToJson("this is not json at all {")

    def test_dict_passthrough(self, endpoint):
        original = {"already": "parsed"}
        result = endpoint.parseStringToJson(original)
        assert result is original


# =====================================================================
# TestChatQueryDefaultFlattening
# =====================================================================


class TestChatQueryDefaultFlattening:
    """Default chat_query flattens messages and calls query() — endpoints
    without native multi-turn support should still work."""

    def test_single_user_message_flattened(self):
        endpoint = _make_fake(query_returns="hello back")
        result = endpoint.chat_query([{"role": "user", "content": "hi"}])
        assert result == "hello back"

    def test_multi_turn_flattening_preserves_order(self):
        """Capture the flattened prompt passed to query()."""
        captured = {}

        class _Capturing(BaseAIEndpoint):
            def _initialize_client(self):
                pass

            def _get_default_model(self):
                return "cap"

            def query(self, prompt, output_format=None):
                captured["prompt"] = prompt
                return "ok"

        endpoint = _Capturing({"ai_config": {}})
        endpoint.chat_query(
            [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "ack"},
                {"role": "user", "content": "second"},
            ]
        )
        prompt = captured["prompt"]
        # System message first, then interleaved
        assert prompt.index("System: You are helpful.") < prompt.index("User: first")
        assert prompt.index("User: first") < prompt.index("Assistant: ack")
        assert prompt.index("Assistant: ack") < prompt.index("User: second")
        # Must end with an Assistant prompt to cue completion
        assert prompt.rstrip().endswith("Assistant:")

    def test_query_exception_wrapped_as_request_error(self):
        endpoint = _make_fake(query_raises=RuntimeError("boom"))
        with pytest.raises(AIEndpointRequestError, match="Chat query failed"):
            endpoint.chat_query([{"role": "user", "content": "x"}])


# =====================================================================
# TestHealthCheck
# =====================================================================


class TestHealthCheck:
    """health_check() must never raise — it returns True/False."""

    def test_success_case(self):
        endpoint = _make_fake(query_returns="hello")
        assert endpoint.health_check() is True

    def test_empty_response_returns_false(self):
        endpoint = _make_fake(query_returns="")
        assert endpoint.health_check() is False

    def test_whitespace_response_returns_false(self):
        endpoint = _make_fake(query_returns="   \n  ")
        assert endpoint.health_check() is False

    def test_query_exception_returns_false_not_raise(self):
        endpoint = _make_fake(query_raises=AIEndpointRequestError("down"))
        # Must NOT raise — returns False
        result = endpoint.health_check()
        assert result is False

    def test_unexpected_exception_returns_false(self):
        """Even non-AIEndpointRequestError exceptions should be caught."""
        endpoint = _make_fake(query_raises=TimeoutError("network"))
        assert endpoint.health_check() is False
