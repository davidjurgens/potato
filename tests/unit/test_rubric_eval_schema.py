"""
Unit tests for Rubric Evaluation annotation schema.

Tests the rubric eval schema generator functionality including:
- HTML generation with criteria
- Default and custom scale points
- Custom scale labels
- Show overall row
- Radio inputs for each cell
- Criteria validation
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.rubric_eval import (
    generate_rubric_eval_layout,
    DEFAULT_SCALE_POINTS,
    DEFAULT_SCALE_LABELS,
)


class TestRubricEvalSchema:
    """Tests for rubric eval schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with criteria."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [
                {"name": "clarity", "description": "How clear is the text?"},
                {"name": "accuracy", "description": "How accurate is the content?"},
            ],
        }

        html, keybindings = generate_rubric_eval_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_rubric" in html
        assert 'data-annotation-type="rubric_eval"' in html

    def test_criteria_names_appear(self):
        """Test that criteria names appear in the HTML."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [
                {"name": "fluency", "description": "How fluent?"},
                {"name": "relevance", "description": "How relevant?"},
            ],
        }

        html, _ = generate_rubric_eval_layout(scheme)

        assert "fluency" in html
        assert "relevance" in html

    def test_criteria_descriptions_appear(self):
        """Test that criteria descriptions appear in the HTML."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [
                {"name": "clarity", "description": "Is the writing clear?"},
            ],
        }

        html, _ = generate_rubric_eval_layout(scheme)

        assert "Is the writing clear?" in html

    def test_default_five_scale_points(self):
        """Test that the default scale has 5 points."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "quality"}],
        }

        html, _ = generate_rubric_eval_layout(scheme)

        # Should have radio values 1-5
        assert 'value="1"' in html
        assert 'value="5"' in html
        assert 'value="6"' not in html

    def test_custom_scale_points(self):
        """Test that custom scale_points configures the number of radio buttons."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "quality"}],
            "scale_points": 7,
        }

        html, _ = generate_rubric_eval_layout(scheme)

        assert 'value="7"' in html
        assert 'value="8"' not in html

    def test_default_scale_labels(self):
        """Test that default scale labels appear in the HTML."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "quality"}],
        }

        html, _ = generate_rubric_eval_layout(scheme)

        # Default labels: Poor, Below Average, Average, Good, Excellent
        assert DEFAULT_SCALE_LABELS[0] in html  # "Poor"
        assert DEFAULT_SCALE_LABELS[-1] in html  # "Excellent"

    def test_custom_scale_labels(self):
        """Test that custom scale labels are rendered."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "quality"}],
            "scale_points": 3,
            "scale_labels": ["Bad", "OK", "Great"],
        }

        html, _ = generate_rubric_eval_layout(scheme)

        assert "Bad" in html
        assert "OK" in html
        assert "Great" in html

    def test_show_overall_adds_row(self):
        """Test that show_overall adds an 'overall' row."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "clarity"}],
            "show_overall": True,
        }

        html, _ = generate_rubric_eval_layout(scheme)

        assert "overall" in html.lower()
        assert "rubric-overall-row" in html

    def test_show_overall_false_no_row(self):
        """Test that show_overall=False omits the overall row."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "clarity"}],
            "show_overall": False,
        }

        html, _ = generate_rubric_eval_layout(scheme)

        assert "rubric-overall-row" not in html

    def test_radio_inputs_present(self):
        """Test that radio inputs are present for each criterion cell."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "quality"}],
        }

        html, _ = generate_rubric_eval_layout(scheme)

        assert 'type="radio"' in html
        assert "rubric-radio" in html

    def test_annotation_input_class(self):
        """Test that radio inputs carry annotation-input class."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "quality"}],
        }

        html, _ = generate_rubric_eval_layout(scheme)

        assert "annotation-input" in html

    def test_no_keybindings(self):
        """Test that rubric eval returns no keybindings."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "quality"}],
        }

        _, keybindings = generate_rubric_eval_layout(scheme)

        assert keybindings == []

    def test_table_structure(self):
        """Test that rubric generates a table structure."""
        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "quality"}],
        }

        html, _ = generate_rubric_eval_layout(scheme)

        assert "rubric-table" in html
        assert "<thead>" in html
        assert "<tbody>" in html

    def test_default_constants(self):
        """Test that default constants have expected values."""
        assert DEFAULT_SCALE_POINTS == 5
        assert len(DEFAULT_SCALE_LABELS) == 5


class TestRubricEvalSchemaValidation:
    """Tests for rubric eval schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "quality"}],
        }

        html, keybindings = generate_rubric_eval_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "quality"}],
        }

        html, keybindings = generate_rubric_eval_layout(scheme)
        assert "annotation-error" in html

    def test_missing_criteria_raises_error(self):
        """Test that missing criteria raises ValueError."""
        scheme = {
            "name": "test_rubric",
            "description": "Test",
            "annotation_type": "rubric_eval",
            "criteria": [],
        }

        # Empty criteria list should raise ValueError via safe_generate_layout
        # which catches it and returns error HTML
        html, _ = generate_rubric_eval_layout(scheme)
        assert "annotation-error" in html


class TestRubricEvalSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that rubric_eval is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("rubric_eval")

    def test_in_supported_types(self):
        """Test that rubric_eval is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "rubric_eval" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_rubric",
            "description": "Test Rubric",
            "annotation_type": "rubric_eval",
            "criteria": [{"name": "quality", "description": "Overall quality"}],
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestRubricEvalConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that rubric_eval is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "rubric_eval",
            "name": "test",
            "description": "Test",
            "criteria": [{"name": "quality"}],
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_missing_criteria_rejected(self):
        """Test that missing criteria is rejected by config module."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "rubric_eval",
            "name": "test",
            "description": "Test",
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_empty_criteria_rejected(self):
        """Test that empty criteria list is rejected by config module."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "rubric_eval",
            "name": "test",
            "description": "Test",
            "criteria": [],
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_criteria_format_rejected(self):
        """Test that criteria without 'name' field is rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "rubric_eval",
            "name": "test",
            "description": "Test",
            "criteria": [{"description": "no name field"}],
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
