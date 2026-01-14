#!/usr/bin/env python3
"""
Selenium tests for annotation persistence across navigation round-trips.

This test specifically covers the bug where loadAnnotations() was clearing
server-rendered checkbox states when navigating back to a previously annotated
instance.

The bug scenario:
1. User annotates instance 1 (checks some checkboxes)
2. User navigates to instance 2 (navigation saves annotations)
3. User navigates back to instance 1
4. Server renders page with checked attributes from saved annotations
5. BUG: loadAnnotations() was calling clearAllFormInputs() which wiped server state
6. FIX: loadAnnotations() now reads state from DOM instead of clearing it

This test ensures the fix works correctly.
"""

import os
import time
import unittest
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_config, create_test_data_file


def create_multiselect_annotation_config(test_dir: str, num_instances: int = 3, **kwargs):
    """
    Create a test configuration with multiselect (checkbox) annotation.

    Args:
        test_dir: Directory to create the config in
        num_instances: Number of test instances to create
        **kwargs: Additional config options

    Returns:
        Tuple of (config_file_path, data_file_path)
    """
    # Create test data with multiple instances
    test_data = [
        {"id": str(i), "text": f"Test instance {i} for checkbox annotation persistence testing."}
        for i in range(1, num_instances + 1)
    ]

    data_file = create_test_data_file(test_dir, test_data)

    # Create multiselect (checkbox) annotation scheme
    annotation_schemes = [
        {
            "name": "test_colors",
            "annotation_type": "multiselect",
            "labels": ["red", "green", "blue", "yellow"],
            "description": "Select all colors that apply",
            "sequential_key_binding": True
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        **kwargs
    )

    return config_file, data_file


def create_radio_annotation_config(test_dir: str, num_instances: int = 3, **kwargs):
    """
    Create a test configuration with radio button annotation.

    Args:
        test_dir: Directory to create the config in
        num_instances: Number of test instances to create
        **kwargs: Additional config options

    Returns:
        Tuple of (config_file_path, data_file_path)
    """
    # Create test data with multiple instances
    test_data = [
        {"id": str(i), "text": f"Test instance {i} for radio button persistence testing."}
        for i in range(1, num_instances + 1)
    ]

    data_file = create_test_data_file(test_dir, test_data)

    # Create radio button annotation scheme
    annotation_schemes = [
        {
            "name": "sentiment",
            "annotation_type": "radio",
            "labels": ["positive", "neutral", "negative"],
            "description": "Select the sentiment",
            "sequential_key_binding": True
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        **kwargs
    )

    return config_file, data_file


class TestAnnotationPersistenceRoundtrip(unittest.TestCase):
    """
    Tests for annotation persistence when navigating away and back.

    These tests specifically target the bug where server-rendered checkbox
    states were being cleared by JavaScript on page load.
    """

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server for all tests."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", "annotation_persistence_roundtrip")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create multiselect config with 3 instances
        cls.config_file, cls.data_file = create_multiselect_annotation_config(
            cls.test_dir,
            num_instances=3,
            annotation_task_name="Annotation Persistence Roundtrip Test",
            require_password=False
        )

        cls.server = FlaskTestServer(port=9020, debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options
        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        timestamp = int(time.time())
        self.test_user = f"test_persistence_{timestamp}"
        self._register_and_login()

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _register_and_login(self):
        """Register and login a test user."""
        self.driver.get(f"{self.server.base_url}/")

        # Wait for login page
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-tab"))
        )

        # Switch to registration
        register_tab = self.driver.find_element(By.ID, "register-tab")
        register_tab.click()

        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "register-content"))
        )

        # Fill registration form
        username_field = self.driver.find_element(By.ID, "register-email")
        password_field = self.driver.find_element(By.ID, "register-pass")
        username_field.send_keys(self.test_user)
        password_field.send_keys("test_password")

        register_form = self.driver.find_element(By.CSS_SELECTOR, "#register-content form")
        register_form.submit()

        # Wait for annotation page to load
        time.sleep(2)
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "main-content"))
        )

    def _wait_for_page_ready(self):
        """Wait for the annotation page to be fully loaded."""
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "main-content"))
        )
        # Wait for checkboxes to be present
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='checkbox']"))
        )
        time.sleep(0.5)  # Allow JS to initialize

    def _get_checkbox_states(self):
        """Get the checked state of all checkboxes."""
        checkboxes = self.driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        states = {}
        for cb in checkboxes:
            label = cb.get_attribute("label_name") or cb.get_attribute("value")
            states[label] = cb.is_selected()
        return states

    def _click_checkbox(self, value):
        """Click a checkbox with the given value."""
        checkbox = self.driver.find_element(By.CSS_SELECTOR, f"input[type='checkbox'][value='{value}']")
        # Scroll into view
        self.driver.execute_script("arguments[0].scrollIntoView(true);", checkbox)
        time.sleep(0.1)
        checkbox.click()
        time.sleep(0.3)  # Allow state to update

    def _navigate_next(self):
        """Navigate to the next instance using keyboard."""
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ARROW_RIGHT)
        time.sleep(1)  # Wait for navigation and page reload
        self._wait_for_page_ready()

    def _navigate_prev(self):
        """Navigate to the previous instance using keyboard."""
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ARROW_LEFT)
        time.sleep(1)  # Wait for navigation and page reload
        self._wait_for_page_ready()

    def test_checkbox_persistence_after_navigation_roundtrip(self):
        """
        Test that checkbox annotations persist after navigating away and back.

        This is the primary test for the bug fix where loadAnnotations() was
        clearing server-rendered checkbox states.

        Steps:
        1. On instance 1, check some checkboxes
        2. Navigate to instance 2
        3. Navigate back to instance 1
        4. Verify the checkboxes are still checked
        """
        self._wait_for_page_ready()

        # Verify we start on instance 1
        instance_id = self.driver.find_element(By.ID, "instance_id").get_attribute("value")
        self.assertEqual(instance_id, "1", "Should start on instance 1")

        # Check some checkboxes on instance 1
        self._click_checkbox("1")  # "red" (value "1" with sequential keybinding)
        self._click_checkbox("3")  # "blue" (value "3")

        # Verify checkboxes are checked
        states_before = self._get_checkbox_states()
        self.assertTrue(states_before.get("red", False), "Red should be checked before navigation")
        self.assertTrue(states_before.get("blue", False), "Blue should be checked before navigation")
        self.assertFalse(states_before.get("green", True), "Green should NOT be checked")

        # Navigate to instance 2
        self._navigate_next()

        # Verify we're on instance 2
        instance_id = self.driver.find_element(By.ID, "instance_id").get_attribute("value")
        self.assertEqual(instance_id, "2", "Should be on instance 2 after navigation")

        # Navigate back to instance 1
        self._navigate_prev()

        # Verify we're back on instance 1
        instance_id = self.driver.find_element(By.ID, "instance_id").get_attribute("value")
        self.assertEqual(instance_id, "1", "Should be back on instance 1")

        # THE KEY TEST: Verify checkboxes are still checked after roundtrip
        states_after = self._get_checkbox_states()
        self.assertTrue(
            states_after.get("red", False),
            "Red should still be checked after navigation roundtrip - this tests the loadAnnotations() fix"
        )
        self.assertTrue(
            states_after.get("blue", False),
            "Blue should still be checked after navigation roundtrip - this tests the loadAnnotations() fix"
        )
        self.assertFalse(
            states_after.get("green", True),
            "Green should still NOT be checked after navigation roundtrip"
        )

    def test_multiple_navigation_roundtrips(self):
        """
        Test that annotations persist through multiple navigation roundtrips.
        """
        self._wait_for_page_ready()

        # Check checkboxes on instance 1
        self._click_checkbox("1")  # red
        self._click_checkbox("2")  # green

        # Navigate to instance 2, then instance 3
        self._navigate_next()
        self._navigate_next()

        # Navigate all the way back to instance 1
        self._navigate_prev()
        self._navigate_prev()

        # Verify checkboxes are still checked
        states = self._get_checkbox_states()
        self.assertTrue(states.get("red", False), "Red should persist through multiple roundtrips")
        self.assertTrue(states.get("green", False), "Green should persist through multiple roundtrips")

    def test_different_annotations_on_different_instances(self):
        """
        Test that different instances maintain their own annotation states.
        """
        self._wait_for_page_ready()

        # Annotate instance 1: red and blue
        self._click_checkbox("1")  # red
        self._click_checkbox("3")  # blue

        # Navigate to instance 2 and annotate: green and yellow
        self._navigate_next()
        self._click_checkbox("2")  # green
        self._click_checkbox("4")  # yellow

        # Navigate back to instance 1 and verify its state
        self._navigate_prev()
        states_1 = self._get_checkbox_states()
        self.assertTrue(states_1.get("red", False), "Instance 1 should have red checked")
        self.assertTrue(states_1.get("blue", False), "Instance 1 should have blue checked")
        self.assertFalse(states_1.get("green", True), "Instance 1 should NOT have green checked")
        self.assertFalse(states_1.get("yellow", True), "Instance 1 should NOT have yellow checked")

        # Navigate to instance 2 and verify its state
        self._navigate_next()
        states_2 = self._get_checkbox_states()
        self.assertFalse(states_2.get("red", True), "Instance 2 should NOT have red checked")
        self.assertFalse(states_2.get("blue", True), "Instance 2 should NOT have blue checked")
        self.assertTrue(states_2.get("green", False), "Instance 2 should have green checked")
        self.assertTrue(states_2.get("yellow", False), "Instance 2 should have yellow checked")

    def test_keybinding_annotations_persist(self):
        """
        Test that annotations made via keyboard shortcuts persist.
        """
        self._wait_for_page_ready()

        # Use keyboard shortcuts to select checkboxes
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys("1")  # Select red
        time.sleep(0.3)
        body.send_keys("3")  # Select blue
        time.sleep(0.3)

        # Navigate away and back
        self._navigate_next()
        self._navigate_prev()

        # Verify keybinding-selected checkboxes persist
        states = self._get_checkbox_states()
        self.assertTrue(states.get("red", False), "Keybinding-selected red should persist")
        self.assertTrue(states.get("blue", False), "Keybinding-selected blue should persist")


class TestRadioButtonPersistenceRoundtrip(unittest.TestCase):
    """
    Tests for radio button annotation persistence across navigation.
    """

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server for radio button tests."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", "radio_persistence_roundtrip")
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.config_file, cls.data_file = create_radio_annotation_config(
            cls.test_dir,
            num_instances=3,
            annotation_task_name="Radio Persistence Roundtrip Test",
            require_password=False
        )

        cls.server = FlaskTestServer(port=9021, debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        timestamp = int(time.time())
        self.test_user = f"test_radio_{timestamp}"
        self._register_and_login()

    def tearDown(self):
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _register_and_login(self):
        """Register and login a test user."""
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-tab"))
        )

        register_tab = self.driver.find_element(By.ID, "register-tab")
        register_tab.click()
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "register-content"))
        )

        username_field = self.driver.find_element(By.ID, "register-email")
        password_field = self.driver.find_element(By.ID, "register-pass")
        username_field.send_keys(self.test_user)
        password_field.send_keys("test_password")

        register_form = self.driver.find_element(By.CSS_SELECTOR, "#register-content form")
        register_form.submit()

        time.sleep(2)
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "main-content"))
        )

    def _wait_for_page_ready(self):
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "main-content"))
        )
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='radio']"))
        )
        time.sleep(0.5)

    def _get_selected_radio(self):
        """Get the value of the currently selected radio button."""
        radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        for radio in radios:
            if radio.is_selected():
                return radio.get_attribute("label_name") or radio.get_attribute("value")
        return None

    def _click_radio(self, value):
        """Click a radio button with the given value."""
        radio = self.driver.find_element(By.CSS_SELECTOR, f"input[type='radio'][value='{value}']")
        self.driver.execute_script("arguments[0].scrollIntoView(true);", radio)
        time.sleep(0.1)
        radio.click()
        time.sleep(0.3)

    def _navigate_next(self):
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ARROW_RIGHT)
        time.sleep(1)
        self._wait_for_page_ready()

    def _navigate_prev(self):
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ARROW_LEFT)
        time.sleep(1)
        self._wait_for_page_ready()

    def test_radio_persistence_after_navigation_roundtrip(self):
        """
        Test that radio button selection persists after navigating away and back.
        """
        self._wait_for_page_ready()

        # Select "positive" on instance 1
        self._click_radio("1")  # positive

        # Verify selection
        selected_before = self._get_selected_radio()
        self.assertEqual(selected_before, "positive", "Should have positive selected before navigation")

        # Navigate to instance 2 and back
        self._navigate_next()
        self._navigate_prev()

        # Verify selection persists
        selected_after = self._get_selected_radio()
        self.assertEqual(
            selected_after, "positive",
            "Radio selection should persist after navigation roundtrip"
        )

    def test_different_radio_selections_on_different_instances(self):
        """
        Test that different instances maintain their own radio selections.
        """
        self._wait_for_page_ready()

        # Select "positive" on instance 1
        self._click_radio("1")  # positive

        # Navigate to instance 2 and select "negative"
        self._navigate_next()
        self._click_radio("3")  # negative

        # Navigate back to instance 1 and verify
        self._navigate_prev()
        self.assertEqual(self._get_selected_radio(), "positive", "Instance 1 should have positive")

        # Navigate to instance 2 and verify
        self._navigate_next()
        self.assertEqual(self._get_selected_radio(), "negative", "Instance 2 should have negative")


if __name__ == "__main__":
    unittest.main()
