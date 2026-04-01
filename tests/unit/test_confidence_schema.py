"""
Unit tests for confidence annotation schema.

Tests the confidence schema generator functionality including:
- HTML generation
- Likert vs slider mode
- Default 5-point scale
- Custom labels
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.confidence import (
    generate_confidence_layout,
    DEFAULT_SCALE_POINTS,
    DEFAULT_SCALE_TYPE,
    DEFAULT_LABELS,
)


class TestConfidenceSchema:
    """Tests for confidence schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_conf",
            "description": "Test",
            "annotation_type": "confidence",
        }

        html, keybindings = generate_confidence_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_conf" in html
        assert "Test" in html
        assert 'data-annotation-type="confidence"' in html

    def test_default_likert_mode(self):
        """Test that Likert mode is the default."""
        scheme = {
            "name": "test_conf",
            "description": "Test",
            "annotation_type": "confidence",
        }

        html, _ = generate_confidence_layout(scheme)

        assert "confidence-radio" in html

    def test_slider_mode(self):
        """Test that slider mode produces a slider input."""
        scheme = {
            "name": "test_conf_slider",
            "description": "Test",
            "annotation_type": "confidence",
            "scale_type": "slider",
        }

        html, _ = generate_confidence_layout(scheme)

        assert "confidence-slider" in html

    def test_default_five_scale_points(self):
        """Test that the default scale has 5 points."""
        scheme = {
            "name": "test_conf",
            "description": "Test",
            "annotation_type": "confidence",
        }

        html, _ = generate_confidence_layout(scheme)

        # There should be 5 radio buttons (values 1-5)
        assert 'value="1"' in html
        assert 'value="5"' in html
        assert 'value="6"' not in html

    def test_custom_scale_points(self):
        """Test that scale_points configures the number of radio buttons."""
        scheme = {
            "name": "test_conf_7",
            "description": "Test",
            "annotation_type": "confidence",
            "scale_points": 7,
        }

        html, _ = generate_confidence_layout(scheme)

        assert 'value="7"' in html
        assert 'value="8"' not in html

    def test_default_labels_present(self):
        """Test that default scale labels appear in the HTML."""
        scheme = {
            "name": "test_conf",
            "description": "Test",
            "annotation_type": "confidence",
        }

        html, _ = generate_confidence_layout(scheme)

        # At least some default labels should be present
        assert DEFAULT_LABELS[0] in html  # "Guessing"
        assert DEFAULT_LABELS[-1] in html  # "Certain"

    def test_custom_labels(self):
        """Test that custom scale labels are rendered."""
        scheme = {
            "name": "test_conf_custom",
            "description": "Test",
            "annotation_type": "confidence",
            "labels": ["Low", "Medium", "High"],
            "scale_points": 3,
        }

        html, _ = generate_confidence_layout(scheme)

        assert "Low" in html
        assert "Medium" in html
        assert "High" in html

    def test_no_keybindings(self):
        """Test that confidence returns no keybindings."""
        scheme = {
            "name": "test_conf",
            "description": "Test",
            "annotation_type": "confidence",
        }

        _, keybindings = generate_confidence_layout(scheme)

        assert keybindings == []

    def test_annotation_input_class(self):
        """Test that inputs carry annotation-input class."""
        scheme = {
            "name": "test_conf",
            "description": "Test",
            "annotation_type": "confidence",
        }

        html, _ = generate_confidence_layout(scheme)

        assert "annotation-input" in html

    def test_slider_custom_labels(self):
        """Test that slider mode uses custom left/right labels."""
        scheme = {
            "name": "test_conf_slider_labels",
            "description": "Test",
            "annotation_type": "confidence",
            "scale_type": "slider",
            "left_label": "Not Sure",
            "right_label": "Absolutely Sure",
        }

        html, _ = generate_confidence_layout(scheme)

        assert "Not Sure" in html
        assert "Absolutely Sure" in html


class TestConfidenceSchemaValidation:
    """Tests for confidence schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "confidence",
        }

        html, keybindings = generate_confidence_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "confidence",
        }

        html, keybindings = generate_confidence_layout(scheme)
        assert "annotation-error" in html


class TestConfidenceSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that confidence is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("confidence")

    def test_in_supported_types(self):
        """Test that confidence is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "confidence" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_conf",
            "description": "Test",
            "annotation_type": "confidence",
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestConfidenceConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that confidence is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "confidence",
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
