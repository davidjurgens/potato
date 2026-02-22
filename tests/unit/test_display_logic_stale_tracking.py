"""
Unit tests for stale annotation tracking in display logic.

Tests that when annotations become stale (the schema becomes hidden due to
display logic changes), they are properly tracked and marked.
"""

import pytest
from potato.server_utils.display_logic import (
    DisplayLogicCondition,
    DisplayLogicRule,
    DisplayLogicEvaluator,
    DisplayLogicValidator,
)


class TestStaleAnnotationDetection:
    """Tests for detecting when annotations become stale."""

    def test_annotation_becomes_stale_on_parent_change(self):
        """Test that child annotations are marked stale when parent condition changes."""
        # Setup: Schema B depends on Schema A = "Yes"
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="schema_a", operator="equals", value="Yes")
            ]
        )

        # Initially, schema_a = "Yes", so schema_b is visible and has a value
        annotations_initial = {"schema_a": "Yes", "schema_b": "Some explanation"}
        visible_initial = DisplayLogicEvaluator.evaluate_rule(rule, annotations_initial)
        assert visible_initial is True

        # User changes schema_a to "No"
        annotations_after = {"schema_a": "No", "schema_b": "Some explanation"}
        visible_after = DisplayLogicEvaluator.evaluate_rule(rule, annotations_after)
        assert visible_after is False

        # The annotation in schema_b is now stale (hidden but has value)
        stale_annotations = {}
        if not visible_after and "schema_b" in annotations_after:
            stale_annotations["schema_b"] = annotations_after["schema_b"]

        assert "schema_b" in stale_annotations
        assert stale_annotations["schema_b"] == "Some explanation"

    def test_no_stale_if_no_value(self):
        """Test that empty schemas don't generate stale tracking."""
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="parent", operator="equals", value="Show")
            ]
        )

        # Schema is hidden and has no value - not stale
        annotations = {"parent": "Hide", "child": None}
        visible = DisplayLogicEvaluator.evaluate_rule(rule, annotations)
        assert visible is False

        # Child has no value, so nothing to mark as stale
        if not visible and annotations.get("child"):
            assert False, "Should not mark empty value as stale"

    def test_stale_tracking_with_multiselect(self):
        """Test stale tracking works with multiselect (list) values."""
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="category", operator="equals", value="Advanced")
            ]
        )

        # Initially showing advanced options
        annotations_initial = {
            "category": "Advanced",
            "advanced_options": ["Option1", "Option2", "Option3"]
        }
        visible_initial = DisplayLogicEvaluator.evaluate_rule(rule, annotations_initial)
        assert visible_initial is True

        # User changes to Basic
        annotations_after = {
            "category": "Basic",
            "advanced_options": ["Option1", "Option2", "Option3"]  # Value preserved
        }
        visible_after = DisplayLogicEvaluator.evaluate_rule(rule, annotations_after)
        assert visible_after is False

        # Track stale annotation
        stale_annotations = {}
        if not visible_after and annotations_after.get("advanced_options"):
            stale_annotations["advanced_options"] = annotations_after["advanced_options"]

        assert "advanced_options" in stale_annotations
        assert stale_annotations["advanced_options"] == ["Option1", "Option2", "Option3"]

    def test_stale_tracking_with_numeric_value(self):
        """Test stale tracking with numeric slider values."""
        rule = DisplayLogicRule(
            conditions=[
                DisplayLogicCondition(schema="enabled", operator="equals", value="Yes")
            ]
        )

        # Initially enabled with slider value
        annotations_initial = {"enabled": "Yes", "intensity": 7}
        visible_initial = DisplayLogicEvaluator.evaluate_rule(rule, annotations_initial)
        assert visible_initial is True

        # Disabled
        annotations_after = {"enabled": "No", "intensity": 7}
        visible_after = DisplayLogicEvaluator.evaluate_rule(rule, annotations_after)
        assert visible_after is False

        # Track stale
        stale_annotations = {}
        if not visible_after and "intensity" in annotations_after:
            stale_annotations["intensity"] = annotations_after["intensity"]

        assert stale_annotations["intensity"] == 7


class TestChainedStaleAnnotations:
    """Tests for stale tracking in chained display logic."""

    def test_cascading_stale_annotations(self):
        """Test that changing a parent makes all descendants stale."""
        # Schema B depends on A, Schema C depends on B
        rule_b = DisplayLogicRule(
            conditions=[DisplayLogicCondition(schema="schema_a", operator="equals", value="X")]
        )
        rule_c = DisplayLogicRule(
            conditions=[DisplayLogicCondition(schema="schema_b", operator="not_empty")]
        )

        # All schemas visible and have values
        annotations = {
            "schema_a": "X",
            "schema_b": "Value B",
            "schema_c": "Value C"
        }

        b_visible = DisplayLogicEvaluator.evaluate_rule(rule_b, annotations)
        c_visible = DisplayLogicEvaluator.evaluate_rule(rule_c, annotations)
        assert b_visible is True
        assert c_visible is True

        # Change A to something else
        annotations_after = {
            "schema_a": "Y",
            "schema_b": "Value B",
            "schema_c": "Value C"
        }

        b_visible_after = DisplayLogicEvaluator.evaluate_rule(rule_b, annotations_after)
        # Note: C's visibility depends on B having a value, which it still does
        # But in practice, the UI would hide B, making C's dependency on B unreachable
        # The stale tracking happens at the UI level

        assert b_visible_after is False

        # Both B and C have stale values
        stale = {}
        if not b_visible_after:
            if annotations_after.get("schema_b"):
                stale["schema_b"] = annotations_after["schema_b"]
            # In a cascading scenario, C would also become stale
            # (handled by the UI re-evaluating all dependencies)

        assert "schema_b" in stale


class TestStaleAnnotationPreservation:
    """Tests that stale annotations are preserved, not deleted."""

    def test_stale_value_preserved_after_hiding(self):
        """Test that hiding a schema preserves its annotation value."""
        rule = DisplayLogicRule(
            conditions=[DisplayLogicCondition(schema="show", operator="equals", value="Yes")]
        )

        # Start with value
        annotations = {"show": "Yes", "detail": "Important details here"}
        visible = DisplayLogicEvaluator.evaluate_rule(rule, annotations)
        assert visible is True

        # Hide by changing parent
        annotations["show"] = "No"
        visible = DisplayLogicEvaluator.evaluate_rule(rule, annotations)
        assert visible is False

        # The detail value should still be there
        assert annotations["detail"] == "Important details here"

    def test_stale_value_reactivated_when_shown_again(self):
        """Test that stale values are restored when schema becomes visible again."""
        rule = DisplayLogicRule(
            conditions=[DisplayLogicCondition(schema="toggle", operator="equals", value="On")]
        )

        annotations = {"toggle": "On", "setting": "Custom value"}

        # Toggle off
        annotations["toggle"] = "Off"
        assert DisplayLogicEvaluator.evaluate_rule(rule, annotations) is False
        assert annotations["setting"] == "Custom value"  # Preserved

        # Toggle back on
        annotations["toggle"] = "On"
        assert DisplayLogicEvaluator.evaluate_rule(rule, annotations) is True
        assert annotations["setting"] == "Custom value"  # Still there


class TestStaleAnnotationOutput:
    """Tests for stale annotation output format."""

    def test_visibility_state_includes_stale_info(self):
        """Test that evaluate_visibility returns reason when hidden."""
        display_logic = {
            "show_when": [
                {"schema": "parent", "operator": "equals", "value": "Show"}
            ]
        }

        annotations = {"parent": "Hide"}
        visible, reason = DisplayLogicEvaluator.evaluate_visibility(
            "child_schema", display_logic, annotations
        )

        assert visible is False
        assert reason is not None
        assert "Conditions not met" in reason
        assert "parent" in reason

    def test_stale_annotations_separated_in_output(self):
        """Test structure for separating active vs stale annotations."""
        # This simulates what the frontend would do
        rule_config = {
            "show_when": [
                {"schema": "main", "operator": "equals", "value": "Advanced"}
            ]
        }

        all_annotations = {
            "main": "Basic",  # Changed from Advanced
            "always_visible": "Value 1",
            "conditional_detail": "This detail is now stale"
        }

        schemas_with_display_logic = {"conditional_detail": rule_config}

        # Separate active from stale
        active_annotations = {}
        stale_annotations = {}

        for schema, value in all_annotations.items():
            if schema in schemas_with_display_logic:
                rule = schemas_with_display_logic[schema]
                visible, _ = DisplayLogicEvaluator.evaluate_visibility(
                    schema, rule, all_annotations
                )
                if visible:
                    active_annotations[schema] = value
                elif value:  # Has a value but hidden
                    stale_annotations[schema] = value
            else:
                active_annotations[schema] = value

        assert "main" in active_annotations
        assert "always_visible" in active_annotations
        assert "conditional_detail" not in active_annotations
        assert "conditional_detail" in stale_annotations
        assert stale_annotations["conditional_detail"] == "This detail is now stale"


class TestVisibilityStateTracking:
    """Tests for tracking visibility state changes."""

    def test_visibility_state_output(self):
        """Test get_visibility_state-like functionality."""
        rules = {
            "detail_a": {
                "show_when": [{"schema": "main", "operator": "equals", "value": "A"}]
            },
            "detail_b": {
                "show_when": [{"schema": "main", "operator": "equals", "value": "B"}]
            }
        }

        annotations = {"main": "A", "detail_a": "Info A", "detail_b": "Info B"}

        visibility_state = {}
        for schema, rule in rules.items():
            visible, reason = DisplayLogicEvaluator.evaluate_visibility(
                schema, rule, annotations
            )
            visibility_state[schema] = {
                "visible": visible,
                "reason": reason
            }

        assert visibility_state["detail_a"]["visible"] is True
        assert visibility_state["detail_a"]["reason"] is None

        assert visibility_state["detail_b"]["visible"] is False
        assert visibility_state["detail_b"]["reason"] is not None
        assert "B" in visibility_state["detail_b"]["reason"]  # Expected value mentioned
