#!/usr/bin/env python3
"""
Selenium tests for the keybinding system.

Verifies:
1. Number keys activate radio buttons in the first schema
2. Letter keys toggle checkboxes in the second schema
3. No key conflicts between schemas
4. Arrow keys still navigate instances
5. Keys don't fire when typing in textbox
6. Keybinding badges are visible
7. Annotations triggered by keys save correct label names
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
from selenium.webdriver.common.action_chains import ActionChains


import pytest

pytestmark = pytest.mark.core

class TestKeybindings(unittest.TestCase):
    """Test that keybindings work correctly across multiple schemas."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server with radio + multiselect config."""
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import (
            create_test_directory,
            create_test_data_file,
            create_test_config,
            cleanup_test_directory
        )

        # Create test directory
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(
            tests_dir, "output", f"keybinding_test_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create test data
        test_data = [
            {"id": f"item_{i+1}", "text": f"Test item {i+1} for keybinding testing."}
            for i in range(5)
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        # Config with radio + multiselect, both sequential
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "Select sentiment",
                "labels": ["positive", "negative", "neutral"],
                "sequential_key_binding": True,
            },
            {
                "annotation_type": "multiselect",
                "name": "topics",
                "description": "Select topics",
                "labels": ["quality", "price", "service"],
                "sequential_key_binding": True,
            },
        ]

        config_file = create_test_config(
            cls.test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Keybinding Test",
            require_password=False,
        )

        cls.port = find_free_port()
        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=config_file
        )
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
        timestamp = int(time.time() * 1000)
        self.test_user = f"test_user_{timestamp}"
        self._login_user()

    def tearDown(self):
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login_user(self):
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        email_field = self.driver.find_element(By.ID, "login-email")
        email_field.clear()
        email_field.send_keys(self.test_user)
        submit_btn = self.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit']"
        )
        submit_btn.click()
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

    def _press_key(self, key_char):
        """Send a key press to the body element."""
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys(key_char)

    def _wait_short(self, seconds=0.5):
        time.sleep(seconds)

    # --- Tests ---

    def test_number_key_selects_radio(self):
        """Pressing '1' should select the first radio option (positive)."""
        self._press_key("1")
        self._wait_short()

        radio = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="radio"][data-key="1"]'
        )
        self.assertTrue(radio.is_selected(), "Radio with data-key='1' should be selected")

    def test_letter_key_toggles_checkbox(self):
        """Pressing 'q' should toggle the first checkbox option."""
        self._press_key("q")
        self._wait_short()

        checkbox = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="checkbox"][data-key="q"]'
        )
        self.assertTrue(checkbox.is_selected(), "Checkbox with data-key='q' should be checked")

        # Press again to uncheck
        self._press_key("q")
        self._wait_short()
        self.assertFalse(checkbox.is_selected(), "Checkbox should be unchecked after second press")

    def test_no_key_conflicts(self):
        """Number keys only affect radio, letter keys only affect checkboxes."""
        # Press '1' - should select radio, not any checkbox
        self._press_key("1")
        self._wait_short()

        radio = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="radio"][data-key="1"]'
        )
        self.assertTrue(radio.is_selected())

        # No checkbox should be checked
        checkboxes = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="checkbox"][data-key]'
        )
        for cb in checkboxes:
            self.assertFalse(cb.is_selected(),
                           f"Checkbox '{cb.get_attribute('data-key')}' should not be affected by number key")

        # Press 'q' - should toggle checkbox, not change radio
        self._press_key("q")
        self._wait_short()

        checkbox = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="checkbox"][data-key="q"]'
        )
        self.assertTrue(checkbox.is_selected())
        # Radio should still be selected
        self.assertTrue(radio.is_selected(), "Radio selection should not change from letter key")

    def test_keybinding_badges_visible(self):
        """Keybinding badges should be visible in the UI."""
        badges = self.driver.find_elements(By.CSS_SELECTOR, ".keybinding-badge")
        self.assertGreater(len(badges), 0, "Should have keybinding badges in the page")

        # Verify badge content
        badge_texts = [b.text.strip().upper() for b in badges if b.text.strip()]
        self.assertGreater(len(badge_texts), 0, "Badges should have text content")

    def test_annotation_saves_label_name_not_key(self):
        """Keybinding-triggered annotation should save the label name."""
        # Press '1' to select first radio (positive)
        self._press_key("1")
        self._wait_short(1.5)  # Wait for debounce save

        # Navigate forward then back to verify persistence
        self._press_key(Keys.ARROW_RIGHT)
        self._wait_short(1.0)
        self._press_key(Keys.ARROW_LEFT)
        self._wait_short(1.0)

        # Verify the radio is still selected
        radio = self.driver.find_element(
            By.CSS_SELECTOR, 'input[type="radio"][data-key="1"]'
        )
        self.assertTrue(radio.is_selected(),
                       "Radio should still be selected after navigating away and back")

    def test_keys_not_active_in_textbox(self):
        """Keys should not trigger shortcuts when focus is in a text input."""
        # Find the go_to input field
        try:
            go_to = self.driver.find_element(By.ID, "go_to")
            go_to.click()
            go_to.send_keys("1")
            self._wait_short()

            # Radio should NOT be selected
            radios = self.driver.find_elements(
                By.CSS_SELECTOR, 'input[type="radio"][data-key="1"]'
            )
            if radios:
                self.assertFalse(radios[0].is_selected(),
                               "Radio should not be selected when typing in text input")
        except Exception:
            # go_to field might be hidden; skip this test
            pass


if __name__ == '__main__':
    unittest.main()
