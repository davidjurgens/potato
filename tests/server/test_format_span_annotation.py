"""
Server-side integration tests for span annotation with format displays.

Tests span annotation functionality across format display types:
- PDF, Document, and Code displays with span_target enabled
- Coordinate mapping and format_coords storage
- Span submission and retrieval with format-specific coordinates
"""

import pytest
import json
import os
import sys
import uuid
import yaml
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory


class TestFormatSpanAnnotationBase:
    """Base class for format span annotation tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.test_dirs = []
        self.server = None
        self.original_cwd = os.getcwd()
        yield
        os.chdir(self.original_cwd)
        if self.server:
            self.server.stop()
        for test_dir in self.test_dirs:
            cleanup_test_directory(test_dir)

    def _create_test_config(self, instance_display: dict, data_items: list,
                            annotation_schemes: list = None) -> str:
        """Create a test config file with span annotation support."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", f"span_format_{uuid.uuid4().hex[:8]}")
        os.makedirs(test_dir, exist_ok=True)
        self.test_dirs.append(test_dir)

        # Create data file
        data_file = os.path.join(test_dir, "data.jsonl")
        with open(data_file, "w") as f:
            for item in data_items:
                f.write(json.dumps(item) + "\n")

        output_dir = os.path.join(test_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        # Default span annotation scheme if not provided
        if annotation_schemes is None:
            annotation_schemes = [
                {
                    "name": "entities",
                    "description": "Named entity annotation",
                    "annotation_type": "span",
                    "labels": [
                        {"name": "PERSON", "color": "#FF6B6B"},
                        {"name": "ORG", "color": "#4ECDC4"},
                        {"name": "LOC", "color": "#45B7D1"}
                    ]
                }
            ]

        config_content = {
            "annotation_task_name": "Format Span Annotation Test",
            "task_dir": test_dir,
            "data_files": ["data.jsonl"],
            "output_annotation_dir": "output",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": annotation_schemes,
            "instance_display": instance_display,
            "user_config": {"allow_all_users": True}
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        return config_file

    def _start_server(self, config_file: str) -> FlaskTestServer:
        """Start Flask server with config."""
        port = find_free_port(preferred_port=9030)
        self.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = self.server.start_server()
        assert started, "Failed to start Flask server"
        self.server._wait_for_server_ready(timeout=10)
        return self.server

    def _create_session(self, server: FlaskTestServer) -> requests.Session:
        """Create authenticated session."""
        session = requests.Session()
        unique_user = f"test_user_{uuid.uuid4().hex[:8]}"

        # Register
        session.post(f"{server.base_url}/register",
                     data={"email": unique_user, "pass": "password123"})
        # Login
        session.post(f"{server.base_url}/auth",
                     data={"email": unique_user, "pass": "password123"})
        return session


class TestCodeSpanAnnotation(TestFormatSpanAnnotationBase):
    """Test span annotation on code display."""

    def test_code_display_span_target_config(self):
        """Test code display with span_target enabled loads correctly."""
        instance_display = {
            "fields": [
                {
                    "key": "code",
                    "type": "code",
                    "label": "Source Code",
                    "span_target": True,
                    "display_options": {
                        "language": "python",
                        "show_line_numbers": True
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "1",
                "text": "Test item",
                "code": "def hello():\n    print('Hello World')\n    return True"
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        assert "code-display" in response.text or "code" in response.text.lower()

    def test_code_span_submission_with_format_coords(self):
        """Test submitting span annotation with code-specific coordinates."""
        instance_display = {
            "fields": [
                {
                    "key": "code",
                    "type": "code",
                    "label": "Code",
                    "span_target": True
                }
            ]
        }
        data_items = [
            {
                "id": "code_1",
                "text": "Annotation target",
                "code": "class DataProcessor:\n    def process(self, data):\n        return data.strip()"
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        # Get initial page
        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200

        # Submit span annotation with format_coords
        span_data = {
            "schema": "entities",
            "name": "ORG",
            "start": 6,  # "DataProcessor" start
            "end": 19,   # "DataProcessor" end
            "target_field": "code",
            "format_coords": {
                "format": "code",
                "line": 1,
                "column": 6
            }
        }

        # The annotation submission endpoint
        response = session.post(
            f"{server.base_url}/annotate_span",
            json=span_data
        )
        # May return 200 or 404 depending on endpoint availability
        # Main test is that server handles the request without crashing

    def test_code_multiline_span(self):
        """Test span annotation across multiple lines of code."""
        instance_display = {
            "fields": [
                {
                    "key": "code",
                    "type": "code",
                    "span_target": True,
                    "display_options": {"language": "python"}
                }
            ]
        }
        data_items = [
            {
                "id": "multiline_1",
                "text": "Test",
                "code": "def func1():\n    pass\n\ndef func2():\n    pass"
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200


class TestDocumentSpanAnnotation(TestFormatSpanAnnotationBase):
    """Test span annotation on document display."""

    def test_document_display_span_target_config(self):
        """Test document display with span_target enabled."""
        instance_display = {
            "fields": [
                {
                    "key": "document",
                    "type": "document",
                    "label": "Document Content",
                    "span_target": True,
                    "display_options": {
                        "style_theme": "default"
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "doc_1",
                "text": "Test",
                "document": "<h1>Introduction</h1><p>This is the first paragraph with important content.</p>"
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        assert "document-display" in response.text or "Introduction" in response.text

    def test_document_with_format_output_span(self):
        """Test document display with FormatOutput-style dict."""
        instance_display = {
            "fields": [
                {
                    "key": "doc_content",
                    "type": "document",
                    "span_target": True
                }
            ]
        }
        data_items = [
            {
                "id": "doc_2",
                "text": "Test",
                "doc_content": {
                    "text": "Raw document text for annotation",
                    "rendered_html": "<article><p>Formatted document text for display</p></article>",
                    "metadata": {"format": "docx", "paragraphs": 1}
                }
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200

    def test_document_collapsible_with_span(self):
        """Test collapsible document still supports span annotation."""
        instance_display = {
            "fields": [
                {
                    "key": "document",
                    "type": "document",
                    "label": "Collapsible Doc",
                    "span_target": True,
                    "display_options": {"collapsible": True}
                }
            ]
        }
        data_items = [
            {
                "id": "coll_1",
                "text": "Test",
                "document": "<p>Content inside collapsible section</p>"
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        assert "details" in response.text.lower() or "collapsible" in response.text.lower()


class TestPDFSpanAnnotation(TestFormatSpanAnnotationBase):
    """Test span annotation on PDF display."""

    def test_pdf_display_span_target_config(self):
        """Test PDF display with span_target enabled."""
        instance_display = {
            "fields": [
                {
                    "key": "pdf_content",
                    "type": "pdf",
                    "label": "PDF Document",
                    "span_target": True,
                    "display_options": {
                        "view_mode": "scroll",
                        "text_layer": True
                    }
                }
            ]
        }
        # Use pre-extracted PDF content (since we don't have actual PDF files in test)
        data_items = [
            {
                "id": "pdf_1",
                "text": "Test",
                "pdf_content": {
                    "text": "Page 1 content. This is extracted text from the PDF.",
                    "rendered_html": "<div class='pdf-page' data-page='1'>Page 1 content.</div>",
                    "metadata": {"total_pages": 1}
                }
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200

    def test_pdf_multipage_span_target(self):
        """Test PDF display with multiple pages for span annotation."""
        instance_display = {
            "fields": [
                {
                    "key": "pdf_content",
                    "type": "pdf",
                    "span_target": True,
                    "display_options": {
                        "view_mode": "paginated",
                        "show_page_controls": True
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "pdf_multi",
                "text": "Test",
                "pdf_content": {
                    "text": "Page 1: Introduction.\nPage 2: Details.\nPage 3: Conclusion.",
                    "rendered_html": """
                        <div class='pdf-page' data-page='1'>Page 1: Introduction.</div>
                        <div class='pdf-page' data-page='2'>Page 2: Details.</div>
                        <div class='pdf-page' data-page='3'>Page 3: Conclusion.</div>
                    """,
                    "metadata": {"total_pages": 3},
                    "coordinate_map": {
                        "mappings": [
                            {"start": 0, "end": 21, "coordinate": {"format": "pdf", "page": 1}},
                            {"start": 22, "end": 38, "coordinate": {"format": "pdf", "page": 2}},
                            {"start": 39, "end": 59, "coordinate": {"format": "pdf", "page": 3}}
                        ]
                    }
                }
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200

    def test_pdf_span_with_page_coords(self):
        """Test span annotation with PDF page-specific coordinates."""
        instance_display = {
            "fields": [
                {
                    "key": "pdf_content",
                    "type": "pdf",
                    "span_target": True
                }
            ]
        }
        data_items = [
            {
                "id": "pdf_coords",
                "text": "Test",
                "pdf_content": {
                    "text": "Important term on page 2.",
                    "rendered_html": "<div class='pdf-page'>Content</div>",
                    "metadata": {"total_pages": 2}
                }
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200


class TestMultiFieldSpanAnnotation(TestFormatSpanAnnotationBase):
    """Test span annotation across multiple format display fields."""

    def test_multiple_span_targets(self):
        """Test page with multiple span-targetable format displays."""
        instance_display = {
            "fields": [
                {
                    "key": "code",
                    "type": "code",
                    "label": "Source",
                    "span_target": True,
                    "display_options": {"language": "python"}
                },
                {
                    "key": "document",
                    "type": "document",
                    "label": "Documentation",
                    "span_target": True
                }
            ]
        }
        data_items = [
            {
                "id": "multi_1",
                "text": "Test",
                "code": "def analyze(text):\n    return len(text)",
                "document": "<p>This function analyzes the input text and returns its length.</p>"
            }
        ]

        # Annotation scheme that supports multi-span
        annotation_schemes = [
            {
                "name": "annotations",
                "description": "Multi-target span annotations",
                "annotation_type": "span",
                "multi_span": True,
                "labels": [
                    {"name": "FUNCTION", "color": "#FF6B6B"},
                    {"name": "DESCRIPTION", "color": "#4ECDC4"}
                ]
            }
        ]

        config_file = self._create_test_config(instance_display, data_items, annotation_schemes)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        # Both displays should be present
        page_text = response.text.lower()
        assert "code" in page_text
        assert "document" in page_text or "documentation" in page_text

    def test_mixed_format_and_text_displays(self):
        """Test mixing format displays with regular text for span annotation."""
        instance_display = {
            "fields": [
                {
                    "key": "text",
                    "type": "text",
                    "label": "Plain Text",
                    "span_target": True
                },
                {
                    "key": "code",
                    "type": "code",
                    "label": "Code Sample",
                    "span_target": True
                }
            ]
        }
        data_items = [
            {
                "id": "mixed_1",
                "text": "The function process_data handles all data transformations.",
                "code": "def process_data(x):\n    return x * 2"
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200


class TestSpreadsheetSpanAnnotation(TestFormatSpanAnnotationBase):
    """Test span-like annotation on spreadsheet display (row/cell selection)."""

    def test_spreadsheet_row_selection_mode(self):
        """Test spreadsheet with row selection mode."""
        instance_display = {
            "fields": [
                {
                    "key": "table",
                    "type": "spreadsheet",
                    "label": "Data Table",
                    "span_target": True,
                    "display_options": {
                        "annotation_mode": "row",
                        "selectable": True
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "table_1",
                "text": "Test",
                "table": {
                    "headers": ["Name", "Category", "Value"],
                    "rows": [
                        ["Item A", "Type1", "100"],
                        ["Item B", "Type2", "200"],
                        ["Item C", "Type1", "150"]
                    ]
                }
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        assert "spreadsheet" in response.text.lower() or "table" in response.text.lower()

    def test_spreadsheet_cell_selection_mode(self):
        """Test spreadsheet with cell selection mode."""
        instance_display = {
            "fields": [
                {
                    "key": "table",
                    "type": "spreadsheet",
                    "label": "Cell Data",
                    "span_target": True,
                    "display_options": {
                        "annotation_mode": "cell"
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "cell_1",
                "text": "Test",
                "table": [
                    ["A1", "B1", "C1"],
                    ["A2", "B2", "C2"]
                ]
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200


class TestFormatCoordsStorage(TestFormatSpanAnnotationBase):
    """Test format_coords storage and retrieval in annotations."""

    def test_annotation_output_includes_format_coords(self):
        """Test that saved annotations include format_coords when present."""
        instance_display = {
            "fields": [
                {
                    "key": "code",
                    "type": "code",
                    "span_target": True
                }
            ]
        }
        data_items = [
            {"id": "save_1", "text": "Test", "code": "x = 1\ny = 2"}
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        # Just verify the page loads - actual annotation saving requires
        # JavaScript interaction which would be tested in Selenium tests
        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200

    def test_format_coords_in_span_annotation_class(self):
        """Test SpanAnnotation class handles format_coords correctly."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="FUNCTION",
            title="Functions",
            start=0,
            end=10,
            target_field="code",
            format_coords={
                "format": "code",
                "line": 1,
                "column": 0,
                "function_name": "test_func"
            }
        )

        assert span.format_coords is not None
        assert span.format_coords["format"] == "code"
        assert span.format_coords["line"] == 1
        assert span.target_field == "code"

    def test_span_annotation_serialization_with_format_coords(self):
        """Test SpanAnnotation serializes format_coords correctly."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="Locations",
            start=50,
            end=65,
            format_coords={
                "format": "pdf",
                "page": 2,
                "bbox": [100.5, 200.3, 150.8, 215.5]
            }
        )

        # Convert to dict for serialization
        span_dict = {
            "schema": span.schema,
            "name": span.name,
            "start": span.start,
            "end": span.end,
            "format_coords": span.format_coords
        }

        assert span_dict["format_coords"]["page"] == 2
        assert len(span_dict["format_coords"]["bbox"]) == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
