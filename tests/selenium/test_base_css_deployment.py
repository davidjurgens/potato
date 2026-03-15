"""
Selenium tests verifying that base_css is deployed correctly in the browser.
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


class TestBaseCssDeployment(unittest.TestCase):
    """Verify base_css is injected and applied in the browser."""

    @classmethod
    def setUpClass(cls):
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_options

    def _start_server(self, test_dir, config_path):
        port = find_free_port()
        server = FlaskTestServer(port=port, debug=False, config_file=config_path)
        started = server.start_server()
        self.assertTrue(started, "Failed to start server")
        server._wait_for_server_ready(timeout=10)
        return server

    def _make_driver_and_login(self, server):
        driver = webdriver.Chrome(options=self.chrome_options)
        driver.get(f"{server.base_url}/")
        time.sleep(0.5)
        try:
            email_input = driver.find_element(By.NAME, "email")
            email_input.send_keys(f"css_test_user_{int(time.time())}")
            # Try to find password field (may not exist)
            try:
                pass_input = driver.find_element(By.NAME, "pass")
                pass_input.send_keys("password123")
            except Exception:
                pass
            # Submit
            submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
            submit.click()
            time.sleep(1)
        except Exception:
            pass
        return driver

    def test_base_css_style_tag_present(self):
        """Verify <style id='potato-project-base-css'> exists in DOM when configured."""
        test_dir = create_test_directory("css_tag_test")
        try:
            # Write a CSS file
            css_path = os.path.join(test_dir, "project.css")
            with open(css_path, "w") as f:
                f.write("body { font-family: monospace; }")

            # Create test data and config with base_css
            data = [{"id": "1", "text": "Test item"}]
            create_test_data_file(test_dir, data)
            config_path = create_test_config(
                test_dir,
                [{"annotation_type": "radio", "name": "test", "labels": ["a", "b"], "description": "Test"}],
                additional_config={"base_css": css_path},
            )

            server = self._start_server(test_dir, config_path)
            driver = self._make_driver_and_login(server)

            try:
                driver.get(f"{server.base_url}/annotate")
                time.sleep(1)

                style_tag = driver.find_elements(By.ID, "potato-project-base-css")
                self.assertTrue(len(style_tag) > 0, "Expected potato-project-base-css style tag in DOM")
                self.assertIn("font-family: monospace", style_tag[0].get_attribute("innerHTML"))
            finally:
                driver.quit()
                server.stop_server()
        finally:
            cleanup_test_directory(test_dir)

    def test_base_css_styles_applied(self):
        """Verify custom CSS rules actually apply (computed style check)."""
        test_dir = create_test_directory("css_applied_test")
        try:
            css_path = os.path.join(test_dir, "project.css")
            with open(css_path, "w") as f:
                f.write("body { background-color: rgb(255, 200, 200) !important; }")

            data = [{"id": "1", "text": "Test item"}]
            create_test_data_file(test_dir, data)
            config_path = create_test_config(
                test_dir,
                [{"annotation_type": "radio", "name": "test", "labels": ["a", "b"], "description": "Test"}],
                additional_config={"base_css": css_path},
            )

            server = self._start_server(test_dir, config_path)
            driver = self._make_driver_and_login(server)

            try:
                driver.get(f"{server.base_url}/annotate")
                time.sleep(1)

                bg_color = driver.execute_script(
                    "return window.getComputedStyle(document.body).backgroundColor;"
                )
                self.assertEqual(
                    bg_color,
                    "rgb(255, 200, 200)",
                    f"Expected pink background from base_css, got {bg_color}",
                )
            finally:
                driver.quit()
                server.stop_server()
        finally:
            cleanup_test_directory(test_dir)

    def test_no_base_css_no_extra_style_tag(self):
        """Without base_css configured, no potato-project-base-css tag should exist."""
        test_dir = create_test_directory("css_absent_test")
        try:
            data = [{"id": "1", "text": "Test item"}]
            create_test_data_file(test_dir, data)
            config_path = create_test_config(
                test_dir,
                [{"annotation_type": "radio", "name": "test", "labels": ["a", "b"], "description": "Test"}],
            )

            server = self._start_server(test_dir, config_path)
            driver = self._make_driver_and_login(server)

            try:
                driver.get(f"{server.base_url}/annotate")
                time.sleep(1)

                style_tags = driver.find_elements(By.ID, "potato-project-base-css")
                self.assertEqual(len(style_tags), 0, "No base_css tag should be present when not configured")
            finally:
                driver.quit()
                server.stop_server()
        finally:
            cleanup_test_directory(test_dir)


if __name__ == "__main__":
    unittest.main()
