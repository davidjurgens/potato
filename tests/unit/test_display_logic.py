"""
Unit tests for display_logic.py

Tests the conditional schema branching functionality including:
- Condition validation
- All operators (equals, contains, matches, numeric, range, length)
- Rule evaluation with AND/OR logic
- Circular dependency detection
- Display logic validator
"""

import pytest
from potato.server_utils.display_logic import (
    DisplayLogicCondition,
    DisplayLogicRule,
    DisplayLogicValidator,
    DisplayLogicEvaluator,
    validate_display_logic_config,
    get_display_logic_dependencies,
    SUPPORTED_OPERATORS,
)


class TestDisplayLogicCondition:
    """Tests for DisplayLogicCondition dataclass."""

    def test_valid_condition_equals(self):
        """Test creating a valid equals condition."""
        cond = DisplayLogicCondition(
            schema="rating",
            operator="equals",
            value="Good"
        )
        assert cond.schema == "rating"
        assert cond.operator == "equals"
        assert cond.value == "Good"
        assert cond.case_sensitive is False

    def test_valid_condition_with_case_sensitive(self):
        """Test creating a condition with case sensitivity."""
        cond = DisplayLogicCondition(
            schema="text_input",
            operator="contains",
            value="Error",
            case_sensitive=True
        )
        assert cond.case_sensitive is True

    def test_invalid_operator_raises_error(self):
        """Test that invalid operators raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported operator"):
            DisplayLogicCondition(
                schema="test",
                operator="invalid_op",
                value="test"
            )

    def test_empty_operator_no_value_needed(self):
        """Test that empty operator doesn't require a value."""
        cond = DisplayLogicCondition(
            schema="text",
            operator="empty"
        )
        assert cond.value is None

    def test_not_empty_operator_no_value_needed(self):
        """Test that not_empty operator doesn't require a value."""
        cond = DisplayLogicCondition(
            schema="text",
            operator="not_empty"
        )
        assert cond.value is None

    def test_range_operator_requires_list(self):
        """Test that range operators require [min, max] list."""
        with pytest.raises(ValueError, match="requires a range value"):
            DisplayLogicCondition(
                schema="score",
                operator="in_range",
                value=5  # Should be [min, max]
            )

    def test_range_operator_requires_two_values(self):
        """Test that range operators require exactly 2 values."""
        with pytest.raises(ValueError, match="requires a range value"):
            DisplayLogicCondition(
                schema="score",
                operator="in_range",
                value=[1, 2, 3]  # Should be [min, max]
            )

    def test_to_dict(self):
        """Test serialization to dictionary."""
        cond = DisplayLogicCondition(
            schema="rating",
            operator="equals",
            value="Good",
            case_sensitive=True
        )
        d = cond.to_dict()
        assert d["schema"] == "rating"
        assert d["operator"] == "equals"
        assert d["value"] == "Good"
        assert d["case_sensitive"] is True

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "schema": "rating",
            "operator": "equals",
            "value": ["Good", "Excellent"]
        }
        cond = DisplayLogicCondition.from_dict(data)
        assert cond.schema == "rating"
        assert cond.operator == "equals"
        assert cond.value == ["Good", "Excellent"]


class TestDisplayLogicRule:
    """Tests for DisplayLogicRule dataclass."""

    def test_valid_rule_all_logic(self):
        """Test creating a rule with AND logic."""
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="a", operator="equals", value="X"),
                DisplayLogicCondition(schema="b", operator="equals", value="Y"),
            ],
            logic="all"
        )
        assert len(rule.conditions) == 2
        assert rule.logic == "all"

    def test_valid_rule_any_logic(self):
        """Test creating a rule with OR logic."""
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="a", operator="equals", value="X"),
            ],
            logic="any"
        )
        assert rule.logic == "any"

    def test_invalid_logic_raises_error(self):
        """Test that invalid logic type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid logic type"):
            DisplayLogicRule(logic="invalid")

    def test_get_watched_schemas(self):
        """Test extracting watched schema names from conditions."""
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="schema_a", operator="equals", value="X"),
                DisplayLogicCondition(schema="schema_b", operator="contains", value="Y"),
                DisplayLogicCondition(schema="schema_a", operator="not_empty"),
            ]
        )
        watched = rule.get_watched_schemas()
        assert watched == {"schema_a", "schema_b"}

    def test_to_dict_and_from_dict(self):
        """Test round-trip serialization."""
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="rating", operator="equals", value="Good"),
            ],
            logic="all"
        )
        d = rule.to_dict()
        rule2 = DisplayLogicRule.from_dict(d)
        assert len(rule2.conditions) == 1
        assert rule2.conditions[0].schema == "rating"
        assert rule2.logic == "all"


class TestDisplayLogicEvaluator:
    """Tests for DisplayLogicEvaluator."""

    # --- Empty/Not Empty Tests ---

    def test_empty_with_none(self):
        """Test empty operator with None value."""
        cond = DisplayLogicCondition(schema="field", operator="empty")
        result = DisplayLogicEvaluator.evaluate_condition(cond, None)
        assert result is True

    def test_empty_with_empty_string(self):
        """Test empty operator with empty string."""
        cond = DisplayLogicCondition(schema="field", operator="empty")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "")
        assert result is True

    def test_empty_with_whitespace_only(self):
        """Test empty operator with whitespace-only string."""
        cond = DisplayLogicCondition(schema="field", operator="empty")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "   ")
        assert result is True

    def test_empty_with_value(self):
        """Test empty operator with actual value."""
        cond = DisplayLogicCondition(schema="field", operator="empty")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "text")
        assert result is False

    def test_empty_with_empty_list(self):
        """Test empty operator with empty list."""
        cond = DisplayLogicCondition(schema="field", operator="empty")
        result = DisplayLogicEvaluator.evaluate_condition(cond, [])
        assert result is True

    def test_not_empty_with_value(self):
        """Test not_empty operator with value."""
        cond = DisplayLogicCondition(schema="field", operator="not_empty")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "text")
        assert result is True

    def test_not_empty_with_none(self):
        """Test not_empty operator with None."""
        cond = DisplayLogicCondition(schema="field", operator="not_empty")
        result = DisplayLogicEvaluator.evaluate_condition(cond, None)
        assert result is False

    # --- Equals Tests ---

    def test_equals_single_value_match(self):
        """Test equals with single value - match."""
        cond = DisplayLogicCondition(schema="rating", operator="equals", value="Good")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "Good")
        assert result is True

    def test_equals_single_value_no_match(self):
        """Test equals with single value - no match."""
        cond = DisplayLogicCondition(schema="rating", operator="equals", value="Good")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "Bad")
        assert result is False

    def test_equals_case_insensitive(self):
        """Test equals with case insensitive comparison."""
        cond = DisplayLogicCondition(schema="rating", operator="equals", value="good", case_sensitive=False)
        result = DisplayLogicEvaluator.evaluate_condition(cond, "GOOD")
        assert result is True

    def test_equals_case_sensitive(self):
        """Test equals with case sensitive comparison."""
        cond = DisplayLogicCondition(schema="rating", operator="equals", value="Good", case_sensitive=True)
        result = DisplayLogicEvaluator.evaluate_condition(cond, "good")
        assert result is False

    def test_equals_list_match_any(self):
        """Test equals with list of values - matches any."""
        cond = DisplayLogicCondition(schema="rating", operator="equals", value=["Good", "Excellent"])
        result = DisplayLogicEvaluator.evaluate_condition(cond, "Excellent")
        assert result is True

    def test_equals_list_no_match(self):
        """Test equals with list of values - no match."""
        cond = DisplayLogicCondition(schema="rating", operator="equals", value=["Good", "Excellent"])
        result = DisplayLogicEvaluator.evaluate_condition(cond, "Bad")
        assert result is False

    def test_not_equals(self):
        """Test not_equals operator."""
        cond = DisplayLogicCondition(schema="rating", operator="not_equals", value="Bad")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "Good")
        assert result is True

    def test_not_equals_match_fails(self):
        """Test not_equals operator when value matches."""
        cond = DisplayLogicCondition(schema="rating", operator="not_equals", value="Bad")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "Bad")
        assert result is False

    # --- Contains Tests ---

    def test_contains_string_substring(self):
        """Test contains with string substring."""
        cond = DisplayLogicCondition(schema="text", operator="contains", value="error")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "This has an error message")
        assert result is True

    def test_contains_string_no_match(self):
        """Test contains with string - no match."""
        cond = DisplayLogicCondition(schema="text", operator="contains", value="error")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "All good here")
        assert result is False

    def test_contains_list_membership(self):
        """Test contains with list membership (multiselect)."""
        cond = DisplayLogicCondition(schema="options", operator="contains", value="Option2")
        result = DisplayLogicEvaluator.evaluate_condition(cond, ["Option1", "Option2", "Option3"])
        assert result is True

    def test_contains_list_no_member(self):
        """Test contains with list - not a member."""
        cond = DisplayLogicCondition(schema="options", operator="contains", value="Option5")
        result = DisplayLogicEvaluator.evaluate_condition(cond, ["Option1", "Option2"])
        assert result is False

    def test_contains_with_value_list_any(self):
        """Test contains with list of values to check - matches any."""
        cond = DisplayLogicCondition(schema="tags", operator="contains", value=["urgent", "important"])
        result = DisplayLogicEvaluator.evaluate_condition(cond, ["normal", "important"])
        assert result is True

    def test_not_contains(self):
        """Test not_contains operator."""
        cond = DisplayLogicCondition(schema="text", operator="not_contains", value="spam")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "normal text")
        assert result is True

    # --- Matches Tests ---

    def test_matches_regex_simple(self):
        """Test matches with simple regex."""
        cond = DisplayLogicCondition(schema="code", operator="matches", value=r"^[A-Z]{2}\d{4}$")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "AB1234")
        assert result is True

    def test_matches_regex_no_match(self):
        """Test matches with regex - no match."""
        cond = DisplayLogicCondition(schema="code", operator="matches", value=r"^[A-Z]{2}\d{4}$")
        result = DisplayLogicEvaluator.evaluate_condition(cond, "1234AB")
        assert result is False

    def test_matches_case_insensitive(self):
        """Test matches with case insensitive regex."""
        cond = DisplayLogicCondition(schema="text", operator="matches", value=r"error", case_sensitive=False)
        result = DisplayLogicEvaluator.evaluate_condition(cond, "ERROR occurred")
        assert result is True

    def test_matches_case_sensitive(self):
        """Test matches with case sensitive regex."""
        cond = DisplayLogicCondition(schema="text", operator="matches", value=r"error", case_sensitive=True)
        result = DisplayLogicEvaluator.evaluate_condition(cond, "ERROR occurred")
        assert result is False

    # --- Numeric Comparison Tests ---

    def test_gt_true(self):
        """Test greater than - true."""
        cond = DisplayLogicCondition(schema="score", operator="gt", value=5)
        result = DisplayLogicEvaluator.evaluate_condition(cond, 7)
        assert result is True

    def test_gt_equal_false(self):
        """Test greater than - equal returns false."""
        cond = DisplayLogicCondition(schema="score", operator="gt", value=5)
        result = DisplayLogicEvaluator.evaluate_condition(cond, 5)
        assert result is False

    def test_gte_true(self):
        """Test greater than or equal - true."""
        cond = DisplayLogicCondition(schema="score", operator="gte", value=5)
        result = DisplayLogicEvaluator.evaluate_condition(cond, 5)
        assert result is True

    def test_lt_true(self):
        """Test less than - true."""
        cond = DisplayLogicCondition(schema="score", operator="lt", value=5)
        result = DisplayLogicEvaluator.evaluate_condition(cond, 3)
        assert result is True

    def test_lte_true(self):
        """Test less than or equal - true."""
        cond = DisplayLogicCondition(schema="score", operator="lte", value=5)
        result = DisplayLogicEvaluator.evaluate_condition(cond, 5)
        assert result is True

    def test_numeric_with_string_number(self):
        """Test numeric comparison with string that's a number."""
        cond = DisplayLogicCondition(schema="score", operator="gt", value=5)
        result = DisplayLogicEvaluator.evaluate_condition(cond, "7")
        assert result is True

    def test_numeric_with_invalid_value(self):
        """Test numeric comparison with non-numeric value returns False."""
        cond = DisplayLogicCondition(schema="score", operator="gt", value=5)
        result = DisplayLogicEvaluator.evaluate_condition(cond, "not a number")
        assert result is False

    # --- Range Tests ---

    def test_in_range_middle(self):
        """Test in_range with value in middle of range."""
        cond = DisplayLogicCondition(schema="score", operator="in_range", value=[3, 7])
        result = DisplayLogicEvaluator.evaluate_condition(cond, 5)
        assert result is True

    def test_in_range_at_min(self):
        """Test in_range at minimum (inclusive)."""
        cond = DisplayLogicCondition(schema="score", operator="in_range", value=[3, 7])
        result = DisplayLogicEvaluator.evaluate_condition(cond, 3)
        assert result is True

    def test_in_range_at_max(self):
        """Test in_range at maximum (inclusive)."""
        cond = DisplayLogicCondition(schema="score", operator="in_range", value=[3, 7])
        result = DisplayLogicEvaluator.evaluate_condition(cond, 7)
        assert result is True

    def test_in_range_outside(self):
        """Test in_range with value outside range."""
        cond = DisplayLogicCondition(schema="score", operator="in_range", value=[3, 7])
        result = DisplayLogicEvaluator.evaluate_condition(cond, 8)
        assert result is False

    def test_not_in_range(self):
        """Test not_in_range operator."""
        cond = DisplayLogicCondition(schema="score", operator="not_in_range", value=[3, 7])
        result = DisplayLogicEvaluator.evaluate_condition(cond, 2)
        assert result is True

    def test_not_in_range_inside(self):
        """Test not_in_range with value inside range."""
        cond = DisplayLogicCondition(schema="score", operator="not_in_range", value=[3, 7])
        result = DisplayLogicEvaluator.evaluate_condition(cond, 5)
        assert result is False

    # --- Length Tests ---

    def test_length_gt_true(self):
        """Test length_gt - true."""
        cond = DisplayLogicCondition(schema="text", operator="length_gt", value=5)
        result = DisplayLogicEvaluator.evaluate_condition(cond, "hello world")
        assert result is True

    def test_length_gt_false(self):
        """Test length_gt - false."""
        cond = DisplayLogicCondition(schema="text", operator="length_gt", value=20)
        result = DisplayLogicEvaluator.evaluate_condition(cond, "short")
        assert result is False

    def test_length_lt_true(self):
        """Test length_lt - true."""
        cond = DisplayLogicCondition(schema="text", operator="length_lt", value=10)
        result = DisplayLogicEvaluator.evaluate_condition(cond, "short")
        assert result is True

    def test_length_in_range(self):
        """Test length_in_range."""
        cond = DisplayLogicCondition(schema="text", operator="length_in_range", value=[5, 15])
        result = DisplayLogicEvaluator.evaluate_condition(cond, "hello world")
        assert result is True

    def test_length_in_range_outside(self):
        """Test length_in_range - outside range."""
        cond = DisplayLogicCondition(schema="text", operator="length_in_range", value=[5, 8])
        result = DisplayLogicEvaluator.evaluate_condition(cond, "hello world")
        assert result is False


class TestDisplayLogicRuleEvaluation:
    """Tests for complete rule evaluation with AND/OR logic."""

    def test_all_logic_all_true(self):
        """Test ALL logic with all conditions true."""
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="a", operator="equals", value="X"),
                DisplayLogicCondition(schema="b", operator="equals", value="Y"),
            ],
            logic="all"
        )
        annotations = {"a": "X", "b": "Y"}
        result = DisplayLogicEvaluator.evaluate_rule(rule, annotations)
        assert result is True

    def test_all_logic_one_false(self):
        """Test ALL logic with one condition false."""
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="a", operator="equals", value="X"),
                DisplayLogicCondition(schema="b", operator="equals", value="Y"),
            ],
            logic="all"
        )
        annotations = {"a": "X", "b": "Z"}  # b doesn't match
        result = DisplayLogicEvaluator.evaluate_rule(rule, annotations)
        assert result is False

    def test_any_logic_one_true(self):
        """Test ANY logic with one condition true."""
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="a", operator="equals", value="X"),
                DisplayLogicCondition(schema="b", operator="equals", value="Y"),
            ],
            logic="any"
        )
        annotations = {"a": "X", "b": "Z"}  # Only a matches
        result = DisplayLogicEvaluator.evaluate_rule(rule, annotations)
        assert result is True

    def test_any_logic_all_false(self):
        """Test ANY logic with all conditions false."""
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="a", operator="equals", value="X"),
                DisplayLogicCondition(schema="b", operator="equals", value="Y"),
            ],
            logic="any"
        )
        annotations = {"a": "W", "b": "Z"}  # Neither matches
        result = DisplayLogicEvaluator.evaluate_rule(rule, annotations)
        assert result is False

    def test_empty_conditions_returns_true(self):
        """Test that empty conditions list returns true (always visible)."""
        rule = DisplayLogicRule(conditions=[])
        result = DisplayLogicEvaluator.evaluate_rule(rule, {})
        assert result is True


class TestDisplayLogicValidator:
    """Tests for the DisplayLogicValidator class."""

    def test_valid_configuration(self):
        """Test a valid display_logic configuration."""
        schemes = [
            {"name": "rating", "annotation_type": "radio"},
            {
                "name": "explanation",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [
                        {"schema": "rating", "operator": "equals", "value": "Bad"}
                    ]
                }
            }
        ]
        validator = DisplayLogicValidator(schemes)
        is_valid, errors = validator.validate()
        assert is_valid is True
        assert len(errors) == 0

    def test_missing_show_when(self):
        """Test error when show_when is missing."""
        schemes = [
            {
                "name": "test",
                "annotation_type": "text",
                "display_logic": {}
            }
        ]
        validator = DisplayLogicValidator(schemes)
        is_valid, errors = validator.validate()
        assert is_valid is False
        assert any("show_when" in e for e in errors)

    def test_invalid_operator(self):
        """Test error for invalid operator."""
        schemes = [
            {"name": "rating", "annotation_type": "radio"},
            {
                "name": "test",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [
                        {"schema": "rating", "operator": "bad_operator", "value": "X"}
                    ]
                }
            }
        ]
        validator = DisplayLogicValidator(schemes)
        is_valid, errors = validator.validate()
        assert is_valid is False
        assert any("bad_operator" in e for e in errors)

    def test_missing_schema_field(self):
        """Test error when condition is missing schema field."""
        schemes = [
            {
                "name": "test",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [
                        {"operator": "equals", "value": "X"}  # Missing schema
                    ]
                }
            }
        ]
        validator = DisplayLogicValidator(schemes)
        is_valid, errors = validator.validate()
        assert is_valid is False
        assert any("schema" in e for e in errors)

    def test_unknown_referenced_schema(self):
        """Test error when referencing a schema that doesn't exist."""
        schemes = [
            {
                "name": "test",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [
                        {"schema": "nonexistent", "operator": "equals", "value": "X"}
                    ]
                }
            }
        ]
        validator = DisplayLogicValidator(schemes)
        is_valid, errors = validator.validate()
        assert is_valid is False
        assert any("nonexistent" in e for e in errors)

    def test_circular_dependency_detection(self):
        """Test detection of circular dependencies."""
        schemes = [
            {
                "name": "a",
                "annotation_type": "radio",
                "display_logic": {
                    "show_when": [{"schema": "b", "operator": "not_empty"}]
                }
            },
            {
                "name": "b",
                "annotation_type": "radio",
                "display_logic": {
                    "show_when": [{"schema": "a", "operator": "not_empty"}]
                }
            }
        ]
        validator = DisplayLogicValidator(schemes)
        is_valid, errors = validator.validate()
        assert is_valid is False
        assert any("Circular" in e for e in errors)

    def test_no_circular_dependency_chain(self):
        """Test that a valid dependency chain is not flagged."""
        schemes = [
            {"name": "a", "annotation_type": "radio"},
            {
                "name": "b",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [{"schema": "a", "operator": "not_empty"}]
                }
            },
            {
                "name": "c",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [{"schema": "b", "operator": "not_empty"}]
                }
            }
        ]
        validator = DisplayLogicValidator(schemes)
        is_valid, errors = validator.validate()
        assert is_valid is True

    def test_invalid_logic_value(self):
        """Test error for invalid logic value."""
        schemes = [
            {"name": "rating", "annotation_type": "radio"},
            {
                "name": "test",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [
                        {"schema": "rating", "operator": "equals", "value": "X"}
                    ],
                    "logic": "invalid"  # Should be 'all' or 'any'
                }
            }
        ]
        validator = DisplayLogicValidator(schemes)
        is_valid, errors = validator.validate()
        assert is_valid is False
        assert any("'logic'" in e for e in errors)

    def test_range_validation_min_gt_max(self):
        """Test error when range min > max."""
        schemes = [
            {"name": "score", "annotation_type": "slider"},
            {
                "name": "test",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [
                        {"schema": "score", "operator": "in_range", "value": [10, 5]}  # min > max
                    ]
                }
            }
        ]
        validator = DisplayLogicValidator(schemes)
        is_valid, errors = validator.validate()
        assert is_valid is False
        assert any("greater than max" in e for e in errors)

    def test_get_schema_dependencies(self):
        """Test getting dependencies for a schema."""
        schemes = [
            {"name": "a", "annotation_type": "radio"},
            {
                "name": "b",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [
                        {"schema": "a", "operator": "not_empty"},
                        {"schema": "c", "operator": "not_empty"}
                    ]
                }
            },
            {"name": "c", "annotation_type": "radio"}
        ]
        validator = DisplayLogicValidator(schemes)
        deps = validator.get_schema_dependencies("b")
        assert deps == {"a", "c"}

    def test_get_dependents(self):
        """Test getting schemas that depend on a given schema."""
        schemes = [
            {"name": "a", "annotation_type": "radio"},
            {
                "name": "b",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [{"schema": "a", "operator": "not_empty"}]
                }
            },
            {
                "name": "c",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [{"schema": "a", "operator": "equals", "value": "X"}]
                }
            }
        ]
        validator = DisplayLogicValidator(schemes)
        dependents = validator.get_dependents("a")
        assert dependents == {"b", "c"}


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_validate_display_logic_config(self):
        """Test the validate_display_logic_config convenience function."""
        schemes = [
            {"name": "rating", "annotation_type": "radio"},
            {
                "name": "explanation",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [
                        {"schema": "rating", "operator": "equals", "value": "Bad"}
                    ]
                }
            }
        ]
        is_valid, errors = validate_display_logic_config(schemes)
        assert is_valid is True

    def test_get_display_logic_dependencies(self):
        """Test the get_display_logic_dependencies convenience function."""
        schemes = [
            {"name": "a", "annotation_type": "radio"},
            {
                "name": "b",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [{"schema": "a", "operator": "not_empty"}]
                }
            }
        ]
        deps = get_display_logic_dependencies(schemes)
        assert "b" in deps
        assert "a" in deps["b"]


class TestEvaluateVisibility:
    """Tests for the evaluate_visibility function."""

    def test_no_display_logic_returns_visible(self):
        """Test that schemas without display_logic are always visible."""
        visible, reason = DisplayLogicEvaluator.evaluate_visibility(
            "test_schema", None, {}
        )
        assert visible is True
        assert reason is None

    def test_conditions_met_returns_visible(self):
        """Test visibility when conditions are met."""
        display_logic = {
            "show_when": [
                {"schema": "rating", "operator": "equals", "value": "Good"}
            ]
        }
        annotations = {"rating": "Good"}
        visible, reason = DisplayLogicEvaluator.evaluate_visibility(
            "test_schema", display_logic, annotations
        )
        assert visible is True
        assert reason is None

    def test_conditions_not_met_returns_hidden(self):
        """Test visibility when conditions are not met."""
        display_logic = {
            "show_when": [
                {"schema": "rating", "operator": "equals", "value": "Good"}
            ]
        }
        annotations = {"rating": "Bad"}
        visible, reason = DisplayLogicEvaluator.evaluate_visibility(
            "test_schema", display_logic, annotations
        )
        assert visible is False
        assert reason is not None
        assert "Conditions not met" in reason


class TestSupportedOperators:
    """Tests for the SUPPORTED_OPERATORS constant."""

    def test_all_expected_operators_present(self):
        """Test that all expected operators are in SUPPORTED_OPERATORS."""
        expected = [
            "equals", "not_equals", "contains", "not_contains",
            "matches", "gt", "gte", "lt", "lte",
            "in_range", "not_in_range", "empty", "not_empty",
            "length_gt", "length_lt", "length_in_range"
        ]
        for op in expected:
            assert op in SUPPORTED_OPERATORS, f"Missing operator: {op}"
