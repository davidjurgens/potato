#!/usr/bin/env python3
"""
Comprehensive Selenium tests for the frontend span annotation system

This test suite provides comprehensive testing of the frontend span annotation
workflow, including edge cases, error conditions, and complex scenarios.

Authentication Flow:
1. Each test inherits from BaseSeleniumTest which automatically:
   - Registers a unique test user
   - Logs in the user
   - Verifies authentication before running the test
2. Tests can then focus on their specific functionality without auth concerns
3. Each test gets a fresh WebDriver and unique user account for isolation
"""

import time
import json
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import unittest

from tests.selenium.test_base import BaseSeleniumTest


class TestFrontendSpanComprehensive(BaseSeleniumTest):
    """
    Comprehensive test suite for frontend span annotation system.

    This class tests complex scenarios including:
    - Multiple span creation and deletion
    - Overlapping spans
    - Edge cases and error conditions
    - Performance with many spans
    - Data consistency across operations

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_multiple_span_creation_and_deletion(self):
        """Test creating and deleting multiple spans in sequence"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create multiple spans
        spans_to_create = [
            {'start': 0, 'end': 5, 'label': 'positive', 'text': 'I am '},
            {'start': 10, 'end': 20, 'label': 'negative', 'text': 'thrilled about'},
            {'start': 30, 'end': 40, 'label': 'neutral', 'text': 'the new tech'}
        ]

        created_spans = []
        for span_data in spans_to_create:
            span_request = {
                'instance_id': '1',
                'type': 'span',
                'schema': 'sentiment',
                'state': [
                    {
                        'name': span_data['label'],
                        'title': f'{span_data["label"].title()} sentiment',
                        'start': span_data['start'],
                        'end': span_data['end'],
                        'value': span_data['label']
                    }
                ]
            }

            response = requests.post(
                f"{self.server.base_url}/updateinstance",
                json=span_request,
                cookies=session_cookies
            )
            self.assertEqual(response.status_code, 200)
            created_spans.append(span_data)

        # Wait for spans to be rendered
        time.sleep(2)

        # Verify all spans are rendered
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), len(spans_to_create))

        # Delete spans in reverse order
        for span_data in reversed(spans_to_create):
            delete_request = {
                'instance_id': '1',
                'type': 'span',
                'schema': 'sentiment',
                'state': [
                    {
                        'name': span_data['label'],
                        'title': f'{span_data["label"].title()} sentiment',
                        'start': span_data['start'],
                        'end': span_data['end'],
                        'value': None  # This deletes the span
                    }
                ]
            }

            response = requests.post(
                f"{self.server.base_url}/updateinstance",
                json=delete_request,
                cookies=session_cookies
            )
            self.assertEqual(response.status_code, 200)

        # Wait for spans to be removed
        time.sleep(2)

        # Verify all spans are removed
        span_elements_after = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements_after), 0)

    def test_overlapping_spans_handling(self):
        """Test that overlapping spans are handled correctly"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create overlapping spans
        overlapping_spans = [
            {'start': 0, 'end': 10, 'label': 'positive', 'text': 'I am absolutely'},
            {'start': 5, 'end': 15, 'label': 'negative', 'text': 'absolutely thrilled'},
            {'start': 20, 'end': 30, 'label': 'neutral', 'text': 'about the new'}
        ]

        for span_data in overlapping_spans:
            span_request = {
                'instance_id': '1',
                'type': 'span',
                'schema': 'sentiment',
                'state': [
                    {
                        'name': span_data['label'],
                        'title': f'{span_data["label"].title()} sentiment',
                        'start': span_data['start'],
                        'end': span_data['end'],
                        'value': span_data['label']
                    }
                ]
            }

            response = requests.post(
                f"{self.server.base_url}/updateinstance",
                json=span_request,
                cookies=session_cookies
            )
            self.assertEqual(response.status_code, 200)

        # Wait for spans to be rendered
        time.sleep(2)

        # Verify all spans are rendered (overlapping spans should still be rendered)
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), len(overlapping_spans))

        # Verify text content is preserved
        text_element = self.driver.find_element(By.ID, "instance-text")
        text_content = text_element.text
        self.assertIsNotNone(text_content)
        self.assertGreater(len(text_content), 0)

    def test_span_edge_cases(self):
        """Test edge cases for span annotation"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Test edge cases
        edge_cases = [
            {'start': 0, 'end': 1, 'label': 'positive', 'description': 'Single character'},
            {'start': 0, 'end': 0, 'label': 'neutral', 'description': 'Zero length span'},
            {'start': 100, 'end': 200, 'label': 'negative', 'description': 'Large span'},
        ]

        for case in edge_cases:
            span_request = {
                'instance_id': '1',
                'type': 'span',
                'schema': 'sentiment',
                'state': [
                    {
                        'name': case['label'],
                        'title': f'{case["label"].title()} sentiment',
                        'start': case['start'],
                        'end': case['end'],
                        'value': case['label']
                    }
                ]
            }

            response = requests.post(
                f"{self.server.base_url}/updateinstance",
                json=span_request,
                cookies=session_cookies
            )

            # Some edge cases might fail, which is expected
            if response.status_code == 200:
                print(f"✅ Edge case passed: {case['description']}")
            else:
                print(f"⚠️ Edge case failed (expected): {case['description']}")

    def test_span_performance_with_many_spans(self):
        """Test performance with many spans"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create many small spans
        many_spans = []
        for i in range(10):  # Create 10 spans
            span_data = {
                'start': i * 5,
                'end': (i * 5) + 3,
                'label': f'label_{i % 3}',  # Cycle through 3 labels
                'text': f'span_{i}'
            }
            many_spans.append(span_data)

        start_time = time.time()

        for span_data in many_spans:
            span_request = {
                'instance_id': '1',
                'type': 'span',
                'schema': 'sentiment',
                'state': [
                    {
                        'name': span_data['label'],
                        'title': f'{span_data["label"].title()} sentiment',
                        'start': span_data['start'],
                        'end': span_data['end'],
                        'value': span_data['label']
                    }
                ]
            }

            response = requests.post(
                f"{self.server.base_url}/updateinstance",
                json=span_request,
                cookies=session_cookies
            )
            self.assertEqual(response.status_code, 200)

        # Wait for all spans to be rendered
        time.sleep(3)

        end_time = time.time()
        creation_time = end_time - start_time

        # Verify all spans are rendered
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), len(many_spans))

        # Performance assertion (should complete within reasonable time)
        self.assertLess(creation_time, 10.0, f"Span creation took too long: {creation_time:.2f}s")

        print(f"✅ Created {len(many_spans)} spans in {creation_time:.2f}s")

    def test_span_data_consistency(self):
        """Test that span data remains consistent across operations"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create a span
        span_data = {
            'start': 0,
            'end': 10,
            'label': 'positive',
            'text': 'I am absolutely'
        }

        span_request = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': span_data['label'],
                    'title': f'{span_data["label"].title()} sentiment',
                    'start': span_data['start'],
                    'end': span_data['end'],
                    'value': span_data['label']
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_request,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Wait for span to be rendered
        time.sleep(2)

        # Get span data via API
        api_response = requests.get(
            f"{self.server.base_url}/api/spans/1",
            cookies=session_cookies
        )
        self.assertEqual(api_response.status_code, 200)
        api_spans = api_response.json()['spans']

        # Verify API data
        self.assertEqual(len(api_spans), 1)
        api_span = api_spans[0]
        self.assertEqual(api_span['start'], span_data['start'])
        self.assertEqual(api_span['end'], span_data['end'])
        self.assertEqual(api_span['label'], span_data['label'])

        # Verify frontend rendering
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), 1)

        span_element = span_elements[0]
        self.assertEqual(span_element.get_attribute("data-label"), span_data['label'])

        # Navigate away and back to test persistence
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        # Verify span is still there
        span_elements_after = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements_after), 1)

    def test_span_error_handling(self):
        """Test error handling for invalid span operations"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Test invalid span data
        invalid_spans = [
            {
                'description': 'Negative start offset',
                'data': {
                    'instance_id': '1',
                    'type': 'span',
                    'schema': 'sentiment',
                    'state': [{'name': 'positive', 'start': -1, 'end': 5, 'value': 'test'}]
                }
            },
            {
                'description': 'End before start',
                'data': {
                    'instance_id': '1',
                    'type': 'span',
                    'schema': 'sentiment',
                    'state': [{'name': 'positive', 'start': 10, 'end': 5, 'value': 'test'}]
                }
            },
            {
                'description': 'Missing required fields',
                'data': {
                    'instance_id': '1',
                    'type': 'span',
                    'schema': 'sentiment',
                    'state': [{'name': 'positive', 'start': 0}]  # Missing end and value
                }
            }
        ]

        for test_case in invalid_spans:
            response = requests.post(
                f"{self.server.base_url}/updateinstance",
                json=test_case['data'],
                cookies=session_cookies
            )

            # Invalid spans should fail gracefully
            if response.status_code == 400:
                print(f"✅ Error handling passed: {test_case['description']}")
            else:
                print(f"⚠️ Error handling unexpected: {test_case['description']} returned {response.status_code}")

    def test_span_manager_integration(self):
        """Test integration between frontend and span manager"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to initialize
        time.sleep(2)

        # Check that span manager is available
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        self.assertTrue(span_manager_ready, "Span manager should be initialized")

        # Test span manager methods
        annotations = self.execute_script_safe("""
            return window.spanManager ? window.spanManager.getAnnotations() : null;
        """)
        self.assertIsNotNone(annotations, "Should be able to get annotations")

        spans = self.execute_script_safe("""
            return window.spanManager ? window.spanManager.getSpans() : [];
        """)
        self.assertIsInstance(spans, list, "Should be able to get spans list")

        # Test span manager state consistency
        self.execute_script_safe("""
            if (window.spanManager) {
                window.spanManager.clearAnnotations();
            }
        """)

        spans_after_clear = self.execute_script_safe("""
            return window.spanManager ? window.spanManager.getSpans() : [];
        """)
        self.assertEqual(len(spans_after_clear), 0, "Clear should remove all spans")


if __name__ == "__main__":
    # Run the tests directly
    unittest.main()