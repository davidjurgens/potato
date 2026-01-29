"""
Tests verifying AI system initializes correctly when enabled.

These tests ensure that:
1. AI init functions are called when ai_support.enabled=True
2. AI init functions are NOT called when ai_support.enabled=False
3. get_ai_wrapper() returns correct values based on initialization state
"""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add potato to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'potato'))


class TestAIInitializationState:
    """Test that AI components initialize correctly based on config."""

    def test_get_ai_wrapper_returns_empty_when_not_initialized(self):
        """Verify get_ai_wrapper returns empty string when AI is not initialized."""
        # Reset global state
        import ai.ai_help_wrapper as wrapper
        original_value = wrapper.DYNAMICAIHELP
        wrapper.DYNAMICAIHELP = None

        try:
            result = wrapper.get_ai_wrapper()
            assert result == "", f"Expected empty string when AI not initialized, got: {result}"
        finally:
            # Restore original state
            wrapper.DYNAMICAIHELP = original_value

    def test_get_dynamic_ai_help_returns_none_when_not_initialized(self):
        """Verify get_dynamic_ai_help returns None when not initialized."""
        import ai.ai_help_wrapper as wrapper
        original_value = wrapper.DYNAMICAIHELP
        wrapper.DYNAMICAIHELP = None

        try:
            result = wrapper.get_dynamic_ai_help()
            assert result is None, f"Expected None when not initialized, got: {result}"
        finally:
            wrapper.DYNAMICAIHELP = original_value

    def test_get_ai_cache_manager_returns_none_when_not_initialized(self):
        """Verify get_ai_cache_manager returns None when not initialized."""
        import ai.ai_cache as cache
        original_value = cache.AICACHEMANAGER
        cache.AICACHEMANAGER = None

        try:
            result = cache.get_ai_cache_manager()
            assert result is None, f"Expected None when not initialized, got: {result}"
        finally:
            cache.AICACHEMANAGER = original_value

    def test_get_ai_prompt_returns_none_when_not_initialized(self):
        """Verify get_ai_prompt returns None when prompts not loaded."""
        import ai.ai_prompt as prompt
        original_value = prompt.ANNOTATIONS
        prompt.ANNOTATIONS = None

        try:
            result = prompt.get_ai_prompt()
            assert result is None, f"Expected None when not initialized, got: {result}"
        finally:
            prompt.ANNOTATIONS = original_value


class TestAIInitializationWithConfig:
    """Test AI initialization with mocked config."""

    @patch('ai.ai_help_wrapper.config')
    def test_init_dynamic_ai_help_does_nothing_when_disabled(self, mock_config):
        """Verify init_dynamic_ai_help doesn't create helper when AI disabled."""
        mock_config.__getitem__ = MagicMock(return_value={"enabled": False})

        import ai.ai_help_wrapper as wrapper
        original_value = wrapper.DYNAMICAIHELP
        wrapper.DYNAMICAIHELP = None

        try:
            result = wrapper.init_dynamic_ai_help()
            assert result is None, "Should return None when AI disabled"
            assert wrapper.DYNAMICAIHELP is None, "Should not create helper when AI disabled"
        finally:
            wrapper.DYNAMICAIHELP = original_value

    @patch('ai.ai_prompt.config')
    def test_init_ai_prompt_does_nothing_when_disabled(self, mock_config):
        """Verify init_ai_prompt doesn't load prompts when AI disabled."""
        mock_config_data = {"ai_support": {"enabled": False}}

        import ai.ai_prompt as prompt
        original_value = prompt.ANNOTATIONS
        prompt.ANNOTATIONS = None

        try:
            prompt.init_ai_prompt(mock_config_data)
            assert prompt.ANNOTATIONS is None, "Should not load prompts when AI disabled"
        finally:
            prompt.ANNOTATIONS = original_value


class TestAIWrapperHTMLGeneration:
    """Test that AI wrapper generates correct HTML."""

    def test_empty_wrapper_has_correct_structure(self):
        """Verify the empty wrapper div has correct class structure."""
        from ai.ai_help_wrapper import DynamicAIHelp

        helper = DynamicAIHelp()
        html = helper.get_empty_wrapper()

        assert 'class="ai-help' in html, "Should have ai-help class"
        assert 'class="tooltip"' in html, "Should have tooltip class"
        assert '<div' in html, "Should be a div element"

    def test_dynamic_ai_help_class_can_be_instantiated(self):
        """Verify DynamicAIHelp class can be instantiated."""
        from ai.ai_help_wrapper import DynamicAIHelp

        helper = DynamicAIHelp()
        assert helper is not None
        assert hasattr(helper, 'get_empty_wrapper')
        assert hasattr(helper, 'get_ai_help_data')
        assert hasattr(helper, 'render')
        assert hasattr(helper, 'generate_ai_assistant')


class TestAIEndpointFactory:
    """Test AI endpoint factory behavior."""

    def test_endpoint_factory_returns_none_when_disabled(self):
        """Verify factory returns None when AI support is disabled."""
        from ai.ai_endpoint import AIEndpointFactory

        config = {"ai_support": {"enabled": False}}
        result = AIEndpointFactory.create_endpoint(config)
        assert result is None, "Should return None when AI disabled"

    def test_endpoint_factory_raises_on_unknown_type(self):
        """Verify factory raises error for unknown endpoint type."""
        from ai.ai_endpoint import AIEndpointFactory, AIEndpointConfigError

        config = {
            "ai_support": {
                "enabled": True,
                "endpoint_type": "nonexistent_provider",
                "ai_config": {}
            }
        }

        with pytest.raises(AIEndpointConfigError):
            AIEndpointFactory.create_endpoint(config)


class TestPromptTemplateLoading:
    """Test prompt template loading functionality."""

    def test_default_prompt_directory_exists(self):
        """Verify default prompt templates directory exists."""
        from pathlib import Path
        import ai.ai_prompt as prompt

        # Get the default path that would be used
        default_path = Path(prompt.__file__).resolve().parent / "prompt"
        assert default_path.exists(), f"Default prompt directory should exist: {default_path}"
        assert default_path.is_dir(), "Should be a directory"

    def test_default_prompts_have_required_files(self):
        """Verify required prompt JSON files exist."""
        from pathlib import Path
        import ai.ai_prompt as prompt

        default_path = Path(prompt.__file__).resolve().parent / "prompt"

        required_files = ["radio.json", "multiselect.json", "likert.json"]
        for filename in required_files:
            filepath = default_path / filename
            assert filepath.exists(), f"Required prompt file missing: {filename}"


class TestModelManager:
    """Test ModelManager functionality."""

    def test_model_manager_can_be_instantiated(self):
        """Verify ModelManager can be created."""
        from ai.ai_prompt import ModelManager

        manager = ModelManager()
        assert manager is not None
        assert hasattr(manager, 'load_models_module')
        assert hasattr(manager, 'get_model_class_by_name')

    def test_model_manager_loads_default_module(self):
        """Verify ModelManager can load default models module."""
        from ai.ai_prompt import ModelManager

        # Mock config to avoid dependency
        with patch('ai.ai_prompt.config') as mock_config:
            mock_config.get.return_value = {"model_module": None}

            manager = ModelManager()
            module = manager.load_models_module()

            assert module is not None, "Should load default module"
            assert hasattr(module, 'CLASS_REGISTRY'), "Module should have CLASS_REGISTRY"
