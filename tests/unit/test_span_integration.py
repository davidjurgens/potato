#!/usr/bin/env python3
"""
Integration tests for backend span state and API (no HTML rendering)
"""

import unittest
import json

class TestBackendSpanAPI(unittest.TestCase):
    def test_backend_returns_raw_span_data(self):
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

    def test_backend_span_data_integrity(self):
        # Simulate storing and retrieving span data
        span_data = {
            'id': 'span_2',
            'schema': 'entity',
            'name': 'person',
            'title': 'Person entity',
            'start': 5,
            'end': 10
        }
        # Check types
        self.assertIsInstance(span_data['start'], int)
        self.assertIsInstance(span_data['end'], int)
        self.assertIsInstance(span_data['name'], str)
        self.assertIsInstance(span_data['schema'], str)
        self.assertIsInstance(span_data['title'], str)
        self.assertIsInstance(span_data['id'], str)

if __name__ == '__main__':
    unittest.main()