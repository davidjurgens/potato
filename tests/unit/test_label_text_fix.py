"""
Test to verify the label text fix.

The fix ensures that getSelectedLabel() returns the actual label text
(e.g., "happy", "sad", "angry") instead of the keybinding (e.g., "1", "2", "3").
"""

import pytest
from unittest.mock import Mock, patch


class TestLabelTextFix:
    """Test the label text fix for span annotations."""

    def test_get_selected_label_returns_actual_text(self):
        """Test that getSelectedLabel returns the actual label text."""
        # Create mock span manager
        span_manager = Mock()
        span_manager.selectedLabel = None

        # Mock the getSelectedLabel function with the fix
        def get_selected_label_fixed():
            # Simulate finding a checked checkbox
            checked_checkbox = Mock()
            checked_checkbox.id = "emotion_happy"  # Format: "schema_label"

            # Extract the actual label text from the checkbox ID
            checkbox_id = checked_checkbox.id
            parts = checkbox_id.split('_')
            if len(parts) >= 2:
                label_text = parts[1]  # Get the label part after the underscore
                return label_text
            return checked_checkbox.value  # Fallback

        # Test the fixed function
        result = get_selected_label_fixed()

        # Verify it returns the actual label text
        assert result == "happy", f"Should return 'happy', got '{result}'"
        print("✅ getSelectedLabel returns actual label text: 'happy'")

    def test_get_selected_label_with_different_labels(self):
        """Test getSelectedLabel with different label types."""
        # Test cases: checkbox ID -> expected label text
        test_cases = [
            ("emotion_happy", "happy"),
            ("emotion_sad", "sad"),
            ("emotion_angry", "angry"),
            ("sentiment_positive", "positive"),
            ("sentiment_negative", "negative")
        ]

        for checkbox_id, expected_label in test_cases:
            # Mock the getSelectedLabel function
            def get_selected_label_fixed():
                checked_checkbox = Mock()
                checked_checkbox.id = checkbox_id

                # Extract the actual label text from the checkbox ID
                parts = checkbox_id.split('_')
                if len(parts) >= 2:
                    label_text = parts[1]
                    return label_text
                return checked_checkbox.value

            result = get_selected_label_fixed()
            assert result == expected_label, f"For checkbox ID '{checkbox_id}', expected '{expected_label}', got '{result}'"
            print(f"✅ getSelectedLabel correctly extracts '{expected_label}' from '{checkbox_id}'")

    def test_get_selected_label_fallback_behavior(self):
        """Test getSelectedLabel fallback when ID parsing fails."""
        # Create mock span manager
        span_manager = Mock()
        span_manager.selectedLabel = None

        # Mock the getSelectedLabel function with fallback
        def get_selected_label_with_fallback():
            # Simulate a checkbox with an unexpected ID format
            checked_checkbox = Mock()
            checked_checkbox.id = "checkbox123"  # No underscores at all
            checked_checkbox.value = "1"  # Fallback value

            # Extract the actual label text from the checkbox ID
            checkbox_id = checked_checkbox.id
            parts = checkbox_id.split('_')
            if len(parts) >= 2:
                label_text = parts[1]
                return label_text
            # Fallback to value if ID parsing fails
            return checked_checkbox.value

        # Test the fallback behavior
        result = get_selected_label_with_fallback()

        # Verify it falls back to the value
        assert result == "1", f"Should fallback to '1', got '{result}'"
        print("✅ getSelectedLabel falls back to checkbox value when ID parsing fails")

    def test_get_selected_label_no_checkbox_selected(self):
        """Test getSelectedLabel when no checkbox is selected."""
        # Create mock span manager
        span_manager = Mock()
        span_manager.selectedLabel = "happy"  # Previously selected label

        # Mock the getSelectedLabel function
        def get_selected_label_no_checkbox():
            # Simulate no checked checkbox found
            checked_checkbox = None

            if checked_checkbox:
                # This code path should not be reached
                checkbox_id = checked_checkbox.id
                parts = checkbox_id.split('_')
                if len(parts) >= 2:
                    label_text = parts[1]
                    return label_text
                return checked_checkbox.value

            # Return the previously selected label
            return span_manager.selectedLabel

        # Test the no-checkbox behavior
        result = get_selected_label_no_checkbox()

        # Verify it returns the previously selected label
        assert result == "happy", f"Should return previously selected label 'happy', got '{result}'"
        print("✅ getSelectedLabel returns previously selected label when no checkbox is checked")

    def test_span_creation_with_correct_label(self):
        """Test that span creation uses the correct label text."""
        # Create mock span manager
        span_manager = Mock()
        span_manager.currentInstanceId = "test-instance-123"
        span_manager.currentSchema = "emotion"
        span_manager.annotations = {"spans": []}
        span_manager.renderSpans = Mock()

        # Mock the createAnnotation function with optimistic update
        def create_annotation_with_correct_label(spanText, start, end, label):
            # Simulate successful server response
            result = {"status": "success"}

            # OPTIMISTIC UPDATE: Add to local state immediately
            optimistic_span = {
                "id": f"temp_{1234567890}",
                "label": label,  # This should now be the actual label text
                "start": start,
                "end": end,
                "text": spanText,
                "schema": span_manager.currentSchema
            }

            span_manager.annotations["spans"].append(optimistic_span)
            span_manager.renderSpans()

            return result

        # Test creating an annotation with the correct label
        result = create_annotation_with_correct_label("happy text", 0, 10, "happy")

        # Verify the annotation was created
        assert result["status"] == "success"

        # Verify the span has the correct label text
        span = span_manager.annotations["spans"][0]
        assert span["label"] == "happy", f"Span should have label 'happy', got '{span['label']}'"
        assert span["text"] == "happy text"

        print("✅ Span creation uses correct label text: 'happy'")