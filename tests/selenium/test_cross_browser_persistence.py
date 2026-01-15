#!/usr/bin/env python3
"""
Cross-browser test for annotation persistence.

This test runs the same persistence tests on Chrome, Firefox, and Safari (if available)
to ensure consistent behavior across all major browsers.

Known browser-specific issues that have been fixed:
- Firefox: Form state restoration across page navigations
- Firefox: Instance ID mismatch after navigation
- Firefox: Span overlay cleanup timing issues
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
from selenium.webdriver.firefox.options import Options as FirefoxOptions
import pytest


class CrossBrowserTestBase:
    """Base class for cross-browser testing."""

    browser_name = None
    driver = None

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server (shared across browsers)."""
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_config,
            create_test_data_file,
            cleanup_test_directory
        )

        # Create a test directory
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(tests_dir, "output", f"cross_browser_test_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create test data
        test_data = [
            {"id": f"item_{i+1}", "text": f"Cross-browser test item {i+1} with content for testing."}
            for i in range(5)
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        # Create annotation schemes
        annotation_schemes = [
            {
                "name": "checkbox_test",
                "annotation_type": "multiselect",
                "labels": ["opt1", "opt2", "opt3"],
                "description": "Select options"
            },
            {
                "name": "radio_test",
                "annotation_type": "radio",
                "labels": ["choice_a", "choice_b"],
                "description": "Choose one"
            },
            {
                "name": "text_test",
                "annotation_type": "text",
                "description": "Enter text"
            }
        ]

        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Cross Browser Test",
            require_password=False
        )

        # Start server on a unique port for each browser
        cls.port = 9030 + hash(cls.browser_name) % 10 if cls.browser_name else 9030
        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        if not started:
            raise RuntimeError(f"Failed to start Flask server for {cls.browser_name}")
        cls.server._wait_for_server_ready(timeout=10)

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    def _create_driver(self):
        """Create a browser driver - override in subclass."""
        raise NotImplementedError

    def setUp(self):
        """Set up for each test."""
        self.driver = self._create_driver()
        timestamp = int(time.time() * 1000)
        self.test_user = f"test_{self.browser_name}_{timestamp}"
        self._login_user()

    def tearDown(self):
        """Clean up after each test."""
        if self.driver:
            self.driver.quit()

    def _login_user(self):
        """Login the test user."""
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

    def _wait_for_page(self, timeout=10):
        """Wait for annotation page to load."""
        WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.CLASS_NAME, "annotation-form"))
        )
        time.sleep(1)

    def _get_instance_id(self):
        """Get current instance ID."""
        return self.driver.find_element(By.ID, "instance_id").get_attribute("value")

    def _navigate_next(self):
        """Navigate to next instance."""
        try:
            btn = self.driver.find_element(By.ID, "next-btn")
        except:
            btn = self.driver.find_element(By.CSS_SELECTOR, 'a[onclick*="click_to_next"]')
        # Use JavaScript click for Safari reliability
        if self.browser_name == "safari":
            self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)
        else:
            btn.click()
            time.sleep(2)
        self._wait_for_page()

    def _navigate_prev(self):
        """Navigate to previous instance."""
        try:
            btn = self.driver.find_element(By.ID, "prev-btn")
        except:
            btn = self.driver.find_element(By.CSS_SELECTOR, 'a[onclick*="click_to_prev"]')
        # Use JavaScript click for Safari reliability
        if self.browser_name == "safari":
            self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)
        else:
            btn.click()
            time.sleep(2)
        self._wait_for_page()

    def _get_checked_checkboxes(self):
        """Get checked checkbox labels."""
        cbs = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"][schema="checkbox_test"]')
        return [cb.get_attribute('label_name') for cb in cbs if cb.is_selected()]

    def _get_selected_radio(self):
        """Get selected radio label."""
        radios = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="radio"][schema="radio_test"]')
        for r in radios:
            if r.is_selected():
                return r.get_attribute('label_name')
        return None

    def _get_text_value(self):
        """Get text input value."""
        txt = self.driver.find_element(By.CSS_SELECTOR, '[schema="text_test"]')
        return txt.get_attribute('value') or ''

    def _click_checkbox(self, label):
        """Click a checkbox."""
        cb = self.driver.find_element(
            By.CSS_SELECTOR, f'input[type="checkbox"][schema="checkbox_test"][label_name="{label}"]'
        )
        # Use JavaScript click for Safari reliability
        if self.browser_name == "safari":
            self.driver.execute_script("arguments[0].click();", cb)
            time.sleep(0.8)
        else:
            cb.click()
            time.sleep(0.5)

    def _click_radio(self, label):
        """Click a radio button."""
        r = self.driver.find_element(
            By.CSS_SELECTOR, f'input[type="radio"][schema="radio_test"][label_name="{label}"]'
        )
        # Use JavaScript click for Safari reliability
        if self.browser_name == "safari":
            self.driver.execute_script("arguments[0].click();", r)
            time.sleep(0.8)
        else:
            r.click()
            time.sleep(0.5)

    def _enter_text(self, text):
        """Enter text."""
        txt = self.driver.find_element(By.CSS_SELECTOR, '[schema="text_test"]')
        txt.clear()
        txt.send_keys(text)
        # Safari needs more time
        if self.browser_name == "safari":
            time.sleep(2.0)
        else:
            time.sleep(1.5)

    # ==================== TESTS ====================

    def test_checkbox_no_persist_to_next(self):
        """Checkbox shouldn't persist to next instance."""
        self._wait_for_page()
        inst1 = self._get_instance_id()

        # Check some boxes
        self._click_checkbox("opt1")
        self._click_checkbox("opt2")
        checked1 = self._get_checked_checkboxes()
        self.assertEqual(len(checked1), 2, f"[{self.browser_name}] Should have 2 checkboxes")

        # Navigate to next
        self._navigate_next()
        inst2 = self._get_instance_id()
        self.assertNotEqual(inst1, inst2)

        # Should be empty
        checked2 = self._get_checked_checkboxes()
        self.assertEqual(
            len(checked2), 0,
            f"[{self.browser_name}] BUG: Checkboxes persisted! {checked2}"
        )

    def test_checkbox_persists_on_return(self):
        """Checkbox should persist when returning."""
        self._wait_for_page()
        inst1 = self._get_instance_id()

        self._click_checkbox("opt3")
        self._navigate_next()
        self._navigate_prev()

        self.assertEqual(self._get_instance_id(), inst1)
        checked = self._get_checked_checkboxes()
        self.assertIn('opt3', checked, f"[{self.browser_name}] BUG: Checkbox not preserved!")

    def test_radio_no_persist_to_next(self):
        """Radio shouldn't persist to next instance."""
        self._wait_for_page()
        inst1 = self._get_instance_id()

        self._click_radio("choice_a")
        self.assertEqual(self._get_selected_radio(), "choice_a")

        self._navigate_next()
        inst2 = self._get_instance_id()
        self.assertNotEqual(inst1, inst2)

        selected = self._get_selected_radio()
        self.assertIsNone(
            selected,
            f"[{self.browser_name}] BUG: Radio persisted! {selected}"
        )

    def test_radio_persists_on_return(self):
        """Radio should persist when returning."""
        self._wait_for_page()
        inst1 = self._get_instance_id()

        self._click_radio("choice_b")
        self._navigate_next()
        self._navigate_prev()

        self.assertEqual(self._get_instance_id(), inst1)
        self.assertEqual(
            self._get_selected_radio(), "choice_b",
            f"[{self.browser_name}] BUG: Radio not preserved!"
        )

    def test_text_no_persist_to_next(self):
        """Text shouldn't persist to next instance."""
        self._wait_for_page()
        inst1 = self._get_instance_id()

        self._enter_text("Test text for instance 1")
        self.assertEqual(self._get_text_value(), "Test text for instance 1")

        self._navigate_next()
        inst2 = self._get_instance_id()
        self.assertNotEqual(inst1, inst2)

        text = self._get_text_value()
        self.assertEqual(
            text, '',
            f"[{self.browser_name}] BUG: Text persisted! '{text}'"
        )

    def test_text_persists_on_return(self):
        """Text should persist when returning."""
        self._wait_for_page()
        inst1 = self._get_instance_id()

        self._enter_text("Preserved text")
        self._navigate_next()
        self._navigate_prev()

        self.assertEqual(self._get_instance_id(), inst1)
        self.assertEqual(
            self._get_text_value(), "Preserved text",
            f"[{self.browser_name}] BUG: Text not preserved!"
        )

    def test_instance_id_correct_after_navigation(self):
        """Instance ID should match after navigation (Firefox-specific bug)."""
        self._wait_for_page()

        inst1 = self._get_instance_id()
        self._navigate_next()
        inst2 = self._get_instance_id()
        self._navigate_prev()
        inst_back = self._get_instance_id()

        self.assertNotEqual(inst1, inst2, f"[{self.browser_name}] Should be different instances")
        self.assertEqual(inst1, inst_back, f"[{self.browser_name}] Should return to same instance")


class TestChromeAnnotationPersistence(CrossBrowserTestBase, unittest.TestCase):
    """Chrome-specific tests."""

    browser_name = "chrome"

    def _create_driver(self):
        options = ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        return webdriver.Chrome(options=options)


class TestFirefoxAnnotationPersistence(CrossBrowserTestBase, unittest.TestCase):
    """Firefox-specific tests."""

    browser_name = "firefox"

    def _create_driver(self):
        options = FirefoxOptions()
        options.add_argument("--headless")
        return webdriver.Firefox(options=options)


class TestSafariAnnotationPersistence(CrossBrowserTestBase, unittest.TestCase):
    """Safari-specific tests - requires manual enabling of remote automation."""

    browser_name = "safari"

    def _create_driver(self):
        return webdriver.Safari()


if __name__ == '__main__':
    unittest.main(verbosity=2)
