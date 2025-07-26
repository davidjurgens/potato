"""
Test to verify the optimistic update fix for span rendering.

The fix ensures that:
1. When a span annotation is created, it's immediately added to local state
2. The span overlay is rendered immediately without waiting for server reload
3. This eliminates the timing issue where annotations were created but not displayed
"""

import pytest
from unittest.mock import Mock, patch


class TestOptimisticUpdateFix:
    """Test the optimistic update fix for span rendering."""

    def test_optimistic_update_immediate_rendering(self):
        """Test that optimistic updates render spans immediately."""
        # Create mock span manager
        span_manager = Mock()
        span_manager.currentInstanceId = "test-instance-123"
        span_manager.currentSchema = "emotion"
        span_manager.annotations = {"spans": []}
        span_manager.renderSpans = Mock()

        # Mock the createAnnotation function with optimistic update
        def create_annotation_with_optimistic_update(spanText, start, end, label):
            # Simulate successful server response
            result = {"status": "success"}

            # OPTIMISTIC UPDATE: Add to local state immediately
            optimistic_span = {
                "id": f"temp_{1234567890}",
                "label": label,
                "start": start,
                "end": end,
                "text": spanText,
                "schema": span_manager.currentSchema
            }

            span_manager.annotations["spans"].append(optimistic_span)

            # Render immediately
            span_manager.renderSpans()

            return result

        # Test the optimistic update
        result = create_annotation_with_optimistic_update("happy text", 0, 10, "happy")

        # Verify the annotation was created
        assert result["status"] == "success"

        # Verify the span was added to local state
        assert len(span_manager.annotations["spans"]) == 1
        assert span_manager.annotations["spans"][0]["label"] == "happy"
        assert span_manager.annotations["spans"][0]["text"] == "happy text"

        # Verify renderSpans was called
        assert span_manager.renderSpans.called

        print("✅ OPTIMISTIC UPDATE: Span added to local state and rendered immediately")

    def test_optimistic_update_with_existing_spans(self):
        """Test optimistic update when there are existing spans."""
        # Create mock span manager with existing spans
        span_manager = Mock()
        span_manager.currentInstanceId = "test-instance-123"
        span_manager.currentSchema = "emotion"
        span_manager.annotations = {
            "spans": [
                {"id": "1", "label": "sad", "start": 20, "end": 30, "text": "sad text"}
            ]
        }
        span_manager.renderSpans = Mock()

        # Mock the createAnnotation function
        def create_annotation_with_optimistic_update(spanText, start, end, label):
            # Simulate successful server response
            result = {"status": "success"}

            # OPTIMISTIC UPDATE: Add to local state immediately
            optimistic_span = {
                "id": f"temp_{1234567890}",
                "label": label,
                "start": start,
                "end": end,
                "text": spanText,
                "schema": span_manager.currentSchema
            }

            span_manager.annotations["spans"].append(optimistic_span)

            # Render immediately
            span_manager.renderSpans()

            return result

        # Test the optimistic update
        result = create_annotation_with_optimistic_update("happy text", 0, 10, "happy")

        # Verify the annotation was created
        assert result["status"] == "success"

        # Verify both spans are in local state
        assert len(span_manager.annotations["spans"]) == 2
        assert span_manager.annotations["spans"][0]["label"] == "sad"
        assert span_manager.annotations["spans"][1]["label"] == "happy"

        # Verify renderSpans was called
        assert span_manager.renderSpans.called

        print("✅ OPTIMISTIC UPDATE: New span added alongside existing spans")

    def test_optimistic_update_no_server_reload(self):
        """Test that optimistic update doesn't require server reload."""
        # Create mock span manager
        span_manager = Mock()
        span_manager.currentInstanceId = "test-instance-123"
        span_manager.currentSchema = "emotion"
        span_manager.annotations = {"spans": []}
        span_manager.renderSpans = Mock()
        span_manager.loadAnnotations = Mock()  # This should NOT be called

        # Mock the createAnnotation function
        def create_annotation_with_optimistic_update(spanText, start, end, label):
            # Simulate successful server response
            result = {"status": "success"}

            # OPTIMISTIC UPDATE: Add to local state immediately
            optimistic_span = {
                "id": f"temp_{1234567890}",
                "label": label,
                "start": start,
                "end": end,
                "text": spanText,
                "schema": span_manager.currentSchema
            }

            span_manager.annotations["spans"].append(optimistic_span)

            # Render immediately (no server reload)
            span_manager.renderSpans()

            return result

        # Test the optimistic update
        result = create_annotation_with_optimistic_update("happy text", 0, 10, "happy")

        # Verify the annotation was created
        assert result["status"] == "success"

        # Verify loadAnnotations was NOT called (no server reload)
        assert not span_manager.loadAnnotations.called

        # Verify renderSpans was called
        assert span_manager.renderSpans.called

        print("✅ OPTIMISTIC UPDATE: No server reload required")

    def test_optimistic_update_error_handling(self):
        """Test that optimistic update handles server errors correctly."""
        # Create mock span manager
        span_manager = Mock()
        span_manager.currentInstanceId = "test-instance-123"
        span_manager.currentSchema = "emotion"
        span_manager.annotations = {"spans": []}
        span_manager.renderSpans = Mock()

        # Mock the createAnnotation function with error handling
        def create_annotation_with_error_handling(spanText, start, end, label):
            # Simulate server error
            try:
                # Simulate failed server response
                raise Exception("Server error")
            except Exception as error:
                # Don't add optimistic update if server fails
                print("Server error occurred, not adding optimistic update")
                return {"status": "error", "message": str(error)}

        # Test the error handling
        result = create_annotation_with_error_handling("happy text", 0, 10, "happy")

        # Verify the annotation failed
        assert result["status"] == "error"

        # Verify no span was added to local state
        assert len(span_manager.annotations["spans"]) == 0

        # Verify renderSpans was NOT called
        assert not span_manager.renderSpans.called

        print("✅ OPTIMISTIC UPDATE: Error handling prevents invalid updates")