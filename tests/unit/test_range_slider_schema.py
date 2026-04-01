"""
Unit tests for range_slider annotation schema.

Tests the range_slider schema generator functionality including:
- HTML generation
- Dual-thumb slider elements (low and high)
- Fill element
- Default min/max values
- Custom left/right labels
- show_values option
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.range_slider import (
    generate_range_slider_layout,
    DEFAULT_MIN,
    DEFAULT_MAX,
    DEFAULT_STEP,
)


class TestRangeSliderSchema:
    """Tests for range_slider schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_rs",
            "description": "Test",
            "annotation_type": "range_slider",
        }

        html, keybindings = generate_range_slider_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_rs" in html
        assert "Test" in html
        assert 'data-annotation-type="range_slider"' in html

    def test_low_thumb_present(self):
        """Test that the low thumb input is present."""
        scheme = {
            "name": "test_rs",
            "description": "Test",
            "annotation_type": "range_slider",
        }

        html, _ = generate_range_slider_layout(scheme)

        assert "range-slider-low" in html

    def test_high_thumb_present(self):
        """Test that the high thumb input is present."""
        scheme = {
            "name": "test_rs",
            "description": "Test",
            "annotation_type": "range_slider",
        }

        html, _ = generate_range_slider_layout(scheme)

        assert "range-slider-high" in html

    def test_fill_element_present(self):
        """Test that the fill/track element is present."""
        scheme = {
            "name": "test_rs",
            "description": "Test",
            "annotation_type": "range_slider",
        }

        html, _ = generate_range_slider_layout(scheme)

        assert "range-slider-fill" in html

    def test_default_min_max_values(self):
        """Test that default min (0) and max (100) are embedded in HTML."""
        scheme = {
            "name": "test_rs",
            "description": "Test",
            "annotation_type": "range_slider",
        }

        html, _ = generate_range_slider_layout(scheme)

        assert f'min="{DEFAULT_MIN}"' in html
        assert f'max="{DEFAULT_MAX}"' in html

    def test_custom_min_max_values(self):
        """Test that custom min/max values are applied."""
        scheme = {
            "name": "test_rs_custom",
            "description": "Test",
            "annotation_type": "range_slider",
            "min_value": -10,
            "max_value": 10,
        }

        html, _ = generate_range_slider_layout(scheme)

        assert 'min="-10"' in html
        assert 'max="10"' in html

    def test_custom_left_right_labels(self):
        """Test that custom left and right labels appear in the HTML."""
        scheme = {
            "name": "test_rs_labels",
            "description": "Test",
            "annotation_type": "range_slider",
            "left_label": "Very Low",
            "right_label": "Very High",
        }

        html, _ = generate_range_slider_layout(scheme)

        assert "Very Low" in html
        assert "Very High" in html

    def test_show_values_enabled_by_default(self):
        """Test that value displays are shown by default."""
        scheme = {
            "name": "test_rs",
            "description": "Test",
            "annotation_type": "range_slider",
        }

        html, _ = generate_range_slider_layout(scheme)

        assert "range-slider-val-low" in html
        assert "range-slider-val-high" in html

    def test_show_values_disabled(self):
        """Test that value displays are hidden when show_values=False."""
        scheme = {
            "name": "test_rs_no_vals",
            "description": "Test",
            "annotation_type": "range_slider",
            "show_values": False,
        }

        html, _ = generate_range_slider_layout(scheme)

        assert "range-slider-val-low" not in html
        assert "range-slider-val-high" not in html

    def test_no_keybindings(self):
        """Test that range_slider returns no keybindings."""
        scheme = {
            "name": "test_rs",
            "description": "Test",
            "annotation_type": "range_slider",
        }

        _, keybindings = generate_range_slider_layout(scheme)

        assert keybindings == []

    def test_annotation_input_class(self):
        """Test that slider inputs carry annotation-input class."""
        scheme = {
            "name": "test_rs",
            "description": "Test",
            "annotation_type": "range_slider",
        }

        html, _ = generate_range_slider_layout(scheme)

        assert "annotation-input" in html


class TestRangeSliderSchemaValidation:
    """Tests for range_slider schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "range_slider",
        }

        html, keybindings = generate_range_slider_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "range_slider",
        }

        html, keybindings = generate_range_slider_layout(scheme)
        assert "annotation-error" in html


class TestRangeSliderSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that range_slider is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("range_slider")

    def test_in_supported_types(self):
        """Test that range_slider is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "range_slider" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_rs",
            "description": "Test",
            "annotation_type": "range_slider",
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestRangeSliderConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that range_slider is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "range_slider",
            "name": "test",
            "description": "Test",
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_type_rejected(self):
        """Test that invalid types are still rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "nonexistent_type",
            "name": "test",
            "description": "Test",
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
