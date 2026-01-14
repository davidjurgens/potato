#!/usr/bin/env python3
"""
Firefox-specific test for checkbox persistence bug.
"""

import time
import unittest
import os
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options as FirefoxOptions


class TestCheckboxPersistenceFirefox(unittest.TestCase):
    """Test checkbox persistence in Firefox."""

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server."""
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_multiselect_annotation_config,
            cleanup_test_directory
        )

        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(tests_dir, "output", f"firefox_checkbox_test_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.config_file, cls.data_file = create_multiselect_annotation_config(
            cls.test_dir,
            num_items=5,
            annotation_task_name="Firefox Checkbox Test",
            require_password=False
        )

        cls.server = FlaskTestServer(port=9024, debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        # Firefox options
        cls.firefox_options = FirefoxOptions()
        cls.firefox_options.add_argument("--headless")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Firefox(options=self.firefox_options)
        timestamp = int(time.time() * 1000)
        self.test_user = f"test_user_ff_{timestamp}"
        self._login_user()

    def tearDown(self):
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login_user(self):
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

    def _wait_for_annotation_page(self, timeout=10):
        WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.CLASS_NAME, "annotation-form"))
        )
        time.sleep(1)

    def _get_checked_checkboxes(self):
        checkboxes = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"].annotation-input')
        return [cb for cb in checkboxes if cb.is_selected()]

    def _get_checkbox_by_label(self, label_name):
        return self.driver.find_element(
            By.CSS_SELECTOR,
            f'input[type="checkbox"][label_name="{label_name}"]'
        )

    def _click_checkbox(self, checkbox):
        checkbox.click()
        time.sleep(0.5)

    def _navigate_next(self):
        try:
            next_button = self.driver.find_element(By.ID, "next-btn")
        except:
            next_button = self.driver.find_element(By.CSS_SELECTOR, 'a[onclick*="click_to_next"]')
        next_button.click()
        time.sleep(2)
        self._wait_for_annotation_page()

    def _navigate_prev(self):
        try:
            prev_button = self.driver.find_element(By.ID, "prev-btn")
        except:
            prev_button = self.driver.find_element(By.CSS_SELECTOR, 'a[onclick*="click_to_prev"]')
        prev_button.click()
        time.sleep(2)
        self._wait_for_annotation_page()

    def _get_current_instance_id(self):
        instance_field = self.driver.find_element(By.ID, "instance_id")
        return instance_field.get_attribute("value")

    def test_checkbox_does_not_persist_to_next_instance_firefox(self):
        """Test that checkboxes don't persist to next instance in Firefox."""
        self._wait_for_annotation_page()

        instance_id_1 = self._get_current_instance_id()
        print(f"[Firefox] Starting on instance: {instance_id_1}")

        # Verify no checkboxes initially checked
        initially_checked = self._get_checked_checkboxes()
        self.assertEqual(len(initially_checked), 0, "No checkboxes should be checked initially")

        # Check blue and red
        blue_checkbox = self._get_checkbox_by_label("blue")
        self._click_checkbox(blue_checkbox)
        red_checkbox = self._get_checkbox_by_label("red")
        self._click_checkbox(red_checkbox)

        checked_on_instance_1 = self._get_checked_checkboxes()
        self.assertEqual(len(checked_on_instance_1), 2)
        print(f"[Firefox] Checked 2 checkboxes on instance 1")

        # Navigate to instance 2
        self._navigate_next()

        instance_id_2 = self._get_current_instance_id()
        print(f"[Firefox] Navigated to instance: {instance_id_2}")
        self.assertNotEqual(instance_id_1, instance_id_2)

        # CRITICAL: No checkboxes should be checked
        checked_on_instance_2 = self._get_checked_checkboxes()

        # Debug: print page state
        print(f"[Firefox] Checked checkboxes on instance 2: {[cb.get_attribute('label_name') for cb in checked_on_instance_2]}")

        # Also check raw DOM state
        all_checkboxes = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
        for cb in all_checkboxes:
            label = cb.get_attribute('label_name')
            checked = cb.is_selected()
            checked_attr = cb.get_attribute('checked')
            print(f"[Firefox DEBUG] Checkbox {label}: is_selected={checked}, checked_attr={checked_attr}")

        self.assertEqual(
            len(checked_on_instance_2), 0,
            f"BUG: Checkboxes from instance 1 persisted to instance 2! "
            f"Found {len(checked_on_instance_2)} checked: "
            f"{[cb.get_attribute('label_name') for cb in checked_on_instance_2]}"
        )
        print("[Firefox] ✓ No checkboxes persisted to instance 2")

    def test_checkbox_persists_when_navigating_back_firefox(self):
        """Test that checkboxes persist when navigating back in Firefox."""
        self._wait_for_annotation_page()

        instance_id_1 = self._get_current_instance_id()
        print(f"[Firefox] Starting on instance: {instance_id_1}")

        # Check green
        green_checkbox = self._get_checkbox_by_label("green")
        self._click_checkbox(green_checkbox)
        print("[Firefox] Checked 'green' checkbox on instance 1")

        # Navigate to instance 2
        self._navigate_next()
        instance_id_2 = self._get_current_instance_id()
        print(f"[Firefox] Navigated to instance: {instance_id_2}")

        # Navigate back to instance 1
        self._navigate_prev()
        instance_id_back = self._get_current_instance_id()
        print(f"[Firefox] Navigated back to instance: {instance_id_back}")

        self.assertEqual(instance_id_1, instance_id_back)

        # Green should still be checked
        green_checkbox_back = self._get_checkbox_by_label("green")
        self.assertTrue(
            green_checkbox_back.is_selected(),
            "BUG: Checkbox state was lost when navigating back!"
        )
        print("[Firefox] ✓ Checkbox state preserved when navigating back")


if __name__ == '__main__':
    unittest.main(verbosity=2)
