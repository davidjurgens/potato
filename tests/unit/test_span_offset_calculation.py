#!/usr/bin/env python3
"""
Unit tests to diagnose span offset calculation issues.
This test focuses on the specific problem where offsets are negative or incorrect.
"""

import pytest
import json
from unittest.mock import Mock, patch
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import requests

from potato.user_state_management import get_user_state_manager, UserPhase
from potato.item_state_management import get_item_state_manager
from potato.server_utils.schemas.span import SpanAnnotation


class TestSpanOffsetCalculation:
    """Test span offset calculation to diagnose production issues."""

    def setup_method(self):
        """Set up test environment."""
        # Clear any existing state
        get_user_state_manager().clear()
        get_item_state_manager().clear()

        # Create test instance with the exact text from the production issue
        self.test_text = "The new artificial intelligence model achieved remarkable results in natural language processing tasks, outperforming previous benchmarks by a significant margin."
        self.test_instance = {
            "id": "test_offset_instance",
            "text": self.test_text
        }

        # Add to item manager
        item_manager = get_item_state_manager()
        item_manager.add_item(self.test_instance["id"], self.test_instance)

        # Create test user
        self.test_user = "test_offset_user"
        user_state_manager = get_user_state_manager()
        user_state_manager.add_user(self.test_user)
        user_state = user_state_manager.get_user_state(self.test_user)
        user_state.advance_to_phase(UserPhase.ANNOTATION, None)

        # Assign instance to user
        item_manager.assign_instances_to_user(user_state)

    def test_span_creation_with_correct_offsets(self, client):
        """Test that span creation produces correct offsets."""
        print("\n🧪 Testing span creation with correct offsets")
        print("=" * 60)

        # Create authenticated session
        with client.session_transaction() as sess:
            sess['username'] = self.test_user

        # Test data for the specific production issue
        selected_text = "The new artificial intelligence"
        expected_start = 0
        expected_end = len(selected_text)

        print(f"📝 Test text: '{self.test_text}'")
        print(f"📝 Selected text: '{selected_text}'")
        print(f"📝 Expected start: {expected_start}")
        print(f"📝 Expected end: {expected_end}")
        print(f"📝 Text length: {len(self.test_text)}")

        # Create span annotation
        span_data = {
            'instance_id': self.test_instance["id"],
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': expected_start,
                    'end': expected_end,
                    'value': selected_text
                }
            ]
        }

        print(f"📤 Sending span data: {json.dumps(span_data, indent=2)}")

        # Send request
        response = client.post('/updateinstance',
                              data=json.dumps(span_data),
                              content_type='application/json')

        print(f"📥 Response status: {response.status_code}")
        print(f"📥 Response data: {response.data.decode()}")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        # Get user state to verify span was created
        user_state = get_user_state_manager().get_user_state(self.test_user)
        spans = user_state.get_span_annotations(self.test_instance["id"])

        print(f"🔍 Found {len(spans)} spans in user state")

        assert len(spans) > 0, "No spans found in user state"

        # Check the first span
        span_obj = list(spans.keys())[0]
        span_value = spans[span_obj]

        print(f"🔍 Span object: {span_obj}")
        print(f"🔍 Span value: {span_value}")
        print(f"🔍 Span start: {span_obj.get_start()}")
        print(f"🔍 Span end: {span_obj.get_end()}")
        print(f"🔍 Span schema: {span_obj.get_schema()}")
        print(f"🔍 Span name: {span_obj.get_name()}")

        # Verify offsets are correct
        assert span_obj.get_start() == expected_start, f"Expected start {expected_start}, got {span_obj.get_start()}"
        assert span_obj.get_end() == expected_end, f"Expected end {expected_end}, got {span_obj.get_end()}"
        assert span_obj.get_start() >= 0, f"Start offset should be non-negative, got {span_obj.get_start()}"
        assert span_obj.get_end() > span_obj.get_start(), f"End should be greater than start"

        # Verify the text matches
        actual_text = self.test_text[span_obj.get_start():span_obj.get_end()]
        assert actual_text == selected_text, f"Expected text '{selected_text}', got '{actual_text}'"

        print("✅ Span creation with correct offsets test passed")

    def test_span_creation_with_negative_offsets(self, client):
        """Test that negative offsets are detected and handled."""
        print("\n🧪 Testing span creation with negative offsets")
        print("=" * 60)

        # Create authenticated session
        with client.session_transaction() as sess:
            sess['username'] = self.test_user

        # Test with negative offsets (simulating the production issue)
        span_data = {
            'instance_id': self.test_instance["id"],
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': -2,  # Negative offset like in production
                    'end': -2,    # Negative offset like in production
                    'value': "The new artificial intelligence"
                }
            ]
        }

        print(f"📤 Sending span data with negative offsets: {json.dumps(span_data, indent=2)}")

        # Send request
        response = client.post('/updateinstance',
                              data=json.dumps(span_data),
                              content_type='application/json')

        print(f"📥 Response status: {response.status_code}")
        print(f"📥 Response data: {response.data.decode()}")

        # The backend should handle negative offsets gracefully
        # Check if the span was created with corrected offsets
        user_state = get_user_state_manager().get_user_state(self.test_user)
        spans = user_state.get_span_annotations(self.test_instance["id"])

        if len(spans) > 0:
            span_obj = list(spans.keys())[0]
            print(f"🔍 Span created with start: {span_obj.get_start()}, end: {span_obj.get_end()}")

            # The backend should either reject negative offsets or correct them
            assert span_obj.get_start() >= 0, f"Start offset should be non-negative, got {span_obj.get_start()}"
            assert span_obj.get_end() >= 0, f"End offset should be non-negative, got {span_obj.get_end()}"

        print("✅ Negative offset handling test completed")

    def test_text_position_calculation_edge_cases(self, client):
        """Test various edge cases in text position calculation."""
        print("\n🧪 Testing text position calculation edge cases")
        print("=" * 60)

        # Create authenticated session
        with client.session_transaction() as sess:
            sess['username'] = self.test_user

        test_cases = [
            {
                "name": "Start of text",
                "text": "The new artificial intelligence",
                "expected_start": 0,
                "expected_end": 30
            },
            {
                "name": "Middle of text",
                "text": "artificial intelligence model",
                "expected_start": 8,
                "expected_end": 35
            },
            {
                "name": "End of text",
                "text": "significant margin.",
                "expected_start": 108,
                "expected_end": 125
            },
            {
                "name": "Single word",
                "text": "The",
                "expected_start": 0,
                "expected_end": 3
            },
            {
                "name": "Repeated text",
                "text": "The",
                "expected_start": 0,  # Should find first occurrence
                "expected_end": 3
            }
        ]

        for i, test_case in enumerate(test_cases):
            print(f"\n📋 Test case {i+1}: {test_case['name']}")
            print(f"   Text: '{test_case['text']}'")
            print(f"   Expected: {test_case['expected_start']}-{test_case['expected_end']}")

            # Create span annotation
            span_data = {
                'instance_id': self.test_instance["id"],
                'type': 'span',
                'schema': 'sentiment',
                'state': [
                    {
                        'name': 'positive',
                        'title': 'Positive sentiment',
                        'start': test_case['expected_start'],
                        'end': test_case['expected_end'],
                        'value': test_case['text']
                    }
                ]
            }

            # Send request
            response = client.post('/updateinstance',
                                  data=json.dumps(span_data),
                                  content_type='application/json')

            assert response.status_code == 200, f"Test case {i+1} failed with status {response.status_code}"

            # Verify the span
            user_state = get_user_state_manager().get_user_state(self.test_user)
            spans = user_state.get_span_annotations(self.test_instance["id"])

            # Find the span for this test case
            span_found = False
            for span_obj, value in spans.items():
                if value == test_case['text']:
                    print(f"   Actual: {span_obj.get_start()}-{span_obj.get_end()}")

                    # Verify offsets
                    assert span_obj.get_start() == test_case['expected_start'], \
                        f"Expected start {test_case['expected_start']}, got {span_obj.get_start()}"
                    assert span_obj.get_end() == test_case['expected_end'], \
                        f"Expected end {test_case['expected_end']}, got {span_obj.get_end()}"

                    # Verify text extraction
                    actual_text = self.test_text[span_obj.get_start():span_obj.get_end()]
                    assert actual_text == test_case['text'], \
                        f"Expected text '{test_case['text']}', got '{actual_text}'"

                    span_found = True
                    break

            assert span_found, f"Span not found for test case {i+1}"
            print(f"   ✅ Test case {i+1} passed")

        print("\n✅ All edge case tests passed")

    def test_frontend_text_selection_simulation(self, client):
        """Simulate frontend text selection to identify offset calculation issues."""
        print("\n🧪 Testing frontend text selection simulation")
        print("=" * 60)

        # Create authenticated session
        with client.session_transaction() as sess:
            sess['username'] = self.test_user

        # Simulate what the frontend should be doing
        selected_text = "The new artificial intelligence"

        # Method 1: Use text.indexOf() approach (like frontend might do)
        text_start = self.test_text.find(selected_text)
        text_end = text_start + len(selected_text)

        print(f"📝 Using text.indexOf() approach:")
        print(f"   Selected text: '{selected_text}'")
        print(f"   text.indexOf() result: {text_start}")
        print(f"   Calculated start: {text_start}")
        print(f"   Calculated end: {text_end}")

        # Method 2: Use character-by-character approach
        char_start = 0
        char_end = len(selected_text)

        print(f"📝 Using character-by-character approach:")
        print(f"   Selected text: '{selected_text}'")
        print(f"   Character start: {char_start}")
        print(f"   Character end: {char_end}")

        # Method 3: Use word boundary approach
        words = self.test_text.split()
        target_words = selected_text.split()

        word_start = 0
        word_end = 0
        current_pos = 0

        for i, word in enumerate(words):
            if word == target_words[0] and i + len(target_words) <= len(words):
                # Check if the next words match
                match = True
                for j, target_word in enumerate(target_words):
                    if i + j >= len(words) or words[i + j] != target_word:
                        match = False
                        break

                if match:
                    word_start = current_pos
                    word_end = current_pos + len(selected_text)
                    break

            current_pos += len(word) + 1  # +1 for space

        print(f"📝 Using word boundary approach:")
        print(f"   Word start: {word_start}")
        print(f"   Word end: {word_end}")

        # Test all three methods
        methods = [
            ("text.indexOf()", text_start, text_end),
            ("character-by-character", char_start, char_end),
            ("word boundary", word_start, word_end)
        ]

        for method_name, start, end in methods:
            print(f"\n📋 Testing method: {method_name}")
            print(f"   Start: {start}, End: {end}")

            if start < 0 or end < 0:
                print(f"   ❌ Invalid offsets: start={start}, end={end}")
                continue

            if start >= end:
                print(f"   ❌ Invalid range: start={start}, end={end}")
                continue

            # Create span with this method's offsets
            span_data = {
                'instance_id': self.test_instance["id"],
                'type': 'span',
                'schema': 'sentiment',
                'state': [
                    {
                        'name': 'positive',
                        'title': 'Positive sentiment',
                        'start': start,
                        'end': end,
                        'value': selected_text
                    }
                ]
            }

            response = client.post('/updateinstance',
                                  data=json.dumps(span_data),
                                  content_type='application/json')

            if response.status_code == 200:
                # Verify the span
                user_state = get_user_state_manager().get_user_state(self.test_user)
                spans = user_state.get_span_annotations(self.test_instance["id"])

                span_found = False
                for span_obj, value in spans.items():
                    if value == selected_text:
                        actual_text = self.test_text[span_obj.get_start():span_obj.get_end()]
                        if actual_text == selected_text:
                            print(f"   ✅ Method works correctly")
                            print(f"   ✅ Actual text: '{actual_text}'")
                            span_found = True
                            break

                if not span_found:
                    print(f"   ❌ Span not found or text mismatch")
            else:
                print(f"   ❌ Request failed: {response.status_code}")

        print("\n✅ Frontend text selection simulation completed")

    def test_span_rendering_verification(self, client):
        """Test that spans are rendered correctly in the frontend."""
        print("\n🧪 Testing span rendering verification")
        print("=" * 60)

        # Create authenticated session
        with client.session_transaction() as sess:
            sess['username'] = self.test_user

        # Create a span with correct offsets
        selected_text = "The new artificial intelligence"
        start = 0
        end = len(selected_text)

        span_data = {
            'instance_id': self.test_instance["id"],
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': start,
                    'end': end,
                    'value': selected_text
                }
            ]
        }

        response = client.post('/updateinstance',
                              data=json.dumps(span_data),
                              content_type='application/json')

        assert response.status_code == 200

        # Test the API endpoint that frontend uses
        response = client.get(f'/api/spans/{self.test_instance["id"]}')
        assert response.status_code == 200

        data = json.loads(response.data)
        print(f"📥 API response: {json.dumps(data, indent=2)}")

        assert 'spans' in data, "API response should contain 'spans'"
        assert len(data['spans']) > 0, "Should have at least one span"

        span = data['spans'][0]
        print(f"🔍 Span from API:")
        print(f"   ID: {span['id']}")
        print(f"   Start: {span['start']}")
        print(f"   End: {span['end']}")
        print(f"   Text: '{span['text']}'")
        print(f"   Label: {span['label']}")

        # Verify the span data
        assert span['start'] == start, f"Expected start {start}, got {span['start']}"
        assert span['end'] == end, f"Expected end {end}, got {span['end']}"
        assert span['text'] == selected_text, f"Expected text '{selected_text}', got '{span['text']}'"
        assert span['start'] >= 0, f"Start should be non-negative, got {span['start']}"
        assert span['end'] > span['start'], f"End should be greater than start"

        print("✅ Span rendering verification test passed")


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "-s"])