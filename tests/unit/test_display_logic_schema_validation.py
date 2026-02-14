"""
Unit tests for display logic schema validation.

Tests that incompatible operator-schema combinations are detected and
generate helpful error messages at config validation time.
"""

import pytest
from potato.server_utils.config_module import (
    validate_yaml_structure,
    validate_display_logic_structure,
    ConfigValidationError,
)
from potato.server_utils.display_logic import (
    DisplayLogicValidator,
    DisplayLogicCondition,
    SUPPORTED_OPERATORS,
)


class TestOperatorValidation:
    """Test validation of operators in display_logic conditions."""

    def create_config(self, tmp_path, annotation_schemes):
        """Helper to create a basic config structure."""
        return {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": annotation_schemes
        }

    def test_valid_equals_operator(self, tmp_path):
        """Test that valid equals operator passes validation."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "radio", "name": "choice", "description": "Choice", "labels": ["A", "B"]},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "choice", "operator": "equals", "value": "A"}]
                }
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))

    def test_invalid_operator_raises_error(self, tmp_path):
        """Test that invalid operator raises ConfigValidationError with helpful message."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "radio", "name": "choice", "description": "Choice", "labels": ["A", "B"]},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "choice", "operator": "invalid_operator", "value": "A"}]
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        error_msg = str(exc_info.value)
        assert "invalid_operator" in error_msg
        assert "not supported" in error_msg.lower() or "valid operators" in error_msg.lower()

    def test_missing_operator_raises_error(self, tmp_path):
        """Test that missing operator field raises error."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "radio", "name": "choice", "description": "Choice", "labels": ["A", "B"]},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "choice", "value": "A"}]  # Missing operator
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "operator" in str(exc_info.value).lower()

    def test_missing_schema_raises_error(self, tmp_path):
        """Test that missing schema field raises error."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "radio", "name": "choice", "description": "Choice", "labels": ["A", "B"]},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"operator": "equals", "value": "A"}]  # Missing schema
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "schema" in str(exc_info.value).lower()


class TestNumericOperatorValidation:
    """Test validation of numeric operators."""

    def create_config(self, tmp_path, annotation_schemes):
        """Helper to create a basic config structure."""
        return {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": annotation_schemes
        }

    def test_gt_requires_numeric_value(self, tmp_path):
        """Test that gt operator requires numeric value."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "slider", "name": "score", "description": "Score",
             "min_value": 1, "max_value": 10, "starting_value": 5},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "score", "operator": "gt", "value": "not_a_number"}]
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        error_msg = str(exc_info.value)
        assert "numeric" in error_msg.lower() or "number" in error_msg.lower()

    def test_lt_requires_numeric_value(self, tmp_path):
        """Test that lt operator requires numeric value."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "slider", "name": "score", "description": "Score",
             "min_value": 1, "max_value": 10, "starting_value": 5},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "score", "operator": "lt", "value": "abc"}]
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "numeric" in str(exc_info.value).lower()

    def test_gte_with_valid_numeric(self, tmp_path):
        """Test that gte operator works with valid numeric value."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "slider", "name": "score", "description": "Score",
             "min_value": 1, "max_value": 10, "starting_value": 5},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "score", "operator": "gte", "value": 5}]
                }
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))

    def test_lte_with_float_value(self, tmp_path):
        """Test that lte operator works with float value."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "slider", "name": "score", "description": "Score",
             "min_value": 1, "max_value": 10, "starting_value": 5},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "score", "operator": "lte", "value": 7.5}]
                }
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))


class TestRangeOperatorValidation:
    """Test validation of range operators."""

    def create_config(self, tmp_path, annotation_schemes):
        """Helper to create a basic config structure."""
        return {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": annotation_schemes
        }

    def test_in_range_requires_list(self, tmp_path):
        """Test that in_range requires a list value."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "slider", "name": "score", "description": "Score",
             "min_value": 1, "max_value": 10, "starting_value": 5},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "score", "operator": "in_range", "value": 5}]  # Not a list
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        error_msg = str(exc_info.value)
        assert "range" in error_msg.lower() or "[min, max]" in error_msg.lower()

    def test_in_range_requires_two_values(self, tmp_path):
        """Test that in_range requires exactly 2 values."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "slider", "name": "score", "description": "Score",
             "min_value": 1, "max_value": 10, "starting_value": 5},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "score", "operator": "in_range", "value": [1, 5, 10]}]  # 3 values
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "2" in str(exc_info.value) or "two" in str(exc_info.value).lower()

    def test_in_range_min_greater_than_max(self, tmp_path):
        """Test that in_range catches min > max."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "slider", "name": "score", "description": "Score",
             "min_value": 1, "max_value": 10, "starting_value": 5},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "score", "operator": "in_range", "value": [10, 5]}]  # Wrong order
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        error_msg = str(exc_info.value)
        assert "greater than max" in error_msg.lower() or "min" in error_msg.lower()

    def test_not_in_range_validates_same_as_in_range(self, tmp_path):
        """Test that not_in_range has same validation as in_range."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "slider", "name": "score", "description": "Score",
             "min_value": 1, "max_value": 10, "starting_value": 5},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "score", "operator": "not_in_range", "value": "invalid"}]
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "range" in str(exc_info.value).lower()

    def test_valid_in_range(self, tmp_path):
        """Test that valid in_range passes validation."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "slider", "name": "score", "description": "Score",
             "min_value": 1, "max_value": 10, "starting_value": 5},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "score", "operator": "in_range", "value": [3, 7]}]
                }
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))


class TestRegexOperatorValidation:
    """Test validation of regex (matches) operator."""

    def create_config(self, tmp_path, annotation_schemes):
        """Helper to create a basic config structure."""
        return {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": annotation_schemes
        }

    def test_matches_requires_value(self, tmp_path):
        """Test that matches operator requires a value."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "text", "name": "input", "description": "Input"},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "input", "operator": "matches"}]  # Missing value
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "requires" in str(exc_info.value).lower()

    def test_matches_invalid_regex_pattern(self, tmp_path):
        """Test that invalid regex pattern raises error with helpful message."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "text", "name": "input", "description": "Input"},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "input", "operator": "matches", "value": "[invalid(regex"}]
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        error_msg = str(exc_info.value)
        assert "regex" in error_msg.lower() or "pattern" in error_msg.lower()

    def test_matches_valid_regex(self, tmp_path):
        """Test that valid regex pattern passes validation."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "text", "name": "input", "description": "Input"},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "input", "operator": "matches", "value": r"^[A-Z]{2}\d{4}$"}]
                }
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))


class TestEmptyNotEmptyOperatorValidation:
    """Test validation of empty/not_empty operators."""

    def create_config(self, tmp_path, annotation_schemes):
        """Helper to create a basic config structure."""
        return {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": annotation_schemes
        }

    def test_empty_without_value_is_valid(self, tmp_path):
        """Test that empty operator works without value."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "text", "name": "input", "description": "Input"},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "input", "operator": "empty"}]  # No value needed
                }
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))

    def test_not_empty_without_value_is_valid(self, tmp_path):
        """Test that not_empty operator works without value."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "text", "name": "input", "description": "Input"},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "input", "operator": "not_empty"}]  # No value needed
                }
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))


class TestLengthOperatorValidation:
    """Test validation of length operators."""

    def create_config(self, tmp_path, annotation_schemes):
        """Helper to create a basic config structure."""
        return {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": annotation_schemes
        }

    def test_length_gt_requires_numeric(self, tmp_path):
        """Test that length_gt requires numeric value."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "text", "name": "input", "description": "Input"},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "input", "operator": "length_gt", "value": "abc"}]
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "numeric" in str(exc_info.value).lower()

    def test_length_in_range_requires_list(self, tmp_path):
        """Test that length_in_range requires a list value."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "text", "name": "input", "description": "Input"},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "input", "operator": "length_in_range", "value": 50}]
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "range" in str(exc_info.value).lower()

    def test_valid_length_gt(self, tmp_path):
        """Test that valid length_gt passes validation."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "text", "name": "input", "description": "Input"},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "input", "operator": "length_gt", "value": 50}]
                }
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))


class TestSchemaReferenceValidation:
    """Test validation of schema references in display_logic."""

    def create_config(self, tmp_path, annotation_schemes):
        """Helper to create a basic config structure."""
        return {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": annotation_schemes
        }

    def test_unknown_schema_reference(self, tmp_path):
        """Test that referencing unknown schema raises error."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "radio", "name": "choice", "description": "Choice", "labels": ["A", "B"]},
            {
                "annotation_type": "text", "name": "detail", "description": "Detail",
                "display_logic": {
                    "show_when": [{"schema": "nonexistent_schema", "operator": "equals", "value": "A"}]
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        error_msg = str(exc_info.value)
        assert "nonexistent_schema" in error_msg
        assert "unknown" in error_msg.lower() or "references" in error_msg.lower()

    def test_circular_dependency_detected(self, tmp_path):
        """Test that circular dependencies are detected."""
        config = self.create_config(tmp_path, [
            {
                "annotation_type": "radio", "name": "schema_a", "description": "A", "labels": ["X", "Y"],
                "display_logic": {
                    "show_when": [{"schema": "schema_b", "operator": "not_empty"}]
                }
            },
            {
                "annotation_type": "radio", "name": "schema_b", "description": "B", "labels": ["X", "Y"],
                "display_logic": {
                    "show_when": [{"schema": "schema_a", "operator": "not_empty"}]
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "circular" in str(exc_info.value).lower()

    def test_three_way_circular_dependency(self, tmp_path):
        """Test that three-way circular dependencies are detected."""
        config = self.create_config(tmp_path, [
            {
                "annotation_type": "radio", "name": "a", "description": "A", "labels": ["X"],
                "display_logic": {"show_when": [{"schema": "c", "operator": "not_empty"}]}
            },
            {
                "annotation_type": "radio", "name": "b", "description": "B", "labels": ["X"],
                "display_logic": {"show_when": [{"schema": "a", "operator": "not_empty"}]}
            },
            {
                "annotation_type": "radio", "name": "c", "description": "C", "labels": ["X"],
                "display_logic": {"show_when": [{"schema": "b", "operator": "not_empty"}]}
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "circular" in str(exc_info.value).lower()

    def test_valid_chain_dependency(self, tmp_path):
        """Test that valid chain dependencies pass validation."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "radio", "name": "a", "description": "A", "labels": ["X", "Y"]},
            {
                "annotation_type": "radio", "name": "b", "description": "B", "labels": ["X", "Y"],
                "display_logic": {"show_when": [{"schema": "a", "operator": "equals", "value": "X"}]}
            },
            {
                "annotation_type": "text", "name": "c", "description": "C",
                "display_logic": {"show_when": [{"schema": "b", "operator": "equals", "value": "X"}]}
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))


class TestLogicFieldValidation:
    """Test validation of the 'logic' field in display_logic."""

    def create_config(self, tmp_path, annotation_schemes):
        """Helper to create a basic config structure."""
        return {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": annotation_schemes
        }

    def test_invalid_logic_value(self, tmp_path):
        """Test that invalid logic value raises error."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "radio", "name": "a", "description": "A", "labels": ["X", "Y"]},
            {"annotation_type": "radio", "name": "b", "description": "B", "labels": ["X", "Y"]},
            {
                "annotation_type": "text", "name": "c", "description": "C",
                "display_logic": {
                    "show_when": [
                        {"schema": "a", "operator": "equals", "value": "X"},
                        {"schema": "b", "operator": "equals", "value": "Y"}
                    ],
                    "logic": "invalid"  # Should be 'all' or 'any'
                }
            }
        ])

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        error_msg = str(exc_info.value)
        assert "logic" in error_msg.lower()
        assert "all" in error_msg.lower() or "any" in error_msg.lower()

    def test_valid_all_logic(self, tmp_path):
        """Test that 'all' logic value passes validation."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "radio", "name": "a", "description": "A", "labels": ["X", "Y"]},
            {"annotation_type": "radio", "name": "b", "description": "B", "labels": ["X", "Y"]},
            {
                "annotation_type": "text", "name": "c", "description": "C",
                "display_logic": {
                    "show_when": [
                        {"schema": "a", "operator": "equals", "value": "X"},
                        {"schema": "b", "operator": "equals", "value": "Y"}
                    ],
                    "logic": "all"
                }
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))

    def test_valid_any_logic(self, tmp_path):
        """Test that 'any' logic value passes validation."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "radio", "name": "a", "description": "A", "labels": ["X", "Y"]},
            {"annotation_type": "radio", "name": "b", "description": "B", "labels": ["X", "Y"]},
            {
                "annotation_type": "text", "name": "c", "description": "C",
                "display_logic": {
                    "show_when": [
                        {"schema": "a", "operator": "equals", "value": "X"},
                        {"schema": "b", "operator": "equals", "value": "Y"}
                    ],
                    "logic": "any"
                }
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))

    def test_default_logic_is_all(self, tmp_path):
        """Test that default logic (when not specified) works (defaults to 'all')."""
        config = self.create_config(tmp_path, [
            {"annotation_type": "radio", "name": "a", "description": "A", "labels": ["X", "Y"]},
            {
                "annotation_type": "text", "name": "c", "description": "C",
                "display_logic": {
                    "show_when": [{"schema": "a", "operator": "equals", "value": "X"}]
                    # No 'logic' field - should default to 'all'
                }
            }
        ])
        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))
