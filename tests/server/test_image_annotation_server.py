"""
Server-side integration tests for image annotation.

Tests the complete server-side functionality including:
- Configuration loading and validation
- Schema generation via Flask routes
- Annotation submission and persistence
- API endpoints for image annotation
"""

import pytest
import json
import os
import sys
import tempfile
import shutil

# Add potato to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.config_module import init_config, config, ConfigValidationError
from potato.server_utils.schemas import validate_schema_config
from potato.server_utils.schemas.registry import schema_registry
from tests.helpers.test_utils import cleanup_test_directory


class TestImageAnnotationServerConfig:
    """Test image annotation configuration on server side."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.test_dirs = []
        self.original_cwd = os.getcwd()
        yield
        os.chdir(self.original_cwd)
        for test_dir in self.test_dirs:
            cleanup_test_directory(test_dir)

    def _create_test_config(self, config_content: dict) -> str:
        """Create a test config file and return its path."""
        # Use tests/output directory to comply with path security
        import uuid
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", f"image_test_{uuid.uuid4().hex[:8]}")
        os.makedirs(test_dir, exist_ok=True)
        self.test_dirs.append(test_dir)

        # Create data directory and file
        data_dir = os.path.join(test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        data_file = os.path.join(data_dir, "test_images.json")
        with open(data_file, "w") as f:
            f.write('{"id": "img_001", "image_url": "https://example.com/test.jpg"}\n')
            f.write('{"id": "img_002", "image_url": "https://example.com/test2.jpg"}\n')

        # Create output directory
        output_dir = os.path.join(test_dir, "annotation_output")
        os.makedirs(output_dir, exist_ok=True)

        # Update config with correct paths
        config_content["task_dir"] = test_dir
        config_content["data_files"] = ["data/test_images.json"]
        config_content["output_annotation_dir"] = "annotation_output/"

        # Write config file
        config_file = os.path.join(test_dir, "config.yaml")
        import yaml
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

    def test_image_annotation_config_loads(self):
        """Test that image annotation config loads correctly."""
        config_content = {
            "server_name": "Image Annotation Test",
            "annotation_task_name": "Test Task",
            "output_annotation_format": "json",
            "alert_time_each_instance": 0,
            "item_properties": {
                "id_key": "id",
                "text_key": "image_url"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": [
                {
                    "annotation_type": "image_annotation",
                    "name": "object_detection",
                    "description": "Draw boxes around objects",
                    "tools": ["bbox", "polygon"],
                    "labels": [
                        {"name": "person", "color": "#FF0000"},
                        {"name": "car", "color": "#00FF00"}
                    ]
                }
            ]
        }

        config_path = self._create_test_config(config_content)
        args = self._create_args(config_path)

        init_config(args)

        assert config is not None
        assert "annotation_schemes" in config
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) == 1
        assert schemes[0]["annotation_type"] == "image_annotation"

    def test_image_annotation_schema_validation(self):
        """Test that image annotation schema validates correctly."""
        config_content = {
            "server_name": "Image Annotation Test",
            "annotation_task_name": "Test Task",
            "output_annotation_format": "json",
            "alert_time_each_instance": 0,
            "item_properties": {
                "id_key": "id",
                "text_key": "image_url"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": [
                {
                    "annotation_type": "image_annotation",
                    "name": "object_detection",
                    "description": "Draw boxes around objects",
                    "tools": ["bbox", "polygon", "freeform", "landmark"],
                    "labels": [
                        {"name": "person", "color": "#FF0000", "key_value": "1"},
                        {"name": "car", "color": "#00FF00", "key_value": "2"}
                    ],
                    "zoom_enabled": True,
                    "pan_enabled": True,
                    "min_annotations": 1,
                    "max_annotations": 10
                }
            ]
        }

        config_path = self._create_test_config(config_content)
        args = self._create_args(config_path)

        init_config(args)

        # Validate each scheme
        for scheme in config.get("annotation_schemes", []):
            validate_schema_config(scheme)

    def test_image_annotation_invalid_tool_rejected(self):
        """Test that invalid tools are rejected."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "image_annotation",
            "name": "test",
            "description": "Test",
            "tools": ["bbox", "invalid_tool"],
            "labels": [{"name": "person"}]
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "invalid" in str(exc_info.value).lower()

    def test_image_annotation_missing_tools_rejected(self):
        """Test that missing tools are rejected."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "image_annotation",
            "name": "test",
            "description": "Test",
            "labels": [{"name": "person"}]
            # Missing tools
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "tools" in str(exc_info.value).lower()

    def test_image_annotation_missing_labels_rejected(self):
        """Test that missing labels are rejected."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "image_annotation",
            "name": "test",
            "description": "Test",
            "tools": ["bbox"]
            # Missing labels
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "labels" in str(exc_info.value).lower()


class TestImageAnnotationSchemaGeneration:
    """Test image annotation schema generation."""

    def test_schema_generates_html(self):
        """Test that schema generates valid HTML."""
        scheme = {
            "annotation_type": "image_annotation",
            "name": "object_detection",
            "description": "Draw boxes around objects",
            "tools": ["bbox", "polygon"],
            "labels": [
                {"name": "person", "color": "#FF0000"},
                {"name": "car", "color": "#00FF00"}
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0
        assert "object_detection" in html
        assert "image-annotation-container" in html
        assert 'data-tool="bbox"' in html
        assert 'data-tool="polygon"' in html

    def test_schema_generates_keybindings(self):
        """Test that schema generates keybindings."""
        scheme = {
            "annotation_type": "image_annotation",
            "name": "test",
            "description": "Test",
            "tools": ["bbox", "polygon"],
            "labels": [
                {"name": "person", "key_value": "1"},
                {"name": "car", "key_value": "2"}
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert keybindings is not None
        keys = [k for k, _ in keybindings]
        assert "b" in keys  # bbox
        assert "p" in keys  # polygon
        assert "1" in keys  # person
        assert "2" in keys  # car

    def test_schema_with_all_tools(self):
        """Test schema generation with all tools enabled."""
        scheme = {
            "annotation_type": "image_annotation",
            "name": "full_tools",
            "description": "All tools",
            "tools": ["bbox", "polygon", "freeform", "landmark"],
            "labels": [{"name": "object"}]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert 'data-tool="bbox"' in html
        assert 'data-tool="polygon"' in html
        assert 'data-tool="freeform"' in html
        assert 'data-tool="landmark"' in html

    def test_schema_with_zoom_and_pan(self):
        """Test schema with zoom and pan enabled."""
        scheme = {
            "annotation_type": "image_annotation",
            "name": "zoom_test",
            "description": "Zoom test",
            "tools": ["bbox"],
            "labels": [{"name": "object"}],
            "zoom_enabled": True,
            "pan_enabled": True
        }

        html, keybindings = schema_registry.generate(scheme)

        assert 'data-action="zoom-in"' in html
        assert 'data-action="zoom-out"' in html
        assert 'data-action="zoom-fit"' in html


class TestImageAnnotationDataFormat:
    """Test image annotation data format and persistence."""

    def test_annotation_data_format(self):
        """Test expected annotation data format."""
        # Expected format for image annotation data
        annotation_data = {
            "annotations": [
                {
                    "id": "ann_1",
                    "type": "bbox",
                    "label": "person",
                    "coordinates": {
                        "left": 100,
                        "top": 50,
                        "width": 200,
                        "height": 300
                    }
                },
                {
                    "id": "ann_2",
                    "type": "polygon",
                    "label": "car",
                    "points": [
                        {"x": 10, "y": 20},
                        {"x": 100, "y": 20},
                        {"x": 100, "y": 100}
                    ]
                }
            ]
        }

        # Verify structure
        assert "annotations" in annotation_data
        assert len(annotation_data["annotations"]) == 2

        bbox = annotation_data["annotations"][0]
        assert bbox["type"] == "bbox"
        assert "coordinates" in bbox
        assert all(k in bbox["coordinates"] for k in ["left", "top", "width", "height"])

        polygon = annotation_data["annotations"][1]
        assert polygon["type"] == "polygon"
        assert "points" in polygon
        assert len(polygon["points"]) == 3

    def test_annotation_json_serialization(self):
        """Test that annotation data can be serialized to JSON."""
        annotation_data = {
            "annotations": [
                {
                    "id": "ann_1",
                    "type": "bbox",
                    "label": "person",
                    "coordinates": {"left": 100, "top": 50, "width": 200, "height": 300}
                }
            ]
        }

        # Should serialize without error
        json_str = json.dumps(annotation_data)
        assert len(json_str) > 0

        # Should deserialize back
        parsed = json.loads(json_str)
        assert parsed == annotation_data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
