"""
Server-side integration tests for format display types.

Tests the complete server-side functionality for new format displays:
- PDF, Document, Spreadsheet, and Code display types
- Configuration loading and validation
- Instance display rendering with format displays
- Display registry integration
"""

import pytest
import json
import os
import sys
import uuid
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.config_module import init_config, config, ConfigValidationError
from potato.server_utils.displays import display_registry
from potato.server_utils.instance_display import InstanceDisplayRenderer, InstanceDisplayError
from tests.helpers.test_utils import cleanup_test_directory


class TestFormatDisplayRegistry:
    """Test format display types are registered correctly."""

    def test_pdf_display_registered(self):
        """Test PDF display type is registered."""
        assert display_registry.is_registered("pdf")
        display = display_registry.get("pdf")
        assert display is not None
        assert display.supports_span_target is True

    def test_document_display_registered(self):
        """Test document display type is registered."""
        assert display_registry.is_registered("document")
        display = display_registry.get("document")
        assert display is not None
        assert display.supports_span_target is True

    def test_spreadsheet_display_registered(self):
        """Test spreadsheet display type is registered."""
        assert display_registry.is_registered("spreadsheet")
        display = display_registry.get("spreadsheet")
        assert display is not None
        assert display.supports_span_target is True

    def test_code_display_registered(self):
        """Test code display type is registered."""
        assert display_registry.is_registered("code")
        display = display_registry.get("code")
        assert display is not None
        assert display.supports_span_target is True

    def test_all_format_displays_in_supported_types(self):
        """Test all format displays are in supported types list."""
        types = display_registry.get_supported_types()
        assert "pdf" in types
        assert "document" in types
        assert "spreadsheet" in types
        assert "code" in types


class TestFormatDisplayRendering:
    """Test rendering of format display types."""

    def test_pdf_render_url(self):
        """Test rendering PDF with URL."""
        field_config = {"key": "document", "type": "pdf"}
        html = display_registry.render("pdf", field_config, "/path/to/document.pdf")

        assert "pdf-display" in html
        assert "/path/to/document.pdf" in html

    def test_pdf_render_extracted_content(self):
        """Test rendering PDF with pre-extracted content."""
        field_config = {"key": "document", "type": "pdf"}
        data = {
            "text": "Extracted text content",
            "rendered_html": "<div class='pdf-page'>Page content</div>",
            "metadata": {"total_pages": 3}
        }
        html = display_registry.render("pdf", field_config, data)

        assert "pdf-extracted" in html
        assert "Page content" in html

    def test_document_render_html(self):
        """Test rendering document with HTML content."""
        field_config = {"key": "doc", "type": "document"}
        html = display_registry.render("document", field_config, "<p>Test paragraph</p>")

        assert "document-display" in html
        assert "Test paragraph" in html

    def test_document_render_format_output(self):
        """Test rendering document with FormatOutput dict."""
        field_config = {"key": "doc", "type": "document"}
        data = {
            "text": "Raw text",
            "rendered_html": "<article>Formatted document</article>",
            "metadata": {"format": "docx"}
        }
        html = display_registry.render("document", field_config, data)

        assert "Formatted document" in html

    def test_spreadsheet_render_list_of_lists(self):
        """Test rendering spreadsheet with list of lists."""
        field_config = {"key": "table", "type": "spreadsheet"}
        data = [
            ["Name", "Value"],
            ["Item1", "100"],
            ["Item2", "200"]
        ]
        html = display_registry.render("spreadsheet", field_config, data)

        assert "spreadsheet-table" in html
        assert "Item1" in html
        assert "200" in html

    def test_spreadsheet_render_dict_format(self):
        """Test rendering spreadsheet with headers/rows dict."""
        field_config = {"key": "table", "type": "spreadsheet"}
        data = {
            "headers": ["Column A", "Column B"],
            "rows": [["A1", "B1"], ["A2", "B2"]]
        }
        html = display_registry.render("spreadsheet", field_config, data)

        assert "Column A" in html
        assert "A1" in html

    def test_code_render_string(self):
        """Test rendering code with string content."""
        field_config = {"key": "code", "type": "code"}
        code = "def hello():\n    print('Hello')"
        html = display_registry.render("code", field_config, code)

        assert "code-display" in html
        assert "def hello()" in html or "def" in html

    def test_code_render_with_language(self):
        """Test rendering code with language option."""
        field_config = {
            "key": "code",
            "type": "code",
            "display_options": {"language": "python"}
        }
        code = "import os"
        html = display_registry.render("code", field_config, code)

        assert "python" in html.lower()


class TestFormatDisplayConfig:
    """Test format display configuration validation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.test_dirs = []
        self.original_cwd = os.getcwd()
        yield
        os.chdir(self.original_cwd)
        for test_dir in self.test_dirs:
            cleanup_test_directory(test_dir)

    def _create_test_config(self, instance_display_config: dict) -> str:
        """Create a test config file with instance_display."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", f"format_test_{uuid.uuid4().hex[:8]}")
        os.makedirs(test_dir, exist_ok=True)
        self.test_dirs.append(test_dir)

        # Create data file
        data_file = os.path.join(test_dir, "data.json")
        with open(data_file, "w") as f:
            f.write('{"id": "1", "text": "Test", "code": "print(1)", "table": [["A"]]}\n')

        output_dir = os.path.join(test_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        config_content = {
            "annotation_task_name": "Format Display Test",
            "task_dir": test_dir,
            "data_files": ["data.json"],
            "output_annotation_dir": "output",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "test",
                    "description": "Test annotation",
                    "annotation_type": "radio",
                    "labels": [{"name": "yes"}, {"name": "no"}]
                }
            ],
            "instance_display": instance_display_config,
            "user_config": {"allow_all_users": True}
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        return config_file

    def _create_args(self, config_path):
        """Create args object for init_config."""
        class Args:
            pass
        args = Args()
        args.config_file = config_path
        args.verbose = False
        args.very_verbose = False
        args.debug = False
        args.customjs = None
        args.customjs_hostname = None
        args.persist_sessions = False
        return args

    def test_code_display_config_valid(self):
        """Test code display configuration validates."""
        instance_display = {
            "fields": [
                {
                    "key": "code",
                    "type": "code",
                    "label": "Code",
                    "display_options": {
                        "language": "python",
                        "show_line_numbers": True
                    }
                }
            ]
        }
        config_file = self._create_test_config(instance_display)
        args = self._create_args(config_file)

        # Should not raise
        init_config(args)

    def test_spreadsheet_display_config_valid(self):
        """Test spreadsheet display configuration validates."""
        instance_display = {
            "fields": [
                {
                    "key": "table",
                    "type": "spreadsheet",
                    "label": "Data",
                    "display_options": {
                        "annotation_mode": "row",
                        "show_headers": True
                    }
                }
            ]
        }
        config_file = self._create_test_config(instance_display)
        args = self._create_args(config_file)

        # Should not raise
        init_config(args)

    def test_pdf_display_config_valid(self):
        """Test PDF display configuration validates."""
        instance_display = {
            "fields": [
                {
                    "key": "text",
                    "type": "pdf",
                    "label": "Document",
                    "display_options": {
                        "view_mode": "scroll",
                        "text_layer": True
                    }
                }
            ]
        }
        config_file = self._create_test_config(instance_display)
        args = self._create_args(config_file)

        # Should not raise
        init_config(args)

    def test_document_display_config_valid(self):
        """Test document display configuration validates."""
        instance_display = {
            "fields": [
                {
                    "key": "text",
                    "type": "document",
                    "label": "Doc",
                    "display_options": {
                        "collapsible": True,
                        "style_theme": "minimal"
                    }
                }
            ]
        }
        config_file = self._create_test_config(instance_display)
        args = self._create_args(config_file)

        # Should not raise
        init_config(args)

    def test_invalid_spreadsheet_annotation_mode(self):
        """Test invalid spreadsheet annotation_mode is rejected."""
        instance_display = {
            "fields": [
                {
                    "key": "table",
                    "type": "spreadsheet",
                    "display_options": {
                        "annotation_mode": "invalid_mode"
                    }
                }
            ]
        }
        config_file = self._create_test_config(instance_display)
        args = self._create_args(config_file)

        with pytest.raises(ConfigValidationError, match="annotation_mode"):
            init_config(args)

    def test_invalid_pdf_view_mode(self):
        """Test invalid PDF view_mode is rejected."""
        instance_display = {
            "fields": [
                {
                    "key": "text",
                    "type": "pdf",
                    "display_options": {
                        "view_mode": "invalid_mode"
                    }
                }
            ]
        }
        config_file = self._create_test_config(instance_display)
        args = self._create_args(config_file)

        with pytest.raises(ConfigValidationError, match="view_mode"):
            init_config(args)


class TestInstanceDisplayRenderer:
    """Test InstanceDisplayRenderer with format displays."""

    def test_renderer_with_code_display(self):
        """Test renderer handles code display type."""
        config = {
            "instance_display": {
                "fields": [
                    {"key": "code", "type": "code", "label": "Source"}
                ]
            }
        }
        renderer = InstanceDisplayRenderer(config)
        instance_data = {"code": "print('hello')"}

        html = renderer.render(instance_data)

        assert "code-display" in html or "code" in html.lower()

    def test_renderer_with_spreadsheet_display(self):
        """Test renderer handles spreadsheet display type."""
        config = {
            "instance_display": {
                "fields": [
                    {"key": "table", "type": "spreadsheet", "label": "Data"}
                ]
            }
        }
        renderer = InstanceDisplayRenderer(config)
        instance_data = {"table": [["A", "B"], ["1", "2"]]}

        html = renderer.render(instance_data)

        assert "spreadsheet" in html.lower()

    def test_renderer_span_targets_include_new_types(self):
        """Test span targets include new format types."""
        config = {
            "instance_display": {
                "fields": [
                    {"key": "code", "type": "code", "span_target": True},
                    {"key": "doc", "type": "document", "span_target": True}
                ]
            }
        }
        renderer = InstanceDisplayRenderer(config)

        assert "code" in renderer.span_targets
        assert "doc" in renderer.span_targets

    def test_renderer_missing_field_raises(self):
        """Test renderer raises for missing field."""
        config = {
            "instance_display": {
                "fields": [
                    {"key": "missing_field", "type": "code"}
                ]
            }
        }
        renderer = InstanceDisplayRenderer(config)
        instance_data = {"other_key": "value"}

        with pytest.raises(InstanceDisplayError, match="missing_field"):
            renderer.render(instance_data)


class TestFormatHandlingConfig:
    """Test format_handling configuration validation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.test_dirs = []
        self.original_cwd = os.getcwd()
        yield
        os.chdir(self.original_cwd)
        for test_dir in self.test_dirs:
            cleanup_test_directory(test_dir)

    def _create_config_with_format_handling(self, format_handling: dict) -> str:
        """Create test config with format_handling section."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", f"format_handling_{uuid.uuid4().hex[:8]}")
        os.makedirs(test_dir, exist_ok=True)
        self.test_dirs.append(test_dir)

        data_file = os.path.join(test_dir, "data.json")
        with open(data_file, "w") as f:
            f.write('{"id": "1", "text": "Test"}\n')

        output_dir = os.path.join(test_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        config_content = {
            "annotation_task_name": "Format Handling Test",
            "task_dir": test_dir,
            "data_files": ["data.json"],
            "output_annotation_dir": "output",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "test",
                    "description": "Test annotation",
                    "annotation_type": "radio",
                    "labels": [{"name": "yes"}]
                }
            ],
            "format_handling": format_handling,
            "user_config": {"allow_all_users": True}
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        return config_file

    def _create_args(self, config_path):
        class Args:
            pass
        args = Args()
        args.config_file = config_path
        args.verbose = False
        args.very_verbose = False
        args.debug = False
        args.customjs = None
        args.customjs_hostname = None
        args.persist_sessions = False
        return args

    def test_format_handling_valid_config(self):
        """Test valid format_handling config."""
        format_handling = {
            "enabled": True,
            "default_format": "auto",
            "pdf": {"extraction_mode": "text"},
            "spreadsheet": {"annotation_mode": "row", "max_rows": 500}
        }
        config_file = self._create_config_with_format_handling(format_handling)
        args = self._create_args(config_file)

        # Should not raise
        init_config(args)

    def test_format_handling_invalid_pdf_extraction_mode(self):
        """Test invalid PDF extraction mode is rejected."""
        format_handling = {
            "pdf": {"extraction_mode": "invalid"}
        }
        config_file = self._create_config_with_format_handling(format_handling)
        args = self._create_args(config_file)

        with pytest.raises(ConfigValidationError, match="extraction_mode"):
            init_config(args)

    def test_format_handling_invalid_default_format(self):
        """Test invalid default_format is rejected."""
        format_handling = {
            "default_format": "invalid_format"
        }
        config_file = self._create_config_with_format_handling(format_handling)
        args = self._create_args(config_file)

        with pytest.raises(ConfigValidationError, match="default_format"):
            init_config(args)
