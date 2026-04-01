"""
Unit tests for VAS (Visual Analog Scale) annotation schema.

Tests the VAS schema generator functionality including:
- HTML generation
- Default and custom range
- Endpoint labels
- Continuous step
- Show value toggle
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.vas import (
    generate_vas_layout,
    DEFAULT_MIN,
    DEFAULT_MAX,
    DEFAULT_SHOW_VALUE,
)


class TestVasSchema:
    """Tests for VAS schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_vas",
            "description": "Test",
            "annotation_type": "vas",
        }

        html, keybindings = generate_vas_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_vas" in html
        assert 'data-annotation-type="vas"' in html

    def test_default_range(self):
        """Test that default range uses 0-100."""
        scheme = {
            "name": "test_vas",
            "description": "Test",
            "annotation_type": "vas",
        }

        html, _ = generate_vas_layout(scheme)

        assert 'min="0"' in html
        assert 'max="100"' in html

    def test_custom_range(self):
        """Test that custom min/max values are rendered."""
        scheme = {
            "name": "test_vas",
            "description": "Test",
            "annotation_type": "vas",
            "min_value": 10,
            "max_value": 200,
        }

        html, _ = generate_vas_layout(scheme)

        assert 'min="10"' in html
        assert 'max="200"' in html

    def test_endpoint_labels(self):
        """Test that left and right endpoint labels are rendered."""
        scheme = {
            "name": "test_vas",
            "description": "Test",
            "annotation_type": "vas",
            "left_label": "No pain",
            "right_label": "Worst pain",
        }

        html, _ = generate_vas_layout(scheme)

        assert "No pain" in html
        assert "Worst pain" in html

    def test_continuous_step(self):
        """Test that step is set to 'any' for continuous values."""
        scheme = {
            "name": "test_vas",
            "description": "Test",
            "annotation_type": "vas",
        }

        html, _ = generate_vas_layout(scheme)

        assert 'step="any"' in html

    def test_show_value_false_default(self):
        """Test that value display is hidden by default."""
        scheme = {
            "name": "test_vas",
            "description": "Test",
            "annotation_type": "vas",
        }

        html, _ = generate_vas_layout(scheme)

        assert "vas-value-display" not in html

    def test_show_value_true(self):
        """Test that show_value=True adds value display element."""
        scheme = {
            "name": "test_vas",
            "description": "Test",
            "annotation_type": "vas",
            "show_value": True,
        }

        html, _ = generate_vas_layout(scheme)

        assert "vas-value-display" in html

    def test_no_keybindings(self):
        """Test that VAS returns no keybindings."""
        scheme = {
            "name": "test_vas",
            "description": "Test",
            "annotation_type": "vas",
        }

        _, keybindings = generate_vas_layout(scheme)

        assert keybindings == []

    def test_annotation_input_class(self):
        """Test that inputs carry annotation-input class."""
        scheme = {
            "name": "test_vas",
            "description": "Test",
            "annotation_type": "vas",
        }

        html, _ = generate_vas_layout(scheme)

        assert "annotation-input" in html

    def test_range_input_type(self):
        """Test that the input is a range type."""
        scheme = {
            "name": "test_vas",
            "description": "Test",
            "annotation_type": "vas",
        }

        html, _ = generate_vas_layout(scheme)

        assert 'type="range"' in html

    def test_description_in_legend(self):
        """Test that description appears in the HTML."""
        scheme = {
            "name": "test_vas",
            "description": "Rate your pain level",
            "annotation_type": "vas",
        }

        html, _ = generate_vas_layout(scheme)

        assert "Rate your pain level" in html

    def test_default_constants(self):
        """Test that default constants have expected values."""
        assert DEFAULT_MIN == 0
        assert DEFAULT_MAX == 100
        assert DEFAULT_SHOW_VALUE is False


class TestVasSchemaValidation:
    """Tests for VAS schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "vas",
        }

        html, keybindings = generate_vas_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "vas",
        }

        html, keybindings = generate_vas_layout(scheme)
        assert "annotation-error" in html


class TestVasSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that vas is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("vas")

    def test_in_supported_types(self):
        """Test that vas is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "vas" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_vas",
            "description": "Test",
            "annotation_type": "vas",
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestVasConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that vas is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "vas",
            "name": "test",
            "description": "Test",
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_range_rejected(self):
        """Test that min >= max is rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "vas",
            "name": "test",
            "description": "Test",
            "min_value": 100,
            "max_value": 10,
        }

        with pytest.raises(ConfigValidationError):
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
