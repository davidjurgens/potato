"""
Tests for get_displayed_text function in flask_server.py.

These tests verify that the function correctly handles:
- String inputs (normalization)
- List inputs (pairwise comparisons)
- Various list_as_text configurations
"""

import pytest
from unittest.mock import patch, MagicMock


class TestGetDisplayedTextString:
    """Test get_displayed_text with string inputs."""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        """Mock the config module for testing."""
        mock_config = MagicMock()
        mock_config.get.return_value = {}
        with patch('potato.flask_server.config', mock_config):
            yield mock_config

    def test_simple_string_returned(self, mock_config):
        """Basic string input should be returned normalized."""
        from potato.flask_server import get_displayed_text

        result = get_displayed_text("Hello world")
        assert result == "Hello world"

    def test_string_whitespace_normalized(self, mock_config):
        """Multiple spaces should be normalized to single space."""
        from potato.flask_server import get_displayed_text

        result = get_displayed_text("Hello    world")
        assert result == "Hello world"

    def test_string_tabs_removed(self, mock_config):
        """Tabs (non-printable) are removed by the normalization regex."""
        from potato.flask_server import get_displayed_text

        result = get_displayed_text("Hello\tworld")
        # Tabs are outside the printable range (0x20-0x7E) so they're removed
        assert result == "Helloworld"

    def test_string_stripped(self, mock_config):
        """Leading/trailing whitespace should be stripped."""
        from potato.flask_server import get_displayed_text

        result = get_displayed_text("  Hello world  ")
        assert result == "Hello world"

    def test_non_printable_removed(self, mock_config):
        """Non-printable characters should be removed."""
        from potato.flask_server import get_displayed_text

        result = get_displayed_text("Hello\x00world")
        assert result == "Helloworld"

    def test_newlines_preserved_by_default(self, mock_config):
        """Newlines should be preserved by default."""
        from potato.flask_server import get_displayed_text

        result = get_displayed_text("Hello\nworld")
        assert "\n" in result or result == "Hello\nworld"

    def test_highlight_linebreaks_converts_newlines(self, mock_config):
        """With highlight_linebreaks=True, newlines become <br/>."""
        mock_config.get.side_effect = lambda key, default=None: {
            "highlight_linebreaks": True,
            "list_as_text": {}
        }.get(key, default)

        from potato.flask_server import get_displayed_text

        result = get_displayed_text("Hello\nworld")
        assert "<br/>" in result


class TestGetDisplayedTextList:
    """Test get_displayed_text with list inputs (pairwise comparisons)."""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        """Mock the config module for testing."""
        mock_config = MagicMock()
        mock_config.get.return_value = {}
        with patch('potato.flask_server.config', mock_config):
            yield mock_config

    def test_list_with_alphabet_prefix_default(self, mock_config):
        """List input should use alphabet prefix by default."""
        mock_config.get.side_effect = lambda key, default=None: {
            "list_as_text": {},  # Empty config uses alphabet default
            "highlight_linebreaks": False
        }.get(key, default)

        from potato.flask_server import get_displayed_text

        result = get_displayed_text(["First item", "Second item"])

        assert "<b>A.</b>" in result
        assert "<b>B.</b>" in result
        assert "First item" in result
        assert "Second item" in result

    def test_list_with_explicit_alphabet_prefix(self, mock_config):
        """List with explicit alphabet prefix type."""
        mock_config.get.side_effect = lambda key, default=None: {
            "list_as_text": {"text_list_prefix_type": "alphabet"},
            "highlight_linebreaks": False
        }.get(key, default)

        from potato.flask_server import get_displayed_text

        result = get_displayed_text(["A", "B", "C"])

        assert "<b>A.</b>" in result
        assert "<b>B.</b>" in result
        assert "<b>C.</b>" in result

    def test_list_with_number_prefix(self, mock_config):
        """List with number prefix type."""
        mock_config.get.side_effect = lambda key, default=None: {
            "list_as_text": {"text_list_prefix_type": "number"},
            "highlight_linebreaks": False
        }.get(key, default)

        from potato.flask_server import get_displayed_text

        result = get_displayed_text(["First", "Second", "Third"])

        assert "<b>1.</b>" in result
        assert "<b>2.</b>" in result
        assert "<b>3.</b>" in result

    def test_list_items_separated_by_br(self, mock_config):
        """List items should be separated by <br/><br/>."""
        mock_config.get.side_effect = lambda key, default=None: {
            "list_as_text": {},
            "highlight_linebreaks": False
        }.get(key, default)

        from potato.flask_server import get_displayed_text

        result = get_displayed_text(["First", "Second"])

        assert "<br/><br/>" in result

    def test_empty_list(self, mock_config):
        """Empty list should return empty string."""
        mock_config.get.side_effect = lambda key, default=None: {
            "list_as_text": {},
            "highlight_linebreaks": False
        }.get(key, default)

        from potato.flask_server import get_displayed_text

        result = get_displayed_text([])

        assert result == ""

    def test_single_item_list(self, mock_config):
        """Single item list should work without separator."""
        mock_config.get.side_effect = lambda key, default=None: {
            "list_as_text": {},
            "highlight_linebreaks": False
        }.get(key, default)

        from potato.flask_server import get_displayed_text

        result = get_displayed_text(["Only item"])

        assert "<b>A.</b>" in result
        assert "Only item" in result
        assert "<br/><br/>" not in result

    def test_list_with_non_string_items(self, mock_config):
        """List containing integers should convert to strings."""
        mock_config.get.side_effect = lambda key, default=None: {
            "list_as_text": {},
            "highlight_linebreaks": False
        }.get(key, default)

        from potato.flask_server import get_displayed_text

        result = get_displayed_text([123, 456])

        assert "123" in result
        assert "456" in result

    def test_list_items_normalized(self, mock_config):
        """Items within list should have whitespace normalized."""
        mock_config.get.side_effect = lambda key, default=None: {
            "list_as_text": {},
            "highlight_linebreaks": False
        }.get(key, default)

        from potato.flask_server import get_displayed_text

        result = get_displayed_text(["Hello    world", "Foo   bar"])

        # Items should be normalized
        assert "Hello world" in result
        assert "Foo bar" in result

    def test_unknown_prefix_type_defaults_to_alphabet(self, mock_config):
        """Unknown prefix type should fall back to alphabet."""
        mock_config.get.side_effect = lambda key, default=None: {
            "list_as_text": {"text_list_prefix_type": "unknown_type"},
            "highlight_linebreaks": False
        }.get(key, default)

        from potato.flask_server import get_displayed_text

        result = get_displayed_text(["First", "Second"])

        # Should use alphabet as fallback
        assert "<b>A.</b>" in result
        assert "<b>B.</b>" in result


class TestGetDisplayedTextEdgeCases:
    """Edge case tests for get_displayed_text."""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        """Mock the config module for testing."""
        mock_config = MagicMock()
        mock_config.get.return_value = {}
        with patch('potato.flask_server.config', mock_config):
            yield mock_config

    def test_empty_string(self, mock_config):
        """Empty string should return empty string."""
        from potato.flask_server import get_displayed_text

        result = get_displayed_text("")
        assert result == ""

    def test_whitespace_only_string(self, mock_config):
        """Whitespace-only string should return empty after strip."""
        from potato.flask_server import get_displayed_text

        result = get_displayed_text("   ")
        assert result == ""

    def test_long_list(self, mock_config):
        """List with many items should work (test alphabet wrapping)."""
        mock_config.get.side_effect = lambda key, default=None: {
            "list_as_text": {},
            "highlight_linebreaks": False
        }.get(key, default)

        from potato.flask_server import get_displayed_text

        items = [f"Item {i}" for i in range(5)]
        result = get_displayed_text(items)

        assert "<b>A.</b>" in result
        assert "<b>E.</b>" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
