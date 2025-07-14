#!/usr/bin/env python3
"""
Integration test for the enhanced span annotation system
"""

import unittest
import tempfile
import os
import json
from unittest.mock import patch, MagicMock

# Import the classes we're testing
from potato.item_state_management import SpanAnnotation
from potato.server_utils.schemas.span import render_span_annotations


class TestSpanAnnotationIntegration(unittest.TestCase):
    """Integration tests for the span annotation system"""

    def test_span_annotation_lifecycle(self):
        """Test the complete lifecycle of a span annotation"""
        # 1. Create a span annotation
        span = SpanAnnotation(
            schema="sentiment",
            name="positive",
            title="Positive sentiment",
            start=0,
            end=5,
            annotation_id="test_span_1"
        )

        # 2. Verify the span has the expected properties
        self.assertEqual(span.get_schema(), "sentiment")
        self.assertEqual(span.get_name(), "positive")
        self.assertEqual(span.get_title(), "Positive sentiment")
        self.assertEqual(span.get_start(), 0)
        self.assertEqual(span.get_end(), 5)
        self.assertEqual(span.get_id(), "test_span_1")

        # 3. Test rendering the span
        text = "This is a test sentence."
        rendered = render_span_annotations(text, [span])

        # 4. Verify the rendered output contains expected elements
        self.assertIn('class="span-highlight"', rendered)
        self.assertIn('data-annotation-id="test_span_1"', rendered)
        self.assertIn('data-label="positive"', rendered)
        self.assertIn('schema="sentiment"', rendered)
        self.assertIn("This", rendered)  # The annotated text should be preserved

    def test_multiple_span_annotations(self):
        """Test handling multiple span annotations"""
        # Create multiple spans
        span1 = SpanAnnotation("sentiment", "positive", "Positive", 0, 4, "span_1")
        span2 = SpanAnnotation("sentiment", "negative", "Negative", 8, 12, "span_2")

        text = "This is a test sentence."
        rendered = render_span_annotations(text, [span1, span2])

        # Verify both spans are rendered
        self.assertIn('data-annotation-id="span_1"', rendered)
        self.assertIn('data-annotation-id="span_2"', rendered)
        self.assertIn('data-label="positive"', rendered)
        self.assertIn('data-label="negative"', rendered)

    def test_nested_span_annotations(self):
        """Test nested span annotations"""
        # Create nested spans
        outer_span = SpanAnnotation("sentiment", "positive", "Positive", 0, 12, "outer")
        inner_span = SpanAnnotation("sentiment", "negative", "Negative", 5, 8, "inner")

        text = "This is a test sentence."
        rendered = render_span_annotations(text, [outer_span, inner_span])

        # Verify both spans are rendered with proper nesting
        self.assertIn('data-annotation-id="outer"', rendered)
        self.assertIn('data-annotation-id="inner"', rendered)

        # Count span tags to verify proper nesting
        span_count = rendered.count('<span class="span-highlight"')
        close_span_count = rendered.count('</span>')
        self.assertEqual(span_count, close_span_count, "Span tags should be properly balanced")

    def test_span_annotation_serialization(self):
        """Test that span annotations can be serialized to JSON"""
        span = SpanAnnotation("sentiment", "positive", "Positive sentiment", 0, 5, "test_id")

        # Convert to dictionary (simulating API response)
        span_dict = {
            'id': span.get_id(),
            'schema': span.get_schema(),
            'name': span.get_name(),
            'title': span.get_title(),
            'start': span.get_start(),
            'end': span.get_end()
        }

        # Test JSON serialization
        json_str = json.dumps(span_dict)
        self.assertIsInstance(json_str, str)

        # Test JSON deserialization
        deserialized = json.loads(json_str)
        self.assertEqual(deserialized['id'], "test_id")
        self.assertEqual(deserialized['schema'], "sentiment")
        self.assertEqual(deserialized['name'], "positive")
        self.assertEqual(deserialized['start'], 0)
        self.assertEqual(deserialized['end'], 5)

    def test_span_annotation_edge_cases(self):
        """Test edge cases for span annotations"""
        # Test empty text
        empty_rendered = render_span_annotations("", [])
        self.assertEqual(empty_rendered, "")

        # Test no annotations
        text = "This is a test."
        no_annotations = render_span_annotations(text, [])
        self.assertEqual(no_annotations, text)

        # Test span at the very beginning
        start_span = SpanAnnotation("test", "label", "Label", 0, 4, "start")
        start_rendered = render_span_annotations(text, [start_span])
        self.assertIn('data-annotation-id="start"', start_rendered)

        # Test span at the very end
        end_span = SpanAnnotation("test", "label", "Label", 10, 14, "end")
        end_rendered = render_span_annotations(text, [end_span])
        self.assertIn('data-annotation-id="end"', end_rendered)

    def test_span_annotation_equality_and_hash(self):
        """Test span annotation equality and hashing"""
        span1 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id1")
        span2 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id2")  # Different ID
        span3 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id1")  # Same ID

        # Equality should be based on content, not ID
        self.assertEqual(span1, span2)
        self.assertEqual(span1, span3)

        # Hash should be consistent
        self.assertEqual(hash(span1), hash(span2))
        self.assertEqual(hash(span1), hash(span3))

        # Different content should have different hash
        span4 = SpanAnnotation("schema2", "label1", "title1", 0, 5, "id1")
        self.assertNotEqual(hash(span1), hash(span4))


if __name__ == '__main__':
    unittest.main()