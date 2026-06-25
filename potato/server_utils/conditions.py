"""
Shared condition matcher for item-data rules.

Extracted from ``triage.py`` so both the triage scorer and the automation-rules
engine evaluate the same ``when`` grammar against an item's data dict:

    {"field": "metadata.score", "lt": 0.5}
    {"field": "status", "in": ["error", "failed"]}
    {"field": "tags", "contains": "urgent"}
    {"field": "feedback", "exists": true}

Supported operators: ``equals``, ``in``, ``contains``, ``exists``,
``lt`` / ``lte`` / ``gt`` / ``gte``. String comparisons for equals/in are
case-insensitive; numeric comparisons coerce both sides; ``contains`` tests
membership in a list/string field. Field paths may be dotted (``metadata.score``).
"""

from __future__ import annotations

from typing import Any, Dict


def lookup(data: Dict[str, Any], field: str):
    """Resolve a possibly dotted field path against an item dict.

    Returns None if any segment is missing or a non-dict is traversed.
    """
    cur = data
    for part in str(field).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def as_number(value):
    """Coerce a value to float, or None if it isn't numeric (bools excluded)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (ValueError, AttributeError):
            return None
    return None


def matches(condition: Dict[str, Any], data: Dict[str, Any]) -> bool:
    """Evaluate a single ``when`` condition against item data."""
    field = condition.get("field")
    if field is None:
        return False
    value = lookup(data, field)

    if "exists" in condition:
        present = value is not None
        return present == bool(condition["exists"])

    # Absent fields never match value-based operators.
    if value is None:
        return False

    if "equals" in condition:
        target = condition["equals"]
        if isinstance(value, str) and isinstance(target, str):
            return value.strip().lower() == target.strip().lower()
        return value == target

    if "in" in condition:
        options = condition["in"] or []
        norm = [o.lower() if isinstance(o, str) else o for o in options]
        v = value.lower() if isinstance(value, str) else value
        return v in norm

    if "contains" in condition:
        target = condition["contains"]
        if isinstance(value, (list, tuple, set)):
            tnorm = target.lower() if isinstance(target, str) else target
            return any(
                (item.lower() if isinstance(item, str) else item) == tnorm
                for item in value
            )
        if isinstance(value, str) and isinstance(target, str):
            return target.lower() in value.lower()
        return False

    for op in ("lt", "lte", "gt", "gte"):
        if op in condition:
            lhs, rhs = as_number(value), as_number(condition[op])
            if lhs is None or rhs is None:
                return False
            if op == "lt":
                return lhs < rhs
            if op == "lte":
                return lhs <= rhs
            if op == "gt":
                return lhs > rhs
            return lhs >= rhs

    return False


def matches_all(conditions, data: Dict[str, Any]) -> bool:
    """True if every condition in the list matches (AND). Empty list -> True
    (an unconditional rule)."""
    if not conditions:
        return True
    if isinstance(conditions, dict):
        conditions = [conditions]
    return all(matches(c, data) for c in conditions)
