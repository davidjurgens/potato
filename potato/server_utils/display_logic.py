"""
Display Logic Module for Conditional Schema Branching

This module provides the core validation and evaluation logic for conditional
annotation schemas. It allows schemas to show/hide based on user responses
to other schemas.

Key Components:
- DisplayLogicCondition: Represents a single condition (e.g., "schema X equals 'Yes'")
- DisplayLogicRule: Represents a complete rule with multiple conditions and AND/OR logic
- DisplayLogicValidator: Validates display_logic configurations
- DisplayLogicEvaluator: Evaluates conditions at runtime

Example Configuration:
    display_logic:
      show_when:
        - schema: contains_pii
          operator: equals
          value: "Yes"
      logic: all  # 'all' = AND, 'any' = OR
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

# Supported operators and their descriptions
SUPPORTED_OPERATORS = {
    # Value comparison
    "equals": "Exact value match (single value or list of values)",
    "not_equals": "Value doesn't match any specified values",

    # Collection operators
    "contains": "List/text contains value(s)",
    "not_contains": "List/text doesn't contain value(s)",

    # Regex
    "matches": "Regex pattern match",

    # Numeric comparison
    "gt": "Greater than",
    "gte": "Greater than or equal",
    "lt": "Less than",
    "lte": "Less than or equal",
    "in_range": "Value is within range (inclusive)",
    "not_in_range": "Value is outside range",

    # Emptiness
    "empty": "Field is empty or not set",
    "not_empty": "Field has a value",

    # Text length
    "length_gt": "Text length greater than",
    "length_lt": "Text length less than",
    "length_in_range": "Text length within range (inclusive)",
}


@dataclass
class DisplayLogicCondition:
    """
    Represents a single condition in a display logic rule.

    Attributes:
        schema: Name of the schema to watch
        operator: Comparison operator (equals, contains, gt, etc.)
        value: Value(s) to compare against (can be single value, list, or range)
        case_sensitive: Whether text comparisons are case-sensitive (default: False)
    """
    schema: str
    operator: str
    value: Any = None
    case_sensitive: bool = False

    def __post_init__(self):
        """Validate the condition after initialization."""
        if self.operator not in SUPPORTED_OPERATORS:
            raise ValueError(f"Unsupported operator: {self.operator}. "
                           f"Supported operators: {list(SUPPORTED_OPERATORS.keys())}")

        # Validate operator-specific requirements
        if self.operator in ("empty", "not_empty"):
            # These operators don't require a value
            pass
        elif self.operator in ("in_range", "not_in_range", "length_in_range"):
            # Range operators require a list of exactly 2 values
            if not isinstance(self.value, (list, tuple)) or len(self.value) != 2:
                raise ValueError(f"Operator '{self.operator}' requires a range value "
                               f"as [min, max], got: {self.value}")
            # Validate that range values are numeric
            for v in self.value:
                if not isinstance(v, (int, float)):
                    raise ValueError(f"Operator '{self.operator}' requires numeric range values, "
                                   f"got: {self.value}")
        elif self.operator in ("gt", "gte", "lt", "lte", "length_gt", "length_lt"):
            # Numeric operators require numeric values
            if self.value is None:
                raise ValueError(f"Operator '{self.operator}' requires a numeric value")
            if not isinstance(self.value, (int, float)):
                raise ValueError(f"Operator '{self.operator}' requires a numeric value, "
                               f"got: {type(self.value).__name__} '{self.value}'")
        elif self.value is None and self.operator not in ("empty", "not_empty"):
            raise ValueError(f"Operator '{self.operator}' requires a value")

    def to_dict(self) -> Dict[str, Any]:
        """Convert condition to dictionary for serialization."""
        result = {
            "schema": self.schema,
            "operator": self.operator,
        }
        if self.value is not None:
            result["value"] = self.value
        if self.case_sensitive:
            result["case_sensitive"] = True
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DisplayLogicCondition":
        """Create a condition from a dictionary."""
        return cls(
            schema=data["schema"],
            operator=data["operator"],
            value=data.get("value"),
            case_sensitive=data.get("case_sensitive", False)
        )


@dataclass
class DisplayLogicRule:
    """
    Represents a complete display logic rule with multiple conditions.

    Attributes:
        conditions: List of DisplayLogicCondition objects
        logic: 'all' (AND) or 'any' (OR) - how to combine conditions
    """
    conditions: List[DisplayLogicCondition] = field(default_factory=list)
    logic: str = "all"  # 'all' = AND, 'any' = OR

    def __post_init__(self):
        """Validate the rule after initialization."""
        if self.logic not in ("all", "any"):
            raise ValueError(f"Invalid logic type: {self.logic}. Must be 'all' or 'any'")

    def get_watched_schemas(self) -> Set[str]:
        """Return set of schema names this rule depends on."""
        return {condition.schema for condition in self.conditions}

    def to_dict(self) -> Dict[str, Any]:
        """Convert rule to dictionary for serialization."""
        return {
            "show_when": [c.to_dict() for c in self.conditions],
            "logic": self.logic
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DisplayLogicRule":
        """Create a rule from a dictionary (config format)."""
        conditions = []
        show_when = data.get("show_when", [])

        for cond_data in show_when:
            conditions.append(DisplayLogicCondition.from_dict(cond_data))

        return cls(
            conditions=conditions,
            logic=data.get("logic", "all")
        )


class DisplayLogicValidator:
    """
    Validates display_logic configurations in annotation schemes.

    Responsibilities:
    - Validate condition syntax and operators
    - Check that referenced schemas exist
    - Detect circular dependencies
    - Warn about potential issues
    """

    def __init__(self, annotation_schemes: List[Dict[str, Any]]):
        """
        Initialize the validator with all annotation schemes.

        Args:
            annotation_schemes: List of annotation scheme configurations
        """
        self.schemes = annotation_schemes
        self.schema_names = {s.get("name") for s in annotation_schemes if "name" in s}
        self.dependency_graph: Dict[str, Set[str]] = {}
        self._build_dependency_graph()

    def _build_dependency_graph(self) -> None:
        """Build a graph of schema dependencies for cycle detection."""
        for scheme in self.schemes:
            schema_name = scheme.get("name")
            if not schema_name:
                continue

            display_logic = scheme.get("display_logic", {})
            if not display_logic:
                self.dependency_graph[schema_name] = set()
                continue

            # Extract schemas this one depends on
            dependencies = set()
            show_when = display_logic.get("show_when", [])
            for condition in show_when:
                if "schema" in condition:
                    dependencies.add(condition["schema"])

            self.dependency_graph[schema_name] = dependencies

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate all display_logic configurations.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        for scheme in self.schemes:
            schema_name = scheme.get("name", "<unnamed>")
            display_logic = scheme.get("display_logic")

            # Skip if display_logic is not present (None) or not a dict
            if display_logic is None:
                continue
            if not isinstance(display_logic, dict):
                errors.append(f"Schema '{schema_name}': display_logic must be a dictionary")
                continue

            # Validate structure (including empty dict - which is invalid)
            structure_errors = self._validate_structure(schema_name, display_logic)
            errors.extend(structure_errors)

            # Validate referenced schemas exist
            reference_errors = self._validate_references(schema_name, display_logic)
            errors.extend(reference_errors)

        # Check for circular dependencies
        cycle_errors = self._detect_cycles()
        errors.extend(cycle_errors)

        return len(errors) == 0, errors

    def _validate_structure(self, schema_name: str, display_logic: Dict) -> List[str]:
        """Validate the structure of a display_logic configuration."""
        errors = []

        # Must have show_when
        if "show_when" not in display_logic:
            errors.append(f"Schema '{schema_name}': display_logic must have 'show_when' field")
            return errors

        show_when = display_logic["show_when"]
        if not isinstance(show_when, list):
            errors.append(f"Schema '{schema_name}': 'show_when' must be a list of conditions")
            return errors

        if len(show_when) == 0:
            errors.append(f"Schema '{schema_name}': 'show_when' must have at least one condition")
            return errors

        # Validate each condition
        for i, condition in enumerate(show_when):
            prefix = f"Schema '{schema_name}', condition {i+1}"

            if not isinstance(condition, dict):
                errors.append(f"{prefix}: condition must be a dictionary")
                continue

            # Required fields
            if "schema" not in condition:
                errors.append(f"{prefix}: missing required 'schema' field")

            if "operator" not in condition:
                errors.append(f"{prefix}: missing required 'operator' field")
            elif condition["operator"] not in SUPPORTED_OPERATORS:
                errors.append(f"{prefix}: unsupported operator '{condition['operator']}'. "
                            f"Supported: {list(SUPPORTED_OPERATORS.keys())}")

            # Validate operator-specific requirements
            operator = condition.get("operator")
            if operator:
                op_errors = self._validate_operator_value(prefix, operator, condition.get("value"))
                errors.extend(op_errors)

        # Validate logic field if present
        logic = display_logic.get("logic", "all")
        if logic not in ("all", "any"):
            errors.append(f"Schema '{schema_name}': 'logic' must be 'all' or 'any', got '{logic}'")

        return errors

    def _validate_operator_value(self, prefix: str, operator: str, value: Any) -> List[str]:
        """Validate that the value is appropriate for the operator."""
        errors = []

        # Operators that don't need a value
        if operator in ("empty", "not_empty"):
            return errors

        # Range operators need [min, max]
        if operator in ("in_range", "not_in_range", "length_in_range"):
            if not isinstance(value, (list, tuple)):
                errors.append(f"{prefix}: operator '{operator}' requires a range value as [min, max]")
            elif len(value) != 2:
                errors.append(f"{prefix}: range value must have exactly 2 elements [min, max]")
            else:
                try:
                    min_val, max_val = float(value[0]), float(value[1])
                    if min_val > max_val:
                        errors.append(f"{prefix}: range min ({min_val}) is greater than max ({max_val})")
                except (ValueError, TypeError):
                    errors.append(f"{prefix}: range values must be numeric")
            return errors

        # Numeric operators need numeric values
        if operator in ("gt", "gte", "lt", "lte", "length_gt", "length_lt"):
            if value is None:
                errors.append(f"{prefix}: operator '{operator}' requires a value")
            else:
                try:
                    float(value)
                except (ValueError, TypeError):
                    errors.append(f"{prefix}: operator '{operator}' requires a numeric value")
            return errors

        # Regex operator needs a valid pattern
        if operator == "matches":
            if value is None:
                errors.append(f"{prefix}: operator 'matches' requires a regex pattern")
            else:
                try:
                    re.compile(value)
                except re.error as e:
                    errors.append(f"{prefix}: invalid regex pattern '{value}': {e}")
            return errors

        # Other operators just need a non-None value
        if value is None:
            errors.append(f"{prefix}: operator '{operator}' requires a value")

        return errors

    def _validate_references(self, schema_name: str, display_logic: Dict) -> List[str]:
        """Validate that all referenced schemas exist."""
        errors = []
        show_when = display_logic.get("show_when", [])

        for i, condition in enumerate(show_when):
            ref_schema = condition.get("schema")
            if ref_schema and ref_schema not in self.schema_names:
                errors.append(
                    f"Schema '{schema_name}', condition {i+1}: references unknown schema '{ref_schema}'"
                )

        return errors

    def _detect_cycles(self) -> List[str]:
        """Detect circular dependencies using DFS."""
        errors = []
        visited = set()
        rec_stack = set()

        def dfs(node: str, path: List[str]) -> Optional[List[str]]:
            """DFS to detect cycles, returns cycle path if found."""
            if node in rec_stack:
                # Found a cycle
                cycle_start = path.index(node)
                return path[cycle_start:] + [node]

            if node in visited:
                return None

            visited.add(node)
            rec_stack.add(node)

            for neighbor in self.dependency_graph.get(node, set()):
                result = dfs(neighbor, path + [node])
                if result:
                    return result

            rec_stack.remove(node)
            return None

        for schema in self.dependency_graph:
            if schema not in visited:
                cycle = dfs(schema, [])
                if cycle:
                    cycle_str = " -> ".join(cycle)
                    errors.append(f"Circular dependency detected: {cycle_str}")

        return errors

    def get_schema_dependencies(self, schema_name: str) -> Set[str]:
        """Get the schemas that a given schema depends on."""
        return self.dependency_graph.get(schema_name, set())

    def get_dependents(self, schema_name: str) -> Set[str]:
        """Get schemas that depend on the given schema."""
        dependents = set()
        for schema, deps in self.dependency_graph.items():
            if schema_name in deps:
                dependents.add(schema)
        return dependents


class DisplayLogicEvaluator:
    """
    Evaluates display logic conditions at runtime.

    This class is used both server-side (Python) and provides the logic
    that's replicated in the frontend JavaScript.
    """

    @staticmethod
    def evaluate_condition(
        condition: DisplayLogicCondition,
        schema_value: Any
    ) -> bool:
        """
        Evaluate a single condition against a schema value.

        Args:
            condition: The condition to evaluate
            schema_value: Current value of the watched schema

        Returns:
            bool: Whether the condition is satisfied
        """
        operator = condition.operator
        expected = condition.value
        case_sensitive = condition.case_sensitive

        # Handle empty checks first
        if operator == "empty":
            return DisplayLogicEvaluator._is_empty(schema_value)

        if operator == "not_empty":
            return not DisplayLogicEvaluator._is_empty(schema_value)

        # For all other operators, normalize the actual value
        actual = schema_value

        # Apply case normalization for text comparisons
        if not case_sensitive and isinstance(actual, str):
            actual = actual.lower()

        # Equality operators
        if operator == "equals":
            return DisplayLogicEvaluator._check_equals(actual, expected, case_sensitive)

        if operator == "not_equals":
            return not DisplayLogicEvaluator._check_equals(actual, expected, case_sensitive)

        # Contains operators (for lists and text)
        if operator == "contains":
            return DisplayLogicEvaluator._check_contains(actual, expected, case_sensitive)

        if operator == "not_contains":
            return not DisplayLogicEvaluator._check_contains(actual, expected, case_sensitive)

        # Regex matching
        if operator == "matches":
            if not isinstance(actual, str):
                actual = str(actual) if actual is not None else ""
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                return bool(re.search(expected, actual, flags))
            except re.error:
                logger.warning(f"Invalid regex pattern: {expected}")
                return False

        # Numeric comparisons
        if operator in ("gt", "gte", "lt", "lte"):
            return DisplayLogicEvaluator._check_numeric(operator, actual, expected)

        # Range operators
        if operator in ("in_range", "not_in_range"):
            result = DisplayLogicEvaluator._check_range(actual, expected)
            return result if operator == "in_range" else not result

        # Length operators
        if operator in ("length_gt", "length_lt"):
            return DisplayLogicEvaluator._check_length(operator, actual, expected)

        if operator == "length_in_range":
            return DisplayLogicEvaluator._check_length_range(actual, expected)

        logger.warning(f"Unknown operator: {operator}")
        return False

    @staticmethod
    def _is_empty(value: Any) -> bool:
        """Check if a value is considered empty."""
        if value is None:
            return True
        if isinstance(value, str):
            return len(value.strip()) == 0
        if isinstance(value, (list, dict, set)):
            return len(value) == 0
        return False

    @staticmethod
    def _check_equals(actual: Any, expected: Any, case_sensitive: bool) -> bool:
        """Check equality, handling single values and lists."""
        # If expected is a list, check if actual matches ANY of them
        if isinstance(expected, list):
            for exp in expected:
                if DisplayLogicEvaluator._values_equal(actual, exp, case_sensitive):
                    return True
            return False

        return DisplayLogicEvaluator._values_equal(actual, expected, case_sensitive)

    @staticmethod
    def _values_equal(actual: Any, expected: Any, case_sensitive: bool) -> bool:
        """Compare two values for equality."""
        # Handle None
        if actual is None and expected is None:
            return True
        if actual is None or expected is None:
            return False

        # String comparison with case sensitivity
        if isinstance(expected, str):
            actual_str = str(actual)
            if not case_sensitive:
                return actual_str.lower() == expected.lower()
            return actual_str == expected

        # Direct comparison for non-strings
        return actual == expected

    @staticmethod
    def _check_contains(actual: Any, expected: Any, case_sensitive: bool) -> bool:
        """Check if actual contains expected value(s)."""
        # If expected is a list, check if actual contains ANY of them
        if isinstance(expected, list):
            for exp in expected:
                if DisplayLogicEvaluator._value_contains(actual, exp, case_sensitive):
                    return True
            return False

        return DisplayLogicEvaluator._value_contains(actual, expected, case_sensitive)

    @staticmethod
    def _value_contains(actual: Any, expected: Any, case_sensitive: bool) -> bool:
        """Check if actual contains a single expected value."""
        # If actual is a list (multiselect), check membership
        if isinstance(actual, list):
            for item in actual:
                if DisplayLogicEvaluator._values_equal(item, expected, case_sensitive):
                    return True
            return False

        # If actual is a string, check substring
        if isinstance(actual, str):
            expected_str = str(expected)
            if not case_sensitive:
                return expected_str.lower() in actual.lower()
            return expected_str in actual

        # Fallback to equality
        return DisplayLogicEvaluator._values_equal(actual, expected, case_sensitive)

    @staticmethod
    def _check_numeric(operator: str, actual: Any, expected: Any) -> bool:
        """Check numeric comparison."""
        try:
            actual_num = float(actual) if actual is not None else 0
            expected_num = float(expected)
        except (ValueError, TypeError):
            return False

        if operator == "gt":
            return actual_num > expected_num
        if operator == "gte":
            return actual_num >= expected_num
        if operator == "lt":
            return actual_num < expected_num
        if operator == "lte":
            return actual_num <= expected_num

        return False

    @staticmethod
    def _check_range(actual: Any, range_val: List) -> bool:
        """Check if actual is within range (inclusive)."""
        try:
            actual_num = float(actual) if actual is not None else 0
            min_val, max_val = float(range_val[0]), float(range_val[1])
        except (ValueError, TypeError, IndexError):
            return False

        return min_val <= actual_num <= max_val

    @staticmethod
    def _check_length(operator: str, actual: Any, expected: Any) -> bool:
        """Check text length comparison."""
        try:
            length = len(str(actual)) if actual is not None else 0
            expected_len = int(expected)
        except (ValueError, TypeError):
            return False

        if operator == "length_gt":
            return length > expected_len
        if operator == "length_lt":
            return length < expected_len

        return False

    @staticmethod
    def _check_length_range(actual: Any, range_val: List) -> bool:
        """Check if text length is within range (inclusive)."""
        try:
            length = len(str(actual)) if actual is not None else 0
            min_len, max_len = int(range_val[0]), int(range_val[1])
        except (ValueError, TypeError, IndexError):
            return False

        return min_len <= length <= max_len

    @staticmethod
    def evaluate_rule(
        rule: DisplayLogicRule,
        annotations: Dict[str, Any]
    ) -> bool:
        """
        Evaluate a complete display logic rule.

        Args:
            rule: The DisplayLogicRule to evaluate
            annotations: Current annotations dictionary {schema_name: value}

        Returns:
            bool: Whether the schema should be visible
        """
        if not rule.conditions:
            # No conditions = always visible
            return True

        results = []
        for condition in rule.conditions:
            schema_value = annotations.get(condition.schema)
            result = DisplayLogicEvaluator.evaluate_condition(condition, schema_value)
            results.append(result)

        if rule.logic == "all":
            return all(results)
        else:  # "any"
            return any(results)

    @staticmethod
    def evaluate_visibility(
        schema_name: str,
        display_logic: Optional[Dict],
        annotations: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluate whether a schema should be visible.

        Args:
            schema_name: Name of the schema being evaluated
            display_logic: The display_logic configuration (can be None)
            annotations: Current annotations dictionary

        Returns:
            Tuple of (is_visible, reason_if_hidden)
        """
        if not display_logic:
            return True, None

        try:
            rule = DisplayLogicRule.from_dict(display_logic)
            is_visible = DisplayLogicEvaluator.evaluate_rule(rule, annotations)

            if not is_visible:
                # Build reason string
                reasons = []
                for cond in rule.conditions:
                    actual_val = annotations.get(cond.schema, "<not set>")
                    reasons.append(f"{cond.schema} {cond.operator} {cond.value} (actual: {actual_val})")
                reason = f"Conditions not met ({rule.logic}): " + ", ".join(reasons)
                return False, reason

            return True, None

        except Exception as e:
            logger.error(f"Error evaluating display logic for {schema_name}: {e}")
            # Default to visible on error
            return True, None


def validate_display_logic_config(
    annotation_schemes: List[Dict[str, Any]]
) -> Tuple[bool, List[str]]:
    """
    Convenience function to validate display_logic across all annotation schemes.

    Args:
        annotation_schemes: List of annotation scheme configurations

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    validator = DisplayLogicValidator(annotation_schemes)
    return validator.validate()


def get_display_logic_dependencies(
    annotation_schemes: List[Dict[str, Any]]
) -> Dict[str, Set[str]]:
    """
    Get the dependency graph for all schemas with display_logic.

    Args:
        annotation_schemes: List of annotation scheme configurations

    Returns:
        Dictionary mapping schema names to their dependencies
    """
    validator = DisplayLogicValidator(annotation_schemes)
    return validator.dependency_graph
