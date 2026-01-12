"""
Unit tests for image annotation schema.

Tests the image_annotation schema generator functionality including:
- HTML generation
- Label processing
- Tool validation
- Keybinding generation
- Config validation
"""

import pytest
import json
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.image_annotation import (
    generate_image_annotation_layout,
    _process_labels,
    _generate_tool_buttons,
    _generate_label_selector,
    _generate_keybindings,
    VALID_TOOLS,
    DEFAULT_COLORS,
)


class TestImageAnnotationSchema:
    """Tests for image annotation schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_bbox",
            "description": "Test bounding box annotation",
            "annotation_type": "image_annotation",
            "tools": ["bbox"],
            "labels": [
                {"name": "person", "color": "#FF0000"},
                {"name": "car", "color": "#00FF00"},
            ],
        }

        html, keybindings = generate_image_annotation_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_bbox" in html
        assert "Test bounding box annotation" in html
        assert 'data-tool="bbox"' in html
        assert "person" in html
        assert "car" in html

    def test_multiple_tools(self):
        """Test schema with all tools enabled."""
        scheme = {
            "name": "multi_tool",
            "description": "Multi-tool annotation",
            "annotation_type": "image_annotation",
            "tools": ["bbox", "polygon", "freeform", "landmark"],
            "labels": [{"name": "object"}],
        }

        html, keybindings = generate_image_annotation_layout(scheme)

        for tool in ["bbox", "polygon", "freeform", "landmark"]:
            assert f'data-tool="{tool}"' in html

    def test_label_color_assignment(self):
        """Test that labels get colors assigned."""
        scheme = {
            "name": "color_test",
            "description": "Color assignment test",
            "annotation_type": "image_annotation",
            "tools": ["bbox"],
            "labels": ["label1", "label2", "label3"],  # String labels
        }

        html, keybindings = generate_image_annotation_layout(scheme)

        assert "label1" in html
        assert "label2" in html
        assert "label3" in html
        # Should have color indicators
        assert "label-color-dot" in html

    def test_keybinding_generation(self):
        """Test keybinding generation for tools and labels."""
        scheme = {
            "name": "keybind_test",
            "description": "Keybinding test",
            "annotation_type": "image_annotation",
            "tools": ["bbox", "polygon"],
            "labels": [
                {"name": "person", "key_value": "1"},
                {"name": "car", "key_value": "2"},
            ],
        }

        html, keybindings = generate_image_annotation_layout(scheme)

        # Should have tool keybindings
        tool_keys = [k for k, _ in keybindings]
        assert "b" in tool_keys  # bbox
        assert "p" in tool_keys  # polygon

        # Should have label keybindings
        assert "1" in tool_keys
        assert "2" in tool_keys

    def test_zoom_controls_present(self):
        """Test that zoom controls are generated."""
        scheme = {
            "name": "zoom_test",
            "description": "Zoom test",
            "annotation_type": "image_annotation",
            "tools": ["bbox"],
            "labels": [{"name": "test"}],
            "zoom_enabled": True,
        }

        html, _ = generate_image_annotation_layout(scheme)

        assert 'data-action="zoom-in"' in html
        assert 'data-action="zoom-out"' in html
        assert 'data-action="zoom-fit"' in html
        assert 'data-action="zoom-reset"' in html

    def test_edit_controls_present(self):
        """Test that edit controls are generated."""
        scheme = {
            "name": "edit_test",
            "description": "Edit test",
            "annotation_type": "image_annotation",
            "tools": ["bbox"],
            "labels": [{"name": "test"}],
        }

        html, _ = generate_image_annotation_layout(scheme)

        assert 'data-action="undo"' in html
        assert 'data-action="redo"' in html
        assert 'data-action="delete"' in html

    def test_hidden_input_present(self):
        """Test that hidden input for data storage is present."""
        scheme = {
            "name": "input_test",
            "description": "Input test",
            "annotation_type": "image_annotation",
            "tools": ["bbox"],
            "labels": [{"name": "test"}],
        }

        html, _ = generate_image_annotation_layout(scheme)

        assert 'type="hidden"' in html
        assert 'name="input_test"' in html
        assert 'class="annotation-data-input"' in html

    def test_config_json_embedded(self):
        """Test that JavaScript config is embedded in HTML."""
        scheme = {
            "name": "config_test",
            "description": "Config test",
            "annotation_type": "image_annotation",
            "tools": ["bbox", "polygon"],
            "labels": [{"name": "test", "color": "#FF0000"}],
            "zoom_enabled": True,
            "pan_enabled": True,
            "min_annotations": 1,
            "max_annotations": 10,
        }

        html, _ = generate_image_annotation_layout(scheme)

        # Check config values are in the embedded JSON
        assert '"schemaName":"config_test"' in html.replace(" ", "").replace("\n", "")
        assert '"zoomEnabled":true' in html.replace(" ", "").replace("\n", "")
        assert '"panEnabled":true' in html.replace(" ", "").replace("\n", "")

    def test_missing_labels_error(self):
        """Test error when labels are missing."""
        scheme = {
            "name": "error_test",
            "description": "Error test",
            "annotation_type": "image_annotation",
            "tools": ["bbox"],
            # Missing labels
        }

        # safe_generate_layout catches errors and returns error HTML
        html, keybindings = generate_image_annotation_layout(scheme)
        assert "annotation-error" in html
        assert "labels" in html.lower()

    def test_missing_tools_error(self):
        """Test error when tools are missing."""
        scheme = {
            "name": "error_test",
            "description": "Error test",
            "annotation_type": "image_annotation",
            "labels": [{"name": "test"}],
            # Missing tools
        }

        # safe_generate_layout catches errors and returns error HTML
        html, keybindings = generate_image_annotation_layout(scheme)
        assert "annotation-error" in html
        assert "tools" in html.lower()

    def test_invalid_tool_error(self):
        """Test error when invalid tool is specified."""
        scheme = {
            "name": "error_test",
            "description": "Error test",
            "annotation_type": "image_annotation",
            "tools": ["bbox", "invalid_tool"],
            "labels": [{"name": "test"}],
        }

        # safe_generate_layout catches errors and returns error HTML
        html, keybindings = generate_image_annotation_layout(scheme)
        assert "annotation-error" in html
        assert "invalid" in html.lower()

    def test_empty_tools_error(self):
        """Test error when tools list is empty."""
        scheme = {
            "name": "error_test",
            "description": "Error test",
            "annotation_type": "image_annotation",
            "tools": [],
            "labels": [{"name": "test"}],
        }

        # safe_generate_layout catches errors and returns error HTML
        html, keybindings = generate_image_annotation_layout(scheme)
        assert "annotation-error" in html
        assert "empty" in html.lower() or "non-empty" in html.lower()


class TestLabelProcessing:
    """Tests for label processing functionality."""

    def test_string_labels(self):
        """Test processing of string labels."""
        labels = ["person", "car", "tree"]
        processed = _process_labels(labels)

        assert len(processed) == 3
        assert processed[0]["name"] == "person"
        assert processed[1]["name"] == "car"
        assert processed[2]["name"] == "tree"
        # Should have colors assigned
        for label in processed:
            assert "color" in label
            assert label["color"].startswith("#")

    def test_dict_labels_with_color(self):
        """Test processing of dict labels with custom colors."""
        labels = [
            {"name": "person", "color": "#FF0000"},
            {"name": "car", "color": "#00FF00"},
        ]
        processed = _process_labels(labels)

        assert processed[0]["color"] == "#FF0000"
        assert processed[1]["color"] == "#00FF00"

    def test_dict_labels_without_color(self):
        """Test processing of dict labels without colors (should get default)."""
        labels = [
            {"name": "person"},
            {"name": "car"},
        ]
        processed = _process_labels(labels)

        # Should have default colors assigned
        for label in processed:
            assert "color" in label
            assert label["color"] in DEFAULT_COLORS

    def test_labels_with_key_values(self):
        """Test processing of labels with key_value shortcuts."""
        labels = [
            {"name": "person", "key_value": "1"},
            {"name": "car", "key_value": "2"},
        ]
        processed = _process_labels(labels)

        assert processed[0]["key_value"] == "1"
        assert processed[1]["key_value"] == "2"

    def test_color_cycling(self):
        """Test that colors cycle through defaults for many labels."""
        labels = [f"label_{i}" for i in range(15)]
        processed = _process_labels(labels)

        assert len(processed) == 15
        # Colors should cycle
        assert processed[0]["color"] == processed[10]["color"]


class TestToolButtons:
    """Tests for tool button generation."""

    def test_bbox_button(self):
        """Test bbox tool button generation."""
        html = _generate_tool_buttons(["bbox"])
        assert 'data-tool="bbox"' in html
        assert "Box" in html

    def test_polygon_button(self):
        """Test polygon tool button generation."""
        html = _generate_tool_buttons(["polygon"])
        assert 'data-tool="polygon"' in html
        assert "Polygon" in html

    def test_freeform_button(self):
        """Test freeform tool button generation."""
        html = _generate_tool_buttons(["freeform"])
        assert 'data-tool="freeform"' in html
        assert "Draw" in html

    def test_landmark_button(self):
        """Test landmark tool button generation."""
        html = _generate_tool_buttons(["landmark"])
        assert 'data-tool="landmark"' in html
        assert "Point" in html

    def test_all_tools(self):
        """Test all tools together."""
        html = _generate_tool_buttons(VALID_TOOLS)
        for tool in VALID_TOOLS:
            assert f'data-tool="{tool}"' in html


class TestLabelSelector:
    """Tests for label selector generation."""

    def test_label_buttons(self):
        """Test label button generation."""
        labels = [
            {"name": "person", "color": "#FF0000"},
            {"name": "car", "color": "#00FF00"},
        ]
        html = _generate_label_selector(labels)

        assert 'data-label="person"' in html
        assert 'data-label="car"' in html
        assert 'data-color="#FF0000"' in html
        assert 'data-color="#00FF00"' in html

    def test_color_dots(self):
        """Test color dot indicators."""
        labels = [{"name": "test", "color": "#FF0000"}]
        html = _generate_label_selector(labels)

        assert "label-color-dot" in html
        assert "background-color: #FF0000" in html


class TestKeybindings:
    """Tests for keybinding generation."""

    def test_tool_keybindings(self):
        """Test tool keybindings."""
        labels = [{"name": "test"}]
        keybindings = _generate_keybindings(labels, ["bbox", "polygon"])

        keys = dict(keybindings)
        assert "b" in keys  # bbox
        assert "p" in keys  # polygon
        assert "Bounding Box" in keys["b"]
        assert "Polygon" in keys["p"]

    def test_label_keybindings(self):
        """Test label keybindings."""
        labels = [
            {"name": "person", "key_value": "1"},
            {"name": "car", "key_value": "2"},
        ]
        keybindings = _generate_keybindings(labels, ["bbox"])

        keys = dict(keybindings)
        assert "1" in keys
        assert "2" in keys
        assert "person" in keys["1"]
        assert "car" in keys["2"]

    def test_common_keybindings(self):
        """Test common keybindings are included."""
        labels = [{"name": "test"}]
        keybindings = _generate_keybindings(labels, ["bbox"])

        keys = [k for k, _ in keybindings]
        assert "Del" in keys
        assert "+/-" in keys
        assert "0" in keys


class TestConfigValidation:
    """Tests for config validation in config_module.py."""

    def test_valid_image_annotation_config(self):
        """Test validation passes for valid config."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "name": "test",
            "description": "Test",
            "annotation_type": "image_annotation",
            "tools": ["bbox", "polygon"],
            "labels": [{"name": "person"}],
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_tool_validation(self):
        """Test validation fails for invalid tool."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "name": "test",
            "description": "Test",
            "annotation_type": "image_annotation",
            "tools": ["invalid_tool"],
            "labels": [{"name": "person"}],
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "invalid" in str(exc_info.value).lower()

    def test_missing_tools_validation(self):
        """Test validation fails for missing tools."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "name": "test",
            "description": "Test",
            "annotation_type": "image_annotation",
            "labels": [{"name": "person"}],
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "tools" in str(exc_info.value).lower()

    def test_empty_tools_validation(self):
        """Test validation fails for empty tools list."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "name": "test",
            "description": "Test",
            "annotation_type": "image_annotation",
            "tools": [],
            "labels": [{"name": "person"}],
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "empty" in str(exc_info.value).lower()

    def test_missing_labels_validation(self):
        """Test validation fails for missing labels."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "name": "test",
            "description": "Test",
            "annotation_type": "image_annotation",
            "tools": ["bbox"],
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "labels" in str(exc_info.value).lower()

    def test_min_annotations_validation(self):
        """Test validation for min_annotations field."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "name": "test",
            "description": "Test",
            "annotation_type": "image_annotation",
            "tools": ["bbox"],
            "labels": [{"name": "person"}],
            "min_annotations": -1,  # Invalid
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "min_annotations" in str(exc_info.value).lower()


class TestSchemaRegistry:
    """Tests for schema registry integration."""

    def test_image_annotation_registered(self):
        """Test that image_annotation is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("image_annotation")

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "registry_test",
            "description": "Registry test",
            "annotation_type": "image_annotation",
            "tools": ["bbox"],
            "labels": [{"name": "test"}],
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert "registry_test" in html


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
