#!/usr/bin/env python3
"""
Comprehensive selenium test for annotation persistence with multiple annotation types.

This test verifies that when a page has multiple annotation types (checkbox, radio,
textbox, and span), all annotations:
1. Don't persist to other instances when navigating
2. Are correctly restored when returning to a previously annotated instance
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


class TestComprehensivePersistence(unittest.TestCase):
    """Test annotation persistence with multiple annotation types on the same page."""

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
        cls.test_dir = os.path.join(tests_dir, "output", f"comprehensive_persistence_test_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create test data with 5 items - text long enough for span selection
        test_data = [
            {"id": f"item_{i+1}", "text": f"This is test item number {i+1} with enough text content to allow span annotation selection and testing."}
            for i in range(5)
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        # Create annotation schemes covering all types
        annotation_schemes = [
            {
                "name": "multi_choice",
                "annotation_type": "multiselect",
                "labels": ["red", "blue", "green"],
                "description": "Select all colors that apply"
            },
            {
                "name": "single_choice",
                "annotation_type": "radio",
                "labels": ["option_a", "option_b", "option_c"],
                "description": "Choose one option"
            },
            {
                "name": "text_response",
                "annotation_type": "text",
                "description": "Enter your response"
            },
            {
                "name": "span_labels",
                "annotation_type": "span",
                "labels": ["important", "question"],
                "description": "Mark important spans"
            }
        ]

        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Comprehensive Persistence Test",
            require_password=False
        )

        # Start the server
        cls.server = FlaskTestServer(port=9022, debug=False, config_file=cls.config_file)
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

        # Clean up test directory
        if hasattr(cls, 'test_dir'):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)

        # Generate unique test user
        timestamp = int(time.time() * 1000)
        self.test_user = f"test_user_{timestamp}"

        # Login the user (passwordless mode)
        self._login_user()

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login_user(self):
        """Login the test user via the web interface."""
        self.driver.get(f"{self.server.base_url}/")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )

        # Fill in username (no password needed)
        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(self.test_user)

        # Submit the form
        login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
        login_form.submit()

        # Wait for redirect to annotation page
        time.sleep(2)

        # Verify we're on the annotation interface
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )

    def _wait_for_annotation_page(self, timeout=10):
        """Wait for the annotation page to fully load."""
        WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.CLASS_NAME, "annotation-form"))
        )
        # Give JavaScript time to initialize
        time.sleep(1)

    def _get_current_instance_id(self):
        """Get the current instance ID from the hidden field."""
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

    def _get_checked_checkboxes(self, schema="multi_choice"):
        """Get all checked checkboxes for a schema."""
        checkboxes = self.driver.find_elements(
            By.CSS_SELECTOR, f'input[type="checkbox"][schema="{schema}"]'
        )
        return [cb for cb in checkboxes if cb.is_selected()]

    def _get_selected_radio(self, schema="single_choice"):
        """Get the selected radio button for a schema."""
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, f'input[type="radio"][schema="{schema}"]'
        )
        for rb in radios:
            if rb.is_selected():
                return rb.get_attribute('label_name')
        return None

    def _get_textbox_value(self, schema="text_response"):
        """Get the value of a textbox."""
        textbox = self.driver.find_element(
            By.CSS_SELECTOR, f'input[type="text"][schema="{schema}"], textarea[schema="{schema}"]'
        )
        return textbox.get_attribute('value') or ''

    def _get_span_count(self):
        """Get the number of span annotations visible on the page."""
        # Spans are rendered as overlay elements
        spans = self.driver.find_elements(By.CSS_SELECTOR, '.span-highlight, .span-overlay, [data-span-id]')
        return len(spans)

    def _click_checkbox(self, label_name, schema="multi_choice"):
        """Click a checkbox by label name."""
        checkbox = self.driver.find_element(
            By.CSS_SELECTOR, f'input[type="checkbox"][schema="{schema}"][label_name="{label_name}"]'
        )
        checkbox.click()
        time.sleep(0.5)

    def _click_radio(self, label_name, schema="single_choice"):
        """Click a radio button by label name."""
        radio = self.driver.find_element(
            By.CSS_SELECTOR, f'input[type="radio"][schema="{schema}"][label_name="{label_name}"]'
        )
        radio.click()
        time.sleep(0.5)

    def _enter_text(self, text, schema="text_response"):
        """Enter text into a textbox."""
        textbox = self.driver.find_element(
            By.CSS_SELECTOR, f'input[type="text"][schema="{schema}"], textarea[schema="{schema}"]'
        )
        textbox.clear()
        textbox.send_keys(text)
        time.sleep(1.5)  # Wait for debounced save

    def test_all_types_do_not_persist_to_next_instance(self):
        """
        Test that annotations of all types on instance 1 do NOT persist to instance 2.
        """
        self._wait_for_annotation_page()

        instance_id_1 = self._get_current_instance_id()
        print(f"Starting on instance: {instance_id_1}")

        # Make annotations of each type on instance 1
        # Checkbox
        self._click_checkbox("red")
        self._click_checkbox("blue")
        print("Checked 'red' and 'blue' checkboxes")

        # Radio
        self._click_radio("option_b")
        print("Selected 'option_b' radio")

        # Text
        self._enter_text("Instance 1 text annotation")
        print("Entered text annotation")

        # Verify annotations on instance 1
        self.assertEqual(len(self._get_checked_checkboxes()), 2)
        self.assertEqual(self._get_selected_radio(), "option_b")
        self.assertEqual(self._get_textbox_value(), "Instance 1 text annotation")

        # Navigate to instance 2
        self._navigate_next()
        instance_id_2 = self._get_current_instance_id()
        print(f"Navigated to instance: {instance_id_2}")
        self.assertNotEqual(instance_id_1, instance_id_2)

        # CRITICAL TEST: No annotations should persist to instance 2
        checked_checkboxes = self._get_checked_checkboxes()
        self.assertEqual(
            len(checked_checkboxes), 0,
            f"BUG: Checkboxes persisted! Found: {[cb.get_attribute('label_name') for cb in checked_checkboxes]}"
        )
        print("✓ No checkboxes persisted")

        selected_radio = self._get_selected_radio()
        self.assertIsNone(
            selected_radio,
            f"BUG: Radio persisted! Found: {selected_radio}"
        )
        print("✓ No radio selection persisted")

        text_value = self._get_textbox_value()
        self.assertEqual(
            text_value, '',
            f"BUG: Text persisted! Found: '{text_value}'"
        )
        print("✓ No text persisted")

    def test_all_types_persist_when_navigating_back(self):
        """
        Test that annotations of all types are preserved when navigating away and back.
        """
        self._wait_for_annotation_page()

        instance_id_1 = self._get_current_instance_id()
        print(f"Starting on instance: {instance_id_1}")

        # Make annotations of each type on instance 1
        self._click_checkbox("green")
        self._click_radio("option_c")
        self._enter_text("Preserved text")
        print("Made annotations on instance 1")

        # Navigate away
        self._navigate_next()
        instance_id_2 = self._get_current_instance_id()
        print(f"Navigated to instance: {instance_id_2}")

        # Navigate back
        self._navigate_prev()
        instance_id_back = self._get_current_instance_id()
        print(f"Navigated back to instance: {instance_id_back}")
        self.assertEqual(instance_id_1, instance_id_back)

        # CRITICAL TEST: All annotations should be preserved
        checked_checkboxes = self._get_checked_checkboxes()
        checked_labels = [cb.get_attribute('label_name') for cb in checked_checkboxes]
        self.assertIn(
            'green', checked_labels,
            f"BUG: Checkbox not preserved! Found: {checked_labels}"
        )
        print("✓ Checkbox preserved")

        selected_radio = self._get_selected_radio()
        self.assertEqual(
            selected_radio, 'option_c',
            f"BUG: Radio not preserved! Found: {selected_radio}"
        )
        print("✓ Radio preserved")

        text_value = self._get_textbox_value()
        self.assertEqual(
            text_value, 'Preserved text',
            f"BUG: Text not preserved! Found: '{text_value}'"
        )
        print("✓ Text preserved")

    def test_multiple_instances_maintain_separate_state_all_types(self):
        """
        Test that multiple instances maintain separate state for all annotation types.
        """
        self._wait_for_annotation_page()

        # Instance 1: checkbox=red, radio=option_a, text="text1"
        instance_1 = self._get_current_instance_id()
        self._click_checkbox("red")
        self._click_radio("option_a")
        self._enter_text("text1")
        print(f"Instance 1 ({instance_1}): red, option_a, 'text1'")

        # Instance 2: checkbox=blue, radio=option_b, text="text2"
        self._navigate_next()
        instance_2 = self._get_current_instance_id()
        self._click_checkbox("blue")
        self._click_radio("option_b")
        self._enter_text("text2")
        print(f"Instance 2 ({instance_2}): blue, option_b, 'text2'")

        # Instance 3: checkbox=green, radio=option_c, text="text3"
        self._navigate_next()
        instance_3 = self._get_current_instance_id()
        self._click_checkbox("green")
        self._click_radio("option_c")
        self._enter_text("text3")
        print(f"Instance 3 ({instance_3}): green, option_c, 'text3'")

        # Navigate back and verify each instance
        # Back to Instance 2
        self._navigate_prev()
        self.assertEqual(self._get_current_instance_id(), instance_2)
        checked = [cb.get_attribute('label_name') for cb in self._get_checked_checkboxes()]
        self.assertEqual(checked, ['blue'], f"Instance 2 checkbox wrong: {checked}")
        self.assertEqual(self._get_selected_radio(), 'option_b')
        self.assertEqual(self._get_textbox_value(), 'text2')
        print("✓ Instance 2 state correct")

        # Back to Instance 1
        self._navigate_prev()
        self.assertEqual(self._get_current_instance_id(), instance_1)
        checked = [cb.get_attribute('label_name') for cb in self._get_checked_checkboxes()]
        self.assertEqual(checked, ['red'], f"Instance 1 checkbox wrong: {checked}")
        self.assertEqual(self._get_selected_radio(), 'option_a')
        self.assertEqual(self._get_textbox_value(), 'text1')
        print("✓ Instance 1 state correct")

        # Forward to Instance 3
        self._navigate_next()
        self._navigate_next()
        self.assertEqual(self._get_current_instance_id(), instance_3)
        checked = [cb.get_attribute('label_name') for cb in self._get_checked_checkboxes()]
        self.assertEqual(checked, ['green'], f"Instance 3 checkbox wrong: {checked}")
        self.assertEqual(self._get_selected_radio(), 'option_c')
        self.assertEqual(self._get_textbox_value(), 'text3')
        print("✓ Instance 3 state correct")


if __name__ == '__main__':
    unittest.main(verbosity=2)
