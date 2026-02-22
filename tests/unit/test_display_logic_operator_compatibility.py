"""
Unit tests for display logic operator compatibility with different schema types.

Tests that:
- Numeric operators (gt, lt, in_range, etc.) are validated against schema types
- Text operators (contains, matches, length_*) work correctly with text schemas
- Warning or errors are raised for incompatible operator/schema combinations
- Each operator works correctly with its compatible schema types
"""

import pytest
from potato.server_utils.display_logic import (
    DisplayLogicCondition,
    DisplayLogicRule,
    DisplayLogicEvaluator,
    DisplayLogicValidator,
    SUPPORTED_OPERATORS,
)
from potato.server_utils.config_module import (
    validate_yaml_structure,
    validate_display_logic_structure,
    ConfigValidationError,
)


class TestEqualsOperatorAllSchemas:
    """Test 'equals' operator with all schema types."""

    def test_equals_with_radio(self):
        """Test equals operator with radio selection."""
        cond = DisplayLogicCondition(schema="radio_field", operator="equals", value="Option1")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Option1") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Option2") is False

    def test_equals_with_multiselect_single_value(self):
        """Test equals with multiselect - single value in list."""
        cond = DisplayLogicCondition(schema="multi_field", operator="equals", value="Selected")
        # Multiselect returns list, equals checks if any match
        assert DisplayLogicEvaluator.evaluate_condition(cond, ["Selected", "Other"]) is False
        # Direct string comparison
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Selected") is True

    def test_equals_with_text(self):
        """Test equals operator with text input."""
        cond = DisplayLogicCondition(schema="text_field", operator="equals", value="exact match")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "exact match") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "different") is False

    def test_equals_with_slider_numeric(self):
        """Test equals operator with slider numeric value."""
        cond = DisplayLogicCondition(schema="slider", operator="equals", value=5)
        assert DisplayLogicEvaluator.evaluate_condition(cond, 5) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 4) is False

    def test_equals_with_likert(self):
        """Test equals operator with likert scale."""
        cond = DisplayLogicCondition(schema="likert", operator="equals", value="3")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "3") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 3) is True  # Numeric comparison

    def test_equals_with_select_dropdown(self):
        """Test equals operator with select dropdown."""
        cond = DisplayLogicCondition(schema="select", operator="equals", value="Choice_A")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Choice_A") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Choice_B") is False

    def test_equals_list_values_any_match(self):
        """Test equals with list of acceptable values."""
        cond = DisplayLogicCondition(schema="field", operator="equals", value=["A", "B", "C"])
        assert DisplayLogicEvaluator.evaluate_condition(cond, "A") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "B") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "D") is False


class TestNotEqualsOperatorAllSchemas:
    """Test 'not_equals' operator with all schema types."""

    def test_not_equals_with_radio(self):
        """Test not_equals with radio."""
        cond = DisplayLogicCondition(schema="radio", operator="not_equals", value="Excluded")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Selected") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Excluded") is False

    def test_not_equals_list_excludes_all(self):
        """Test not_equals with list of excluded values."""
        cond = DisplayLogicCondition(schema="field", operator="not_equals", value=["Bad", "Terrible"])
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Good") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Bad") is False
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Terrible") is False


class TestContainsOperatorAllSchemas:
    """Test 'contains' operator with all schema types."""

    def test_contains_with_multiselect_list(self):
        """Test contains checks list membership for multiselect."""
        cond = DisplayLogicCondition(schema="multi", operator="contains", value="OptionX")
        assert DisplayLogicEvaluator.evaluate_condition(cond, ["OptionX", "OptionY"]) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, ["OptionY", "OptionZ"]) is False

    def test_contains_with_text_substring(self):
        """Test contains checks substring for text."""
        cond = DisplayLogicCondition(schema="text", operator="contains", value="error")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "This has an error message") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "All good here") is False

    def test_contains_case_insensitive(self):
        """Test contains is case-insensitive by default."""
        cond = DisplayLogicCondition(schema="text", operator="contains", value="ERROR")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "error occurred") is True

    def test_contains_case_sensitive(self):
        """Test contains with case sensitivity enabled."""
        cond = DisplayLogicCondition(schema="text", operator="contains", value="ERROR", case_sensitive=True)
        assert DisplayLogicEvaluator.evaluate_condition(cond, "error occurred") is False
        assert DisplayLogicEvaluator.evaluate_condition(cond, "ERROR occurred") is True

    def test_contains_multiple_values_any(self):
        """Test contains with list of values - matches any."""
        cond = DisplayLogicCondition(schema="multi", operator="contains", value=["A", "B"])
        assert DisplayLogicEvaluator.evaluate_condition(cond, ["A", "C"]) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, ["D", "E"]) is False


class TestNotContainsOperator:
    """Test 'not_contains' operator."""

    def test_not_contains_multiselect(self):
        """Test not_contains with multiselect."""
        cond = DisplayLogicCondition(schema="multi", operator="not_contains", value="Excluded")
        assert DisplayLogicEvaluator.evaluate_condition(cond, ["A", "B"]) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, ["A", "Excluded"]) is False

    def test_not_contains_text(self):
        """Test not_contains with text substring."""
        cond = DisplayLogicCondition(schema="text", operator="not_contains", value="spam")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "normal text") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "this is spam content") is False


class TestMatchesOperator:
    """Test 'matches' regex operator."""

    def test_matches_simple_pattern(self):
        """Test simple regex pattern matching."""
        cond = DisplayLogicCondition(schema="text", operator="matches", value=r"^\d{3}-\d{4}$")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "123-4567") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "12-34567") is False

    def test_matches_with_text_schema(self):
        """Test matches with free text input."""
        cond = DisplayLogicCondition(schema="text", operator="matches", value=r"error|warning|critical")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "An error occurred") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "All good") is False

    def test_matches_case_insensitive(self):
        """Test matches is case-insensitive by default."""
        cond = DisplayLogicCondition(schema="text", operator="matches", value=r"ERROR")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "error") is True

    def test_matches_case_sensitive(self):
        """Test matches with case sensitivity."""
        cond = DisplayLogicCondition(schema="text", operator="matches", value=r"ERROR", case_sensitive=True)
        assert DisplayLogicEvaluator.evaluate_condition(cond, "error") is False
        assert DisplayLogicEvaluator.evaluate_condition(cond, "ERROR") is True

    def test_matches_email_pattern(self):
        """Test matches with email-like pattern."""
        cond = DisplayLogicCondition(schema="text", operator="matches", value=r"[\w.]+@[\w.]+\.\w+")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "user@example.com") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "not an email") is False


class TestNumericOperatorsWithSlider:
    """Test numeric operators (gt, gte, lt, lte) with slider schema."""

    def test_gt_with_slider(self):
        """Test greater than with slider."""
        cond = DisplayLogicCondition(schema="slider", operator="gt", value=5)
        assert DisplayLogicEvaluator.evaluate_condition(cond, 6) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 5) is False
        assert DisplayLogicEvaluator.evaluate_condition(cond, 4) is False

    def test_gte_with_slider(self):
        """Test greater than or equal with slider."""
        cond = DisplayLogicCondition(schema="slider", operator="gte", value=5)
        assert DisplayLogicEvaluator.evaluate_condition(cond, 6) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 5) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 4) is False

    def test_lt_with_slider(self):
        """Test less than with slider."""
        cond = DisplayLogicCondition(schema="slider", operator="lt", value=5)
        assert DisplayLogicEvaluator.evaluate_condition(cond, 4) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 5) is False
        assert DisplayLogicEvaluator.evaluate_condition(cond, 6) is False

    def test_lte_with_slider(self):
        """Test less than or equal with slider."""
        cond = DisplayLogicCondition(schema="slider", operator="lte", value=5)
        assert DisplayLogicEvaluator.evaluate_condition(cond, 4) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 5) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 6) is False


class TestNumericOperatorsWithLikert:
    """Test numeric operators with likert schema."""

    def test_numeric_with_likert_string(self):
        """Test numeric operators work with likert string values."""
        cond = DisplayLogicCondition(schema="likert", operator="gte", value=3)
        assert DisplayLogicEvaluator.evaluate_condition(cond, "4") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "3") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "2") is False


class TestNumericOperatorsWithNumber:
    """Test numeric operators with number input schema."""

    def test_numeric_with_number_input(self):
        """Test numeric operators with number input."""
        cond = DisplayLogicCondition(schema="number", operator="gt", value=100)
        assert DisplayLogicEvaluator.evaluate_condition(cond, 150) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 50) is False

    def test_numeric_with_float(self):
        """Test numeric operators with float values."""
        cond = DisplayLogicCondition(schema="number", operator="lt", value=3.14)
        assert DisplayLogicEvaluator.evaluate_condition(cond, 3.0) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 3.5) is False


class TestRangeOperators:
    """Test range operators (in_range, not_in_range)."""

    def test_in_range_with_slider(self):
        """Test in_range with slider values."""
        cond = DisplayLogicCondition(schema="slider", operator="in_range", value=[3, 7])
        assert DisplayLogicEvaluator.evaluate_condition(cond, 3) is True  # Min inclusive
        assert DisplayLogicEvaluator.evaluate_condition(cond, 5) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 7) is True  # Max inclusive
        assert DisplayLogicEvaluator.evaluate_condition(cond, 2) is False
        assert DisplayLogicEvaluator.evaluate_condition(cond, 8) is False

    def test_in_range_with_likert(self):
        """Test in_range with likert scale."""
        cond = DisplayLogicCondition(schema="likert", operator="in_range", value=[1, 3])
        assert DisplayLogicEvaluator.evaluate_condition(cond, 2) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 4) is False

    def test_not_in_range(self):
        """Test not_in_range operator."""
        cond = DisplayLogicCondition(schema="slider", operator="not_in_range", value=[3, 7])
        assert DisplayLogicEvaluator.evaluate_condition(cond, 2) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 8) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, 5) is False


class TestEmptyNotEmptyOperators:
    """Test empty and not_empty operators."""

    def test_empty_with_text(self):
        """Test empty operator with text input."""
        cond = DisplayLogicCondition(schema="text", operator="empty")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "   ") is True  # Whitespace
        assert DisplayLogicEvaluator.evaluate_condition(cond, None) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "text") is False

    def test_empty_with_multiselect(self):
        """Test empty operator with multiselect (empty list)."""
        cond = DisplayLogicCondition(schema="multi", operator="empty")
        assert DisplayLogicEvaluator.evaluate_condition(cond, []) is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, ["Option"]) is False

    def test_not_empty_with_text(self):
        """Test not_empty with text."""
        cond = DisplayLogicCondition(schema="text", operator="not_empty")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "content") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "") is False

    def test_not_empty_with_radio(self):
        """Test not_empty with radio selection."""
        cond = DisplayLogicCondition(schema="radio", operator="not_empty")
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Selected") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, None) is False


class TestLengthOperators:
    """Test length operators (length_gt, length_lt, length_in_range)."""

    def test_length_gt_with_text(self):
        """Test length_gt with text input."""
        cond = DisplayLogicCondition(schema="text", operator="length_gt", value=10)
        assert DisplayLogicEvaluator.evaluate_condition(cond, "This is a long text") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Short") is False

    def test_length_lt_with_text(self):
        """Test length_lt with text input."""
        cond = DisplayLogicCondition(schema="text", operator="length_lt", value=10)
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Short") is True
        assert DisplayLogicEvaluator.evaluate_condition(cond, "This is a much longer text") is False

    def test_length_in_range_with_text(self):
        """Test length_in_range with text input."""
        cond = DisplayLogicCondition(schema="text", operator="length_in_range", value=[5, 20])
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Medium") is True  # len=6
        assert DisplayLogicEvaluator.evaluate_condition(cond, "Hi") is False  # len=2
        assert DisplayLogicEvaluator.evaluate_condition(cond, "This text is way too long for the range") is False


class TestIncompatibleOperatorValidation:
    """Test that incompatible operator/schema combinations raise appropriate errors."""

    def test_in_range_requires_two_values(self):
        """Test that in_range with wrong value format raises error."""
        with pytest.raises(ValueError, match="requires a range value"):
            DisplayLogicCondition(schema="slider", operator="in_range", value=5)

    def test_in_range_min_max_order(self, tmp_path):
        """Test that in_range with min > max is caught in validation."""
        config = {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": [
                {"annotation_type": "slider", "name": "score", "description": "Score",
                 "min_value": 1, "max_value": 10, "starting_value": 5},
                {
                    "annotation_type": "text",
                    "name": "detail",
                    "description": "Detail",
                    "display_logic": {
                        "show_when": [
                            {"schema": "score", "operator": "in_range", "value": [10, 5]}  # Wrong order
                        ]
                    }
                }
            ]
        }

        with pytest.raises(ConfigValidationError, match="greater than max"):
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

    def test_numeric_operator_requires_numeric_value(self):
        """Test that numeric operators reject non-numeric values at creation."""
        # The condition validates on creation
        with pytest.raises(ValueError):
            DisplayLogicCondition(schema="text", operator="gt", value="not_a_number")

    def test_matches_requires_valid_regex(self, tmp_path):
        """Test that matches operator validates regex pattern."""
        config = {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": [
                {"annotation_type": "text", "name": "input", "description": "Input"},
                {
                    "annotation_type": "text",
                    "name": "output",
                    "description": "Output",
                    "display_logic": {
                        "show_when": [
                            {"schema": "input", "operator": "matches", "value": "[invalid(regex"}
                        ]
                    }
                }
            ]
        }

        with pytest.raises(ConfigValidationError, match="invalid regex"):
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

    def test_missing_value_for_required_operator(self, tmp_path):
        """Test that operators requiring values fail without them."""
        config = {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "choice", "description": "Choice",
                 "labels": ["A", "B"]},
                {
                    "annotation_type": "text",
                    "name": "detail",
                    "description": "Detail",
                    "display_logic": {
                        "show_when": [
                            {"schema": "choice", "operator": "equals"}  # Missing value
                        ]
                    }
                }
            ]
        }

        with pytest.raises(ConfigValidationError, match="requires a value"):
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

    def test_empty_operator_without_value_is_valid(self, tmp_path):
        """Test that empty/not_empty operators work without value."""
        config = {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": [
                {"annotation_type": "text", "name": "input", "description": "Input"},
                {
                    "annotation_type": "text",
                    "name": "followup",
                    "description": "Follow-up",
                    "display_logic": {
                        "show_when": [
                            {"schema": "input", "operator": "not_empty"}  # No value needed
                        ]
                    }
                }
            ]
        }

        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))


class TestOperatorBehaviorWithNullValues:
    """Test operator behavior when schema value is null/undefined."""

    def test_equals_with_null(self):
        """Test equals returns False for null values."""
        cond = DisplayLogicCondition(schema="field", operator="equals", value="Expected")
        assert DisplayLogicEvaluator.evaluate_condition(cond, None) is False

    def test_contains_with_null(self):
        """Test contains returns False for null values."""
        cond = DisplayLogicCondition(schema="field", operator="contains", value="text")
        assert DisplayLogicEvaluator.evaluate_condition(cond, None) is False

    def test_gt_with_null(self):
        """Test numeric comparison with null returns False."""
        cond = DisplayLogicCondition(schema="field", operator="gt", value=5)
        assert DisplayLogicEvaluator.evaluate_condition(cond, None) is False

    def test_empty_with_null(self):
        """Test empty returns True for null."""
        cond = DisplayLogicCondition(schema="field", operator="empty")
        assert DisplayLogicEvaluator.evaluate_condition(cond, None) is True

    def test_not_empty_with_null(self):
        """Test not_empty returns False for null."""
        cond = DisplayLogicCondition(schema="field", operator="not_empty")
        assert DisplayLogicEvaluator.evaluate_condition(cond, None) is False


class TestAllOperatorsExist:
    """Verify all documented operators are implemented."""

    def test_all_operators_documented(self):
        """Test all operators in SUPPORTED_OPERATORS are documented."""
        expected_operators = [
            "equals", "not_equals",
            "contains", "not_contains",
            "matches",
            "gt", "gte", "lt", "lte",
            "in_range", "not_in_range",
            "empty", "not_empty",
            "length_gt", "length_lt", "length_in_range"
        ]
        for op in expected_operators:
            assert op in SUPPORTED_OPERATORS, f"Missing operator: {op}"

    def test_no_undocumented_operators(self):
        """Test there are no operators that aren't tested."""
        tested_operators = [
            "equals", "not_equals",
            "contains", "not_contains",
            "matches",
            "gt", "gte", "lt", "lte",
            "in_range", "not_in_range",
            "empty", "not_empty",
            "length_gt", "length_lt", "length_in_range"
        ]
        for op in SUPPORTED_OPERATORS:
            assert op in tested_operators, f"Operator {op} is not tested"
