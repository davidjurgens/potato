"""
Unit tests for format handler registry.
"""

import pytest
from unittest.mock import MagicMock, patch

from potato.format_handlers.base import BaseFormatHandler, FormatOutput
from potato.format_handlers.registry import FormatHandlerRegistry


class MockHandler(BaseFormatHandler):
    """Mock handler for testing."""

    format_name = "mock"
    supported_extensions = [".mock", ".mck"]
    description = "Mock format handler"
    requires_dependencies = []

    def extract(self, file_path, options=None):
        return FormatOutput(
            text="mock content",
            rendered_html="<p>mock</p>",
            format_name=self.format_name,
            source_path=file_path
        )


class AnotherMockHandler(BaseFormatHandler):
    """Another mock handler for testing."""

    format_name = "another"
    supported_extensions = [".another"]
    description = "Another mock handler"
    requires_dependencies = ["nonexistent"]

    def extract(self, file_path, options=None):
        return FormatOutput(text="", rendered_html="")


class TestFormatHandlerRegistry:
    """Tests for FormatHandlerRegistry."""

    @pytest.fixture
    def registry(self):
        """Create a fresh registry for each test."""
        return FormatHandlerRegistry()

    @pytest.fixture
    def handler(self):
        """Create a mock handler."""
        return MockHandler()

    def test_register_handler(self, registry, handler):
        """Test registering a handler."""
        registry.register(handler)

        assert registry.is_registered("mock")
        assert "mock" in registry.get_supported_formats()

    def test_register_duplicate_raises(self, registry, handler):
        """Test registering duplicate handler raises error."""
        registry.register(handler)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(handler)

    def test_unregister_handler(self, registry, handler):
        """Test unregistering a handler."""
        registry.register(handler)
        result = registry.unregister("mock")

        assert result is True
        assert not registry.is_registered("mock")

    def test_unregister_nonexistent(self, registry):
        """Test unregistering non-existent handler."""
        result = registry.unregister("nonexistent")
        assert result is False

    def test_get_handler(self, registry, handler):
        """Test getting handler by name."""
        registry.register(handler)
        result = registry.get_handler("mock")

        assert result is handler

    def test_get_handler_nonexistent(self, registry):
        """Test getting non-existent handler."""
        result = registry.get_handler("nonexistent")
        assert result is None

    def test_get_handler_for_file(self, registry, handler):
        """Test getting handler for file path."""
        registry.register(handler)

        result = registry.get_handler_for_file("document.mock")
        assert result is handler

        result = registry.get_handler_for_file("document.mck")
        assert result is handler

    def test_get_handler_for_file_case_insensitive(self, registry, handler):
        """Test file extension matching is case insensitive."""
        registry.register(handler)

        result = registry.get_handler_for_file("document.MOCK")
        assert result is handler

    def test_get_handler_for_file_unsupported(self, registry, handler):
        """Test getting handler for unsupported file."""
        registry.register(handler)

        result = registry.get_handler_for_file("document.pdf")
        assert result is None

    def test_detect_format(self, registry, handler):
        """Test format detection from file path."""
        registry.register(handler)

        result = registry.detect_format("document.mock")
        assert result == "mock"

        result = registry.detect_format("document.unknown")
        assert result is None

    def test_can_handle(self, registry, handler):
        """Test can_handle method."""
        registry.register(handler)

        assert registry.can_handle("document.mock") is True
        assert registry.can_handle("document.pdf") is False

    def test_extract_success(self, registry, handler, tmp_path):
        """Test successful extraction."""
        registry.register(handler)

        test_file = tmp_path / "test.mock"
        test_file.write_text("content")

        result = registry.extract(str(test_file))

        assert isinstance(result, FormatOutput)
        assert result.text == "mock content"

    def test_extract_with_format_override(self, registry, handler, tmp_path):
        """Test extraction with format name override still validates extension."""
        registry.register(handler)

        test_file = tmp_path / "test.txt"  # Wrong extension
        test_file.write_text("content")

        # Even with format override, the handler validates the file extension
        # This is by design - to ensure file compatibility
        with pytest.raises(ValueError, match="Unsupported extension"):
            registry.extract(str(test_file), format_name="mock")

    def test_extract_with_correct_extension(self, registry, handler, tmp_path):
        """Test extraction with correct extension."""
        registry.register(handler)

        test_file = tmp_path / "test.mock"
        test_file.write_text("content")

        result = registry.extract(str(test_file), format_name="mock")

        assert isinstance(result, FormatOutput)
        assert result.text == "mock content"

    def test_extract_no_handler_raises(self, registry, tmp_path):
        """Test extraction with no handler raises error."""
        test_file = tmp_path / "test.unknown"
        test_file.write_text("content")

        with pytest.raises(ValueError, match="No handler"):
            registry.extract(str(test_file))

    def test_extract_file_not_found_raises(self, registry, handler):
        """Test extraction of non-existent file raises error."""
        registry.register(handler)

        with pytest.raises(ValueError, match="not found"):
            registry.extract("/nonexistent/file.mock")

    def test_get_supported_formats(self, registry):
        """Test getting supported formats list."""
        registry.register(MockHandler())
        registry.register(AnotherMockHandler())

        formats = registry.get_supported_formats()

        assert "mock" in formats
        assert "another" in formats
        assert formats == sorted(formats)  # Should be sorted

    def test_get_supported_extensions(self, registry, handler):
        """Test getting supported extensions list."""
        registry.register(handler)

        extensions = registry.get_supported_extensions()

        assert ".mock" in extensions
        assert ".mck" in extensions

    def test_list_handlers(self, registry):
        """Test listing all handlers."""
        registry.register(MockHandler())
        registry.register(AnotherMockHandler())

        handlers = registry.list_handlers()

        assert len(handlers) == 2

        mock_info = next(h for h in handlers if h["name"] == "mock")
        assert mock_info["description"] == "Mock format handler"
        assert mock_info["extensions"] == [".mock", ".mck"]
        assert mock_info["available"] is True

        another_info = next(h for h in handlers if h["name"] == "another")
        assert another_info["available"] is False
        assert "nonexistent" in another_info["missing_dependencies"]

    def test_extension_override_warning(self, registry, caplog):
        """Test warning when extension is overridden."""
        handler1 = MockHandler()
        handler1.format_name = "handler1"

        handler2 = MockHandler()
        handler2.format_name = "handler2"

        registry.register(handler1)

        import logging
        with caplog.at_level(logging.WARNING):
            registry.register(handler2)

        # Should have logged a warning about extension override
        assert any("override" in record.message.lower() or "already mapped" in record.message.lower()
                   for record in caplog.records)
