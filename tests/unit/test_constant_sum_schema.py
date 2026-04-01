"""
Unit tests for constant_sum annotation schema.

Tests the constant_sum schema generator functionality including:
- HTML generation
- Number inputs and slider input_type option
- Labels rendering
- Sum constraint data attributes
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.constant_sum import (
    generate_constant_sum_layout,
    DEFAULT_TOTAL_POINTS,
    DEFAULT_INPUT_TYPE,
)


class TestConstantSumSchema:
    """Tests for constant_sum schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_cs",
            "description": "Test",
            "annotation_type": "constant_sum",
            "labels": ["X", "Y", "Z"],
        }

        html, keybindings = generate_constant_sum_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_cs" in html
        assert "Test" in html
        assert 'data-annotation-type="constant_sum"' in html

    def test_contains_number_inputs_by_default(self):
        """Test that HTML contains number inputs by default."""
        scheme = {
            "name": "test_cs",
            "description": "Test",
            "annotation_type": "constant_sum",
            "labels": ["X", "Y", "Z"],
        }

        html, _ = generate_constant_sum_layout(scheme)

        assert 'type="number"' in html

    def test_slider_input_type(self):
        """Test that input_type=slider produces range inputs."""
        scheme = {
            "name": "test_cs_slider",
            "description": "Test",
            "annotation_type": "constant_sum",
            "labels": ["X", "Y"],
            "input_type": "slider",
        }

        html, _ = generate_constant_sum_layout(scheme)

        assert 'type="range"' in html
        assert "constant-sum-slider" in html

    def test_constant_sum_group_attribute(self):
        """Test that inputs carry data-constant-sum-group attribute."""
        scheme = {
            "name": "test_cs",
            "description": "Test",
            "annotation_type": "constant_sum",
            "labels": ["X", "Y", "Z"],
        }

        html, _ = generate_constant_sum_layout(scheme)

        assert 'data-constant-sum-group' in html

    def test_all_labels_present(self):
        """Test that all label names appear in the HTML."""
        scheme = {
            "name": "test_cs",
            "description": "Test",
            "annotation_type": "constant_sum",
            "labels": ["Alpha", "Beta", "Gamma"],
        }

        html, _ = generate_constant_sum_layout(scheme)

        assert "Alpha" in html
        assert "Beta" in html
        assert "Gamma" in html

    def test_labels_required(self):
        """Test that missing labels produces an error."""
        scheme = {
            "name": "test_cs_no_labels",
            "description": "Test",
            "annotation_type": "constant_sum",
        }

        html, _ = generate_constant_sum_layout(scheme)

        assert "annotation-error" in html

    def test_no_keybindings(self):
        """Test that constant_sum returns no keybindings."""
        scheme = {
            "name": "test_cs",
            "description": "Test",
            "annotation_type": "constant_sum",
            "labels": ["X", "Y", "Z"],
        }

        _, keybindings = generate_constant_sum_layout(scheme)

        assert keybindings == []

    def test_annotation_input_class(self):
        """Test that inputs carry annotation-input class."""
        scheme = {
            "name": "test_cs",
            "description": "Test",
            "annotation_type": "constant_sum",
            "labels": ["X", "Y"],
        }

        html, _ = generate_constant_sum_layout(scheme)

        assert "annotation-input" in html

    def test_default_total_in_html(self):
        """Test that the default total points is embedded in HTML."""
        scheme = {
            "name": "test_cs",
            "description": "Test",
            "annotation_type": "constant_sum",
            "labels": ["X", "Y"],
        }

        html, _ = generate_constant_sum_layout(scheme)

        assert str(DEFAULT_TOTAL_POINTS) in html

    def test_dict_label_format(self):
        """Test that labels can be provided as dicts with a 'name' key."""
        scheme = {
            "name": "test_cs_dict",
            "description": "Test",
            "annotation_type": "constant_sum",
            "labels": [{"name": "Category1"}, {"name": "Category2"}],
        }

        html, _ = generate_constant_sum_layout(scheme)

        assert "Category1" in html
        assert "Category2" in html


class TestConstantSumSchemaValidation:
    """Tests for constant_sum schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "constant_sum",
            "labels": ["X", "Y"],
        }

        html, keybindings = generate_constant_sum_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "constant_sum",
            "labels": ["X", "Y"],
        }

        html, keybindings = generate_constant_sum_layout(scheme)
        assert "annotation-error" in html


class TestConstantSumSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that constant_sum is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("constant_sum")

    def test_in_supported_types(self):
        """Test that constant_sum is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "constant_sum" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_cs",
            "description": "Test",
            "annotation_type": "constant_sum",
            "labels": ["X", "Y", "Z"],
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestConstantSumConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that constant_sum is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "constant_sum",
            "name": "test",
            "description": "Test",
            "labels": ["A", "B"],
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
