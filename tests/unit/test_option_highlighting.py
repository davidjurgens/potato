"""
Unit tests for the Option Highlighting feature.

Tests cover:
- Configuration validation
- Output format model
- AiCacheManager option highlighting methods
"""

import pytest
from unittest.mock import MagicMock, patch


class TestOptionHighlightFormat:
    """Test the OptionHighlightFormat Pydantic model."""

    def test_basic_format(self):
        """Test basic OptionHighlightFormat creation."""
        from potato.ai.prompt.models_module import OptionHighlightFormat

        result = OptionHighlightFormat(
            highlighted_options=["positive", "neutral"],
            confidence=0.85
        )

        assert result.highlighted_options == ["positive", "neutral"]
        assert result.confidence == 0.85

    def test_format_without_confidence(self):
        """Test OptionHighlightFormat with optional confidence."""
        from potato.ai.prompt.models_module import OptionHighlightFormat

        result = OptionHighlightFormat(
            highlighted_options=["negative"]
        )

        assert result.highlighted_options == ["negative"]
        assert result.confidence is None

    def test_format_empty_options(self):
        """Test OptionHighlightFormat with empty options list."""
        from potato.ai.prompt.models_module import OptionHighlightFormat

        result = OptionHighlightFormat(
            highlighted_options=[]
        )

        assert result.highlighted_options == []

    def test_format_in_registry(self):
        """Test that OptionHighlightFormat is in the class registry."""
        from potato.ai.prompt.models_module import CLASS_REGISTRY, OptionHighlightFormat

        assert "option_highlight" in CLASS_REGISTRY
        assert CLASS_REGISTRY["option_highlight"] == OptionHighlightFormat


class TestOptionHighlightingConfigValidation:
    """Test configuration validation for option highlighting."""

    def test_valid_config(self):
        """Test that a valid config passes validation."""
        from potato.server_utils.config_module import _validate_option_highlighting_config

        config = {
            "enabled": True,
            "top_k": 3,
            "dim_opacity": 0.4,
            "auto_apply": True,
            "schemas": ["sentiment", "topic"],
            "prefetch_count": 20
        }

        # Should not raise
        _validate_option_highlighting_config(config)

    def test_invalid_top_k_too_low(self):
        """Test that top_k below 1 fails validation."""
        from potato.server_utils.config_module import (
            _validate_option_highlighting_config,
            ConfigValidationError
        )

        config = {"top_k": 0}

        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_option_highlighting_config(config)

        assert "top_k" in str(exc_info.value)

    def test_invalid_top_k_too_high(self):
        """Test that top_k above 10 fails validation."""
        from potato.server_utils.config_module import (
            _validate_option_highlighting_config,
            ConfigValidationError
        )

        config = {"top_k": 15}

        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_option_highlighting_config(config)

        assert "top_k" in str(exc_info.value)

    def test_invalid_dim_opacity_too_low(self):
        """Test that dim_opacity below 0.1 fails validation."""
        from potato.server_utils.config_module import (
            _validate_option_highlighting_config,
            ConfigValidationError
        )

        config = {"dim_opacity": 0.05}

        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_option_highlighting_config(config)

        assert "dim_opacity" in str(exc_info.value)

    def test_invalid_dim_opacity_too_high(self):
        """Test that dim_opacity above 0.9 fails validation."""
        from potato.server_utils.config_module import (
            _validate_option_highlighting_config,
            ConfigValidationError
        )

        config = {"dim_opacity": 0.95}

        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_option_highlighting_config(config)

        assert "dim_opacity" in str(exc_info.value)

    def test_invalid_enabled_type(self):
        """Test that non-boolean enabled fails validation."""
        from potato.server_utils.config_module import (
            _validate_option_highlighting_config,
            ConfigValidationError
        )

        config = {"enabled": "yes"}

        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_option_highlighting_config(config)

        assert "enabled" in str(exc_info.value)

    def test_invalid_auto_apply_type(self):
        """Test that non-boolean auto_apply fails validation."""
        from potato.server_utils.config_module import (
            _validate_option_highlighting_config,
            ConfigValidationError
        )

        config = {"auto_apply": "true"}

        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_option_highlighting_config(config)

        assert "auto_apply" in str(exc_info.value)

    def test_schemas_null_valid(self):
        """Test that schemas: null is valid."""
        from potato.server_utils.config_module import _validate_option_highlighting_config

        config = {"schemas": None}

        # Should not raise
        _validate_option_highlighting_config(config)

    def test_schemas_list_valid(self):
        """Test that schemas as list of strings is valid."""
        from potato.server_utils.config_module import _validate_option_highlighting_config

        config = {"schemas": ["sentiment", "topic"]}

        # Should not raise
        _validate_option_highlighting_config(config)

    def test_invalid_schemas_not_list(self):
        """Test that schemas as non-list fails validation."""
        from potato.server_utils.config_module import (
            _validate_option_highlighting_config,
            ConfigValidationError
        )

        config = {"schemas": "sentiment"}

        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_option_highlighting_config(config)

        assert "schemas" in str(exc_info.value)

    def test_invalid_schemas_contains_non_string(self):
        """Test that schemas with non-string elements fails validation."""
        from potato.server_utils.config_module import (
            _validate_option_highlighting_config,
            ConfigValidationError
        )

        config = {"schemas": ["sentiment", 123]}

        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_option_highlighting_config(config)

        assert "schemas" in str(exc_info.value)

    def test_invalid_prefetch_count_negative(self):
        """Test that negative prefetch_count fails validation."""
        from potato.server_utils.config_module import (
            _validate_option_highlighting_config,
            ConfigValidationError
        )

        config = {"prefetch_count": -5}

        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_option_highlighting_config(config)

        assert "prefetch_count" in str(exc_info.value)

    def test_invalid_prefetch_count_too_high(self):
        """Test that prefetch_count above 100 fails validation."""
        from potato.server_utils.config_module import (
            _validate_option_highlighting_config,
            ConfigValidationError
        )

        config = {"prefetch_count": 150}

        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_option_highlighting_config(config)

        assert "prefetch_count" in str(exc_info.value)


class TestOptionHighlightingSchemaCheck:
    """Test schema eligibility checking for option highlighting."""

    def test_discrete_types_eligible(self):
        """Test that discrete annotation types are eligible."""
        # Mock the config and AiCacheManager
        mock_config = {
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "test_radio"},
                {"annotation_type": "multiselect", "name": "test_multi"},
                {"annotation_type": "likert", "name": "test_likert"},
                {"annotation_type": "select", "name": "test_select"},
            ]
        }

        with patch('potato.ai.ai_cache.config', mock_config):
            from potato.ai.ai_cache import AiCacheManager

            # Create a minimal mock manager
            manager = MagicMock(spec=AiCacheManager)
            manager.option_highlighting_enabled = True
            manager.option_highlighting_schemas = None

            # Bind the method from the real class
            manager.is_option_highlighting_enabled_for_scheme = (
                lambda annotation_id: AiCacheManager.is_option_highlighting_enabled_for_scheme(manager, annotation_id)
            )

            # All discrete types should be eligible
            with patch('potato.ai.ai_cache.config', mock_config):
                assert manager.is_option_highlighting_enabled_for_scheme(0)  # radio
                assert manager.is_option_highlighting_enabled_for_scheme(1)  # multiselect
                assert manager.is_option_highlighting_enabled_for_scheme(2)  # likert
                assert manager.is_option_highlighting_enabled_for_scheme(3)  # select

    def test_non_discrete_types_not_eligible(self):
        """Test that non-discrete annotation types are not eligible."""
        mock_config = {
            "annotation_schemes": [
                {"annotation_type": "span", "name": "test_span"},
                {"annotation_type": "textbox", "name": "test_textbox"},
                {"annotation_type": "slider", "name": "test_slider"},
            ]
        }

        with patch('potato.ai.ai_cache.config', mock_config):
            from potato.ai.ai_cache import AiCacheManager

            manager = MagicMock(spec=AiCacheManager)
            manager.option_highlighting_enabled = True
            manager.option_highlighting_schemas = None

            manager.is_option_highlighting_enabled_for_scheme = (
                lambda annotation_id: AiCacheManager.is_option_highlighting_enabled_for_scheme(manager, annotation_id)
            )

            # Non-discrete types should not be eligible
            with patch('potato.ai.ai_cache.config', mock_config):
                assert not manager.is_option_highlighting_enabled_for_scheme(0)  # span
                assert not manager.is_option_highlighting_enabled_for_scheme(1)  # textbox
                assert not manager.is_option_highlighting_enabled_for_scheme(2)  # slider

    def test_schemas_filter_applied(self):
        """Test that schemas filter limits which schemas get highlighting."""
        mock_config = {
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "sentiment"},
                {"annotation_type": "radio", "name": "topic"},
                {"annotation_type": "radio", "name": "other"},
            ]
        }

        with patch('potato.ai.ai_cache.config', mock_config):
            from potato.ai.ai_cache import AiCacheManager

            manager = MagicMock(spec=AiCacheManager)
            manager.option_highlighting_enabled = True
            manager.option_highlighting_schemas = ["sentiment", "topic"]

            manager.is_option_highlighting_enabled_for_scheme = (
                lambda annotation_id: AiCacheManager.is_option_highlighting_enabled_for_scheme(manager, annotation_id)
            )

            with patch('potato.ai.ai_cache.config', mock_config):
                assert manager.is_option_highlighting_enabled_for_scheme(0)  # sentiment - in filter
                assert manager.is_option_highlighting_enabled_for_scheme(1)  # topic - in filter
                assert not manager.is_option_highlighting_enabled_for_scheme(2)  # other - not in filter


class TestOptionHighlightPrompt:
    """Test that the option highlight prompt is properly loaded."""

    def test_prompt_file_exists(self):
        """Test that the option_highlight.json prompt file exists."""
        import os
        from pathlib import Path

        prompt_dir = Path(__file__).parent.parent.parent / "potato" / "ai" / "prompt"
        prompt_file = prompt_dir / "option_highlight.json"

        assert prompt_file.exists(), f"Prompt file not found: {prompt_file}"

    def test_prompt_file_valid_json(self):
        """Test that the prompt file contains valid JSON."""
        import json
        from pathlib import Path

        prompt_dir = Path(__file__).parent.parent.parent / "potato" / "ai" / "prompt"
        prompt_file = prompt_dir / "option_highlight.json"

        with open(prompt_file) as f:
            data = json.load(f)

        assert "option_highlight" in data
        assert "prompt" in data["option_highlight"]
        assert "output_format" in data["option_highlight"]

    def test_prompt_has_required_variables(self):
        """Test that the prompt template has required variables."""
        import json
        from pathlib import Path

        prompt_dir = Path(__file__).parent.parent.parent / "potato" / "ai" / "prompt"
        prompt_file = prompt_dir / "option_highlight.json"

        with open(prompt_file) as f:
            data = json.load(f)

        prompt = data["option_highlight"]["prompt"]

        # Check for required template variables
        assert "${text}" in prompt, "Prompt must include ${text} variable"
        assert "${description}" in prompt, "Prompt must include ${description} variable"
        assert "${labels}" in prompt, "Prompt must include ${labels} variable"
        assert "${top_k}" in prompt, "Prompt must include ${top_k} variable"


class TestGetOptionHighlightingConfig:
    """Test the get_option_highlighting_config method."""

    def test_returns_correct_structure(self):
        """Test that get_option_highlighting_config returns expected structure."""
        from potato.ai.ai_cache import AiCacheManager

        manager = MagicMock(spec=AiCacheManager)
        manager.option_highlighting_enabled = True
        manager.option_highlighting_top_k = 3
        manager.option_highlighting_dim_opacity = 0.4
        manager.option_highlighting_auto_apply = True
        manager.option_highlighting_schemas = ["sentiment"]
        manager.option_highlighting_prefetch_count = 20

        manager.get_option_highlighting_config = (
            lambda: AiCacheManager.get_option_highlighting_config(manager)
        )

        result = manager.get_option_highlighting_config()

        assert result["enabled"] is True
        assert result["top_k"] == 3
        assert result["dim_opacity"] == 0.4
        assert result["auto_apply"] is True
        assert result["schemas"] == ["sentiment"]
        assert result["prefetch_count"] == 20

    def test_returns_disabled_when_not_enabled(self):
        """Test config when option highlighting is disabled."""
        from potato.ai.ai_cache import AiCacheManager

        manager = MagicMock(spec=AiCacheManager)
        manager.option_highlighting_enabled = False
        manager.option_highlighting_top_k = 3
        manager.option_highlighting_dim_opacity = 0.4
        manager.option_highlighting_auto_apply = True
        manager.option_highlighting_schemas = None
        manager.option_highlighting_prefetch_count = 20

        manager.get_option_highlighting_config = (
            lambda: AiCacheManager.get_option_highlighting_config(manager)
        )

        result = manager.get_option_highlighting_config()

        assert result["enabled"] is False
