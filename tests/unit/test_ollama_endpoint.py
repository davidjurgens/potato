"""
Unit tests for Ollama endpoint implementation.

Tests Ollama-specific behavior with mocked ollama client.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json


class TestOllamaEndpointInit:
    """Test OllamaEndpoint initialization."""

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_init_with_default_host(self, mock_client_class):
        """Test initialization with default host."""
        mock_client = Mock()
        mock_client.list.return_value = {}
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint

        config = {
            "ai_config": {
                "model": "test-model"
            }
        }

        endpoint = OllamaEndpoint(config)

        # Should use default host
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]
        assert call_kwargs['host'] == "http://localhost:11434"

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_init_with_custom_host(self, mock_client_class):
        """Test initialization with custom host."""
        mock_client = Mock()
        mock_client.list.return_value = {}
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint

        config = {
            "ai_config": {
                "model": "test-model",
                "base_url": "http://custom-host:11434"
            }
        }

        endpoint = OllamaEndpoint(config)

        call_kwargs = mock_client_class.call_args[1]
        assert call_kwargs['host'] == "http://custom-host:11434"

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_init_with_custom_timeout(self, mock_client_class):
        """Test initialization with custom timeout."""
        mock_client = Mock()
        mock_client.list.return_value = {}
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint

        config = {
            "ai_config": {
                "model": "test-model",
                "timeout": 120
            }
        }

        endpoint = OllamaEndpoint(config)

        call_kwargs = mock_client_class.call_args[1]
        assert call_kwargs['timeout'] == 120

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_init_connection_failure_raises(self, mock_client_class):
        """Test that connection failure during init raises error."""
        mock_client = Mock()
        mock_client.list.side_effect = Exception("Connection refused")
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint
        from potato.ai.ai_endpoint import AIEndpointRequestError

        config = {
            "ai_config": {
                "model": "test-model"
            }
        }

        with pytest.raises(AIEndpointRequestError, match="Failed to connect to Ollama"):
            OllamaEndpoint(config)


class TestOllamaEndpointQuery:
    """Test OllamaEndpoint query method."""

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_query_success_string_response(self, mock_client_class):
        """Test successful query with string JSON response."""
        mock_client = Mock()
        mock_client.list.return_value = {}
        mock_client.chat.return_value = {
            'message': {
                'content': '{"hint": "test hint", "suggestive_choice": "positive"}'
            }
        }
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint
        from pydantic import BaseModel

        class TestFormat(BaseModel):
            hint: str
            suggestive_choice: str

        config = {
            "ai_config": {
                "model": "test-model",
                "temperature": 0.7,
                "max_tokens": 150
            }
        }

        endpoint = OllamaEndpoint(config)
        result = endpoint.query("Test prompt", TestFormat)

        assert isinstance(result, dict)
        assert result["hint"] == "test hint"
        assert result["suggestive_choice"] == "positive"

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_query_success_dict_response(self, mock_client_class):
        """Test successful query when Ollama returns dict directly."""
        mock_client = Mock()
        mock_client.list.return_value = {}
        # Some Ollama versions return dict directly with structured output
        mock_client.chat.return_value = {
            'message': {
                'content': {"hint": "direct dict", "suggestive_choice": "neutral"}
            }
        }
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint
        from pydantic import BaseModel

        class TestFormat(BaseModel):
            hint: str
            suggestive_choice: str

        config = {"ai_config": {"model": "test-model"}}

        endpoint = OllamaEndpoint(config)
        result = endpoint.query("Test prompt", TestFormat)

        assert isinstance(result, dict)
        assert result["hint"] == "direct dict"

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_query_empty_content_raises(self, mock_client_class):
        """Test that empty content raises AIEndpointRequestError."""
        mock_client = Mock()
        mock_client.list.return_value = {}
        mock_client.chat.return_value = {
            'message': {
                'content': ''
            }
        }
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint
        from potato.ai.ai_endpoint import AIEndpointRequestError
        from pydantic import BaseModel

        class TestFormat(BaseModel):
            hint: str

        config = {"ai_config": {"model": "test-model"}}

        endpoint = OllamaEndpoint(config)

        with pytest.raises(AIEndpointRequestError, match="Ollama request failed"):
            endpoint.query("Test prompt", TestFormat)

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_query_invalid_json_raises(self, mock_client_class):
        """Test that invalid JSON response raises AIEndpointRequestError."""
        mock_client = Mock()
        mock_client.list.return_value = {}
        mock_client.chat.return_value = {
            'message': {
                'content': 'This is not valid JSON at all'
            }
        }
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint
        from potato.ai.ai_endpoint import AIEndpointRequestError
        from pydantic import BaseModel

        class TestFormat(BaseModel):
            hint: str

        config = {"ai_config": {"model": "test-model"}}

        endpoint = OllamaEndpoint(config)

        with pytest.raises(AIEndpointRequestError, match="Ollama request failed"):
            endpoint.query("Test prompt", TestFormat)

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_query_network_error_raises(self, mock_client_class):
        """Test that network error raises AIEndpointRequestError."""
        mock_client = Mock()
        mock_client.list.return_value = {}
        mock_client.chat.side_effect = Exception("Network timeout")
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint
        from potato.ai.ai_endpoint import AIEndpointRequestError
        from pydantic import BaseModel

        class TestFormat(BaseModel):
            hint: str

        config = {"ai_config": {"model": "test-model"}}

        endpoint = OllamaEndpoint(config)

        with pytest.raises(AIEndpointRequestError, match="Ollama request failed"):
            endpoint.query("Test prompt", TestFormat)

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_query_passes_correct_parameters(self, mock_client_class):
        """Test that query passes correct parameters to Ollama client."""
        mock_client = Mock()
        mock_client.list.return_value = {}
        mock_client.chat.return_value = {
            'message': {'content': '{"hint": "test"}'}
        }
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint
        from pydantic import BaseModel

        class TestFormat(BaseModel):
            hint: str

        config = {
            "ai_config": {
                "model": "qwen3:0.6b",
                "temperature": 0.5,
                "max_tokens": 200
            }
        }

        endpoint = OllamaEndpoint(config)
        endpoint.query("Test prompt", TestFormat)

        # Verify chat was called with correct parameters
        mock_client.chat.assert_called_once()
        call_kwargs = mock_client.chat.call_args[1]

        assert call_kwargs['model'] == "qwen3:0.6b"
        assert call_kwargs['messages'] == [{'role': 'user', 'content': 'Test prompt'}]
        assert call_kwargs['options']['temperature'] == 0.5
        assert call_kwargs['options']['num_predict'] == 200


class TestOllamaEndpointDefaultModel:
    """Test default model handling."""

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_default_model_is_llama32(self, mock_client_class):
        """Test that default model is llama3.2."""
        mock_client = Mock()
        mock_client.list.return_value = {}
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint, DEFAULT_MODEL

        config = {"ai_config": {}}  # No model specified

        endpoint = OllamaEndpoint(config)

        assert endpoint.model == DEFAULT_MODEL
        assert DEFAULT_MODEL == "llama3.2"

    @patch('potato.ai.ollama_endpoint.ollama.Client')
    def test_custom_model_overrides_default(self, mock_client_class):
        """Test that custom model overrides default."""
        mock_client = Mock()
        mock_client.list.return_value = {}
        mock_client_class.return_value = mock_client

        from potato.ai.ollama_endpoint import OllamaEndpoint

        config = {"ai_config": {"model": "qwen3:0.6b"}}

        endpoint = OllamaEndpoint(config)

        assert endpoint.model == "qwen3:0.6b"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
