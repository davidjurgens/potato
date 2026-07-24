"""
Tests for LLM endpoint env-var substitution and base_url handling.

Covers:
- _substitute_env_typed / _substitute_llm_block_env_vars in config_module
  (the ${POTATO_LLM_*} switching scheme used by the demo suite)
- OpenAI agent proxy base_url support
- base_url normalization: bare hosts get '/v1'; pathful URLs (Gemini's
  OpenAI-compat layer) are preserved.
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from potato.server_utils.config_module import (
    _substitute_env_typed,
    _substitute_llm_block_env_vars,
)
from potato.agent_proxy.openai_proxy import (
    OpenAIChatProxy,
    _normalize_base_url as proxy_normalize,
)
from potato.coding_agent_backends.openai_backend import (
    _normalize_base_url as backend_normalize,
)


LLM_ENV = {
    "POTATO_LLM_TEXT_ENDPOINT_TYPE": "vllm",
    "POTATO_LLM_MODEL": "google/gemma-3-4b-it",
    "POTATO_LLM_BASE_URL": "http://burger.si.umich.edu:8001/v1",
    "POTATO_LLM_API_KEY": "EMPTY",
    "POTATO_LLM_MAX_TOKENS": "1024",
}


class TestSubstituteEnvTyped:
    def test_string_substitution(self):
        with patch.dict(os.environ, LLM_ENV):
            result = _substitute_env_typed({"model": "${POTATO_LLM_MODEL}"})
        assert result == {"model": "google/gemma-3-4b-it"}

    def test_numeric_key_coerced_to_int(self):
        with patch.dict(os.environ, LLM_ENV):
            result = _substitute_env_typed({"max_tokens": "${POTATO_LLM_MAX_TOKENS}"})
        assert result == {"max_tokens": 1024}
        assert isinstance(result["max_tokens"], int)

    def test_numeric_key_coerced_to_float(self):
        with patch.dict(os.environ, {"MY_TEMP": "0.3"}):
            result = _substitute_env_typed({"temperature": "${MY_TEMP}"})
        assert result == {"temperature": 0.3}
        assert isinstance(result["temperature"], float)

    def test_non_numeric_key_stays_string(self):
        with patch.dict(os.environ, {"MY_KEY": "12345"}):
            result = _substitute_env_typed({"api_key": "${MY_KEY}"})
        assert result == {"api_key": "12345"}
        assert isinstance(result["api_key"], str)

    def test_yaml_typed_values_pass_through(self):
        result = _substitute_env_typed({"max_tokens": 512, "temperature": 0.1})
        assert result == {"max_tokens": 512, "temperature": 0.1}

    def test_unset_var_left_unchanged(self):
        os.environ.pop("DEFINITELY_NOT_SET_XYZ", None)
        result = _substitute_env_typed({"model": "${DEFINITELY_NOT_SET_XYZ}"})
        assert result == {"model": "${DEFINITELY_NOT_SET_XYZ}"}

    def test_nested_lists_of_dicts(self):
        """judge_calibration.models / solo_mode.labeling_models shape."""
        with patch.dict(os.environ, LLM_ENV):
            result = _substitute_env_typed(
                {
                    "models": [
                        {
                            "endpoint_type": "${POTATO_LLM_TEXT_ENDPOINT_TYPE}",
                            "model": "${POTATO_LLM_MODEL}",
                            "base_url": "${POTATO_LLM_BASE_URL}",
                            "max_tokens": "${POTATO_LLM_MAX_TOKENS}",
                        }
                    ]
                }
            )
        model = result["models"][0]
        assert model["endpoint_type"] == "vllm"
        assert model["base_url"] == "http://burger.si.umich.edu:8001/v1"
        assert model["max_tokens"] == 1024


class TestSubstituteLLMBlocks:
    def test_whitelisted_blocks_substituted(self):
        config = {
            "live_agent": {"ai_config": {"model": "${POTATO_LLM_MODEL}"}},
            "agent_proxy": {"model": "${POTATO_LLM_MODEL}"},
            "solo_mode": {"labeling_models": [{"model": "${POTATO_LLM_MODEL}"}]},
        }
        with patch.dict(os.environ, LLM_ENV):
            result = _substitute_llm_block_env_vars(config)
        assert result["live_agent"]["ai_config"]["model"] == "google/gemma-3-4b-it"
        assert result["agent_proxy"]["model"] == "google/gemma-3-4b-it"
        assert result["solo_mode"]["labeling_models"][0]["model"] == "google/gemma-3-4b-it"

    def test_non_whitelisted_blocks_untouched(self):
        """Prompt-ish content outside LLM blocks must not be substituted."""
        config = {
            "annotation_schemes": [{"description": "literal ${POTATO_LLM_MODEL}"}],
            "html_layout": "uses ${POTATO_LLM_MODEL} literally",
        }
        with patch.dict(os.environ, LLM_ENV):
            result = _substitute_llm_block_env_vars(config)
        assert result["annotation_schemes"][0]["description"] == "literal ${POTATO_LLM_MODEL}"
        assert result["html_layout"] == "uses ${POTATO_LLM_MODEL} literally"

    def test_missing_blocks_ok(self):
        assert _substitute_llm_block_env_vars({}) == {}


class TestBaseUrlNormalization:
    """Both the agent proxy and the coding backend must leave pathful URLs
    (Gemini's OpenAI-compat layer) intact while appending /v1 to bare hosts."""

    @pytest.mark.parametrize("normalize", [proxy_normalize, backend_normalize])
    def test_bare_host_gets_v1(self, normalize):
        assert normalize("http://burger.si.umich.edu:8001") == "http://burger.si.umich.edu:8001/v1"

    @pytest.mark.parametrize("normalize", [proxy_normalize, backend_normalize])
    def test_v1_url_unchanged(self, normalize):
        assert normalize("http://burger.si.umich.edu:8001/v1") == "http://burger.si.umich.edu:8001/v1"

    @pytest.mark.parametrize("normalize", [proxy_normalize, backend_normalize])
    def test_gemini_compat_url_preserved(self, normalize):
        url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        assert normalize(url) == "https://generativelanguage.googleapis.com/v1beta/openai"

    @pytest.mark.parametrize("normalize", [proxy_normalize, backend_normalize])
    def test_empty_passthrough(self, normalize):
        assert normalize("") == ""


class TestOpenAIProxyBaseUrl:
    def _make_proxy(self, config):
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            proxy = OpenAIChatProxy(config)
            return proxy, mock_openai

    def test_base_url_passed_to_client(self):
        _, mock_openai = self._make_proxy(
            {"type": "openai", "model": "gemma", "base_url": "http://burger.si.umich.edu:8001", "api_key": "EMPTY"}
        )
        kwargs = mock_openai.call_args.kwargs
        assert kwargs["base_url"] == "http://burger.si.umich.edu:8001/v1"

    def test_no_base_url_passes_none(self):
        _, mock_openai = self._make_proxy(
            {"type": "openai", "model": "gpt-4o", "api_key": "sk-test"}
        )
        assert mock_openai.call_args.kwargs["base_url"] is None

    def test_local_server_without_key_uses_empty(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            _, mock_openai = self._make_proxy(
                {"type": "openai", "model": "gemma", "base_url": "http://localhost:8001"}
            )
        assert mock_openai.call_args.kwargs["api_key"] == "EMPTY"

    def test_no_key_no_base_url_raises(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with pytest.raises(ValueError):
                OpenAIChatProxy({"type": "openai", "model": "gpt-4o"})
