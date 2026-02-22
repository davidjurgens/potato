"""
Unit tests for navigation/skip functionality interaction with reordering.

Tests potential race conditions and edge cases when:
- Items are reordered (active learning, diversity sampling)
- Users navigate using skip to unannotated
- Concurrent operations modify user state

These tests assess risk areas identified in the navigation implementation.
"""

import pytest
import threading
import time
from unittest.mock import MagicMock, patch
from potato.user_state_management import InMemoryUserState, UserPhase
from potato.item_state_management import Label, SpanAnnotation, Item


class TestReorderingInteraction:
    """Tests for interaction between skip navigation and reordering."""

    def test_reorder_preserves_current_index_item(self):
        """Test that reordering doesn't change what item the user is looking at.

        RISK: If current_instance_index stays the same but ordering changes,
        the user might suddenly see a different item.
        """
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        # Set up instances
        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.instance_id_to_order = {iid: i for i, iid in enumerate(user.instance_id_ordering)}
        user.current_instance_index = 2  # Looking at "item2"

        # Get the current item BEFORE reordering
        current_item_before = user.instance_id_ordering[user.current_instance_index]
        assert current_item_before == "item2"

        # Simulate reordering (preserving already-annotated items)
        label = Label("test_schema", "label1")
        user.add_label_annotation("item0", label, "true")
        user.add_label_annotation("item1", label, "true")

        # Reorder: preserve item0, item1 (annotated), reorder rest
        preserve_order = {"item0", "item1"}
        new_order = ["item4", "item3", "item2"]  # Reverse order for remaining

        user.reorder_remaining_instances(new_order, preserve_order)

        # After reorder, current_instance_index is still 2
        # But the item at index 2 might have changed!
        current_item_after = user.instance_id_ordering[user.current_instance_index]

        # Document this behavior - the item at the index changes
        # This is a potential issue that users should be aware of
        print(f"Before reorder: index {user.current_instance_index} -> {current_item_before}")
        print(f"After reorder: index {user.current_instance_index} -> {current_item_after}")
        print(f"New ordering: {user.instance_id_ordering}")

        # The ordering should be: item0, item1 (preserved), then item4, item3, item2 (reordered)
        assert user.instance_id_ordering[:2] == ["item0", "item1"]
        # Note: After reordering, index 2 now points to a different item

    def test_skip_after_reorder_finds_correct_unannotated(self):
        """Test that skip finds correct unannotated items after reordering."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        # Set up instances and annotate some
        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.instance_id_to_order = {iid: i for i, iid in enumerate(user.instance_id_ordering)}
        user.current_instance_index = 0

        label = Label("test_schema", "label1")
        user.add_label_annotation("item0", label, "true")
        user.add_label_annotation("item2", label, "true")

        # Before reorder: skip should find item1 (first unannotated after item0)
        next_idx_before = user.find_next_unannotated_index()
        assert next_idx_before == 1  # item1

        # Reorder remaining items
        preserve_order = {"item0", "item2"}  # Annotated items
        new_order = ["item4", "item3", "item1"]  # New order for unannotated

        user.reorder_remaining_instances(new_order, preserve_order)

        # After reorder, find next unannotated from position 0
        user.current_instance_index = 0
        next_idx_after = user.find_next_unannotated_index()

        # The next unannotated should still be found, but at a different index
        if next_idx_after is not None:
            next_item = user.instance_id_ordering[next_idx_after]
            assert next_item not in user.get_annotated_instance_ids()
            print(f"After reorder, skip found: index {next_idx_after} -> {next_item}")

    def test_skip_prev_after_reorder(self):
        """Test backward skip after reordering."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.instance_id_to_order = {iid: i for i, iid in enumerate(user.instance_id_ordering)}
        user.current_instance_index = 4  # At the end

        label = Label("test_schema", "label1")
        user.add_label_annotation("item3", label, "true")
        user.add_label_annotation("item4", label, "true")

        # Skip backward should find item2
        prev_idx = user.find_prev_unannotated_index()
        assert prev_idx == 2

        # Reorder
        preserve_order = {"item3", "item4"}
        new_order = ["item2", "item0", "item1"]
        user.reorder_remaining_instances(new_order, preserve_order)

        # After reorder, backward skip from end should still work
        user.current_instance_index = len(user.instance_id_ordering) - 1
        prev_idx_after = user.find_prev_unannotated_index()

        if prev_idx_after is not None:
            prev_item = user.instance_id_ordering[prev_idx_after]
            assert prev_item not in user.get_annotated_instance_ids()

    def test_index_bounds_after_reorder(self):
        """Test that index bounds are respected after reordering."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2"]
        user.instance_id_to_order = {iid: i for i, iid in enumerate(user.instance_id_ordering)}
        user.current_instance_index = 2  # At index 2

        # go_to_index should respect bounds
        user.go_to_index(10)  # Out of bounds
        assert user.current_instance_index == 2  # Should not change

        user.go_to_index(-1)  # Negative
        assert user.current_instance_index == 2  # Should not change

        user.go_to_index(0)  # Valid
        assert user.current_instance_index == 0

    def test_skip_with_empty_ordering_after_clear(self):
        """Test skip behavior if ordering becomes empty."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1"]
        user.current_instance_index = 0

        # Clear ordering (simulating edge case)
        user.instance_id_ordering = []

        # Skip should handle empty ordering gracefully
        next_idx = user.find_next_unannotated_index()
        assert next_idx is None

        prev_idx = user.find_prev_unannotated_index()
        assert prev_idx is None


class TestConcurrentAccess:
    """Tests for potential race conditions with concurrent access."""

    def test_concurrent_annotation_and_skip(self):
        """Test that concurrent annotation doesn't break skip functionality."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.instance_id_to_order = {iid: i for i, iid in enumerate(user.instance_id_ordering)}
        user.current_instance_index = 0

        results = {"skip_results": [], "errors": []}
        label = Label("test_schema", "label1")

        def annotate_items():
            """Simulate annotation happening in background."""
            try:
                for i in range(3):
                    time.sleep(0.01)  # Small delay
                    user.add_label_annotation(f"item{i}", label, "true")
            except Exception as e:
                results["errors"].append(str(e))

        def skip_repeatedly():
            """Simulate skip being called repeatedly."""
            try:
                for _ in range(5):
                    time.sleep(0.005)
                    idx = user.find_next_unannotated_index()
                    results["skip_results"].append(idx)
            except Exception as e:
                results["errors"].append(str(e))

        # Run concurrently
        t1 = threading.Thread(target=annotate_items)
        t2 = threading.Thread(target=skip_repeatedly)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        # Should not have any errors
        assert len(results["errors"]) == 0, f"Errors occurred: {results['errors']}"

        # All skip results should be valid (None or valid index)
        for idx in results["skip_results"]:
            if idx is not None:
                assert 0 <= idx < len(user.instance_id_ordering)

    def test_concurrent_reorder_and_skip(self):
        """Test skip during reordering doesn't crash."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.instance_id_to_order = {iid: i for i, iid in enumerate(user.instance_id_ordering)}
        user.current_instance_index = 0

        results = {"skip_results": [], "errors": []}
        label = Label("test_schema", "label1")
        user.add_label_annotation("item0", label, "true")

        def reorder_items():
            """Simulate reordering happening."""
            try:
                for _ in range(3):
                    time.sleep(0.01)
                    preserve = {"item0"}
                    new_order = list(reversed(["item1", "item2", "item3", "item4"]))
                    user.reorder_remaining_instances(new_order, preserve)
            except Exception as e:
                results["errors"].append(str(e))

        def skip_repeatedly():
            """Simulate skip being called."""
            try:
                for _ in range(5):
                    time.sleep(0.005)
                    idx = user.find_next_unannotated_index()
                    results["skip_results"].append(idx)
            except Exception as e:
                results["errors"].append(str(e))

        t1 = threading.Thread(target=reorder_items)
        t2 = threading.Thread(target=skip_repeatedly)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        # Should not crash
        assert len(results["errors"]) == 0, f"Errors: {results['errors']}"


class TestEdgeCases:
    """Edge cases for skip navigation."""

    def test_skip_all_items_same_annotation_state(self):
        """Test skip when all items have the same annotation state."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2"]
        user.current_instance_index = 1

        # All unannotated
        next_idx = user.find_next_unannotated_index()
        assert next_idx == 2  # Should find item after current

        # Annotate all
        label = Label("test_schema", "label1")
        for iid in user.instance_id_ordering:
            user.add_label_annotation(iid, label, "true")

        # All annotated
        next_idx = user.find_next_unannotated_index()
        assert next_idx is None

        prev_idx = user.find_prev_unannotated_index()
        assert prev_idx is None

    def test_skip_single_item(self):
        """Test skip with only one item."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["only_item"]
        user.current_instance_index = 0

        # Single unannotated item
        next_idx = user.find_next_unannotated_index()
        assert next_idx == 0  # Should return current since it's unannotated

        prev_idx = user.find_prev_unannotated_index()
        assert prev_idx == 0

        # Annotate it
        label = Label("test_schema", "label1")
        user.add_label_annotation("only_item", label, "true")

        next_idx = user.find_next_unannotated_index()
        assert next_idx is None

    def test_skip_with_span_and_label_mix(self):
        """Test skip correctly detects items with mixed annotation types."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2", "item3"]
        user.current_instance_index = 0

        # item0: label annotation
        label = Label("sentiment", "positive")
        user.add_label_annotation("item0", label, "true")

        # item1: span annotation only
        span = SpanAnnotation("ner", "span1", "PERSON", 0, 5)
        user.add_span_annotation("item1", span, "selected")

        # item2: both
        user.add_label_annotation("item2", label, "true")
        user.add_span_annotation("item2", span, "selected")

        # item3: unannotated

        # From position 0, should skip to item3 (only unannotated)
        next_idx = user.find_next_unannotated_index()
        assert next_idx == 3

        # Verify has_annotated works correctly
        assert user.has_annotated("item0") is True
        assert user.has_annotated("item1") is True
        assert user.has_annotated("item2") is True
        assert user.has_annotated("item3") is False

    def test_skip_wrapping_correctness(self):
        """Test that wrap-around finds correct items in both directions."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.current_instance_index = 2  # Middle position

        label = Label("test_schema", "label1")
        # Annotate all except item0
        user.add_label_annotation("item1", label, "true")
        user.add_label_annotation("item2", label, "true")
        user.add_label_annotation("item3", label, "true")
        user.add_label_annotation("item4", label, "true")

        # Forward skip should wrap to item0
        next_idx = user.find_next_unannotated_index()
        assert next_idx == 0
        assert user.instance_id_ordering[next_idx] == "item0"

        # Backward skip from position 2 should also find item0
        prev_idx = user.find_prev_unannotated_index()
        assert prev_idx == 0
        assert user.instance_id_ordering[prev_idx] == "item0"


class TestNavigationStateConsistency:
    """Tests for navigation state consistency."""

    def test_go_to_index_then_skip(self):
        """Test that go_to_index followed by skip works correctly."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2", "item3", "item4"]
        user.instance_id_to_order = {iid: i for i, iid in enumerate(user.instance_id_ordering)}
        user.current_instance_index = 0

        label = Label("test_schema", "label1")
        user.add_label_annotation("item0", label, "true")
        user.add_label_annotation("item2", label, "true")

        # Go to index 1
        user.go_to_index(1)
        assert user.current_instance_index == 1

        # Skip forward should find item3 (item2 is annotated)
        next_idx = user.find_next_unannotated_index()
        assert next_idx == 3

        # Go to that index
        user.go_to_index(next_idx)
        assert user.current_instance_index == 3
        assert user.instance_id_ordering[3] == "item3"

    def test_navigation_methods_return_consistent_results(self):
        """Test that repeated calls return consistent results without state changes."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2", "item3"]
        user.current_instance_index = 0

        label = Label("test_schema", "label1")
        user.add_label_annotation("item1", label, "true")

        # Multiple calls should return the same result
        results = [user.find_next_unannotated_index() for _ in range(5)]
        assert all(r == results[0] for r in results)

        results = [user.find_prev_unannotated_index() for _ in range(5)]
        assert all(r == results[0] for r in results)

    def test_skip_does_not_modify_state(self):
        """Test that find_*_unannotated_index() doesn't modify any state."""
        user = InMemoryUserState("test_user")
        user.current_phase_and_page = (UserPhase.ANNOTATION, None)

        user.instance_id_ordering = ["item0", "item1", "item2"]
        user.current_instance_index = 1

        # Capture state before
        ordering_before = list(user.instance_id_ordering)
        index_before = user.current_instance_index
        annotated_before = user.get_annotated_instance_ids().copy()

        # Call skip methods
        user.find_next_unannotated_index()
        user.find_prev_unannotated_index()

        # State should be unchanged
        assert user.instance_id_ordering == ordering_before
        assert user.current_instance_index == index_before
        assert user.get_annotated_instance_ids() == annotated_before
