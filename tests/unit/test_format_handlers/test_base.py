"""
Unit tests for format handler base classes.
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from potato.format_handlers.base import BaseFormatHandler, FormatOutput


class TestFormatOutput:
    """Tests for FormatOutput dataclass."""

    def test_init_minimal(self):
        """Test creating FormatOutput with minimal data."""
        output = FormatOutput(text="Hello", rendered_html="<p>Hello</p>")

        assert output.text == "Hello"
        assert output.rendered_html == "<p>Hello</p>"
        assert output.coordinate_map == {}
        assert output.metadata == {}
        assert output.format_name == ""
        assert output.source_path == ""

    def test_init_full(self):
        """Test creating FormatOutput with all fields."""
        coord_map = {"mappings": []}
        metadata = {"pages": 5, "format": "pdf"}

        output = FormatOutput(
            text="Content",
            rendered_html="<div>Content</div>",
            coordinate_map=coord_map,
            metadata=metadata,
            format_name="pdf",
            source_path="/path/to/file.pdf"
        )

        assert output.text == "Content"
        assert output.rendered_html == "<div>Content</div>"
        assert output.coordinate_map == coord_map
        assert output.metadata == metadata
        assert output.format_name == "pdf"
        assert output.source_path == "/path/to/file.pdf"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        output = FormatOutput(
            text="Test",
            rendered_html="<p>Test</p>",
            metadata={"key": "value"},
            format_name="test",
            source_path="/test/path"
        )

        result = output.to_dict()

        assert result["text"] == "Test"
        assert result["rendered_html"] == "<p>Test</p>"
        assert result["metadata"] == {"key": "value"}
        assert result["format_name"] == "test"
        assert result["source_path"] == "/test/path"

    def test_get_format_coords_empty(self):
        """Test getting coordinates with empty map."""
        output = FormatOutput(text="", rendered_html="")
        result = output.get_format_coords(0, 10)
        assert result is None

    def test_get_format_coords_with_callback(self):
        """Test getting coordinates with callback function."""
        def mock_get_coords(start, end):
            return {"format": "test", "start": start, "end": end}

        output = FormatOutput(
            text="Test content",
            rendered_html="<p>Test</p>",
            coordinate_map={"get_coords_for_range": mock_get_coords}
        )

        result = output.get_format_coords(5, 10)
        assert result == {"format": "test", "start": 5, "end": 10}


class ConcreteHandler(BaseFormatHandler):
    """Concrete implementation for testing."""

    format_name = "test"
    supported_extensions = [".test", ".tst"]
    description = "Test handler"
    requires_dependencies = []

    def extract(self, file_path, options=None):
        return FormatOutput(
            text="extracted",
            rendered_html="<p>extracted</p>",
            format_name=self.format_name,
            source_path=str(file_path)
        )


class TestBaseFormatHandler:
    """Tests for BaseFormatHandler ABC."""

    @pytest.fixture
    def handler(self):
        """Create a concrete handler instance."""
        return ConcreteHandler()

    def test_can_handle_supported_extension(self, handler):
        """Test can_handle returns True for supported extensions."""
        assert handler.can_handle("document.test") is True
        assert handler.can_handle("document.tst") is True
        assert handler.can_handle("/path/to/file.TEST") is True

    def test_can_handle_unsupported_extension(self, handler):
        """Test can_handle returns False for unsupported extensions."""
        assert handler.can_handle("document.pdf") is False
        assert handler.can_handle("document.txt") is False
        assert handler.can_handle("document") is False

    def test_check_dependencies_all_present(self, handler):
        """Test check_dependencies with no missing deps."""
        handler.requires_dependencies = []
        missing = handler.check_dependencies()
        assert missing == []

    def test_check_dependencies_missing(self, handler):
        """Test check_dependencies with missing deps."""
        handler.requires_dependencies = ["nonexistent_package_xyz"]
        missing = handler.check_dependencies()
        assert "nonexistent_package_xyz" in missing

    def test_validate_file_not_exists(self, handler, tmp_path):
        """Test validation fails for non-existent file."""
        errors = handler.validate_file("/nonexistent/path/file.test")
        assert any("not found" in e.lower() for e in errors)

    def test_validate_file_wrong_extension(self, handler, tmp_path):
        """Test validation fails for wrong extension."""
        test_file = tmp_path / "file.wrong"
        test_file.touch()

        errors = handler.validate_file(str(test_file))
        assert any("unsupported" in e.lower() for e in errors)

    def test_validate_file_success(self, handler, tmp_path):
        """Test validation passes for valid file."""
        test_file = tmp_path / "file.test"
        test_file.touch()

        errors = handler.validate_file(str(test_file))
        assert errors == []

    def test_get_default_options(self, handler):
        """Test default options are returned."""
        defaults = handler.get_default_options()
        assert isinstance(defaults, dict)
        assert "preserve_layout" in defaults
        assert "max_pages" in defaults
        assert "encoding" in defaults

    def test_merge_options_none(self, handler):
        """Test merge_options with None."""
        result = handler.merge_options(None)
        defaults = handler.get_default_options()
        assert result == defaults

    def test_merge_options_override(self, handler):
        """Test merge_options overrides defaults."""
        options = {"preserve_layout": True, "custom_option": "value"}
        result = handler.merge_options(options)

        assert result["preserve_layout"] is True
        assert result["custom_option"] == "value"
        assert "max_pages" in result  # Default preserved

    def test_extract_returns_format_output(self, handler, tmp_path):
        """Test extract returns FormatOutput."""
        test_file = tmp_path / "file.test"
        test_file.write_text("content")

        result = handler.extract(str(test_file))

        assert isinstance(result, FormatOutput)
        assert result.text == "extracted"
        assert result.format_name == "test"
