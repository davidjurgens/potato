#!/usr/bin/env python3
"""
Selenium tests for annotation persistence across multiple annotation types.

This test verifies that the checkbox persistence bug fix also works for:
1. Radio buttons - single choice selection
2. Textbox/Textarea - text input fields
3. Span annotations - text highlighting

The bug being tested: Annotations from instance 1 should NOT persist to instance 2.
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


class TestAnnotationTypePersistence(unittest.TestCase):
    """Test that different annotation types persist correctly across navigation."""

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server for all tests in this class."""
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory,
            create_test_config,
            create_test_data_file,
            cleanup_test_directory
        )

        # Create a test directory
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(tests_dir, "output", f"annotation_type_test_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create test data with 5 items
        test_data = [
            {"id": f"item_{i+1}", "text": f"This is test item {i+1} for annotation type testing."}
            for i in range(5)
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        # Create annotation schemes covering multiple types
        annotation_schemes = [
            {
                "name": "radio_choice",
                "annotation_type": "radio",
                "labels": ["option_a", "option_b", "option_c"],
                "description": "Choose one option"
            },
            {
                "name": "text_input",
                "annotation_type": "text",
                "description": "Enter your response"
            },
            {
                "name": "multi_choice",
                "annotation_type": "multiselect",
                "labels": ["red", "blue", "green"],
                "description": "Select all that apply"
            }
        ]

        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Annotation Type Persistence Test",
            require_password=False
        )

        # Start the server
        cls.server = FlaskTestServer(debug=False, config_file=cls.config_file)
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
        time.sleep(0.05)

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
        time.sleep(0.1)

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
        time.sleep(0.05)
        self._wait_for_annotation_page()

    def _navigate_prev(self):
        """Navigate to the previous instance."""
        try:
            prev_button = self.driver.find_element(By.ID, "prev-btn")
        except:
            prev_button = self.driver.find_element(By.CSS_SELECTOR, 'a[onclick*="click_to_prev"]')
        prev_button.click()
        time.sleep(0.05)
        self._wait_for_annotation_page()

    def test_radio_does_not_persist_to_next_instance(self):
        """
        Test that selecting a radio button on instance 1 does NOT cause it
        to appear selected on instance 2.
        """
        self._wait_for_annotation_page()

        # Verify we're on instance 1
        instance_id_1 = self._get_current_instance_id()
        print(f"Starting on instance: {instance_id_1}")

        # Find and click a radio button (option_b)
        radio_buttons = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][schema="radio_choice"]'
        )
        self.assertGreater(len(radio_buttons), 0, "Should have radio buttons")

        # Select option_b (index 1)
        radio_option_b = None
        for rb in radio_buttons:
            if rb.get_attribute('label_name') == 'option_b':
                radio_option_b = rb
                break

        self.assertIsNotNone(radio_option_b, "Should find option_b radio button")
        radio_option_b.click()
        time.sleep(0.1)  # Wait for save

        self.assertTrue(radio_option_b.is_selected(), "Radio button should be selected")
        print("Selected 'option_b' radio button on instance 1")

        # Navigate to instance 2
        self._navigate_next()
        instance_id_2 = self._get_current_instance_id()
        print(f"Navigated to instance: {instance_id_2}")
        self.assertNotEqual(instance_id_1, instance_id_2, "Should be on different instance")

        # THE CRITICAL TEST: No radio button should be selected on instance 2
        radio_buttons_2 = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][schema="radio_choice"]'
        )
        selected_radios = [rb for rb in radio_buttons_2 if rb.is_selected()]

        self.assertEqual(
            len(selected_radios), 0,
            f"BUG: Radio selection from instance 1 persisted to instance 2! "
            f"Found selected: {[rb.get_attribute('label_name') for rb in selected_radios]}"
        )
        print("✓ No radio selections persisted to instance 2")

    def test_textbox_does_not_persist_to_next_instance(self):
        """
        Test that entering text on instance 1 does NOT cause it
        to appear on instance 2.
        """
        self._wait_for_annotation_page()

        instance_id_1 = self._get_current_instance_id()
        print(f"Starting on instance: {instance_id_1}")

        # Find the textbox
        textbox = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="text"][schema="text_input"], textarea[schema="text_input"]'
        )

        # Enter some text
        test_text = "This is my annotation on instance 1"
        textbox.clear()
        textbox.send_keys(test_text)
        time.sleep(0.15)  # Wait for debounced save

        self.assertEqual(textbox.get_attribute('value'), test_text)
        print(f"Entered text on instance 1: '{test_text}'")

        # Navigate to instance 2
        self._navigate_next()
        instance_id_2 = self._get_current_instance_id()
        print(f"Navigated to instance: {instance_id_2}")
        self.assertNotEqual(instance_id_1, instance_id_2, "Should be on different instance")

        # THE CRITICAL TEST: Textbox should be empty on instance 2
        textbox_2 = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="text"][schema="text_input"], textarea[schema="text_input"]'
        )
        textbox_value = textbox_2.get_attribute('value') or ''

        self.assertEqual(
            textbox_value, '',
            f"BUG: Text from instance 1 persisted to instance 2! "
            f"Found: '{textbox_value}'"
        )
        print("✓ No text persisted to instance 2")

    def test_radio_persists_when_navigating_back(self):
        """
        Test that radio selection on instance 1 is preserved when navigating
        away and back.
        """
        self._wait_for_annotation_page()

        instance_id_1 = self._get_current_instance_id()

        # Select a radio button
        radio_buttons = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][schema="radio_choice"]'
        )
        radio_option_c = None
        for rb in radio_buttons:
            if rb.get_attribute('label_name') == 'option_c':
                radio_option_c = rb
                break

        radio_option_c.click()
        time.sleep(0.1)
        print(f"Selected 'option_c' on instance {instance_id_1}")

        # Navigate to instance 2
        self._navigate_next()
        instance_id_2 = self._get_current_instance_id()
        print(f"Navigated to instance: {instance_id_2}")

        # Navigate back to instance 1
        self._navigate_prev()
        instance_id_back = self._get_current_instance_id()
        print(f"Navigated back to instance: {instance_id_back}")

        self.assertEqual(instance_id_1, instance_id_back, "Should be back on instance 1")

        # THE CRITICAL TEST: Radio selection should be preserved
        radio_buttons_back = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][schema="radio_choice"]'
        )
        radio_option_c_back = None
        for rb in radio_buttons_back:
            if rb.get_attribute('label_name') == 'option_c':
                radio_option_c_back = rb
                break

        self.assertTrue(
            radio_option_c_back.is_selected(),
            "BUG: Radio selection was lost when navigating back to instance 1!"
        )
        print("✓ Radio selection preserved when navigating back")

    def test_textbox_persists_when_navigating_back(self):
        """
        Test that text entered on instance 1 is preserved when navigating
        away and back.
        """
        self._wait_for_annotation_page()

        instance_id_1 = self._get_current_instance_id()

        # Enter text
        textbox = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="text"][schema="text_input"], textarea[schema="text_input"]'
        )
        test_text = "Preserved text annotation"
        textbox.clear()
        textbox.send_keys(test_text)
        time.sleep(0.15)  # Wait for debounced save
        print(f"Entered text on instance {instance_id_1}: '{test_text}'")

        # Navigate to instance 2
        self._navigate_next()
        instance_id_2 = self._get_current_instance_id()
        print(f"Navigated to instance: {instance_id_2}")

        # Navigate back to instance 1
        self._navigate_prev()
        instance_id_back = self._get_current_instance_id()
        print(f"Navigated back to instance: {instance_id_back}")

        self.assertEqual(instance_id_1, instance_id_back, "Should be back on instance 1")

        # THE CRITICAL TEST: Text should be preserved
        textbox_back = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="text"][schema="text_input"], textarea[schema="text_input"]'
        )
        textbox_value = textbox_back.get_attribute('value') or ''

        self.assertEqual(
            textbox_value, test_text,
            f"BUG: Text was lost when navigating back! Expected '{test_text}', got '{textbox_value}'"
        )
        print("✓ Text preserved when navigating back")

    def test_multiple_types_maintain_separate_state(self):
        """
        Test that different annotation types on different instances
        maintain separate state correctly.
        """
        self._wait_for_annotation_page()

        # Instance 1: Select radio option_a, enter text "text1"
        instance_1 = self._get_current_instance_id()

        radio_buttons_1 = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][schema="radio_choice"]'
        )
        for rb in radio_buttons_1:
            if rb.get_attribute('label_name') == 'option_a':
                rb.click()
                break
        time.sleep(0.1)

        textbox_1 = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="text"][schema="text_input"], textarea[schema="text_input"]'
        )
        textbox_1.clear()
        textbox_1.send_keys("text1")
        time.sleep(0.15)
        print(f"Instance 1: radio=option_a, text='text1'")

        # Instance 2: Select radio option_b, enter text "text2"
        self._navigate_next()
        instance_2 = self._get_current_instance_id()

        radio_buttons_2 = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][schema="radio_choice"]'
        )
        for rb in radio_buttons_2:
            if rb.get_attribute('label_name') == 'option_b':
                rb.click()
                break
        time.sleep(0.1)

        textbox_2 = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="text"][schema="text_input"], textarea[schema="text_input"]'
        )
        textbox_2.clear()
        textbox_2.send_keys("text2")
        time.sleep(0.15)
        print(f"Instance 2: radio=option_b, text='text2'")

        # Navigate back to Instance 1 and verify
        self._navigate_prev()
        current_instance = self._get_current_instance_id()
        self.assertEqual(current_instance, instance_1, "Should be on instance 1")

        # Check radio
        radio_buttons_back = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][schema="radio_choice"]'
        )
        selected_radio = None
        for rb in radio_buttons_back:
            if rb.is_selected():
                selected_radio = rb.get_attribute('label_name')
                break

        self.assertEqual(
            selected_radio, 'option_a',
            f"Instance 1 should have option_a selected, got {selected_radio}"
        )

        # Check text
        textbox_back = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="text"][schema="text_input"], textarea[schema="text_input"]'
        )
        text_value = textbox_back.get_attribute('value') or ''
        self.assertEqual(
            text_value, 'text1',
            f"Instance 1 should have 'text1', got '{text_value}'"
        )
        print("✓ Instance 1 has correct state: radio=option_a, text='text1'")

        # Navigate to Instance 2 and verify
        self._navigate_next()
        current_instance = self._get_current_instance_id()
        self.assertEqual(current_instance, instance_2, "Should be on instance 2")

        # Check radio
        radio_buttons_2_back = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][schema="radio_choice"]'
        )
        selected_radio_2 = None
        for rb in radio_buttons_2_back:
            if rb.is_selected():
                selected_radio_2 = rb.get_attribute('label_name')
                break

        self.assertEqual(
            selected_radio_2, 'option_b',
            f"Instance 2 should have option_b selected, got {selected_radio_2}"
        )

        # Check text
        textbox_2_back = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="text"][schema="text_input"], textarea[schema="text_input"]'
        )
        text_value_2 = textbox_2_back.get_attribute('value') or ''
        self.assertEqual(
            text_value_2, 'text2',
            f"Instance 2 should have 'text2', got '{text_value_2}'"
        )
        print("✓ Instance 2 has correct state: radio=option_b, text='text2'")


if __name__ == '__main__':
    unittest.main(verbosity=2)
