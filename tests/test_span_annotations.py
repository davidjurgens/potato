#!/usr/bin/env python3
"""
Unit tests for the enhanced span annotation functionality
"""

import unittest
import json
import tempfile
import os
from unittest.mock import patch, MagicMock

# Import the classes we're testing
from potato.item_state_management import SpanAnnotation
from potato.server_utils.schemas.span import render_span_annotations


class TestSpanAnnotation(unittest.TestCase):
    """Test the enhanced SpanAnnotation class"""

    def test_span_annotation_creation(self):
        """Test creating a span annotation with and without ID"""
        # Test without ID (should auto-generate)
        span1 = SpanAnnotation("test_schema", "positive", "Positive sentiment", 0, 5)
        self.assertEqual(span1.get_schema(), "test_schema")
        self.assertEqual(span1.get_name(), "positive")
        self.assertEqual(span1.get_title(), "Positive sentiment")
        self.assertEqual(span1.get_start(), 0)
        self.assertEqual(span1.get_end(), 5)
        self.assertIsNotNone(span1.get_id())
        self.assertTrue(span1.get_id().startswith("span_"))

        # Test with provided ID
        span2 = SpanAnnotation("test_schema", "negative", "Negative sentiment", 10, 15, "custom_id_123")
        self.assertEqual(span2.get_id(), "custom_id_123")

    def test_span_annotation_equality(self):
        """Test span annotation equality"""
        span1 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id1")
        span2 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id2")  # Different ID
        span3 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id1")  # Same ID

        # Equality should be based on schema, start, end, and name, not ID
        self.assertEqual(span1, span2)
        self.assertEqual(span1, span3)

        # Different content should not be equal
        span4 = SpanAnnotation("schema2", "label1", "title1", 0, 5, "id1")
        self.assertNotEqual(span1, span4)

    def test_span_annotation_string_representation(self):
        """Test string representation of span annotation"""
        span = SpanAnnotation("test_schema", "positive", "Positive sentiment", 0, 5, "test_id")
        str_repr = str(span)
        self.assertIn("test_id", str_repr)
        self.assertIn("test_schema", str_repr)
        self.assertIn("positive", str_repr)
        self.assertIn("0", str_repr)
        self.assertIn("5", str_repr)


class TestRenderSpanAnnotations(unittest.TestCase):
    """Test the new render_span_annotations function"""

    def test_empty_annotations(self):
        """Test rendering with no annotations"""
        text = "This is a test sentence."
        result = render_span_annotations(text, [])
        self.assertEqual(result, text)

    def test_single_annotation(self):
        """Test rendering with a single annotation"""
        text = "This is a test sentence."
        span = SpanAnnotation("sentiment", "positive", "Positive", 0, 4, "span_1")

        result = render_span_annotations(text, [span])

        # Should contain the span wrapper
        self.assertIn('class="span-highlight"', result)
        self.assertIn('data-annotation-id="span_1"', result)
        self.assertIn('data-label="positive"', result)
        self.assertIn('schema="sentiment"', result)
        self.assertIn("This", result)  # The annotated text should be preserved

    def test_multiple_non_overlapping_annotations(self):
        """Test rendering with multiple non-overlapping annotations"""
        text = "This is a test sentence."
        span1 = SpanAnnotation("sentiment", "positive", "Positive", 0, 4, "span_1")
        span2 = SpanAnnotation("sentiment", "negative", "Negative", 8, 12, "span_2")

        result = render_span_annotations(text, [span1, span2])

        # Should contain both spans
        self.assertIn('data-annotation-id="span_1"', result)
        self.assertIn('data-annotation-id="span_2"', result)
        self.assertIn("This", result)  # First annotation
        self.assertIn("a te", result)  # Second annotation (corrected)

    def test_overlapping_annotations(self):
        """Test rendering with overlapping annotations"""
        text = "This is a test sentence."
        span1 = SpanAnnotation("sentiment", "positive", "Positive", 0, 8, "span_1")  # "This is "
        span2 = SpanAnnotation("sentiment", "negative", "Negative", 5, 12, "span_2")  # "is a test"

        result = render_span_annotations(text, [span1, span2])

        # Should contain both spans and handle overlap properly
        self.assertIn('data-annotation-id="span_1"', result)
        self.assertIn('data-annotation-id="span_2"', result)
        self.assertIn("This", result)  # First annotation starts with "This"
        self.assertIn("is ", result)   # Second annotation contains "is "

    def test_nested_annotations(self):
        """Test rendering with nested annotations"""
        text = "This is a test sentence."
        span1 = SpanAnnotation("sentiment", "positive", "Positive", 0, 12, "span_1")  # "This is a test"
        span2 = SpanAnnotation("sentiment", "negative", "Negative", 5, 8, "span_2")   # "is a"

        result = render_span_annotations(text, [span1, span2])

        # Should contain both spans with proper nesting
        self.assertIn('data-annotation-id="span_1"', result)
        self.assertIn('data-annotation-id="span_2"', result)
        self.assertIn("This", result)  # First annotation starts with "This"
        self.assertIn("is ", result)   # Second annotation contains "is "

    def test_annotation_with_color(self):
        """Test rendering with color information"""
        text = "This is a test."
        span = SpanAnnotation("sentiment", "positive", "Positive", 0, 4, "span_1")

        # Mock the get_span_color function to return a specific color
        with patch('potato.server_utils.schemas.span.get_span_color') as mock_get_color:
            mock_get_color.return_value = "(255, 0, 0)"  # Red
            result = render_span_annotations(text, [span])

            # Should contain the color in hex format
            self.assertIn('background-color: #ff000080', result)

    def test_annotation_without_color(self):
        """Test rendering when no color is specified"""
        text = "This is a test."
        span = SpanAnnotation("sentiment", "positive", "Positive", 0, 4, "span_1")

        # Mock the get_span_color function to return None
        with patch('potato.server_utils.schemas.span.get_span_color') as mock_get_color:
            mock_get_color.return_value = None
            result = render_span_annotations(text, [span])

            # Should use default gray color
            self.assertIn('background-color: #80808080', result)


class TestSpanAnnotationAPI(unittest.TestCase):
    """Test the new span annotation API endpoints"""

    def setUp(self):
        """Set up test fixtures"""
        # This would normally set up a Flask test client
        # For now, we'll test the logic without the full Flask app
        pass

    def test_span_annotation_data_structure(self):
        """Test the data structure returned by span annotations"""
        span = SpanAnnotation("sentiment", "positive", "Positive sentiment", 0, 5, "test_id")

        # Simulate the data structure returned by the API
        annotation_data = {
            'id': span.get_id(),
            'schema': span.get_schema(),
            'name': span.get_name(),
            'title': span.get_title(),
            'start': span.get_start(),
            'end': span.get_end()
        }

        expected = {
            'id': 'test_id',
            'schema': 'sentiment',
            'name': 'positive',
            'title': 'Positive sentiment',
            'start': 0,
            'end': 5
        }

        self.assertEqual(annotation_data, expected)


if __name__ == '__main__':
    unittest.main()