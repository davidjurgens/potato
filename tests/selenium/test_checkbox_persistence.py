#!/usr/bin/env python3
"""
Selenium tests for checkbox persistence across instance navigation.

This test verifies that:
1. Checkbox annotations do NOT persist to other instances when navigating
2. Checkbox annotations ARE preserved when navigating back to the same instance
3. The real-time save mechanism via /updateinstance works correctly

The bug this test catches:
- Annotations from instance 1 incorrectly appearing on instance 2 after navigation
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
from selenium.webdriver.common.keys import Keys


class TestCheckboxPersistence(unittest.TestCase):
    """Test that checkbox annotations persist correctly across navigation."""

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server for all tests in this class."""
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import (
            create_test_directory,
            create_multiselect_annotation_config,
            cleanup_test_directory
        )

        # Create a test directory
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(tests_dir, "output", f"checkbox_persistence_test_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create multiselect config with 5 items (need >3 so we can navigate through
        # multiple instances without hitting "done" phase in test_multiple_instances_maintain_separate_state)
        cls.config_file, cls.data_file = create_multiselect_annotation_config(
            cls.test_dir,
            num_items=5,
            annotation_task_name="Checkbox Persistence Test",
            require_password=False
        )

        # Start the server
        cls.port = find_free_port()
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

    def _get_checked_checkboxes(self):
        """Get all checked checkboxes on the page."""
        checkboxes = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"].annotation-input')
        return [cb for cb in checkboxes if cb.is_selected()]

    def _get_checkbox_by_label(self, label_name):
        """Get a checkbox by its label name attribute."""
        return self.driver.find_element(
            By.CSS_SELECTOR,
            f'input[type="checkbox"][label_name="{label_name}"]'
        )

    def _click_checkbox(self, checkbox):
        """Click a checkbox and wait for the real-time save."""
        checkbox.click()
        # Wait for the /updateinstance call to complete
        time.sleep(0.1)

    def _navigate_next(self):
        """Navigate to the next instance."""
        # Find and click the Next button (base_template_v2 uses id="next-btn")
        try:
            next_button = self.driver.find_element(By.ID, "next-btn")
        except:
            # Fallback for base_template v1
            next_button = self.driver.find_element(By.CSS_SELECTOR, 'a[onclick*="click_to_next"]')
        next_button.click()
        # Wait for page reload
        time.sleep(0.05)
        self._wait_for_annotation_page()

    def _navigate_prev(self):
        """Navigate to the previous instance."""
        # Find and click the Previous button (base_template_v2 uses id="prev-btn")
        try:
            prev_button = self.driver.find_element(By.ID, "prev-btn")
        except:
            # Fallback for base_template v1
            prev_button = self.driver.find_element(By.CSS_SELECTOR, 'a[onclick*="click_to_prev"]')
        prev_button.click()
        # Wait for page reload
        time.sleep(0.05)
        self._wait_for_annotation_page()

    def _get_current_instance_id(self):
        """Get the current instance ID from the hidden field."""
        instance_field = self.driver.find_element(By.ID, "instance_id")
        return instance_field.get_attribute("value")

    def test_checkbox_does_not_persist_to_next_instance(self):
        """
        Test that checking a checkbox on instance 1 does NOT cause it
        to appear checked on instance 2.

        This is the main bug we're testing for.
        """
        self._wait_for_annotation_page()

        # Verify we're on instance 1
        instance_id_1 = self._get_current_instance_id()
        print(f"Starting on instance: {instance_id_1}")

        # Verify no checkboxes are checked initially
        initially_checked = self._get_checked_checkboxes()
        self.assertEqual(len(initially_checked), 0, "No checkboxes should be checked initially")

        # Check the "blue" checkbox
        blue_checkbox = self._get_checkbox_by_label("blue")
        self._click_checkbox(blue_checkbox)

        # Verify it's checked
        self.assertTrue(blue_checkbox.is_selected(), "Blue checkbox should be checked after clicking")

        # Also check "red" for good measure
        red_checkbox = self._get_checkbox_by_label("red")
        self._click_checkbox(red_checkbox)

        checked_on_instance_1 = self._get_checked_checkboxes()
        self.assertEqual(len(checked_on_instance_1), 2, "Should have 2 checkboxes checked on instance 1")
        print(f"Checked {len(checked_on_instance_1)} checkboxes on instance 1")

        # Navigate to instance 2
        self._navigate_next()

        # Verify we're on a different instance
        instance_id_2 = self._get_current_instance_id()
        print(f"Navigated to instance: {instance_id_2}")
        self.assertNotEqual(instance_id_1, instance_id_2, "Should be on a different instance")

        # THE CRITICAL TEST: No checkboxes should be checked on instance 2
        checked_on_instance_2 = self._get_checked_checkboxes()
        self.assertEqual(
            len(checked_on_instance_2), 0,
            f"BUG: Checkboxes from instance 1 persisted to instance 2! "
            f"Found {len(checked_on_instance_2)} checked: "
            f"{[cb.get_attribute('label_name') for cb in checked_on_instance_2]}"
        )
        print("✓ No checkboxes persisted to instance 2")

    def test_checkbox_persists_when_navigating_back(self):
        """
        Test that checking a checkbox on instance 1, navigating away,
        and navigating back preserves the checkbox state.
        """
        self._wait_for_annotation_page()

        # Verify we're on instance 1
        instance_id_1 = self._get_current_instance_id()
        print(f"Starting on instance: {instance_id_1}")

        # Check the "green" checkbox
        green_checkbox = self._get_checkbox_by_label("green")
        self._click_checkbox(green_checkbox)

        self.assertTrue(green_checkbox.is_selected(), "Green checkbox should be checked")
        print("Checked 'green' checkbox on instance 1")

        # Navigate to instance 2
        self._navigate_next()
        instance_id_2 = self._get_current_instance_id()
        print(f"Navigated to instance: {instance_id_2}")

        # Verify no checkboxes checked on instance 2
        checked_on_instance_2 = self._get_checked_checkboxes()
        self.assertEqual(len(checked_on_instance_2), 0, "Instance 2 should have no checkboxes checked")

        # Navigate back to instance 1
        self._navigate_prev()
        instance_id_back = self._get_current_instance_id()
        print(f"Navigated back to instance: {instance_id_back}")

        self.assertEqual(instance_id_1, instance_id_back, "Should be back on instance 1")

        # THE CRITICAL TEST: The "green" checkbox should still be checked
        green_checkbox_back = self._get_checkbox_by_label("green")
        self.assertTrue(
            green_checkbox_back.is_selected(),
            "BUG: Checkbox state was lost when navigating back to instance 1!"
        )
        print("✓ Checkbox state preserved when navigating back")

    def test_multiple_instances_maintain_separate_state(self):
        """
        Test that each instance maintains its own checkbox state independently.
        """
        self._wait_for_annotation_page()

        # Instance 1: Check "red"
        instance_1 = self._get_current_instance_id()
        red_cb = self._get_checkbox_by_label("red")
        self._click_checkbox(red_cb)
        print(f"Instance 1 ({instance_1}): Checked 'red'")

        # Navigate to Instance 2: Check "blue"
        self._navigate_next()
        instance_2 = self._get_current_instance_id()
        blue_cb = self._get_checkbox_by_label("blue")
        self._click_checkbox(blue_cb)
        print(f"Instance 2 ({instance_2}): Checked 'blue'")

        # Navigate to Instance 3: Check "green"
        self._navigate_next()
        instance_3 = self._get_current_instance_id()
        green_cb = self._get_checkbox_by_label("green")
        self._click_checkbox(green_cb)
        print(f"Instance 3 ({instance_3}): Checked 'green'")

        # Now navigate back and verify each instance has correct state

        # Back to Instance 2
        self._navigate_prev()
        checked = self._get_checked_checkboxes()
        checked_labels = [cb.get_attribute('label_name') for cb in checked]
        self.assertEqual(checked_labels, ['blue'], f"Instance 2 should only have 'blue', got {checked_labels}")
        print("✓ Instance 2 has correct state: ['blue']")

        # Back to Instance 1
        self._navigate_prev()
        checked = self._get_checked_checkboxes()
        checked_labels = [cb.get_attribute('label_name') for cb in checked]
        self.assertEqual(checked_labels, ['red'], f"Instance 1 should only have 'red', got {checked_labels}")
        print("✓ Instance 1 has correct state: ['red']")

        # Forward to Instance 3
        self._navigate_next()
        self._navigate_next()
        checked = self._get_checked_checkboxes()
        checked_labels = [cb.get_attribute('label_name') for cb in checked]
        self.assertEqual(checked_labels, ['green'], f"Instance 3 should only have 'green', got {checked_labels}")
        print("✓ Instance 3 has correct state: ['green']")


if __name__ == '__main__':
    unittest.main(verbosity=2)
