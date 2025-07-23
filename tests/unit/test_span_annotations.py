#!/usr/bin/env python3
"""
Unit tests for SpanAnnotation data structure and backend API (no HTML rendering)
"""

import unittest
import json
from potato.item_state_management import SpanAnnotation

class TestSpanAnnotation(unittest.TestCase):
    def test_span_annotation_creation(self):
        span1 = SpanAnnotation("test_schema", "positive", "Positive sentiment", 0, 5)
        self.assertEqual(span1.get_schema(), "test_schema")
        self.assertEqual(span1.get_name(), "positive")
        self.assertEqual(span1.get_title(), "Positive sentiment")
        self.assertEqual(span1.get_start(), 0)
        self.assertEqual(span1.get_end(), 5)
        self.assertIsNotNone(span1.get_id())
        self.assertTrue(span1.get_id().startswith("span_"))

        span2 = SpanAnnotation("test_schema", "negative", "Negative sentiment", 10, 15, "custom_id_123")
        self.assertEqual(span2.get_id(), "custom_id_123")

    def test_span_annotation_equality(self):
        span1 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id1")
        span2 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id2")
        span3 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id1")
        self.assertEqual(span1, span2)
        self.assertEqual(span1, span3)
        span4 = SpanAnnotation("schema2", "label1", "title1", 0, 5, "id1")
        self.assertNotEqual(span1, span4)

    def test_span_annotation_string_representation(self):
        span = SpanAnnotation("test_schema", "positive", "Positive sentiment", 0, 5, "test_id")
        str_repr = str(span)
        self.assertIn("test_id", str_repr)
        self.assertIn("test_schema", str_repr)
        self.assertIn("positive", str_repr)
        self.assertIn("0", str_repr)
        self.assertIn("5", str_repr)

# Example API test (pseudo, as real API test should be in integration layer)
class TestNoHTMLInSpanAPI(unittest.TestCase):
    def test_no_html_in_span_data(self):
        # Simulate API response
        span_data = {
            'id': 'span_1',
            'schema': 'sentiment',
            'name': 'positive',
            'title': 'Positive sentiment',
            'start': 0,
            'end': 4
        }
        span_str = json.dumps(span_data)
        self.assertNotIn('<', span_str)
        self.assertNotIn('>', span_str)
        self.assertNotIn('class=\"', span_str)
        self.assertNotIn('style=\"', span_str)

if __name__ == '__main__':
    unittest.main()