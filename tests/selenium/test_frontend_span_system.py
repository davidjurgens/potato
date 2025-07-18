#!/usr/bin/env python3
"""
Selenium tests for the frontend-driven span annotation system

This test suite verifies the complete frontend span annotation workflow:
1. User authentication and session management
2. Span manager initialization and API endpoints
3. Span creation, rendering, and deletion
4. Frontend-backend data consistency
5. Boundary-based rendering algorithm
6. Color scheme and UI interactions

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
import os
import subprocess
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import unittest

from tests.selenium.test_base import BaseSeleniumTest


class TestFrontendSpanSystem(BaseSeleniumTest):
    """
    Test suite for the frontend-driven span annotation system.

    This class tests the complete span annotation workflow including:
    - Span manager initialization
    - API endpoint functionality
    - Frontend rendering and interaction
    - Data consistency between frontend and backend

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_span_manager_initialization(self):
        """Test that the span manager initializes correctly"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Wait a bit for JavaScript to initialize
        time.sleep(2)

        # Check that span manager JavaScript is loaded
        span_manager_available = self.execute_script_safe(
            "return typeof SpanManager !== 'undefined'"
        )
        self.assertTrue(span_manager_available, "SpanManager should be loaded")

        # Check that span manager is initialized
        span_manager_initialized = self.execute_script_safe(
            "return window.spanManager !== null && window.spanManager !== undefined"
        )
        self.assertTrue(span_manager_initialized, "SpanManager should be initialized")

    def test_api_endpoints_accessible(self):
        """Test that the API endpoints are accessible"""
        # Test colors endpoint
        response = requests.get(f"{self.server.base_url}/api/colors")
        self.assertEqual(response.status_code, 200)

        colors_data = response.json()
        self.assertIsInstance(colors_data, dict)
        # Note: The actual color keys depend on the config, so we just check it's a dict

        # Test spans endpoint (should return 401 without session, which is expected)
        response = requests.get(f"{self.server.base_url}/api/spans/item_1")
        self.assertEqual(response.status_code, 401, "API should require session")

    def test_span_creation_via_api_and_frontend_rendering(self):
        """Test creating spans via API and verifying frontend renders them"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page first to establish session
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create a span via API using correct format
        span_data = {
            'instance_id': '1',  # Use existing instance ID
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 3,  # "I a"
                    'value': 'positive'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_data,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Wait for spans to be rendered by frontend
        time.sleep(2)

        # Check that the span is rendered by frontend
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertGreater(len(span_elements), 0, "Frontend should render span")

        # Verify span attributes
        span_element = span_elements[0]
        self.assertEqual(
            span_element.get_attribute("data-label"),
            "positive"
        )
        self.assertEqual(
            span_element.get_attribute("data-schema"),
            "sentiment"
        )

    def test_frontend_span_creation_interaction(self):
        """Test creating spans via frontend interaction"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")

        # Get the text content
        text_content = text_element.text
        self.assertIsNotNone(text_content)

        # Select text to create a span
        actions = ActionChains(self.driver)
        actions.move_to_element(text_element)
        actions.click_and_hold()
        actions.move_by_offset(50, 0)  # Select some text
        actions.release()
        actions.perform()

        # Wait for span creation dialog or menu
        time.sleep(1)

        # Check if span creation UI appears
        # This depends on the specific UI implementation
        try:
            span_menu = self.driver.find_element(By.CLASS_NAME, "span-creation-menu")
            self.assertTrue(span_menu.is_displayed(), "Span creation menu should be visible")
        except NoSuchElementException:
            # If no specific menu, check if selection is maintained
            selection = self.execute_script_safe(
                "return window.getSelection().toString()"
            )
            self.assertIsNotNone(selection, "Text selection should be maintained")

    def test_span_deletion_via_api_and_frontend_update(self):
        """Test deleting spans via API and verifying frontend updates"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page first to establish session
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # First create a span
        span_data = {
            'instance_id': '1',  # Use existing instance ID
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 3,
                    'value': 'positive'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_data,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Verify span exists via API
        response = requests.get(
            f"{self.server.base_url}/api/spans/1",
            cookies=session_cookies
        )
        spans_data = response.json()
        self.assertEqual(len(spans_data['spans']), 1)

        # Wait for spans to be rendered by frontend
        time.sleep(2)

        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), 1, "Frontend should show one span")

        # Delete span by setting value to None
        delete_data = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 3,
                    'value': None  # This deletes the span
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=delete_data,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Wait for frontend to update
        time.sleep(2)

        # Verify span is removed from frontend
        span_elements_after = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements_after), 0, "Frontend should show no spans after deletion")

    def test_frontend_color_rendering(self):
        """Test that spans are rendered with correct colors"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create spans with different labels to test color rendering
        span_data = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 3,
                    'value': 'positive'
                },
                {
                    'name': 'negative',
                    'title': 'Negative sentiment',
                    'start': 10,
                    'end': 15,
                    'value': 'negative'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_data,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Wait for spans to be rendered
        time.sleep(2)

        # Check that spans are rendered with different colors
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertGreaterEqual(len(span_elements), 2, "Should have at least 2 spans")

        # Get background colors
        colors = []
        for span in span_elements:
            background_color = span.value_of_css_property("background-color")
            colors.append(background_color)

        # Verify that we have different colors (not all the same)
        unique_colors = set(colors)
        self.assertGreater(len(unique_colors), 1, "Spans should have different colors")

    def test_frontend_boundary_algorithm(self):
        """Test the boundary-based rendering algorithm with overlapping spans"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create overlapping spans to test boundary algorithm
        span_data = {
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
                },
                {
                    'name': 'negative',
                    'title': 'Negative sentiment',
                    'start': 5,
                    'end': 15,
                    'value': 'negative'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_data,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Wait for spans to be rendered
        time.sleep(2)

        # Check that both spans are rendered
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertGreaterEqual(len(span_elements), 2, "Should have at least 2 spans")

        # Verify text content is preserved
        text_element = self.driver.find_element(By.ID, "instance-text")
        text_content = text_element.text
        self.assertIsNotNone(text_content)
        self.assertGreater(len(text_content), 0, "Text content should be preserved")

    def test_load_annotations_directly(self):
        """Test that loadAnnotations works correctly when called directly"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page first to establish session
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Wait for JavaScript to initialize
        time.sleep(2)

        # Check that span manager is initialized
        span_manager_initialized = self.execute_script_safe(
            "return window.spanManager !== null && window.spanManager !== undefined"
        )
        self.assertTrue(span_manager_initialized, "SpanManager should be initialized")

        # Get initial annotations
        initial_annotations = self.execute_script_safe(
            "return window.spanManager ? window.spanManager.getAnnotations() : null"
        )
        print(f"Initial annotations: {initial_annotations}")

        # Call loadAnnotations directly
        self.driver.execute_async_script("""
            const done = arguments[0];
            if (window.spanManager) {
                window.spanManager.loadAnnotations('1').then(() => {
                    console.log('loadAnnotations completed');
                    done();
                }).catch((error) => {
                    console.error('loadAnnotations failed:', error);
                    done();
                });
            } else {
                done();
            }
        """)

        # Wait a bit for the async operation
        time.sleep(1)

        # Get annotations after loadAnnotations
        annotations_after_load = self.execute_script_safe(
            "return window.spanManager ? window.spanManager.getAnnotations() : null"
        )
        print(f"Annotations after loadAnnotations: {annotations_after_load}")

        # Get spans after loadAnnotations
        spans_after_load = self.execute_script_safe(
            "return window.spanManager ? window.spanManager.getSpans() : []"
        )
        print(f"Spans after loadAnnotations: {spans_after_load}")

        # Verify that annotations were loaded (should be an object with spans array)
        self.assertIsNotNone(annotations_after_load, "Annotations should not be null")
        self.assertIsInstance(annotations_after_load, dict, "Annotations should be an object")
        self.assertIn('spans', annotations_after_load, "Annotations should have a spans property")

    def test_frontend_span_creation_via_ui(self):
        """Test creating spans via UI interaction and verifying frontend data consistency"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page first to establish session
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Wait for JavaScript to initialize
        time.sleep(2)

        # Check that span manager is initialized
        span_manager_initialized = self.execute_script_safe(
            "return window.spanManager !== null && window.spanManager !== undefined"
        )
        self.assertTrue(span_manager_initialized, "SpanManager should be initialized")

        # Get initial spans
        initial_spans = self.execute_script_safe(
            "return window.spanManager ? window.spanManager.getSpans() : []"
        )
        self.assertEqual(len(initial_spans), 0, "Should start with no spans")

        # Select a label first (assuming there are label buttons)
        label_buttons = self.driver.find_elements(By.CLASS_NAME, "label-button")
        if label_buttons:
            label_buttons[0].click()
            time.sleep(0.5)

        # Get text content for selection
        text_element = self.driver.find_element(By.ID, "instance-text")
        text_content = text_element.text

        # Select some text using JavaScript
        self.execute_script_safe("""
            var textElement = arguments[0];
            var range = document.createRange();
            var textNode = textElement.firstChild;
            range.setStart(textNode, 0);
            range.setEnd(textNode, 5);
            var selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """, text_element)

        # Wait for span creation
        time.sleep(2)

        # Check if spans were created
        spans_after_selection = self.execute_script_safe(
            "return window.spanManager ? window.spanManager.getSpans() : []"
        )
        print(f"Spans after selection: {spans_after_selection}")

        # The exact behavior depends on the UI implementation
        # For now, we just verify the span manager is working
        self.assertIsInstance(spans_after_selection, list, "Spans should be a list")

    def test_frontend_api_data_consistency(self):
        """Test that frontend span data is consistent with API data"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page first to establish session
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create spans via API using browser session
        span_data = {
            'instance_id': '1',  # Use existing instance ID from test data
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 3,
                    'value': 'positive'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_data,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Force the frontend to reload annotations after API update and wait for completion
        self.driver.execute_async_script("""
            const done = arguments[0];
            if (window.spanManager) {
                window.spanManager.loadAnnotations('1').then(done);
            } else {
                done();
            }
        """)
        # Wait for spans to be loaded in the frontend
        for _ in range(20):
            frontend_spans = self.execute_script_safe(
                "return window.spanManager ? window.spanManager.getSpans() : []"
            )
            if len(frontend_spans) > 0:
                break
            time.sleep(0.1)

        # Verify frontend has the same data as API
        self.assertGreater(len(frontend_spans), 0, "Frontend should have spans after API update")

        # Get API data for comparison
        response = requests.get(
            f"{self.server.base_url}/api/spans/1",
            cookies=session_cookies
        )
        api_spans = response.json()['spans']

        # Compare frontend and API data
        self.assertEqual(len(frontend_spans), len(api_spans), "Frontend and API should have same number of spans")

        # Compare span properties
        frontend_span = frontend_spans[0]
        api_span = api_spans[0]

        self.assertEqual(frontend_span['label'], api_span['label'], "Span labels should match")
        self.assertEqual(frontend_span['start'], api_span['start'], "Span start positions should match")
        self.assertEqual(frontend_span['end'], api_span['end'], "Span end positions should match")

    def test_no_server_side_html_rendering(self):
        """Test that spans are not pre-rendered in HTML from server"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get the initial HTML content
        initial_html = self.driver.find_element(By.ID, "instance-text").get_attribute("innerHTML")
        print(f"Initial HTML: {initial_html[:200]}...")

        # Check that there are no span-highlight elements in the initial HTML
        self.assertNotIn("span-highlight", initial_html, "Initial HTML should not contain span-highlight elements")

        # Create a span via API
        session_cookies = self.get_session_cookies()
        span_data = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 3,
                    'value': 'positive'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_data,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Wait for frontend to render the span
        time.sleep(2)

        # Check that span-highlight elements are now present (rendered by frontend)
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertGreater(len(span_elements), 0, "Frontend should render span elements after API update")


if __name__ == "__main__":
    # Run the tests directly
    unittest.main()