"""
Unit tests for Conjoint Analysis annotation schema.

Tests the conjoint schema generator functionality including:
- HTML generation with attributes
- Profiles per set creates correct number of cards
- Show none option
- Attribute names in HTML
- Radio inputs present
- Missing attributes/profiles_field validation
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.conjoint import (
    generate_conjoint_layout,
    DEFAULT_PROFILES_PER_SET,
)


class TestConjointSchema:
    """Tests for conjoint schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with attributes."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [
                {"name": "Color", "levels": ["Red", "Blue", "Green"]},
                {"name": "Size", "levels": ["Small", "Large"]},
            ],
        }

        html, keybindings = generate_conjoint_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_conjoint" in html
        assert 'data-annotation-type="conjoint"' in html

    def test_default_profiles_per_set(self):
        """Test that default profiles_per_set creates 3 cards."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red", "Blue"]}],
        }

        html, _ = generate_conjoint_layout(scheme)

        # Should have profile cards for options 1, 2, 3
        assert 'data-profile="1"' in html
        assert 'data-profile="2"' in html
        assert 'data-profile="3"' in html
        # Should not have a 4th profile card
        assert 'data-profile="4"' not in html

    def test_custom_profiles_per_set(self):
        """Test that custom profiles_per_set creates correct number of cards."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red", "Blue"]}],
            "profiles_per_set": 4,
        }

        html, _ = generate_conjoint_layout(scheme)

        assert 'data-profile="1"' in html
        assert 'data-profile="2"' in html
        assert 'data-profile="3"' in html
        assert 'data-profile="4"' in html
        assert 'data-profile="5"' not in html

    def test_two_profiles(self):
        """Test that profiles_per_set=2 creates exactly 2 cards."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red", "Blue"]}],
            "profiles_per_set": 2,
        }

        html, _ = generate_conjoint_layout(scheme)

        assert 'data-profile="1"' in html
        assert 'data-profile="2"' in html
        assert 'data-profile="3"' not in html

    def test_show_none_option_default(self):
        """Test that 'None of these' option is shown by default."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red", "Blue"]}],
        }

        html, _ = generate_conjoint_layout(scheme)

        assert "None of these" in html
        assert "conjoint-none-option" in html

    def test_show_none_option_false(self):
        """Test that 'None of these' is hidden when disabled."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red", "Blue"]}],
            "show_none_option": False,
        }

        html, _ = generate_conjoint_layout(scheme)

        assert "conjoint-none-option" not in html

    def test_attribute_names_appear(self):
        """Test that attribute names appear in the HTML."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [
                {"name": "Brand", "levels": ["A", "B"]},
                {"name": "Price", "levels": ["Low", "High"]},
                {"name": "Quality", "levels": ["Standard", "Premium"]},
            ],
        }

        html, _ = generate_conjoint_layout(scheme)

        assert "Brand" in html
        assert "Price" in html
        assert "Quality" in html

    def test_radio_inputs_present(self):
        """Test that radio inputs are present for profile selection."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red", "Blue"]}],
        }

        html, _ = generate_conjoint_layout(scheme)

        assert 'type="radio"' in html
        assert "conjoint-radio" in html

    def test_annotation_input_class(self):
        """Test that radio inputs carry annotation-input class."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red", "Blue"]}],
        }

        html, _ = generate_conjoint_layout(scheme)

        assert "annotation-input" in html

    def test_no_keybindings(self):
        """Test that conjoint returns no keybindings."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red", "Blue"]}],
        }

        _, keybindings = generate_conjoint_layout(scheme)

        assert keybindings == []

    def test_profile_header_labels(self):
        """Test that profile cards have Option headers."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red", "Blue"]}],
            "profiles_per_set": 2,
        }

        html, _ = generate_conjoint_layout(scheme)

        assert "Option 1" in html
        assert "Option 2" in html

    def test_profiles_field_data_attribute(self):
        """Test that profiles_field data attribute is set."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "profiles_field": "my_profiles",
            "attributes": [{"name": "Color", "levels": ["Red"]}],
        }

        html, _ = generate_conjoint_layout(scheme)

        assert 'data-profiles-field="my_profiles"' in html

    def test_choose_this_label(self):
        """Test that 'Choose this' label is present on profile cards."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red"]}],
        }

        html, _ = generate_conjoint_layout(scheme)

        assert "Choose this" in html

    def test_default_constant(self):
        """Test that default constant has expected value."""
        assert DEFAULT_PROFILES_PER_SET == 3

    def test_with_profiles_field_only(self):
        """Test generation with profiles_field instead of attributes."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "profiles_field": "profiles",
        }

        html, _ = generate_conjoint_layout(scheme)

        assert html is not None
        assert 'data-annotation-type="conjoint"' in html


class TestConjointSchemaValidation:
    """Tests for conjoint schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red"]}],
        }

        html, keybindings = generate_conjoint_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red"]}],
        }

        html, keybindings = generate_conjoint_layout(scheme)
        assert "annotation-error" in html

    def test_missing_attributes_and_profiles_field_raises_error(self):
        """Test that missing both attributes and profiles_field raises ValueError."""
        scheme = {
            "name": "test_conjoint",
            "description": "Test",
            "annotation_type": "conjoint",
        }

        # Should raise ValueError via safe_generate_layout, returning error HTML
        html, _ = generate_conjoint_layout(scheme)
        assert "annotation-error" in html


class TestConjointSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that conjoint is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("conjoint")

    def test_in_supported_types(self):
        """Test that conjoint is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "conjoint" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_conjoint",
            "description": "Test Conjoint",
            "annotation_type": "conjoint",
            "attributes": [{"name": "Color", "levels": ["Red", "Blue"]}],
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestConjointConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that conjoint is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "conjoint",
            "name": "test",
            "description": "Test",
            "attributes": [{"name": "Color", "levels": ["Red", "Blue"]}],
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_with_profiles_field_accepted(self):
        """Test that profiles_field without attributes is accepted."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "conjoint",
            "name": "test",
            "description": "Test",
            "profiles_field": "profiles",
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_missing_attributes_and_profiles_field_rejected(self):
        """Test that missing both attributes and profiles_field is rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "conjoint",
            "name": "test",
            "description": "Test",
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_empty_attributes_rejected(self):
        """Test that empty attributes list is rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "conjoint",
            "name": "test",
            "description": "Test",
            "attributes": [],
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_attribute_format_rejected(self):
        """Test that attributes without 'name' field is rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "conjoint",
            "name": "test",
            "description": "Test",
            "attributes": [{"levels": ["Red", "Blue"]}],
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_profiles_per_set_rejected(self):
        """Test that profiles_per_set < 2 is rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "conjoint",
            "name": "test",
            "description": "Test",
            "attributes": [{"name": "Color", "levels": ["Red"]}],
            "profiles_per_set": 1,
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
