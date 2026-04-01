"""
Unit tests for Error Span annotation schema.

Tests the error span schema generator functionality including:
- HTML generation with error types
- Error types in select options
- Default and custom severities
- Show score display
- Popup structure
- Hidden input for data storage
- Error types validation
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.error_span import (
    generate_error_span_layout,
    DEFAULT_SEVERITIES,
    DEFAULT_MAX_SCORE,
)


class TestErrorSpanSchema:
    """Tests for error span schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with error types."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [
                {"name": "Grammar"},
                {"name": "Spelling"},
            ],
        }

        html, keybindings = generate_error_span_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_errors" in html
        assert 'data-annotation-type="error_span"' in html

    def test_error_types_in_select_options(self):
        """Test that error types appear as select options."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [
                {"name": "Grammar"},
                {"name": "Spelling"},
                {"name": "Style"},
            ],
        }

        html, _ = generate_error_span_layout(scheme)

        assert "Grammar" in html
        assert "Spelling" in html
        assert "Style" in html
        assert "error-span-type-select" in html

    def test_error_types_with_subtypes(self):
        """Test that error types with subtypes create optgroups."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [
                {"name": "Grammar", "subtypes": ["Agreement", "Tense"]},
            ],
        }

        html, _ = generate_error_span_layout(scheme)

        assert "<optgroup" in html
        assert "Agreement" in html
        assert "Tense" in html

    def test_default_severities(self):
        """Test that default severities appear in the HTML."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
        }

        html, _ = generate_error_span_layout(scheme)

        assert "Minor" in html
        assert "Major" in html
        assert "Critical" in html

    def test_custom_severities(self):
        """Test that custom severities are rendered."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
            "severities": [
                {"name": "Low", "weight": -1},
                {"name": "High", "weight": -10},
            ],
        }

        html, _ = generate_error_span_layout(scheme)

        assert "Low" in html
        assert "High" in html

    def test_show_score_default_true(self):
        """Test that score display is shown by default."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
        }

        html, _ = generate_error_span_layout(scheme)

        assert "error-span-score" in html
        assert "Score:" in html

    def test_show_score_false(self):
        """Test that score display is hidden when disabled."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
            "show_score": False,
        }

        html, _ = generate_error_span_layout(scheme)

        assert "error-span-score" not in html

    def test_max_score_in_display(self):
        """Test that max score value appears in the score display."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
            "max_score": 50,
        }

        html, _ = generate_error_span_layout(scheme)

        assert "50" in html

    def test_popup_structure(self):
        """Test that error annotation popup is present."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
        }

        html, _ = generate_error_span_layout(scheme)

        assert "error-span-popup" in html
        assert "Annotate Error" in html
        assert "error-span-popup-save" in html
        assert "error-span-popup-cancel" in html

    def test_hidden_input_for_data(self):
        """Test that a hidden input is present for data storage."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
        }

        html, _ = generate_error_span_layout(scheme)

        assert 'type="hidden"' in html
        assert "error-span-data-input" in html

    def test_annotation_input_class(self):
        """Test that inputs carry annotation-input class."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
        }

        html, _ = generate_error_span_layout(scheme)

        assert "annotation-input" in html

    def test_no_keybindings(self):
        """Test that error span returns no keybindings."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
        }

        _, keybindings = generate_error_span_layout(scheme)

        assert keybindings == []

    def test_error_list_section(self):
        """Test that error list section is present."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
        }

        html, _ = generate_error_span_layout(scheme)

        assert "error-span-list" in html
        assert "Marked Errors:" in html

    def test_severity_radio_inputs(self):
        """Test that severity options use radio inputs."""
        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
        }

        html, _ = generate_error_span_layout(scheme)

        assert 'type="radio"' in html
        assert "error-span-severity-option" in html

    def test_default_constants(self):
        """Test that default constants have expected values."""
        assert DEFAULT_MAX_SCORE == 100
        assert len(DEFAULT_SEVERITIES) == 3
        assert DEFAULT_SEVERITIES[0]["name"] == "Minor"


class TestErrorSpanSchemaValidation:
    """Tests for error span schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
        }

        html, keybindings = generate_error_span_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
        }

        html, keybindings = generate_error_span_layout(scheme)
        assert "annotation-error" in html

    def test_missing_error_types_raises_error(self):
        """Test that missing error_types raises ValueError."""
        scheme = {
            "name": "test_errors",
            "description": "Test",
            "annotation_type": "error_span",
            "error_types": [],
        }

        # Empty error_types should raise ValueError via safe_generate_layout
        html, _ = generate_error_span_layout(scheme)
        assert "annotation-error" in html


class TestErrorSpanSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that error_span is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("error_span")

    def test_in_supported_types(self):
        """Test that error_span is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "error_span" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_errors",
            "description": "Test Errors",
            "annotation_type": "error_span",
            "error_types": [{"name": "Grammar"}],
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestErrorSpanConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that error_span is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "error_span",
            "name": "test",
            "description": "Test",
            "error_types": [{"name": "Grammar"}],
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_missing_error_types_rejected(self):
        """Test that missing error_types is rejected by config module."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "error_span",
            "name": "test",
            "description": "Test",
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_empty_error_types_rejected(self):
        """Test that empty error_types list is rejected by config module."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "error_span",
            "name": "test",
            "description": "Test",
            "error_types": [],
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_error_type_format_rejected(self):
        """Test that error_types without 'name' field is rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "error_span",
            "name": "test",
            "description": "Test",
            "error_types": [{"description": "no name field"}],
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
