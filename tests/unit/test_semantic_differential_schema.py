"""
Unit tests for semantic_differential annotation schema.

Tests the semantic_differential schema generator functionality including:
- HTML generation
- Bipolar pair rows
- Default 7-point scale
- Pole labels rendering
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.semantic_differential import (
    generate_semantic_differential_layout,
    DEFAULT_SCALE_POINTS,
)


class TestSemanticDifferentialSchema:
    """Tests for semantic_differential schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_sd",
            "description": "Test",
            "annotation_type": "semantic_differential",
            "pairs": [["Good", "Bad"], ["Strong", "Weak"]],
        }

        html, keybindings = generate_semantic_differential_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_sd" in html
        assert "Test" in html
        assert 'data-annotation-type="semantic_differential"' in html

    def test_two_rows_for_two_pairs(self):
        """Test that two pairs produce two semantic-differential-row divs."""
        scheme = {
            "name": "test_sd",
            "description": "Test",
            "annotation_type": "semantic_differential",
            "pairs": [["Good", "Bad"], ["Strong", "Weak"]],
        }

        html, _ = generate_semantic_differential_layout(scheme)

        assert html.count('class="semantic-differential-row"') == 2

    def test_pole_labels_present(self):
        """Test that all four pole labels appear in the HTML."""
        scheme = {
            "name": "test_sd",
            "description": "Test",
            "annotation_type": "semantic_differential",
            "pairs": [["Good", "Bad"], ["Strong", "Weak"]],
        }

        html, _ = generate_semantic_differential_layout(scheme)

        assert "Good" in html
        assert "Bad" in html
        assert "Strong" in html
        assert "Weak" in html

    def test_semantic_differential_radio_inputs(self):
        """Test that radio inputs with semantic-differential-radio class are present."""
        scheme = {
            "name": "test_sd",
            "description": "Test",
            "annotation_type": "semantic_differential",
            "pairs": [["Good", "Bad"]],
        }

        html, _ = generate_semantic_differential_layout(scheme)

        assert "semantic-differential-radio" in html

    def test_default_seven_scale_points(self):
        """Test that the default scale has 7 points."""
        scheme = {
            "name": "test_sd",
            "description": "Test",
            "annotation_type": "semantic_differential",
            "pairs": [["Good", "Bad"]],
        }

        html, _ = generate_semantic_differential_layout(scheme)

        # 7 radio buttons with values 1-7
        assert 'value="1"' in html
        assert 'value="7"' in html
        assert 'value="8"' not in html

    def test_custom_scale_points(self):
        """Test that scale_points configures the number of radio buttons."""
        scheme = {
            "name": "test_sd_5pt",
            "description": "Test",
            "annotation_type": "semantic_differential",
            "pairs": [["Happy", "Sad"]],
            "scale_points": 5,
        }

        html, _ = generate_semantic_differential_layout(scheme)

        assert 'value="5"' in html
        assert 'value="6"' not in html

    def test_pairs_required(self):
        """Test that missing pairs produces an error."""
        scheme = {
            "name": "test_sd_no_pairs",
            "description": "Test",
            "annotation_type": "semantic_differential",
        }

        html, _ = generate_semantic_differential_layout(scheme)

        assert "annotation-error" in html

    def test_invalid_pair_format(self):
        """Test that a pair with wrong length (not 2 elements) produces an error."""
        scheme = {
            "name": "test_sd_bad_pair",
            "description": "Test",
            "annotation_type": "semantic_differential",
            "pairs": [["OnlyOne"]],
        }

        html, _ = generate_semantic_differential_layout(scheme)

        assert "annotation-error" in html

    def test_no_keybindings(self):
        """Test that semantic_differential returns no keybindings."""
        scheme = {
            "name": "test_sd",
            "description": "Test",
            "annotation_type": "semantic_differential",
            "pairs": [["Good", "Bad"]],
        }

        _, keybindings = generate_semantic_differential_layout(scheme)

        assert keybindings == []

    def test_annotation_input_class(self):
        """Test that radio inputs carry annotation-input class."""
        scheme = {
            "name": "test_sd",
            "description": "Test",
            "annotation_type": "semantic_differential",
            "pairs": [["Good", "Bad"]],
        }

        html, _ = generate_semantic_differential_layout(scheme)

        assert "annotation-input" in html


class TestSemanticDifferentialSchemaValidation:
    """Tests for semantic_differential schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "semantic_differential",
            "pairs": [["Good", "Bad"]],
        }

        html, keybindings = generate_semantic_differential_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "semantic_differential",
            "pairs": [["Good", "Bad"]],
        }

        html, keybindings = generate_semantic_differential_layout(scheme)
        assert "annotation-error" in html


class TestSemanticDifferentialSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that semantic_differential is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("semantic_differential")

    def test_in_supported_types(self):
        """Test that semantic_differential is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "semantic_differential" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_sd",
            "description": "Test",
            "annotation_type": "semantic_differential",
            "pairs": [["Good", "Bad"]],
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestSemanticDifferentialConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that semantic_differential is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "semantic_differential",
            "name": "test",
            "description": "Test",
            "pairs": [["Good", "Bad"]],
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
