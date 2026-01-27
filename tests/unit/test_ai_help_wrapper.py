"""
Unit tests for AI help wrapper module.

Tests the ai_help_wrapper.py module which provides the AI assistant
HTML rendering functionality.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestGenerateAIHelpHTML:
    """Test the generate_ai_help_html function."""

    def test_returns_empty_string_when_ai_disabled(self):
        """Test that generate_ai_help_html returns empty string when DYNAMICAIHELP is None.

        This is the critical bug fix test - when AI support is disabled,
        DYNAMICAIHELP is None and calling generate_ai_help_html should not crash.
        """
        # Import with DYNAMICAIHELP as None (default state)
        from potato.ai.ai_help_wrapper import generate_ai_help_html, DYNAMICAIHELP

        # Verify DYNAMICAIHELP is None when not initialized
        assert DYNAMICAIHELP is None

        # Should return empty string, not crash
        result = generate_ai_help_html(instance=1, annotation_id=0, annotation_type="radio")
        assert result == ""

    def test_returns_html_when_ai_enabled(self):
        """Test that generate_ai_help_html returns HTML when AI is enabled."""
        from potato.ai import ai_help_wrapper

        # Create a mock DYNAMICAIHELP
        mock_helper = MagicMock()
        mock_helper.render.return_value = "<div>AI Help</div>"

        # Patch the global
        original = ai_help_wrapper.DYNAMICAIHELP
        ai_help_wrapper.DYNAMICAIHELP = mock_helper

        try:
            result = ai_help_wrapper.generate_ai_help_html(
                instance=1, annotation_id=0, annotation_type="radio"
            )
            assert result == "<div>AI Help</div>"
            mock_helper.render.assert_called_once_with(1, 0, "radio")
        finally:
            # Restore original state
            ai_help_wrapper.DYNAMICAIHELP = original


class TestGetAIWrapper:
    """Test the get_ai_wrapper function."""

    def test_returns_empty_string_when_helper_none(self):
        """Test get_ai_wrapper returns empty string when helper is None."""
        from potato.ai.ai_help_wrapper import get_ai_wrapper, DYNAMICAIHELP

        # When DYNAMICAIHELP is None
        assert DYNAMICAIHELP is None
        result = get_ai_wrapper()
        assert result == ""

    def test_returns_wrapper_html_when_helper_exists(self):
        """Test get_ai_wrapper returns wrapper HTML when helper exists."""
        from potato.ai import ai_help_wrapper

        # Create a mock helper
        mock_helper = MagicMock()
        mock_helper.get_empty_wrapper.return_value = '<div class="ai-help"></div>'

        original = ai_help_wrapper.DYNAMICAIHELP
        ai_help_wrapper.DYNAMICAIHELP = mock_helper

        try:
            result = ai_help_wrapper.get_ai_wrapper()
            assert result == '<div class="ai-help"></div>'
        finally:
            ai_help_wrapper.DYNAMICAIHELP = original


class TestInitDynamicAIHelp:
    """Test the init_dynamic_ai_help function."""

    @patch('potato.ai.ai_help_wrapper.config', {'ai_support': {'enabled': False}})
    def test_does_not_initialize_when_disabled(self):
        """Test that init doesn't create helper when AI support is disabled."""
        from potato.ai import ai_help_wrapper

        original = ai_help_wrapper.DYNAMICAIHELP
        ai_help_wrapper.DYNAMICAIHELP = None

        try:
            result = ai_help_wrapper.init_dynamic_ai_help()
            assert result is None
            assert ai_help_wrapper.DYNAMICAIHELP is None
        finally:
            ai_help_wrapper.DYNAMICAIHELP = original


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
