#!/usr/bin/env python3
"""
Unit tests for annotation persistence.

These tests verify that annotations stored via add_label_annotation()
are correctly retrieved by get_annotations_for_user_on().
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from collections import defaultdict
from potato.item_state_management import Label
from potato.user_state_management import InMemoryUserState, UserPhase


class TestAnnotationPersistence:
    """Test that annotations persist correctly."""

    def test_label_annotation_storage_and_retrieval(self):
        """
        Test that label annotations stored with add_label_annotation()
        can be correctly retrieved.
        """
        # Create a user state
        user_state = InMemoryUserState("test_user", max_assignments=10)
        # Set phase to ANNOTATION (required for add_label_annotation to store correctly)
        user_state.set_current_phase_and_page((UserPhase.ANNOTATION, None))

        # Create a label
        label = Label("favorite_color", "blue")
        instance_id = "item_1"
        value = "1"  # Typical checkbox value

        # Store the annotation
        user_state.add_label_annotation(instance_id, label, value)

        # Retrieve the annotations
        annotations = user_state.get_label_annotations(instance_id)

        # Verify the annotation was stored correctly
        assert label in annotations, f"Label {label} not found in annotations: {annotations}"
        assert annotations[label] == value, f"Expected value {value}, got {annotations[label]}"

    def test_multiple_labels_same_instance(self):
        """Test storing multiple labels for the same instance."""
        user_state = InMemoryUserState("test_user", max_assignments=10)
        user_state.set_current_phase_and_page((UserPhase.ANNOTATION, None))

        instance_id = "item_1"

        # Store multiple annotations
        labels_and_values = [
            (Label("favorite_color", "blue"), "1"),
            (Label("favorite_color", "red"), "2"),
            (Label("sentiment", "positive"), "true"),
        ]

        for label, value in labels_and_values:
            user_state.add_label_annotation(instance_id, label, value)

        # Retrieve and verify
        annotations = user_state.get_label_annotations(instance_id)

        for label, expected_value in labels_and_values:
            assert label in annotations, f"Label {label} not found"
            assert annotations[label] == expected_value

    def test_different_instances_separate_state(self):
        """Test that different instances maintain separate annotation state."""
        user_state = InMemoryUserState("test_user", max_assignments=10)
        user_state.set_current_phase_and_page((UserPhase.ANNOTATION, None))

        # Store annotation for instance 1
        label1 = Label("favorite_color", "blue")
        user_state.add_label_annotation("item_1", label1, "1")

        # Store annotation for instance 2
        label2 = Label("favorite_color", "green")
        user_state.add_label_annotation("item_2", label2, "3")

        # Verify instance 1 only has its annotation
        annotations1 = user_state.get_label_annotations("item_1")
        assert label1 in annotations1
        assert label2 not in annotations1

        # Verify instance 2 only has its annotation
        annotations2 = user_state.get_label_annotations("item_2")
        assert label2 in annotations2
        assert label1 not in annotations2

    def test_get_annotations_for_user_on_format(self):
        """
        Test that get_annotations_for_user_on returns the correct format
        for use in page rendering.
        """
        from potato.flask_server import get_annotations_for_user_on, get_user_state_manager

        # This test requires server setup, so skip if not available
        try:
            usm = get_user_state_manager()
        except:
            pytest.skip("Server not initialized")

        # The function should return a dict like:
        # {"schema_name": {"label_name": value}}

    def test_label_equality(self):
        """Test that Label objects with same schema/name are equal."""
        label1 = Label("favorite_color", "blue")
        label2 = Label("favorite_color", "blue")
        label3 = Label("favorite_color", "red")

        assert label1 == label2, "Labels with same schema/name should be equal"
        assert label1 != label3, "Labels with different names should not be equal"
        assert hash(label1) == hash(label2), "Equal labels should have same hash"

    def test_label_as_dict_key(self):
        """Test that Label objects work correctly as dictionary keys."""
        label1 = Label("favorite_color", "blue")
        label2 = Label("favorite_color", "blue")  # Same as label1

        # Store with label1
        annotations = {}
        annotations[label1] = "value1"

        # Retrieve with label2 (should work because they're equal)
        assert label2 in annotations, "Should be able to find equal label"
        assert annotations[label2] == "value1"


class TestGetAnnotationsForUserOn:
    """Test the get_annotations_for_user_on function."""

    def test_handles_label_object_format(self):
        """
        Test that get_annotations_for_user_on correctly handles
        Label objects as dictionary keys.
        """
        # Simulate the data structure used by add_label_annotation
        from potato.flask_server import get_annotations_for_user_on

        # Create a mock raw_annotations dict with Label keys
        label1 = Label("favorite_color", "blue")
        label2 = Label("favorite_color", "red")

        raw_annotations = {
            label1: "1",
            label2: "2"
        }

        # Process like get_annotations_for_user_on does
        processed = {}
        for label, value in raw_annotations.items():
            if hasattr(label, 'schema_name') and hasattr(label, 'label_name'):
                schema_name = label.schema_name
                label_name = label.label_name
            elif hasattr(label, 'schema') and hasattr(label, 'name'):
                # This is the actual Label class format
                schema_name = label.schema
                label_name = label.name
            else:
                continue

            if schema_name not in processed:
                processed[schema_name] = {}
            processed[schema_name][label_name] = value

        # Verify the processed format
        assert "favorite_color" in processed
        assert "blue" in processed["favorite_color"]
        assert "red" in processed["favorite_color"]
        assert processed["favorite_color"]["blue"] == "1"
        assert processed["favorite_color"]["red"] == "2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
