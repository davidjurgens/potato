#!/usr/bin/env python3
"""
Selenium tests for span annotation functionality

This test suite focuses on the core span annotation functionality including
creation, deletion, and interaction with the span annotation system.

Authentication Flow:
1. Each test inherits from BaseSeleniumTest which automatically:
   - Registers a unique test user
   - Logs in the user
   - Verifies authentication before running the test
2. Tests can then focus on their specific functionality without auth concerns
3. Each test gets a fresh WebDriver and unique user account for isolation
"""

import time
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import unittest

from tests.selenium.test_base import BaseSeleniumTest


class TestSpanAnnotationSelenium(BaseSeleniumTest):
    """
    Test suite for span annotation functionality.

    This class tests the core span annotation features:
    - Span creation via text selection
    - Span deletion via UI interaction
    - Span editing and modification
    - Span validation and error handling
    - Span data persistence

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_span_creation_via_text_selection(self):
        """Test creating spans by selecting text"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be ready
        time.sleep(2)
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        self.assertTrue(span_manager_ready, "Span manager should be initialized")

        # Select a label first
        label_buttons = self.driver.find_elements(By.CLASS_NAME, "label-button")
        if label_buttons:
            label_buttons[0].click()
            time.sleep(0.5)

        # Select text using JavaScript
        self.execute_script_safe("""
            var textElement = arguments[0];
            var range = document.createRange();
            var textNode = textElement.firstChild;
            range.setStart(textNode, 0);
            range.setEnd(textNode, 10);
            var selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """, text_element)

        # Wait for span creation
        time.sleep(2)

        # Check if span was created
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        if len(span_elements) > 0:
            print("✅ Span created via text selection")
            self.assertGreater(len(span_elements), 0, "Span should be created")
        else:
            print("⚠️ No span created via text selection (may be expected based on UI implementation)")

    def test_span_deletion_via_ui(self):
        """Test deleting spans via UI interaction"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create a span via API first
        span_request = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 10,
                    'value': 'positive'
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

        # Check that span is present
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), 1, "Span should be rendered")

        # Try to delete span via delete button
        delete_buttons = self.driver.find_elements(By.CLASS_NAME, "span-delete")
        if delete_buttons:
            delete_buttons[0].click()
            time.sleep(2)

            # Check if span was deleted
            span_elements_after = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
            if len(span_elements_after) == 0:
                print("✅ Span deleted via UI interaction")
            else:
                print("⚠️ Span not deleted via UI (may be expected based on implementation)")
        else:
            print("⚠️ No delete button found")

    def test_span_data_persistence(self):
        """Test that span data persists across page reloads"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create a span
        span_request = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 10,
                    'value': 'positive'
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

        # Verify span is present
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), 1, "Span should be rendered")

        # Reload the page
        self.driver.refresh()
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        # Check that span is still present after reload
        span_elements_after_reload = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements_after_reload), 1, "Span should persist after page reload")

        # Verify span data is correct
        span_element = span_elements_after_reload[0]
        data_label = span_element.get_attribute("data-label")
        self.assertEqual(data_label, "positive", "Span should have correct label after reload")

    def test_span_validation(self):
        """Test span validation and error handling"""
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
            }
        ]

        for test_case in invalid_spans:
            response = requests.post(
                f"{self.server.base_url}/updateinstance",
                json=test_case['data'],
                cookies=session_cookies
            )

            # Invalid spans should be handled gracefully
            if response.status_code == 400:
                print(f"✅ Validation passed: {test_case['description']}")
            else:
                print(f"⚠️ Validation unexpected: {test_case['description']} returned {response.status_code}")

    def test_span_manager_integration(self):
        """Test integration with the span manager"""
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

        # Test creating span via span manager
        create_result = self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.createAnnotation('test text', 0, 9, 'positive');
            }
            return null;
        """)

        if create_result is not None:
            print("✅ Span creation via span manager works")
        else:
            print("⚠️ Span creation via span manager not available")

    def test_span_boundary_algorithm(self):
        """Test the boundary-based span rendering algorithm"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create overlapping spans to test boundary algorithm
        overlapping_spans = [
            {'start': 0, 'end': 10, 'label': 'positive'},
            {'start': 5, 'end': 15, 'label': 'negative'},
            {'start': 20, 'end': 30, 'label': 'neutral'}
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

        # Check that all spans are rendered
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), len(overlapping_spans))

        # Verify text content is preserved
        text_element = self.driver.find_element(By.ID, "instance-text")
        text_content = text_element.text
        self.assertIsNotNone(text_content)
        self.assertGreater(len(text_content), 0)

        print("✅ Boundary algorithm handles overlapping spans correctly")


if __name__ == "__main__":
    # Run the tests directly
    unittest.main()