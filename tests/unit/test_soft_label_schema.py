"""
Unit tests for soft_label annotation schema.

Tests the soft_label schema generator functionality including:
- HTML generation
- Slider elements and label rendering
- Distribution chart toggle
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.soft_label import generate_soft_label_layout


class TestSoftLabelSchema:
    """Tests for soft_label schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_sl",
            "description": "Test",
            "annotation_type": "soft_label",
            "labels": ["A", "B", "C"],
        }

        html, keybindings = generate_soft_label_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_sl" in html
        assert "Test" in html
        assert 'data-annotation-type="soft_label"' in html

    def test_contains_slider_inputs(self):
        """Test that HTML contains soft-label slider inputs."""
        scheme = {
            "name": "test_sl",
            "description": "Test",
            "annotation_type": "soft_label",
            "labels": ["A", "B", "C"],
        }

        html, _ = generate_soft_label_layout(scheme)

        assert "soft-label-slider" in html
        assert "annotation-input" in html

    def test_all_labels_present(self):
        """Test that all label names appear in the HTML."""
        scheme = {
            "name": "test_sl",
            "description": "Test",
            "annotation_type": "soft_label",
            "labels": ["Alpha", "Beta", "Gamma"],
        }

        html, _ = generate_soft_label_layout(scheme)

        assert "Alpha" in html
        assert "Beta" in html
        assert "Gamma" in html

    def test_soft_label_group_attribute(self):
        """Test that sliders carry data-soft-label-group attribute."""
        scheme = {
            "name": "test_sl",
            "description": "Test",
            "annotation_type": "soft_label",
            "labels": ["A", "B"],
        }

        html, _ = generate_soft_label_layout(scheme)

        assert 'data-soft-label-group' in html

    def test_distribution_chart_shown_by_default(self):
        """Test that the distribution chart is shown when show_distribution_chart is not set."""
        scheme = {
            "name": "test_sl",
            "description": "Test",
            "annotation_type": "soft_label",
            "labels": ["A", "B"],
        }

        html, _ = generate_soft_label_layout(scheme)

        assert "soft-label-chart" in html

    def test_distribution_chart_hidden_when_disabled(self):
        """Test that the distribution chart is hidden when show_distribution_chart=False."""
        scheme = {
            "name": "test_sl_no_chart",
            "description": "Test",
            "annotation_type": "soft_label",
            "labels": ["A", "B"],
            "show_distribution_chart": False,
        }

        html, _ = generate_soft_label_layout(scheme)

        assert "soft-label-chart" not in html

    def test_labels_required(self):
        """Test that missing labels produces an error."""
        scheme = {
            "name": "test_sl_no_labels",
            "description": "Test",
            "annotation_type": "soft_label",
        }

        html, _ = generate_soft_label_layout(scheme)

        assert "annotation-error" in html

    def test_no_keybindings(self):
        """Test that soft_label returns no keybindings."""
        scheme = {
            "name": "test_sl",
            "description": "Test",
            "annotation_type": "soft_label",
            "labels": ["A", "B", "C"],
        }

        _, keybindings = generate_soft_label_layout(scheme)

        assert keybindings == []

    def test_annotation_input_class(self):
        """Test that inputs carry annotation-input class."""
        scheme = {
            "name": "test_sl",
            "description": "Test",
            "annotation_type": "soft_label",
            "labels": ["X", "Y"],
        }

        html, _ = generate_soft_label_layout(scheme)

        assert 'class="soft-label-slider annotation-input"' in html

    def test_dict_label_format(self):
        """Test that labels can be provided as dicts with a 'name' key."""
        scheme = {
            "name": "test_sl_dict",
            "description": "Test",
            "annotation_type": "soft_label",
            "labels": [{"name": "Option1"}, {"name": "Option2"}],
        }

        html, _ = generate_soft_label_layout(scheme)

        assert "Option1" in html
        assert "Option2" in html


class TestSoftLabelSchemaValidation:
    """Tests for soft_label schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "soft_label",
            "labels": ["A", "B"],
        }

        html, keybindings = generate_soft_label_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "soft_label",
            "labels": ["A", "B"],
        }

        html, keybindings = generate_soft_label_layout(scheme)
        assert "annotation-error" in html


class TestSoftLabelSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that soft_label is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("soft_label")

    def test_in_supported_types(self):
        """Test that soft_label is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "soft_label" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_sl",
            "description": "Test",
            "annotation_type": "soft_label",
            "labels": ["A", "B", "C"],
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestSoftLabelConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that soft_label is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "soft_label",
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
