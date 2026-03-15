"""
Selenium tests for client-side required annotation validation UX.
"""
import os
import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)
from tests.helpers.port_manager import find_free_port


class TestRequiredValidationUI(unittest.TestCase):
    """Test client-side required annotation validation UX."""

    @classmethod
    def setUpClass(cls):
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_options

        # Create test config with required annotation
        cls.test_dir = create_test_directory("req_validation_ui")
        data = [
            {"id": "1", "text": "First item"},
            {"id": "2", "text": "Second item"},
        ]
        create_test_data_file(cls.test_dir, data)
        cls.config_path = create_test_config(
            cls.test_dir,
            [
                {
                    "annotation_type": "radio",
                    "name": "required_q",
                    "labels": ["yes", "no"],
                    "description": "Required question",
                    "required": True,
                },
            ],
        )
        port = find_free_port()
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_path)
        started = cls.server.start_server()
        assert started, "Failed to start server"
        cls.server._wait_for_server_ready(timeout=10)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        cleanup_test_directory(cls.test_dir)

    def _make_driver_and_login(self):
        driver = webdriver.Chrome(options=self.chrome_options)
        driver.get(f"{self.server.base_url}/")
        time.sleep(0.5)
        try:
            email_input = driver.find_element(By.NAME, "email")
            email_input.send_keys(f"valui_user_{int(time.time())}")
            try:
                pass_input = driver.find_element(By.NAME, "pass")
                pass_input.send_keys("password123")
            except Exception:
                pass
            submit = driver.find_element(
                By.CSS_SELECTOR, "button[type='submit'], input[type='submit']"
            )
            submit.click()
            time.sleep(1)
        except Exception:
            pass
        return driver

    def test_no_error_on_initial_load(self):
        """Error messages should not be visible on initial page load."""
        driver = self._make_driver_and_login()
        try:
            driver.get(f"{self.server.base_url}/annotate")
            time.sleep(1)

            # Error div should not be visible
            error_divs = driver.find_elements(By.ID, "required-fields-error")
            if error_divs:
                self.assertNotEqual(
                    error_divs[0].value_of_css_property("display"),
                    "block",
                    "Error should not be visible on initial load",
                )

            # No required-unfilled class on forms
            unfilled = driver.find_elements(By.CSS_SELECTOR, ".required-unfilled")
            self.assertEqual(len(unfilled), 0, "No forms should be marked unfilled initially")
        finally:
            driver.quit()

    def test_error_shown_after_next_click(self):
        """Clicking Next without filling required fields should show error."""
        driver = self._make_driver_and_login()
        try:
            driver.get(f"{self.server.base_url}/annotate")
            time.sleep(1)

            # Click Next without annotating
            next_btn = driver.find_element(By.ID, "next-btn")
            next_btn.click()
            time.sleep(1)

            # Error should now be visible
            error_div = driver.find_element(By.ID, "required-fields-error")
            self.assertEqual(
                error_div.value_of_css_property("display"),
                "block",
                "Error should be visible after clicking Next without annotation",
            )
        finally:
            driver.quit()

    def test_navigation_works_when_filled(self):
        """Navigation should succeed after filling required fields."""
        driver = self._make_driver_and_login()
        try:
            driver.get(f"{self.server.base_url}/annotate")
            time.sleep(1)

            # Click a radio button to fill the required field
            radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            self.assertTrue(len(radios) > 0, "Should find radio buttons")
            radios[0].click()
            time.sleep(0.5)

            # Click Next — should navigate (page reload)
            next_btn = driver.find_element(By.ID, "next-btn")
            next_btn.click()
            time.sleep(2)

            # After successful navigation, the page should have reloaded
            # and error div should not be visible
            error_divs = driver.find_elements(By.ID, "required-fields-error")
            if error_divs:
                display = error_divs[0].value_of_css_property("display")
                self.assertNotEqual(display, "block", "Error should not show after successful navigation")
        finally:
            driver.quit()


if __name__ == "__main__":
    unittest.main()
