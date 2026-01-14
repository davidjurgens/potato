#!/usr/bin/env python3
"""
Selenium test for span annotation persistence when combined with other annotation types.

This test verifies that span annotations work correctly alongside checkbox, radio,
and textbox annotations on the same page.
"""

import time
import unittest
import os
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.action_chains import ActionChains
import requests


class TestSpanWithOtherTypes(unittest.TestCase):
    """Test span annotation persistence with other annotation types."""

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server for all tests in this class."""
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_config,
            create_test_data_file,
            cleanup_test_directory
        )

        # Create a test directory
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(tests_dir, "output", f"span_with_types_test_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create test data with 5 items - text long enough for span selection
        test_data = [
            {"id": "item_1", "text": "The quick brown fox jumps over the lazy dog. This sentence has enough words for testing spans."},
            {"id": "item_2", "text": "A second instance with different text content for comparison testing purposes."},
            {"id": "item_3", "text": "Third instance text that we can use to verify span annotations work correctly."},
            {"id": "item_4", "text": "Fourth test item with sample text for annotation persistence verification."},
            {"id": "item_5", "text": "Fifth and final test instance with adequate content for span selection tests."},
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        # Create annotation schemes covering multiple types including span
        annotation_schemes = [
            {
                "name": "checkbox_schema",
                "annotation_type": "multiselect",
                "labels": ["option1", "option2"],
                "description": "Select options"
            },
            {
                "name": "radio_schema",
                "annotation_type": "radio",
                "labels": ["choice_a", "choice_b"],
                "description": "Choose one"
            },
            {
                "name": "span_schema",
                "annotation_type": "span",
                "labels": ["highlight", "important"],
                "description": "Mark text spans"
            }
        ]

        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Span With Other Types Test",
            require_password=False
        )

        # Start the server
        cls.port = 9023
        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"

        # Wait for server to be ready
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options for headless testing
        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        """Clean up the Flask server after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()

        if hasattr(cls, 'test_dir'):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.session = requests.Session()

        # Generate unique test user
        timestamp = int(time.time() * 1000)
        self.test_user = f"test_user_{timestamp}"

        # Login the user
        self._login_user()

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login_user(self):
        """Login the test user via the web interface."""
        self.driver.get(f"{self.server.base_url}/")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )

        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(self.test_user)

        login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
        login_form.submit()

        time.sleep(2)

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )

        # Also login via requests session for API calls
        self.session.post(
            f"{self.server.base_url}/auth",
            data={"email": self.test_user, "pass": "", "action": "login"}
        )

    def _wait_for_annotation_page(self, timeout=10):
        """Wait for the annotation page to fully load."""
        WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.CLASS_NAME, "annotation-form"))
        )
        time.sleep(1)

    def _get_current_instance_id(self):
        """Get the current instance ID."""
        instance_field = self.driver.find_element(By.ID, "instance_id")
        return instance_field.get_attribute("value")

    def _navigate_next(self):
        """Navigate to the next instance."""
        try:
            next_button = self.driver.find_element(By.ID, "next-btn")
        except:
            next_button = self.driver.find_element(By.CSS_SELECTOR, 'a[onclick*="click_to_next"]')
        next_button.click()
        time.sleep(2)
        self._wait_for_annotation_page()

    def _navigate_prev(self):
        """Navigate to the previous instance."""
        try:
            prev_button = self.driver.find_element(By.ID, "prev-btn")
        except:
            prev_button = self.driver.find_element(By.CSS_SELECTOR, 'a[onclick*="click_to_prev"]')
        prev_button.click()
        time.sleep(2)
        self._wait_for_annotation_page()

    def _create_span_via_api(self, instance_id, label, start, end, text):
        """Create a span annotation via the API."""
        response = self.session.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": instance_id,
                "type": "span",
                "schema": "span_schema",
                "state": [{
                    "name": label,
                    "title": label,
                    "start": start,
                    "end": end,
                    "value": text
                }]
            }
        )
        return response.status_code == 200

    def _get_span_annotations_via_api(self, instance_id):
        """Get span annotations for an instance via API."""
        response = self.session.get(f"{self.server.base_url}/api/spans/{instance_id}")
        if response.status_code == 200:
            return response.json().get("spans", [])
        return []

    def _click_checkbox(self, label_name):
        """Click a checkbox."""
        checkbox = self.driver.find_element(
            By.CSS_SELECTOR, f'input[type="checkbox"][schema="checkbox_schema"][label_name="{label_name}"]'
        )
        checkbox.click()
        time.sleep(0.5)

    def _click_radio(self, label_name):
        """Click a radio button."""
        radio = self.driver.find_element(
            By.CSS_SELECTOR, f'input[type="radio"][schema="radio_schema"][label_name="{label_name}"]'
        )
        radio.click()
        time.sleep(0.5)

    def _get_checked_checkboxes(self):
        """Get checked checkbox labels."""
        checkboxes = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="checkbox"][schema="checkbox_schema"]'
        )
        return [cb.get_attribute('label_name') for cb in checkboxes if cb.is_selected()]

    def _get_selected_radio(self):
        """Get selected radio label."""
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][schema="radio_schema"]'
        )
        for rb in radios:
            if rb.is_selected():
                return rb.get_attribute('label_name')
        return None

    def test_span_does_not_persist_to_next_instance(self):
        """
        Test that span annotations on instance 1 don't appear on instance 2.
        """
        self._wait_for_annotation_page()

        instance_id_1 = self._get_current_instance_id()
        print(f"Starting on instance: {instance_id_1}")

        # Create a span annotation via API (simulating user selection)
        success = self._create_span_via_api(instance_id_1, "highlight", 4, 9, "quick")
        self.assertTrue(success, "Failed to create span annotation")
        print("Created span annotation on instance 1")

        # Verify span exists on instance 1
        spans_1 = self._get_span_annotations_via_api(instance_id_1)
        self.assertEqual(len(spans_1), 1, f"Expected 1 span on instance 1, got {len(spans_1)}")
        print(f"Verified span on instance 1: {spans_1}")

        # Navigate to instance 2
        self._navigate_next()
        instance_id_2 = self._get_current_instance_id()
        print(f"Navigated to instance: {instance_id_2}")
        self.assertNotEqual(instance_id_1, instance_id_2)

        # CRITICAL TEST: No spans should exist on instance 2
        spans_2 = self._get_span_annotations_via_api(instance_id_2)
        self.assertEqual(
            len(spans_2), 0,
            f"BUG: Span persisted to instance 2! Found: {spans_2}"
        )
        print("✓ No spans persisted to instance 2")

    def test_span_persists_when_navigating_back(self):
        """
        Test that span annotations are preserved when navigating away and back.
        """
        self._wait_for_annotation_page()

        instance_id_1 = self._get_current_instance_id()
        print(f"Starting on instance: {instance_id_1}")

        # Create span
        self._create_span_via_api(instance_id_1, "important", 10, 15, "brown")
        print("Created span on instance 1")

        # Navigate away
        self._navigate_next()
        instance_id_2 = self._get_current_instance_id()
        print(f"Navigated to instance: {instance_id_2}")

        # Navigate back
        self._navigate_prev()
        instance_id_back = self._get_current_instance_id()
        print(f"Navigated back to: {instance_id_back}")
        self.assertEqual(instance_id_1, instance_id_back)

        # CRITICAL TEST: Span should still exist
        spans = self._get_span_annotations_via_api(instance_id_1)
        self.assertEqual(
            len(spans), 1,
            f"BUG: Span not preserved! Found: {spans}"
        )
        print("✓ Span preserved when navigating back")

    def test_all_types_work_together(self):
        """
        Test that span, checkbox, and radio annotations all work together on same page.
        """
        self._wait_for_annotation_page()

        instance_id_1 = self._get_current_instance_id()
        print(f"Instance 1: {instance_id_1}")

        # Make all types of annotations on instance 1
        self._click_checkbox("option1")
        self._click_radio("choice_a")
        self._create_span_via_api(instance_id_1, "highlight", 0, 3, "The")
        print("Made all annotation types on instance 1")

        # Navigate to instance 2 and make different annotations
        self._navigate_next()
        instance_id_2 = self._get_current_instance_id()
        print(f"Instance 2: {instance_id_2}")

        self._click_checkbox("option2")
        self._click_radio("choice_b")
        self._create_span_via_api(instance_id_2, "important", 2, 8, "second")
        print("Made all annotation types on instance 2")

        # Navigate back to instance 1 and verify all annotations preserved
        self._navigate_prev()
        self.assertEqual(self._get_current_instance_id(), instance_id_1)

        # Verify checkbox
        checked = self._get_checked_checkboxes()
        self.assertEqual(checked, ['option1'], f"Checkbox wrong: {checked}")
        print("✓ Instance 1 checkbox correct")

        # Verify radio
        selected = self._get_selected_radio()
        self.assertEqual(selected, 'choice_a', f"Radio wrong: {selected}")
        print("✓ Instance 1 radio correct")

        # Verify span
        spans = self._get_span_annotations_via_api(instance_id_1)
        self.assertEqual(len(spans), 1, f"Span wrong: {spans}")
        self.assertEqual(spans[0].get('label') or spans[0].get('name'), 'highlight')
        print("✓ Instance 1 span correct")

        # Navigate to instance 2 and verify
        self._navigate_next()
        self.assertEqual(self._get_current_instance_id(), instance_id_2)

        checked = self._get_checked_checkboxes()
        self.assertEqual(checked, ['option2'], f"Instance 2 checkbox wrong: {checked}")
        print("✓ Instance 2 checkbox correct")

        selected = self._get_selected_radio()
        self.assertEqual(selected, 'choice_b', f"Instance 2 radio wrong: {selected}")
        print("✓ Instance 2 radio correct")

        spans = self._get_span_annotations_via_api(instance_id_2)
        self.assertEqual(len(spans), 1, f"Instance 2 span wrong: {spans}")
        print("✓ Instance 2 span correct")


if __name__ == '__main__':
    unittest.main(verbosity=2)
