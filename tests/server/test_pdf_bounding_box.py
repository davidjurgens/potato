"""
Server-side integration tests for PDF bounding box annotation.

Tests the PDF display bounding box annotation mode:
- Bounding box rendering with paginated navigation
- Coordinate storage with page tracking
- Multiple bounding boxes across pages
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


class TestPDFBoundingBoxBase:
    """Base class for PDF bounding box tests."""

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
        """Create a test config file."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", f"pdf_bbox_{uuid.uuid4().hex[:8]}")
        os.makedirs(test_dir, exist_ok=True)
        self.test_dirs.append(test_dir)

        # Create data file
        data_file = os.path.join(test_dir, "data.jsonl")
        with open(data_file, "w") as f:
            for item in data_items:
                f.write(json.dumps(item) + "\n")

        output_dir = os.path.join(test_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        # Default annotation scheme for bounding boxes
        if annotation_schemes is None:
            annotation_schemes = [
                {
                    "name": "objects",
                    "description": "Object detection annotation",
                    "annotation_type": "radio",
                    "labels": [
                        {"name": "FIGURE"},
                        {"name": "TABLE"},
                        {"name": "CHART"}
                    ]
                }
            ]

        config_content = {
            "annotation_task_name": "PDF Bounding Box Test",
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
        port = find_free_port(preferred_port=9050)
        self.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = self.server.start_server()
        assert started, "Failed to start Flask server"
        self.server._wait_for_server_ready(timeout=10)
        return self.server

    def _create_session(self, server: FlaskTestServer) -> requests.Session:
        """Create authenticated session."""
        session = requests.Session()
        unique_user = f"test_user_{uuid.uuid4().hex[:8]}"

        # Register and login
        session.post(f"{server.base_url}/register",
                     data={"email": unique_user, "pass": "password123"})
        session.post(f"{server.base_url}/auth",
                     data={"email": unique_user, "pass": "password123"})
        return session


class TestPDFBoundingBoxDisplay(TestPDFBoundingBoxBase):
    """Test PDF bounding box display rendering."""

    def test_pdf_bbox_mode_renders(self):
        """Test PDF display in bounding box mode renders correctly."""
        instance_display = {
            "fields": [
                {
                    "key": "pdf_content",
                    "type": "pdf",
                    "label": "Document",
                    "display_options": {
                        "annotation_mode": "bounding_box",
                        "view_mode": "paginated"
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "bbox_1",
                "text": "Test",
                "pdf_content": {
                    "text": "Document with figures and tables.",
                    "rendered_html": "<div class='pdf-page'>Content</div>",
                    "metadata": {"total_pages": 3}
                }
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        assert "pdf-bbox-mode" in response.text or "bounding_box" in response.text

    def test_pdf_bbox_controls_present(self):
        """Test PDF bbox mode has draw/select controls."""
        instance_display = {
            "fields": [
                {
                    "key": "pdf_content",
                    "type": "pdf",
                    "display_options": {
                        "annotation_mode": "bounding_box"
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "controls_1",
                "text": "Test",
                "pdf_content": {
                    "text": "Content",
                    "rendered_html": "<div class='pdf-page'>Page</div>",
                    "metadata": {"total_pages": 1}
                }
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        # Check for bbox tool buttons
        page_text = response.text.lower()
        assert "draw" in page_text or "select" in page_text or "pdf-bbox" in page_text

    def test_pdf_bbox_paginated_navigation(self):
        """Test PDF bbox mode has paginated navigation."""
        instance_display = {
            "fields": [
                {
                    "key": "pdf_content",
                    "type": "pdf",
                    "display_options": {
                        "annotation_mode": "bounding_box",
                        "show_page_controls": True
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "nav_1",
                "text": "Test",
                "pdf_content": {
                    "text": "Multi-page document",
                    "rendered_html": """
                        <div class='pdf-page' data-page='1'>Page 1</div>
                        <div class='pdf-page' data-page='2'>Page 2</div>
                    """,
                    "metadata": {"total_pages": 5}
                }
            }
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200
        # Check for navigation elements
        assert "pdf-navigation" in response.text or "pdf-prev" in response.text.lower() or "prev" in response.text.lower()


class TestBoundingBoxCoordinates(TestPDFBoundingBoxBase):
    """Test bounding box coordinate handling."""

    def test_bounding_box_coordinate_structure(self):
        """Test BoundingBoxCoordinate stores page information."""
        from potato.format_handlers.coordinate_mapping import BoundingBoxCoordinate

        bbox = BoundingBoxCoordinate(
            page=2,
            bbox=[0.1, 0.2, 0.3, 0.4],
            label="FIGURE"
        )

        result = bbox.to_dict()
        assert result["format"] == "bounding_box"
        assert result["page"] == 2
        assert result["bbox"] == [0.1, 0.2, 0.3, 0.4]
        assert result["label"] == "FIGURE"

    def test_bounding_box_pixel_conversion(self):
        """Test converting between normalized and pixel coordinates."""
        from potato.format_handlers.coordinate_mapping import BoundingBoxCoordinate

        # Create from pixel coords
        bbox = BoundingBoxCoordinate.from_pixel_coords(
            page=1,
            x=100,
            y=200,
            width=300,
            height=150,
            page_width=1000,
            page_height=800,
            label="TABLE"
        )

        # Verify normalized coords
        assert bbox.bbox[0] == pytest.approx(0.1)  # x / page_width
        assert bbox.bbox[1] == pytest.approx(0.25)  # y / page_height
        assert bbox.bbox[2] == pytest.approx(0.3)  # width / page_width
        assert bbox.bbox[3] == pytest.approx(0.1875)  # height / page_height

        # Convert back to pixels
        pixels = bbox.to_pixel_coords(1000, 800)
        assert pixels[0] == pytest.approx(100)
        assert pixels[1] == pytest.approx(200)
        assert pixels[2] == pytest.approx(300)
        assert pixels[3] == pytest.approx(150)

    def test_multiple_bboxes_per_page(self):
        """Test storing multiple bounding boxes on same page."""
        from potato.format_handlers.coordinate_mapping import CoordinateMapper, BoundingBoxCoordinate

        mapper = CoordinateMapper()

        # Add multiple boxes on page 1
        mapper.add_mapping(0, 10, BoundingBoxCoordinate(
            page=1, bbox=[0.1, 0.1, 0.2, 0.2], label="FIGURE_1"
        ))
        mapper.add_mapping(10, 20, BoundingBoxCoordinate(
            page=1, bbox=[0.5, 0.1, 0.2, 0.2], label="FIGURE_2"
        ))

        # Add box on page 2
        mapper.add_mapping(20, 30, BoundingBoxCoordinate(
            page=2, bbox=[0.1, 0.5, 0.3, 0.3], label="TABLE_1"
        ))

        assert mapper.get_mapping_count() == 3

        # Get coords for page 1 range
        all_coords = mapper.get_all_coords_for_range(0, 20)
        assert len(all_coords) == 2
        assert all(c["page"] == 1 for c in all_coords)


class TestPDFBoundingBoxConfig(TestPDFBoundingBoxBase):
    """Test PDF bounding box configuration validation."""

    def test_valid_bbox_config(self):
        """Test valid bounding box mode configuration."""
        instance_display = {
            "fields": [
                {
                    "key": "pdf_content",
                    "type": "pdf",
                    "display_options": {
                        "annotation_mode": "bounding_box",
                        "bbox_min_size": 15,
                        "show_bbox_labels": True
                    }
                }
            ]
        }
        data_items = [
            {"id": "1", "text": "Test", "pdf_content": {"text": "Content", "metadata": {}}}
        ]

        config_file = self._create_test_config(instance_display, data_items)
        server = self._start_server(config_file)
        session = self._create_session(server)

        response = session.get(f"{server.base_url}/annotate")
        assert response.status_code == 200

    def test_bbox_mode_forces_paginated_view(self):
        """Test that bounding box mode uses paginated view."""
        from potato.server_utils.displays.pdf_display import PDFDisplay

        display = PDFDisplay()
        field_config = {
            "key": "doc",
            "type": "pdf",
            "display_options": {
                "annotation_mode": "bounding_box",
                "view_mode": "scroll"  # This should be overridden
            }
        }

        html = display.render(field_config, "/path/to/doc.pdf")

        # Should render in paginated mode for bbox
        assert "paginated" in html or "pdf-bbox-mode" in html


class TestPDFMultiPageBoundingBox(TestPDFBoundingBoxBase):
    """Test bounding box annotation on multi-page PDFs."""

    def test_multipage_pdf_bbox_rendering(self):
        """Test multi-page PDF renders with bbox support."""
        instance_display = {
            "fields": [
                {
                    "key": "pdf_content",
                    "type": "pdf",
                    "display_options": {
                        "annotation_mode": "bounding_box"
                    }
                }
            ]
        }
        data_items = [
            {
                "id": "multi_1",
                "text": "Test",
                "pdf_content": {
                    "text": "Page 1 content. Page 2 content. Page 3 content.",
                    "rendered_html": """
                        <div class='pdf-page' data-page='1'>Page 1</div>
                        <div class='pdf-page' data-page='2'>Page 2</div>
                        <div class='pdf-page' data-page='3'>Page 3</div>
                    """,
                    "metadata": {
                        "total_pages": 3,
                        "pages": [
                            {"page_number": 1, "width": 612, "height": 792},
                            {"page_number": 2, "width": 612, "height": 792},
                            {"page_number": 3, "width": 612, "height": 792}
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

    def test_page_tracking_in_bbox_coordinates(self):
        """Test that bounding box coordinates include page number."""
        from potato.format_handlers.coordinate_mapping import BoundingBoxCoordinate

        # Create bboxes for different pages
        bbox_page1 = BoundingBoxCoordinate(
            page=1,
            bbox=[0.1, 0.2, 0.3, 0.2],
            label="FIGURE"
        )
        bbox_page3 = BoundingBoxCoordinate(
            page=3,
            bbox=[0.5, 0.6, 0.2, 0.15],
            label="TABLE"
        )

        dict1 = bbox_page1.to_dict()
        dict3 = bbox_page3.to_dict()

        assert dict1["page"] == 1
        assert dict3["page"] == 3
        assert dict1["label"] == "FIGURE"
        assert dict3["label"] == "TABLE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
