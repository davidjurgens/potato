"""
Unit tests for annotation navigation features.

Tests for:
- find_next_unannotated_index() method
- has_annotated() method
- Annotation status indicator logic
"""

import pytest
from potato.user_state_management import InMemoryUserState, UserPhase
from potato.item_state_management import Label, SpanAnnotation


class TestFindNextUnannotatedIndex:
    """Tests for the find_next_unannotated_index method."""

    def test_find_next_unannotated_basic(self):
        """Test basic case: find first unannotated item after current position."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        # Set up 5 instances
        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.current_instance_index = 0

        # Annotate item0 (current position)
        label = Label("test_schema", "label1")
        user.add_label_annotation("item0", label, "true")

        # Should find item1 (first unannotated after current)
        next_idx = user.find_next_unannotated_index()
        assert next_idx == 1

    def test_find_next_unannotated_skip_annotated(self):
        """Test that it skips annotated items."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.current_instance_index = 0

        # Annotate item0 and item1
        label = Label("test_schema", "label1")
        user.add_label_annotation("item0", label, "true")
        user.add_label_annotation("item1", label, "true")

        # Should skip to item2
        next_idx = user.find_next_unannotated_index()
        assert next_idx == 2

    def test_find_next_unannotated_wrap_around(self):
        """Test that it wraps around to the beginning if no items found after current."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.current_instance_index = 3  # Near the end

        # Annotate items 3 and 4 (at and after current position)
        label = Label("test_schema", "label1")
        user.add_label_annotation("item3", label, "true")
        user.add_label_annotation("item4", label, "true")

        # Should wrap around to item0
        next_idx = user.find_next_unannotated_index()
        assert next_idx == 0

    def test_find_next_unannotated_all_annotated(self):
        """Test that it returns None when all items are annotated."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2"]
        user.current_instance_index = 0

        # Annotate all items
        label = Label("test_schema", "label1")
        user.add_label_annotation("item0", label, "true")
        user.add_label_annotation("item1", label, "true")
        user.add_label_annotation("item2", label, "true")

        # Should return None
        next_idx = user.find_next_unannotated_index()
        assert next_idx is None

    def test_find_next_unannotated_empty_ordering(self):
        """Test handling of empty instance ordering."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = []
        user.current_instance_index = 0

        next_idx = user.find_next_unannotated_index()
        assert next_idx is None

    def test_find_next_unannotated_current_is_only_unannotated(self):
        """Test when current position is the only unannotated item."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2"]
        user.current_instance_index = 1  # On item1

        # Annotate all except item1 (current)
        label = Label("test_schema", "label1")
        user.add_label_annotation("item0", label, "true")
        user.add_label_annotation("item2", label, "true")

        # Should return current index since it's the only unannotated
        next_idx = user.find_next_unannotated_index()
        assert next_idx == 1

    def test_find_next_unannotated_span_annotations(self):
        """Test that span annotations also mark an item as annotated."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2"]
        user.current_instance_index = 0

        # Add span annotation to item0
        span = SpanAnnotation("highlight", "span1", "Entity", 0, 5)
        user.add_span_annotation("item0", span, "selected")

        # Should skip item0 (has span annotation) and go to item1
        next_idx = user.find_next_unannotated_index()
        assert next_idx == 1


class TestFindPrevUnannotatedIndex:
    """Tests for the find_prev_unannotated_index method."""

    def test_find_prev_unannotated_basic(self):
        """Test basic case: find first unannotated item before current position."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        # Set up 5 instances
        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.current_instance_index = 3

        # Annotate item3 (current position)
        label = Label("test_schema", "label1")
        user.add_label_annotation("item3", label, "true")

        # Should find item2 (first unannotated before current)
        prev_idx = user.find_prev_unannotated_index()
        assert prev_idx == 2

    def test_find_prev_unannotated_skip_annotated(self):
        """Test that it skips annotated items."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.current_instance_index = 4

        # Annotate item3 and item4
        label = Label("test_schema", "label1")
        user.add_label_annotation("item3", label, "true")
        user.add_label_annotation("item4", label, "true")

        # Should skip to item2
        prev_idx = user.find_prev_unannotated_index()
        assert prev_idx == 2

    def test_find_prev_unannotated_wrap_around(self):
        """Test that it wraps around to the end if no items found before current."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.current_instance_index = 1  # Near the beginning

        # Annotate items 0 and 1 (at and before current position)
        label = Label("test_schema", "label1")
        user.add_label_annotation("item0", label, "true")
        user.add_label_annotation("item1", label, "true")

        # Should wrap around to item4
        prev_idx = user.find_prev_unannotated_index()
        assert prev_idx == 4

    def test_find_prev_unannotated_all_annotated(self):
        """Test that it returns None when all items are annotated."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2"]
        user.current_instance_index = 2

        # Annotate all items
        label = Label("test_schema", "label1")
        user.add_label_annotation("item0", label, "true")
        user.add_label_annotation("item1", label, "true")
        user.add_label_annotation("item2", label, "true")

        # Should return None
        prev_idx = user.find_prev_unannotated_index()
        assert prev_idx is None

    def test_find_prev_unannotated_empty_ordering(self):
        """Test handling of empty instance ordering."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = []
        user.current_instance_index = 0

        prev_idx = user.find_prev_unannotated_index()
        assert prev_idx is None

    def test_find_prev_unannotated_current_is_only_unannotated(self):
        """Test when current position is the only unannotated item."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2"]
        user.current_instance_index = 1  # On item1

        # Annotate all except item1 (current)
        label = Label("test_schema", "label1")
        user.add_label_annotation("item0", label, "true")
        user.add_label_annotation("item2", label, "true")

        # Should return current index since it's the only unannotated
        prev_idx = user.find_prev_unannotated_index()
        assert prev_idx == 1


class TestHasAnnotated:
    """Tests for the has_annotated method."""

    def test_has_annotated_with_label(self):
        """Test has_annotated returns True for items with label annotations."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        label = Label("test_schema", "label1")
        user.add_label_annotation("item1", label, "true")

        assert user.has_annotated("item1") is True
        assert user.has_annotated("item2") is False

    def test_has_annotated_with_span(self):
        """Test has_annotated returns True for items with span annotations."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        span = SpanAnnotation("highlight", "span1", "Entity", 0, 5)
        user.add_span_annotation("item1", span, "selected")

        assert user.has_annotated("item1") is True
        assert user.has_annotated("item2") is False

    def test_has_annotated_with_both(self):
        """Test has_annotated with both label and span annotations."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        label = Label("test_schema", "label1")
        span = SpanAnnotation("highlight", "span1", "Entity", 0, 5)

        user.add_label_annotation("item1", label, "true")
        user.add_span_annotation("item1", span, "selected")

        assert user.has_annotated("item1") is True


class TestAnnotationStatusLogic:
    """Tests for annotation status indicator logic."""

    def test_annotated_instance_ids_union(self):
        """Test that get_annotated_instance_ids returns union of label and span annotated IDs."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        # Add label annotation to item1
        label = Label("test_schema", "label1")
        user.add_label_annotation("item1", label, "true")

        # Add span annotation to item2
        span = SpanAnnotation("highlight", "span1", "Entity", 0, 5)
        user.add_span_annotation("item2", span, "selected")

        # Both should be in annotated IDs
        annotated_ids = user.get_annotated_instance_ids()
        assert "item1" in annotated_ids
        assert "item2" in annotated_ids
        assert len(annotated_ids) == 2

    def test_annotation_count(self):
        """Test that get_annotation_count returns correct count."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        # Initially zero
        assert user.get_annotation_count() == 0

        # Add label annotation
        label = Label("test_schema", "label1")
        user.add_label_annotation("item1", label, "true")
        assert user.get_annotation_count() == 1

        # Add span annotation to different item
        span = SpanAnnotation("highlight", "span1", "Entity", 0, 5)
        user.add_span_annotation("item2", span, "selected")
        assert user.get_annotation_count() == 2

        # Add more annotations to same item (should not increase count)
        user.add_label_annotation("item1", Label("test_schema", "label2"), "true")
        assert user.get_annotation_count() == 2


class TestNavigationIntegration:
    """Integration tests for navigation and status features."""

    def test_navigation_workflow(self):
        """Test typical navigation workflow with status tracking."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        # Set up instances
        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.current_instance_index = 0

        # Initial state: no annotations
        assert user.has_annotated("item0") is False
        assert user.find_next_unannotated_index() == 1  # Next unannotated is item1

        # Annotate item0
        label = Label("sentiment", "positive")
        user.add_label_annotation("item0", label, "true")

        # Verify status updated
        assert user.has_annotated("item0") is True
        assert user.get_annotation_count() == 1

        # Navigate forward
        user.go_forward()
        assert user.current_instance_index == 1

        # Annotate item1
        user.add_label_annotation("item1", label, "true")
        assert user.has_annotated("item1") is True

        # Skip to next unannotated
        next_idx = user.find_next_unannotated_index()
        assert next_idx == 2
        user.go_to_index(next_idx)
        assert user.current_instance_index == 2

    def test_go_to_index_bounds(self):
        """Test that go_to_index respects bounds."""
        user = InMemoryUserState("test_user")
        user.instance_id_ordering = ["item0", "item1", "item2"]
        user.current_instance_index = 1

        # Valid index
        user.go_to_index(2)
        assert user.current_instance_index == 2

        # Invalid index (too high) - should not change
        user.go_to_index(10)
        assert user.current_instance_index == 2

        # Invalid index (negative) - should not change
        user.go_to_index(-1)
        assert user.current_instance_index == 2

        # Valid: go back to 0
        user.go_to_index(0)
        assert user.current_instance_index == 0
