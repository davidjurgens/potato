"""
Unit tests for format display components.
"""

import pytest
from unittest.mock import MagicMock, patch

from potato.server_utils.displays.pdf_display import PDFDisplay
from potato.server_utils.displays.document_display import DocumentDisplay
from potato.server_utils.displays.spreadsheet_display import SpreadsheetDisplay
from potato.server_utils.displays.code_display import CodeDisplay


class TestPDFDisplay:
    """Tests for PDFDisplay component."""

    @pytest.fixture
    def display(self):
        return PDFDisplay()

    def test_name(self, display):
        """Test display name."""
        assert display.name == "pdf"

    def test_supports_span_target(self, display):
        """Test span target support."""
        assert display.supports_span_target is True

    def test_render_file_path(self, display):
        """Test rendering with file path."""
        field_config = {"key": "document", "type": "pdf"}
        html = display.render(field_config, "/path/to/document.pdf")

        assert "pdf-display" in html
        assert "/path/to/document.pdf" in html
        assert "pdf-canvas" in html

    def test_render_extracted_content(self, display):
        """Test rendering with pre-extracted content."""
        field_config = {"key": "document", "type": "pdf"}
        data = {
            "text": "Extracted text",
            "rendered_html": "<div>Content</div>",
            "metadata": {"total_pages": 5}
        }
        html = display.render(field_config, data)

        assert "pdf-extracted" in html
        assert "Content" in html
        assert "Pages: 5" in html

    def test_render_with_options(self, display):
        """Test rendering with display options."""
        field_config = {
            "key": "document",
            "type": "pdf",
            "display_options": {
                "view_mode": "paginated",
                "max_height": 500,
                "text_layer": False
            }
        }
        html = display.render(field_config, "/path/to/doc.pdf")

        assert "paginated" in html or "view-mode" in html.lower()
        assert "500" in html

    def test_validate_config_valid(self, display):
        """Test config validation with valid config."""
        config = {"key": "document", "type": "pdf"}
        errors = display.validate_config(config)
        assert errors == []

    def test_validate_config_invalid_view_mode(self, display):
        """Test config validation with invalid view_mode."""
        config = {
            "key": "document",
            "type": "pdf",
            "display_options": {"view_mode": "invalid"}
        }
        errors = display.validate_config(config)
        assert any("view_mode" in e.lower() for e in errors)

    def test_get_css_classes(self, display):
        """Test CSS class generation."""
        config = {"key": "doc", "span_target": True}
        classes = display.get_css_classes(config)

        assert "display-type-pdf" in classes
        assert "span-target-pdf" in classes

    def test_render_bounding_box_mode(self, display):
        """Test rendering PDF in bounding box annotation mode."""
        field_config = {
            "key": "document",
            "type": "pdf",
            "display_options": {
                "annotation_mode": "bounding_box",
                "view_mode": "paginated"
            }
        }
        html = display.render(field_config, "/path/to/document.pdf")

        assert "pdf-bbox-mode" in html
        assert "pdf-bbox-canvas" in html
        assert "pdf-bbox-draw-btn" in html
        assert "pdf-bbox-select-btn" in html

    def test_render_bounding_box_with_extracted_content(self, display):
        """Test rendering pre-extracted PDF content in bbox mode."""
        field_config = {
            "key": "document",
            "type": "pdf",
            "display_options": {
                "annotation_mode": "bounding_box"
            }
        }
        data = {
            "text": "Page content",
            "rendered_html": "<div class='pdf-page'>Content</div>",
            "metadata": {"total_pages": 3}
        }
        html = display.render(field_config, data)

        assert "pdf-bbox-mode" in html
        assert "pdf-bbox-tools" in html

    def test_validate_config_bbox_mode(self, display):
        """Test config validation for bounding box mode."""
        config = {
            "key": "document",
            "type": "pdf",
            "display_options": {
                "annotation_mode": "bounding_box"
            }
        }
        errors = display.validate_config(config)
        assert errors == []

    def test_validate_config_invalid_annotation_mode(self, display):
        """Test config validation with invalid annotation mode."""
        config = {
            "key": "document",
            "type": "pdf",
            "display_options": {
                "annotation_mode": "invalid_mode"
            }
        }
        errors = display.validate_config(config)
        assert any("annotation_mode" in e.lower() for e in errors)

    def test_get_css_classes_bbox_mode(self, display):
        """Test CSS classes include bbox mode class."""
        config = {
            "key": "doc",
            "display_options": {
                "annotation_mode": "bounding_box"
            }
        }
        classes = display.get_css_classes(config)

        assert "pdf-bbox-annotation" in classes


class TestDocumentDisplay:
    """Tests for DocumentDisplay component."""

    @pytest.fixture
    def display(self):
        return DocumentDisplay()

    def test_render_bounding_box_mode(self, display):
        """Test rendering document in bounding box mode."""
        field_config = {
            "key": "doc",
            "type": "document",
            "display_options": {
                "annotation_mode": "bounding_box"
            }
        }
        html = display.render(field_config, "<p>Test content</p>")

        assert "document-bbox-mode" in html
        assert "document-bbox-canvas" in html
        assert "document-bbox-draw-btn" in html

    def test_validate_config_bbox_mode(self, display):
        """Test config validation for bounding box mode."""
        config = {
            "key": "doc",
            "type": "document",
            "display_options": {
                "annotation_mode": "bounding_box"
            }
        }
        errors = display.validate_config(config)
        assert errors == []

    def test_validate_config_invalid_annotation_mode(self, display):
        """Test config validation with invalid annotation mode."""
        config = {
            "key": "doc",
            "type": "document",
            "display_options": {
                "annotation_mode": "invalid"
            }
        }
        errors = display.validate_config(config)
        assert any("annotation_mode" in e.lower() for e in errors)

    def test_get_css_classes_bbox_mode(self, display):
        """Test CSS classes include bbox mode."""
        config = {
            "key": "doc",
            "display_options": {
                "annotation_mode": "bounding_box"
            }
        }
        classes = display.get_css_classes(config)
        assert "document-bbox-annotation" in classes

    def test_name(self, display):
        """Test display name."""
        assert display.name == "document"

    def test_supports_span_target(self, display):
        """Test span target support."""
        assert display.supports_span_target is True

    def test_render_string_content(self, display):
        """Test rendering with string content."""
        field_config = {"key": "doc", "type": "document"}
        html = display.render(field_config, "<p>Test content</p>")

        assert "document-display" in html
        assert "Test content" in html

    def test_render_format_output(self, display):
        """Test rendering with FormatOutput-style dict."""
        field_config = {"key": "doc", "type": "document"}
        data = {
            "text": "Raw text",
            "rendered_html": "<article>Formatted content</article>",
            "metadata": {"format": "docx"}
        }
        html = display.render(field_config, data)

        assert "Formatted content" in html

    def test_render_collapsible(self, display):
        """Test rendering with collapsible option."""
        field_config = {
            "key": "doc",
            "type": "document",
            "label": "My Document",
            "display_options": {"collapsible": True}
        }
        html = display.render(field_config, "Content")

        assert "<details" in html
        assert "My Document" in html

    def test_render_with_outline(self, display):
        """Test rendering with outline/TOC."""
        field_config = {
            "key": "doc",
            "type": "document",
            "display_options": {"show_outline": True}
        }
        data = {
            "rendered_html": "<p>Content</p>",
            "metadata": {
                "headings": [
                    {"level": 1, "title": "Introduction", "offset": 0},
                    {"level": 2, "title": "Details", "offset": 100}
                ]
            }
        }
        html = display.render(field_config, data)

        assert "document-outline" in html
        assert "Introduction" in html
        assert "Details" in html


class TestSpreadsheetDisplay:
    """Tests for SpreadsheetDisplay component."""

    @pytest.fixture
    def display(self):
        return SpreadsheetDisplay()

    def test_name(self, display):
        """Test display name."""
        assert display.name == "spreadsheet"

    def test_supports_span_target(self, display):
        """Test span target support."""
        assert display.supports_span_target is True

    def test_render_list_of_lists(self, display):
        """Test rendering with list of lists data."""
        field_config = {"key": "data", "type": "spreadsheet"}
        data = [
            ["A", "B", "C"],
            ["1", "2", "3"],
            ["4", "5", "6"]
        ]
        html = display.render(field_config, data)

        assert "spreadsheet-table" in html
        assert "<td" in html
        assert "A" in html
        assert "6" in html

    def test_render_list_of_dicts(self, display):
        """Test rendering with list of dicts data."""
        field_config = {"key": "data", "type": "spreadsheet"}
        data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25}
        ]
        html = display.render(field_config, data)

        assert "spreadsheet-table" in html
        assert "Alice" in html
        assert "Bob" in html

    def test_render_with_headers(self, display):
        """Test rendering with explicit headers."""
        field_config = {
            "key": "data",
            "type": "spreadsheet",
            "display_options": {"show_headers": True}
        }
        data = {
            "headers": ["Name", "Value"],
            "rows": [["Item1", "100"], ["Item2", "200"]]
        }
        html = display.render(field_config, data)

        assert "<thead>" in html
        assert "Name" in html
        assert "Value" in html

    def test_render_row_mode(self, display):
        """Test rendering in row annotation mode."""
        field_config = {
            "key": "data",
            "type": "spreadsheet",
            "display_options": {"annotation_mode": "row", "selectable": True}
        }
        data = [["A", "B"], ["C", "D"]]
        html = display.render(field_config, data)

        assert "selectable-row" in html
        assert "row-select" in html  # Checkbox

    def test_render_cell_mode(self, display):
        """Test rendering in cell annotation mode."""
        field_config = {
            "key": "data",
            "type": "spreadsheet",
            "display_options": {"annotation_mode": "cell"}
        }
        data = [["A", "B"], ["C", "D"]]
        html = display.render(field_config, data)

        assert "selectable-cell" in html
        assert "data-cell-ref" in html

    def test_cell_reference_generation(self, display):
        """Test A1-style cell reference generation."""
        ref = display._get_cell_ref(0, 0)
        assert ref == "A1"

        ref = display._get_cell_ref(4, 2)
        assert ref == "C5"


class TestCodeDisplay:
    """Tests for CodeDisplay component."""

    @pytest.fixture
    def display(self):
        return CodeDisplay()

    def test_name(self, display):
        """Test display name."""
        assert display.name == "code"

    def test_supports_span_target(self, display):
        """Test span target support."""
        assert display.supports_span_target is True

    def test_render_string_code(self, display):
        """Test rendering with string code."""
        field_config = {"key": "code", "type": "code"}
        code = "def hello():\n    print('Hello')"
        html = display.render(field_config, code)

        assert "code-display" in html
        assert "def hello()" in html or "def" in html
        assert "print" in html

    def test_render_with_line_numbers(self, display):
        """Test rendering with line numbers."""
        field_config = {
            "key": "code",
            "type": "code",
            "display_options": {"show_line_numbers": True}
        }
        code = "line1\nline2\nline3"
        html = display.render(field_config, code)

        assert "line-number" in html
        assert "1" in html
        assert "2" in html
        assert "3" in html

    def test_render_without_line_numbers(self, display):
        """Test rendering without line numbers."""
        field_config = {
            "key": "code",
            "type": "code",
            "display_options": {"show_line_numbers": False}
        }
        code = "code"
        html = display.render(field_config, code)

        # Should still have line content but might not have explicit line numbers
        assert "line-content" in html

    def test_render_with_language(self, display):
        """Test rendering with language specification."""
        field_config = {
            "key": "code",
            "type": "code",
            "display_options": {"language": "python"}
        }
        code = "print('hello')"
        html = display.render(field_config, code)

        assert "python" in html.lower()

    def test_render_with_copy_button(self, display):
        """Test rendering with copy button."""
        field_config = {
            "key": "code",
            "type": "code",
            "display_options": {"copy_button": True}
        }
        code = "code"
        html = display.render(field_config, code)

        assert "code-copy-btn" in html

    def test_render_format_output(self, display):
        """Test rendering with FormatOutput-style dict."""
        field_config = {"key": "code", "type": "code"}
        data = {
            "text": "def foo(): pass",
            "rendered_html": "<pre>highlighted code</pre>",
            "metadata": {"language": "python"}
        }
        html = display.render(field_config, data)

        assert "highlighted code" in html

    def test_get_css_classes(self, display):
        """Test CSS class generation."""
        config = {
            "key": "code",
            "display_options": {"language": "python", "theme": "dark"}
        }
        classes = display.get_css_classes(config)

        assert "display-type-code" in classes
        assert "language-python" in classes
        assert "code-theme-dark" in classes
