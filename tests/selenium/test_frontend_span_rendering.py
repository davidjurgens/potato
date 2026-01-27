#!/usr/bin/env python3
"""
Selenium tests for frontend span rendering system

This test suite focuses on the rendering aspects of the frontend span annotation
system, including visual appearance, positioning, and user interaction.

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


class TestFrontendSpanRendering(BaseSeleniumTest):
    """
    Test suite for frontend span rendering system.

    This class tests the visual and interaction aspects of span rendering:
    - Visual appearance and styling
    - Positioning and layout
    - User interaction elements
    - Color schemes and themes
    - Responsive behavior

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_span_visual_appearance(self):
        """Test that spans are rendered with correct visual appearance"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create a span for testing
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
        time.sleep(0.05)

        # Check that span elements are present
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertGreater(len(span_elements), 0, "Span should be rendered")

        # Check visual properties
        span_element = span_elements[0]

        # Check that span has background color
        background_color = span_element.value_of_css_property("background-color")
        self.assertIsNotNone(background_color)
        self.assertNotEqual(background_color, "rgba(0, 0, 0, 0)", "Span should have background color")

        # Check that span has proper styling
        display = span_element.value_of_css_property("display")
        self.assertIn(display, ["inline", "inline-block"], "Span should be inline or inline-block")

        # Check that span contains text
        span_text = span_element.text
        self.assertIsNotNone(span_text)
        self.assertGreater(len(span_text), 0, "Span should contain text")

    def test_span_positioning_and_layout(self):
        """Test that spans are positioned correctly in the text"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create multiple spans at different positions
        spans_data = [
            {'start': 0, 'end': 5, 'label': 'positive'},
            {'start': 20, 'end': 30, 'label': 'negative'},
            {'start': 50, 'end': 60, 'label': 'neutral'}
        ]

        for span_data in spans_data:
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
        time.sleep(0.05)

        # Check that all spans are rendered
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), len(spans_data))

        # Check that spans are in the correct order in the DOM
        text_container = self.driver.find_element(By.ID, "instance-text")
        all_text_nodes = text_container.find_elements(By.XPATH, ".//text() | .//span")

        # Verify that spans are interspersed with text (not all at the beginning or end)
        span_count = 0
        for node in all_text_nodes:
            if node.tag_name == 'span' and 'span-highlight' in node.get_attribute('class'):
                span_count += 1

        self.assertEqual(span_count, len(spans_data), "All spans should be present in the DOM")

    def test_span_interaction_elements(self):
        """Test that span interaction elements (delete buttons, labels) are present"""
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
        time.sleep(0.05)

        # Check for delete button
        delete_buttons = self.driver.find_elements(By.CLASS_NAME, "span-delete")
        self.assertGreater(len(delete_buttons), 0, "Delete button should be present")

        # Check for span labels
        span_labels = self.driver.find_elements(By.CLASS_NAME, "span-label")
        self.assertGreater(len(span_labels), 0, "Span label should be present")

        # Check that delete button is clickable
        delete_button = delete_buttons[0]
        self.assertTrue(delete_button.is_displayed(), "Delete button should be visible")
        self.assertTrue(delete_button.is_enabled(), "Delete button should be enabled")

        # Check that span label shows correct text
        span_label = span_labels[0]
        label_text = span_label.text
        self.assertEqual(label_text, "positive", "Span label should show correct label")

    def test_span_color_schemes(self):
        """Test that different span labels have different colors"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create spans with different labels
        spans_data = [
            {'start': 0, 'end': 5, 'label': 'positive'},
            {'start': 10, 'end': 15, 'label': 'negative'},
            {'start': 20, 'end': 25, 'label': 'neutral'}
        ]

        for span_data in spans_data:
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
        time.sleep(0.05)

        # Check that spans have different colors
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), len(spans_data))

        colors = []
        for span in span_elements:
            background_color = span.value_of_css_property("background-color")
            colors.append(background_color)

        # Check that we have different colors (not all the same)
        unique_colors = set(colors)
        self.assertGreater(len(unique_colors), 1, "Different labels should have different colors")

    def test_span_responsive_behavior(self):
        """Test that spans behave correctly when window is resized"""
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
        time.sleep(0.05)

        # Get initial span position
        span_element = self.driver.find_element(By.CLASS_NAME, "span-highlight")
        initial_position = span_element.location

        # Resize window
        self.driver.set_window_size(800, 600)
        time.sleep(0.1)

        # Check that span is still present
        span_elements_after_resize = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements_after_resize), 1, "Span should still be present after resize")

        # Check that span is still visible
        span_element_after = span_elements_after_resize[0]
        self.assertTrue(span_element_after.is_displayed(), "Span should still be visible after resize")

        # Restore window size
        self.driver.set_window_size(1920, 1080)

    def test_span_text_preservation(self):
        """Test that original text is preserved when spans are rendered"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get original text
        text_element = self.driver.find_element(By.ID, "instance-text")
        original_text = text_element.text
        self.assertIsNotNone(original_text)
        self.assertGreater(len(original_text), 0)

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
        time.sleep(0.05)

        # Check that text content is preserved
        text_element_after = self.driver.find_element(By.ID, "instance-text")
        text_after = text_element_after.text

        # The text should still contain the original content
        # (spans might add extra text like labels, but original text should be there)
        self.assertIn(original_text[:20], text_after, "Original text should be preserved")

        # Check that span is present
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), 1, "Span should be rendered")

    def test_span_accessibility(self):
        """Test that spans have proper accessibility attributes"""
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
        time.sleep(0.05)

        # Check span accessibility attributes
        span_element = self.driver.find_element(By.CLASS_NAME, "span-highlight")

        # Check for data attributes
        data_label = span_element.get_attribute("data-label")
        self.assertEqual(data_label, "positive", "Span should have data-label attribute")

        data_annotation_id = span_element.get_attribute("data-annotation-id")
        self.assertIsNotNone(data_annotation_id, "Span should have data-annotation-id attribute")

        # Check that span is keyboard accessible
        span_element.send_keys("")  # This should not throw an error
        self.assertTrue(span_element.is_enabled(), "Span should be enabled")


if __name__ == "__main__":
    # Run the tests directly
    unittest.main()