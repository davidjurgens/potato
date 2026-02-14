"""
Unit tests for the annotation form layout system.

Tests cover:
- Layout attribute generation (identifier_utils.py)
- Layout configuration validation (config_module.py)
- Backward compatibility with existing configs
"""

import pytest
from unittest.mock import patch, MagicMock

from potato.server_utils.schemas.identifier_utils import generate_layout_attributes
from potato.server_utils.config_module import (
    validate_layout_config,
    ConfigValidationError
)


class TestGenerateLayoutAttributes:
    """Tests for generate_layout_attributes function."""

    def test_default_attributes(self):
        """Test default layout attributes when no layout config provided."""
        scheme = {"name": "test", "description": "Test"}
        attrs = generate_layout_attributes(scheme)
        assert 'data-grid-columns="1"' in attrs

    def test_column_span_1_to_6(self):
        """Test valid column span values 1-6."""
        for columns in range(1, 7):
            scheme = {"name": "test", "description": "Test", "layout": {"columns": columns}}
            attrs = generate_layout_attributes(scheme)
            assert f'data-grid-columns="{columns}"' in attrs

    def test_column_span_clamped_below_1(self):
        """Test that columns < 1 are clamped to 1."""
        scheme = {"name": "test", "description": "Test", "layout": {"columns": 0}}
        attrs = generate_layout_attributes(scheme)
        assert 'data-grid-columns="1"' in attrs

        scheme["layout"]["columns"] = -5
        attrs = generate_layout_attributes(scheme)
        assert 'data-grid-columns="1"' in attrs

    def test_column_span_clamped_above_6(self):
        """Test that columns > 6 are clamped to 6."""
        scheme = {"name": "test", "description": "Test", "layout": {"columns": 10}}
        attrs = generate_layout_attributes(scheme)
        assert 'data-grid-columns="6"' in attrs

    def test_row_span_values(self):
        """Test row span attribute generation."""
        # Row span 1 (default) should not be included
        scheme = {"name": "test", "description": "Test", "layout": {"rows": 1}}
        attrs = generate_layout_attributes(scheme)
        assert 'data-grid-rows' not in attrs

        # Row span 2-4 should be included
        for rows in range(2, 5):
            scheme["layout"]["rows"] = rows
            attrs = generate_layout_attributes(scheme)
            assert f'data-grid-rows="{rows}"' in attrs

    def test_row_span_clamped_above_4(self):
        """Test that rows > 4 are clamped to 4."""
        scheme = {"name": "test", "description": "Test", "layout": {"rows": 10}}
        attrs = generate_layout_attributes(scheme)
        assert 'data-grid-rows="4"' in attrs

    def test_order_attribute(self):
        """Test explicit ordering attribute generation."""
        scheme = {"name": "test", "description": "Test", "layout": {"order": 5}}
        attrs = generate_layout_attributes(scheme)
        assert 'data-grid-order="5"' in attrs

    def test_order_zero(self):
        """Test order value of 0."""
        scheme = {"name": "test", "description": "Test", "layout": {"order": 0}}
        attrs = generate_layout_attributes(scheme)
        assert 'data-grid-order="0"' in attrs

    def test_min_width_attribute(self):
        """Test minimum width CSS custom property."""
        scheme = {"name": "test", "description": "Test", "layout": {"min_width": "200px"}}
        attrs = generate_layout_attributes(scheme)
        assert 'style="--form-min-width: 200px"' in attrs

    def test_max_width_attribute(self):
        """Test maximum width CSS custom property."""
        scheme = {"name": "test", "description": "Test", "layout": {"max_width": "400px"}}
        attrs = generate_layout_attributes(scheme)
        assert 'style="--form-max-width: 400px"' in attrs

    def test_min_max_width_combined(self):
        """Test both min and max width together."""
        scheme = {"name": "test", "description": "Test", "layout": {"min_width": "200px", "max_width": "400px"}}
        attrs = generate_layout_attributes(scheme)
        assert '--form-min-width: 200px' in attrs
        assert '--form-max-width: 400px' in attrs

    def test_align_self_values(self):
        """Test valid align_self values."""
        valid_alignments = ["start", "center", "end", "stretch"]
        for align in valid_alignments:
            scheme = {"name": "test", "description": "Test", "layout": {"align_self": align}}
            attrs = generate_layout_attributes(scheme)
            assert f'data-align-self="{align}"' in attrs

    def test_align_self_invalid_ignored(self):
        """Test that invalid align_self values are ignored."""
        scheme = {"name": "test", "description": "Test", "layout": {"align_self": "invalid"}}
        attrs = generate_layout_attributes(scheme)
        assert 'data-align-self' not in attrs

    def test_all_attributes_combined(self):
        """Test all layout attributes combined."""
        scheme = {
            "name": "test",
            "description": "Test",
            "layout": {
                "columns": 2,
                "rows": 3,
                "order": 5,
                "min_width": "200px",
                "max_width": "400px",
                "align_self": "center"
            }
        }
        attrs = generate_layout_attributes(scheme)
        assert 'data-grid-columns="2"' in attrs
        assert 'data-grid-rows="3"' in attrs
        assert 'data-grid-order="5"' in attrs
        assert '--form-min-width: 200px' in attrs
        assert '--form-max-width: 400px' in attrs
        assert 'data-align-self="center"' in attrs

    def test_html_escape_width_values(self):
        """Test that width values are properly escaped."""
        scheme = {"name": "test", "description": "Test", "layout": {"min_width": "<script>alert(1)</script>"}}
        attrs = generate_layout_attributes(scheme)
        assert '<script>' not in attrs
        assert '&lt;script&gt;' in attrs


class TestValidateLayoutConfig:
    """Tests for validate_layout_config function."""

    def test_no_layout_config(self):
        """Test that missing layout config passes validation."""
        config_data = {"annotation_schemes": []}
        # Should not raise
        validate_layout_config(config_data)

    def test_layout_must_be_dict(self):
        """Test that layout must be a dictionary."""
        config_data = {"layout": "invalid"}
        with pytest.raises(ConfigValidationError, match="layout must be a dictionary"):
            validate_layout_config(config_data)

    def test_grid_must_be_dict(self):
        """Test that grid section must be a dictionary."""
        config_data = {"layout": {"grid": "invalid"}}
        with pytest.raises(ConfigValidationError, match="layout.grid must be a dictionary"):
            validate_layout_config(config_data)

    def test_grid_columns_valid_range(self):
        """Test that grid.columns accepts values 1-6."""
        for columns in range(1, 7):
            config_data = {"layout": {"grid": {"columns": columns}}}
            # Should not raise
            validate_layout_config(config_data)

    def test_grid_columns_invalid_below(self):
        """Test that grid.columns < 1 is rejected."""
        config_data = {"layout": {"grid": {"columns": 0}}}
        with pytest.raises(ConfigValidationError, match="layout.grid.columns must be an integer between 1 and 6"):
            validate_layout_config(config_data)

    def test_grid_columns_invalid_above(self):
        """Test that grid.columns > 6 is rejected."""
        config_data = {"layout": {"grid": {"columns": 7}}}
        with pytest.raises(ConfigValidationError, match="layout.grid.columns must be an integer between 1 and 6"):
            validate_layout_config(config_data)

    def test_grid_columns_invalid_type(self):
        """Test that non-integer columns is rejected."""
        config_data = {"layout": {"grid": {"columns": "two"}}}
        with pytest.raises(ConfigValidationError, match="layout.grid.columns must be an integer"):
            validate_layout_config(config_data)

    def test_grid_gap_valid(self):
        """Test that valid gap values pass."""
        config_data = {"layout": {"grid": {"gap": "1rem"}}}
        # Should not raise
        validate_layout_config(config_data)

    def test_grid_gap_empty_rejected(self):
        """Test that empty gap value is rejected."""
        config_data = {"layout": {"grid": {"gap": ""}}}
        with pytest.raises(ConfigValidationError, match="layout.grid.gap must be a non-empty CSS value"):
            validate_layout_config(config_data)

    def test_grid_gap_non_string_rejected(self):
        """Test that non-string gap value is rejected."""
        config_data = {"layout": {"grid": {"gap": 16}}}
        with pytest.raises(ConfigValidationError, match="layout.grid.gap must be a non-empty CSS value"):
            validate_layout_config(config_data)

    def test_grid_align_items_valid(self):
        """Test that valid align_items values pass."""
        for align in ["start", "center", "end", "stretch"]:
            config_data = {"layout": {"grid": {"align_items": align}}}
            # Should not raise
            validate_layout_config(config_data)

    def test_grid_align_items_invalid(self):
        """Test that invalid align_items value is rejected."""
        config_data = {"layout": {"grid": {"align_items": "invalid"}}}
        with pytest.raises(ConfigValidationError, match="layout.grid.align_items must be one of"):
            validate_layout_config(config_data)

    def test_breakpoints_must_be_dict(self):
        """Test that breakpoints must be a dictionary."""
        config_data = {"layout": {"breakpoints": "invalid"}}
        with pytest.raises(ConfigValidationError, match="layout.breakpoints must be a dictionary"):
            validate_layout_config(config_data)

    def test_breakpoints_mobile_valid(self):
        """Test that valid mobile breakpoint passes."""
        config_data = {"layout": {"breakpoints": {"mobile": 480}}}
        # Should not raise
        validate_layout_config(config_data)

    def test_breakpoints_mobile_negative_rejected(self):
        """Test that negative mobile breakpoint is rejected."""
        config_data = {"layout": {"breakpoints": {"mobile": -100}}}
        with pytest.raises(ConfigValidationError, match="layout.breakpoints.mobile must be a non-negative integer"):
            validate_layout_config(config_data)

    def test_groups_must_be_list(self):
        """Test that groups must be a list."""
        config_data = {"layout": {"groups": {"id": "test"}}}
        with pytest.raises(ConfigValidationError, match="layout.groups must be a list"):
            validate_layout_config(config_data)

    def test_group_must_be_dict(self):
        """Test that each group must be a dictionary."""
        config_data = {"layout": {"groups": ["invalid"]}}
        with pytest.raises(ConfigValidationError, match="layout.groups\\[0\\] must be a dictionary"):
            validate_layout_config(config_data)

    def test_group_requires_id(self):
        """Test that groups require an id field."""
        config_data = {"layout": {"groups": [{"schemas": ["test"]}]}}
        with pytest.raises(ConfigValidationError, match="layout.groups\\[0\\] missing required 'id' field"):
            validate_layout_config(config_data)

    def test_group_id_must_be_nonempty_string(self):
        """Test that group id must be a non-empty string."""
        config_data = {"layout": {"groups": [{"id": "", "schemas": ["test"]}]}}
        with pytest.raises(ConfigValidationError, match="layout.groups\\[0\\].id must be a non-empty string"):
            validate_layout_config(config_data)

    def test_group_duplicate_id_rejected(self):
        """Test that duplicate group ids are rejected."""
        config_data = {
            "layout": {
                "groups": [
                    {"id": "test", "schemas": ["a"]},
                    {"id": "test", "schemas": ["b"]}
                ]
            },
            "annotation_schemes": [
                {"name": "a", "description": "A", "annotation_type": "radio", "labels": ["x"]},
                {"name": "b", "description": "B", "annotation_type": "radio", "labels": ["y"]}
            ]
        }
        with pytest.raises(ConfigValidationError, match="layout.groups\\[1\\].id 'test' is duplicate"):
            validate_layout_config(config_data)

    def test_group_requires_schemas(self):
        """Test that groups require a schemas field."""
        config_data = {"layout": {"groups": [{"id": "test"}]}}
        with pytest.raises(ConfigValidationError, match="layout.groups\\[0\\] missing required 'schemas' field"):
            validate_layout_config(config_data)

    def test_group_schemas_must_be_list(self):
        """Test that group schemas must be a list."""
        config_data = {"layout": {"groups": [{"id": "test", "schemas": "invalid"}]}}
        with pytest.raises(ConfigValidationError, match="layout.groups\\[0\\].schemas must be a list"):
            validate_layout_config(config_data)

    def test_group_schemas_cannot_be_empty(self):
        """Test that group schemas cannot be empty."""
        config_data = {"layout": {"groups": [{"id": "test", "schemas": []}]}}
        with pytest.raises(ConfigValidationError, match="layout.groups\\[0\\].schemas cannot be empty"):
            validate_layout_config(config_data)

    def test_group_references_valid_schema(self):
        """Test that group schemas reference existing annotation schemes."""
        config_data = {
            "layout": {
                "groups": [{"id": "test", "schemas": ["sentiment"]}]
            },
            "annotation_schemes": [
                {"name": "sentiment", "description": "Sentiment", "annotation_type": "radio", "labels": ["pos", "neg"]}
            ]
        }
        # Should not raise
        validate_layout_config(config_data)

    def test_group_references_unknown_schema(self):
        """Test that group referencing unknown schema is rejected."""
        config_data = {
            "layout": {
                "groups": [{"id": "test", "schemas": ["unknown"]}]
            },
            "annotation_schemes": [
                {"name": "sentiment", "description": "Sentiment", "annotation_type": "radio", "labels": ["pos", "neg"]}
            ]
        }
        with pytest.raises(ConfigValidationError, match="layout.groups\\[0\\].schemas references unknown schema: 'unknown'"):
            validate_layout_config(config_data)

    def test_group_collapsible_must_be_bool(self):
        """Test that collapsible must be a boolean."""
        config_data = {
            "layout": {
                "groups": [{"id": "test", "schemas": ["a"], "collapsible": "yes"}]
            },
            "annotation_schemes": [
                {"name": "a", "description": "A", "annotation_type": "radio", "labels": ["x"]}
            ]
        }
        with pytest.raises(ConfigValidationError, match="layout.groups\\[0\\].collapsible must be a boolean"):
            validate_layout_config(config_data)

    def test_group_collapsed_default_must_be_bool(self):
        """Test that collapsed_default must be a boolean."""
        config_data = {
            "layout": {
                "groups": [{"id": "test", "schemas": ["a"], "collapsed_default": 1}]
            },
            "annotation_schemes": [
                {"name": "a", "description": "A", "annotation_type": "radio", "labels": ["x"]}
            ]
        }
        with pytest.raises(ConfigValidationError, match="layout.groups\\[0\\].collapsed_default must be a boolean"):
            validate_layout_config(config_data)

    def test_order_must_be_list(self):
        """Test that order must be a list."""
        config_data = {"layout": {"order": "a, b, c"}}
        with pytest.raises(ConfigValidationError, match="layout.order must be a list"):
            validate_layout_config(config_data)

    def test_order_items_must_be_strings(self):
        """Test that order items must be strings."""
        config_data = {"layout": {"order": ["a", 123, "b"]}}
        with pytest.raises(ConfigValidationError, match="layout.order\\[1\\] must be a string"):
            validate_layout_config(config_data)

    def test_valid_layout_config(self):
        """Test a complete valid layout configuration."""
        config_data = {
            "layout": {
                "grid": {
                    "columns": 3,
                    "gap": "1.5rem",
                    "row_gap": "2rem",
                    "align_items": "start"
                },
                "breakpoints": {
                    "mobile": 480,
                    "tablet": 768
                },
                "groups": [
                    {
                        "id": "primary",
                        "title": "Primary",
                        "description": "Main annotations",
                        "collapsible": True,
                        "collapsed_default": False,
                        "schemas": ["sentiment", "topic"]
                    }
                ],
                "order": ["sentiment", "topic", "confidence"]
            },
            "annotation_schemes": [
                {"name": "sentiment", "description": "Sentiment", "annotation_type": "radio", "labels": ["pos", "neg"]},
                {"name": "topic", "description": "Topic", "annotation_type": "multiselect", "labels": ["a", "b"]},
                {"name": "confidence", "description": "Confidence", "annotation_type": "likert", "min_label": "Low", "max_label": "High", "size": 5}
            ]
        }
        # Should not raise
        validate_layout_config(config_data)


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing configs."""

    def test_config_without_layout_works(self):
        """Test that configs without layout section still work."""
        scheme = {"name": "test", "description": "Test", "annotation_type": "radio"}
        attrs = generate_layout_attributes(scheme)
        # Should return valid default attributes
        assert 'data-grid-columns="1"' in attrs

    def test_empty_layout_section_works(self):
        """Test that empty layout section works."""
        scheme = {"name": "test", "description": "Test", "layout": {}}
        attrs = generate_layout_attributes(scheme)
        # Should return valid default attributes
        assert 'data-grid-columns="1"' in attrs

    def test_partial_layout_config_works(self):
        """Test that partial layout config works."""
        scheme = {"name": "test", "description": "Test", "layout": {"columns": 2}}
        attrs = generate_layout_attributes(scheme)
        assert 'data-grid-columns="2"' in attrs
        # Other attributes should use defaults
        assert 'data-grid-rows' not in attrs
        assert 'data-grid-order' not in attrs
