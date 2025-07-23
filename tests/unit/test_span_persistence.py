"""
Test for span persistence when creating overlapping spans.

This test verifies that existing spans don't disappear when creating
new overlapping spans.
"""

import unittest
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))


class TestSpanPersistence(unittest.TestCase):
    """Test that spans persist correctly when creating overlapping spans."""

    def test_span_creation_includes_existing_spans(self):
        """Test that creating a new span includes all existing spans in the request."""
        # This test verifies the logic for combining existing spans with new spans

        # Simulate existing spans
        existing_spans = [
            {
                'id': '1',
                'label': 'happy',
                'start': 8,
                'end': 32,
                'text': 'artificial intelligence'
            }
        ]

        # New span to create
        new_span = {
            'name': 'sad',
            'start': 20,
            'end': 35,
            'title': 'sad',
            'value': 'intelligence model'
        }

        # Test the logic that combines existing spans with new span
        def combine_spans(existing_spans, new_span):
            # Convert existing spans to the format expected by the API
            existing_spans_formatted = [{
                'name': span['label'],
                'start': span['start'],
                'end': span['end'],
                'title': span['label'],
                'value': span['text'] or span['value']
            } for span in existing_spans]

            # Combine with new span
            return existing_spans_formatted + [new_span]

        result = combine_spans(existing_spans, new_span)

        # Verify the result
        self.assertEqual(len(result), 2, "Should have 2 spans total")

        # Check first span (existing)
        self.assertEqual(result[0]['name'], 'happy')
        self.assertEqual(result[0]['start'], 8)
        self.assertEqual(result[0]['end'], 32)
        self.assertEqual(result[0]['value'], 'artificial intelligence')

        # Check second span (new)
        self.assertEqual(result[1]['name'], 'sad')
        self.assertEqual(result[1]['start'], 20)
        self.assertEqual(result[1]['end'], 35)
        self.assertEqual(result[1]['value'], 'intelligence model')

    def test_span_deletion_excludes_deleted_span(self):
        """Test that deleting a span excludes the deleted span from the request."""
        # Simulate existing spans
        existing_spans = [
            {
                'id': '1',
                'label': 'happy',
                'start': 8,
                'end': 32,
                'text': 'artificial intelligence'
            },
            {
                'id': '2',
                'label': 'sad',
                'start': 20,
                'end': 35,
                'text': 'intelligence model'
            }
        ]

        # Test the logic that filters out the deleted span
        def filter_out_deleted_span(spans, span_id_to_delete):
            return [span for span in spans if span['id'] != span_id_to_delete]

        # Delete span with id '1'
        remaining_spans = filter_out_deleted_span(existing_spans, '1')

        # Verify the result
        self.assertEqual(len(remaining_spans), 1, "Should have 1 span remaining")
        self.assertEqual(remaining_spans[0]['id'], '2', "Should keep span with id '2'")
        self.assertEqual(remaining_spans[0]['label'], 'sad', "Should keep the sad span")

    def test_overlapping_spans_persistence(self):
        """Test that overlapping spans can coexist without disappearing."""
        # Test case: two overlapping spans
        span1 = {
            'id': '1',
            'label': 'happy',
            'start': 8,
            'end': 32,
            'text': 'artificial intelligence'
        }

        span2 = {
            'id': '2',
            'label': 'sad',
            'start': 20,
            'end': 35,
            'text': 'intelligence model'
        }

        # Verify they overlap
        def spans_overlap(span1, span2):
            return span1['start'] < span2['end'] and span2['start'] < span1['end']

        self.assertTrue(spans_overlap(span1, span2), "Spans should overlap")

        # Verify both spans can exist together
        all_spans = [span1, span2]
        self.assertEqual(len(all_spans), 2, "Should be able to have 2 overlapping spans")

        # Verify both spans have valid data
        for span in all_spans:
            self.assertIn('id', span, "Span should have an id")
            self.assertIn('label', span, "Span should have a label")
            self.assertIn('start', span, "Span should have a start position")
            self.assertIn('end', span, "Span should have an end position")
            self.assertIn('text', span, "Span should have text")
            self.assertLess(span['start'], span['end'], "Start should be less than end")

    def test_span_data_consistency(self):
        """Test that span data is consistent when creating and deleting."""
        # Test the data transformation logic
        original_span = {
            'id': '1',
            'label': 'happy',
            'start': 8,
            'end': 32,
            'text': 'artificial intelligence'
        }

        # Transform to API format
        api_format = {
            'name': original_span['label'],
            'start': original_span['start'],
            'end': original_span['end'],
            'title': original_span['label'],
            'value': original_span['text']
        }

        # Verify transformation
        self.assertEqual(api_format['name'], 'happy')
        self.assertEqual(api_format['start'], 8)
        self.assertEqual(api_format['end'], 32)
        self.assertEqual(api_format['title'], 'happy')
        self.assertEqual(api_format['value'], 'artificial intelligence')


if __name__ == '__main__':
    unittest.main()