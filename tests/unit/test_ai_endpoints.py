"""
Unit tests for AI endpoint system.
"""

import pytest
from unittest.mock import Mock, patch
from potato.ai.ai_endpoint import (
    BaseAIEndpoint,
    AIEndpointFactory,
    AIEndpointConfigError,
    AIEndpointRequestError,
    AIEndpointError
)


class MockAIEndpoint(BaseAIEndpoint):
    """Mock AI endpoint for testing."""

    def _initialize_client(self) -> None:
        self.client = Mock()

    def _get_default_model(self) -> str:
        return "test-model"

    def _get_default_hint_prompt(self) -> str:
        return "Test hint prompt: {description} {annotation_type} {text}"

    def _get_default_keyword_prompt(self) -> str:
        return "Test keyword prompt: {description} {annotation_type} {text}"

    def query(self, prompt: str) -> str:
        return f"Mock response to: {prompt}"


class TestBaseAIEndpoint:
    """Test the base AI endpoint class."""

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        config = {
            "description": "Test description",
            "annotation_type": "radio",
            "ai_config": {}
        }

        endpoint = MockAIEndpoint(config)

        assert endpoint.description == "Test description"
        assert endpoint.annotation_type == "radio"
        assert endpoint.model == "test-model"
        assert endpoint.temperature == 0.1  # New default is 0.1
        assert endpoint.max_tokens == 100

    def test_init_with_custom_config(self):
        """Test initialization with custom configuration."""
        config = {
            "description": "Test description",
            "annotation_type": "radio",
            "ai_config": {
                "model": "custom-model",
                "temperature": 0.5,
                "max_tokens": 200
            }
        }

        endpoint = MockAIEndpoint(config)

        assert endpoint.model == "custom-model"
        assert endpoint.temperature == 0.5
        assert endpoint.max_tokens == 200
        # Prompts are loaded from get_ai_prompt() - may be None or dict
        assert hasattr(endpoint, 'prompts')

    def test_query_method(self):
        """Test query method returns response."""
        config = {
            "description": "Test description",
            "annotation_type": "radio",
            "ai_config": {}
        }

        endpoint = MockAIEndpoint(config)
        response = endpoint.query("Test prompt")

        assert "Mock response to:" in response
        assert "Test prompt" in response

    def test_prompts_loaded(self):
        """Test that prompts are loaded from ai_prompt module."""
        config = {
            "description": "Test description",
            "annotation_type": "radio",
            "ai_config": {}
        }

        endpoint = MockAIEndpoint(config)
        # Prompts should be loaded (may be empty dict if no prompts configured)
        assert hasattr(endpoint, 'prompts')

    def test_health_check_success(self):
        """Test successful health check."""
        config = {
            "description": "Test description",
            "annotation_type": "radio",
            "ai_config": {}
        }

        endpoint = MockAIEndpoint(config)
        assert endpoint.health_check() is True

    def test_health_check_failure(self):
        """Test failed health check."""
        config = {
            "description": "Test description",
            "annotation_type": "radio",
            "ai_config": {}
        }

        endpoint = MockAIEndpoint(config)
        endpoint.query = Mock(side_effect=Exception("Test error"))

        assert endpoint.health_check() is False


class TestAIEndpointFactory:
    """Test the AI endpoint factory."""

    def setup_method(self):
        """Reset factory state before each test."""
        AIEndpointFactory._endpoints.clear()

    def test_register_endpoint(self):
        """Test endpoint registration."""
        AIEndpointFactory.register_endpoint("test", MockAIEndpoint)
        assert "test" in AIEndpointFactory._endpoints
        assert AIEndpointFactory._endpoints["test"] == MockAIEndpoint

    def test_create_endpoint_disabled(self):
        """Test creating endpoint when AI support is disabled."""
        config = {"ai_support": {"enabled": False}}

        endpoint = AIEndpointFactory.create_endpoint(config)
        assert endpoint is None

    def test_create_endpoint_missing_endpoint_type(self):
        """Test creating endpoint without endpoint type."""
        config = {"ai_support": {"enabled": True}}

        with pytest.raises(AIEndpointConfigError, match="endpoint_type is required"):
            AIEndpointFactory.create_endpoint(config)

    def test_create_endpoint_unknown_type(self):
        """Test creating endpoint with unknown type."""
        config = {
            "ai_support": {
                "enabled": True,
                "endpoint_type": "unknown"
            }
        }

        with pytest.raises(AIEndpointConfigError, match="Unknown endpoint type"):
            AIEndpointFactory.create_endpoint(config)

    def test_create_endpoint_success(self):
        """Test successful endpoint creation."""
        AIEndpointFactory.register_endpoint("test", MockAIEndpoint)

        config = {
            "ai_support": {
                "enabled": True,
                "endpoint_type": "test",
                "ai_config": {
                    "model": "test-model",
                    "temperature": 0.3
                }
            }
        }

        endpoint = AIEndpointFactory.create_endpoint(config)
        assert isinstance(endpoint, MockAIEndpoint)
        # Factory passes ai_config to endpoint
        assert endpoint.temperature == 0.3


class TestAIEndpointErrors:
    """Test AI endpoint error handling."""

    def test_config_error(self):
        """Test configuration error."""
        error = AIEndpointConfigError("Test config error")
        assert str(error) == "Test config error"

    def test_request_error(self):
        """Test request error."""
        error = AIEndpointRequestError("Test request error")
        assert str(error) == "Test request error"

    def test_error_inheritance(self):
        """Test error inheritance."""
        config_error = AIEndpointConfigError("Test")
        request_error = AIEndpointRequestError("Test")

        # Both should inherit from AIEndpointError
        assert isinstance(config_error, AIEndpointError)
        assert isinstance(request_error, AIEndpointError)

        # They should not inherit from each other
        assert not isinstance(config_error, AIEndpointRequestError)
        assert not isinstance(request_error, AIEndpointConfigError)


if __name__ == "__main__":
    pytest.main([__file__])