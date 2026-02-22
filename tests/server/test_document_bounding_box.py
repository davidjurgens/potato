"""
Server-side integration tests for document/HTML bounding box annotation.

Tests the document display bounding box annotation mode:
- Bounding box rendering on HTML content
- Coordinate storage
- Multiple bounding boxes
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


class TestDocumentBoundingBoxBase:
    """Base class for document bounding box tests."""

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

    def _create_test_config(self, instance_display: dict, data_items: list) -> str:
        """Create a test config file."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", f"doc_bbox_{uuid.uuid4().hex[:8]}")
        os.makedirs(test_dir, exist_ok=True)
        self.test_dirs.append(test_dir)

        # Create data file
        data_file = os.path.join(test_dir, "data.jsonl")
        with open(data_file, "w") as f:
            for item in data_items:
                f.write(json.dumps(item) + "\n")

        output_dir = os.path.join(test_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        config_content = {
            "annotation_task_name": "Document Bounding Box Test",
            "task_dir": test_dir,
            "data_files": ["data.jsonl"],
            "output_annotation_dir": "output",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "regions",
                    "description": "Region annotation",
                    "annotation_type": "radio",
                    "labels": [
                        {"name": "HEADER"},
                        {"name": "PARAGRAPH"},
                        {"name": "IMAGE"}
                    ]
                }
            ],
            "instance_display": instance_display,
            "user_config": {"allow_all_users": True}
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        return config_file

    def _start_server(self, config_file: str) -> FlaskTestServer:
        """Start Flask server with config."""
        port = find_free_port(preferred_port=9060)
        self.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = self.server.start_server()
        assert started, "Failed to start Flask server"
        self.server._wait_for_server_ready(timeout=10)
        return self.server

    def _create_session(self, server: FlaskTestServer) -> requests.Session:
        """Create authenticated session."""
        session = requests.Session()
        unique_user = f"test_user_{uuid.uuid4().hex[:8]}"

        session.post(f"{server.base_url}/register",
                     data={"email": unique_user, "pass": "password123"})
        session.post(f"{server.base_url}/auth",
                     data={"email": unique_user, "pass": "password123"})
        return session


class TestDocumentBoundingBoxDisplay(TestDocumentBoundingBoxBase):
    """Test document bounding box display rendering."""

    def test_document_bbox_mode_renders(self):
        """Test document display in bounding box mode renders correctly."""
        instance_display = {
            "fields": [
                {
                    "key": "html_content",
                    "type": "document",
                    "label": "Document",
                    "display_options": {
                        "annotation_mode": "bounding_box"
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "doc_1",
                "text": "Test",
                "html_content": "<h1>Title</h1><p>Paragraph with content.</p><img src='test.jpg'/>"
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        assert "document-bbox-mode" in response.text or "bounding_box" in response.text

    def test_document_bbox_controls_present(self):
        """Test document bbox mode has draw/select controls."""
        instance_display = {
            "fields": [
                {
                    "key": "html_content",
                    "type": "document",
                    "display_options": {
                        "annotation_mode": "bounding_box"
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "doc_1",
                "text": "Test",
                "html_content": "<p>Content</p>"
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        page_text = response.text.lower()
        assert "draw" in page_text or "select" in page_text or "bbox" in page_text

    def test_document_bbox_with_format_output(self):
        """Test document bbox mode with FormatOutput-style dict."""
        instance_display = {
            "fields": [
                {
                    "key": "doc_content",
                    "type": "document",
                    "display_options": {
                        "annotation_mode": "bounding_box"
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "doc_1",
                "text": "Test",
                "doc_content": {
                    "text": "Raw text content",
                    "rendered_html": "<article><h1>Title</h1><p>Content here.</p></article>",
                    "metadata": {"format": "docx"}
                }
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200


class TestDocumentBoundingBoxConfig(TestDocumentBoundingBoxBase):
    """Test document bounding box configuration."""

    def test_valid_bbox_config(self):
        """Test valid bounding box configuration."""
        instance_display = {
            "fields": [
                {
                    "key": "html_content",
                    "type": "document",
                    "display_options": {
                        "annotation_mode": "bounding_box",
                        "bbox_min_size": 15,
                        "show_bbox_labels": True
                    }
                }
            ]
        }
        data_items = [
            {"id": "1", "text": "Test", "html_content": "<p>Test</p>"}
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200

    def test_bbox_mode_with_themes(self):
        """Test bounding box mode works with different themes."""
        instance_display = {
            "fields": [
                {
                    "key": "html_content",
                    "type": "document",
                    "display_options": {
                        "annotation_mode": "bounding_box",
                        "style_theme": "minimal"
                    }
                }
            ]
        }
        data_items = [
            {"id": "1", "text": "Test", "html_content": "<p>Content</p>"}
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200


class TestDocumentBoundingBoxCoordinates(TestDocumentBoundingBoxBase):
    """Test document bounding box coordinate handling."""

    def test_bounding_box_coordinate_structure(self):
        """Test BoundingBoxCoordinate for documents."""
        from potato.format_handlers.coordinate_mapping import BoundingBoxCoordinate

        # For HTML documents, page is typically 1 (single "page")
        bbox = BoundingBoxCoordinate(
            page=1,
            bbox=[0.1, 0.2, 0.3, 0.4],
            label="HEADER"
        )

        result = bbox.to_dict()
        assert result["format"] == "bounding_box"
        assert result["page"] == 1
        assert result["bbox"] == [0.1, 0.2, 0.3, 0.4]
        assert result["label"] == "HEADER"

    def test_multiple_bboxes_on_document(self):
        """Test multiple bounding boxes on a single HTML document."""
        from potato.format_handlers.coordinate_mapping import CoordinateMapper, BoundingBoxCoordinate

        mapper = CoordinateMapper()

        # Add multiple boxes (all on "page 1" for HTML)
        mapper.add_mapping(0, 10, BoundingBoxCoordinate(
            page=1, bbox=[0.0, 0.0, 0.5, 0.1], label="HEADER"
        ))
        mapper.add_mapping(10, 20, BoundingBoxCoordinate(
            page=1, bbox=[0.0, 0.1, 1.0, 0.4], label="PARAGRAPH"
        ))
        mapper.add_mapping(20, 30, BoundingBoxCoordinate(
            page=1, bbox=[0.2, 0.5, 0.6, 0.4], label="IMAGE"
        ))

        assert mapper.get_mapping_count() == 3

        all_coords = mapper.get_all_coords_for_range(0, 30)
        assert len(all_coords) == 3
        assert all(c["page"] == 1 for c in all_coords)

        labels = [c["label"] for c in all_coords]
        assert "HEADER" in labels
        assert "PARAGRAPH" in labels
        assert "IMAGE" in labels


class TestMixedSpanAndBboxModes(TestDocumentBoundingBoxBase):
    """Test mixing span and bounding box annotation modes."""

    def test_span_mode_still_works(self):
        """Test that span mode is still the default."""
        instance_display = {
            "fields": [
                {
                    "key": "html_content",
                    "type": "document",
                    "span_target": True
                    # No annotation_mode specified - should default to span
                }
            ]
        }
        data_items = [
            {"id": "1", "text": "Test", "html_content": "<p>Annotate this text.</p>"}
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        # Should NOT have bbox mode elements
        assert "document-bbox-mode" not in response.text

    def test_multiple_fields_different_modes(self):
        """Test multiple document fields with different annotation modes."""
        instance_display = {
            "fields": [
                {
                    "key": "text_content",
                    "type": "document",
                    "label": "Text for Span",
                    "span_target": True,
                    "display_options": {
                        "annotation_mode": "span"
                    }
                },
                {
                    "key": "layout_content",
                    "type": "document",
                    "label": "Layout for Bbox",
                    "display_options": {
                        "annotation_mode": "bounding_box"
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "1",
                "text": "Test",
                "text_content": "<p>Text to annotate with spans.</p>",
                "layout_content": "<div><header>Header</header><main>Content</main></div>"
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        # Should have both content types
        assert "Text to annotate" in response.text or "span" in response.text.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
