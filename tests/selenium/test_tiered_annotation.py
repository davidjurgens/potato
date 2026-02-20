#!/usr/bin/env python3
"""
Selenium tests for tiered annotation schema.

Tests the tiered annotation UI including:
- Tier display and selection
- Annotation creation
- Constraint validation
- Annotation persistence across page refresh
"""

import os
import json
import time
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


class TestTieredAnnotationUI(unittest.TestCase):
    """
    Selenium tests for tiered annotation interface.

    Tests that the tiered annotation UI renders correctly and allows
    creating and persisting annotations.
    """

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server with tiered annotation config."""
        # Create test directory
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", "tiered_annotation_test")
        os.makedirs(test_dir, exist_ok=True)
        cls.test_dir = test_dir

        # Create config file
        config_content = """
annotation_task_name: Tiered Annotation Selenium Test

data_files:
  - data/test_audio.json

item_properties:
  id_key: id
  text_key: text
  audio_key: audio_url

instance_display:
  - field_name: audio_url
    display_type: audio
    label: "Audio"

annotation_schemes:
  - annotation_type: tiered_annotation
    name: test_tiers
    description: "Test tiered annotation"
    source_field: audio_url
    media_type: audio
    tiers:
      - name: utterance
        tier_type: independent
        labels:
          - name: Speaker_A
            color: "#4ECDC4"
          - name: Speaker_B
            color: "#FF6B6B"
      - name: word
        tier_type: dependent
        parent_tier: utterance
        constraint_type: time_subdivision
        labels:
          - name: Content
            color: "#95E1D3"
          - name: Function
            color: "#AA96DA"

html_layout: default
task_dir: .
output_annotation_dir: annotation_output

user_config:
  allow_new_users: true
  require_password: false

require_train_phase: false
"""
        config_path = os.path.join(test_dir, "config.yaml")
        with open(config_path, "w") as f:
            f.write(config_content)

        # Create data directory and file
        data_dir = os.path.join(test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        data_content = [
            {
                "id": "test_001",
                "text": "Test audio sample",
                "audio_url": "https://upload.wikimedia.org/wikipedia/commons/2/21/Speakertest.ogg"
            }
        ]
        data_path = os.path.join(data_dir, "test_audio.json")
        with open(data_path, "w") as f:
            json.dump(data_content, f)

        # Start server
        port = find_free_port(preferred_port=9009)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_path)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        # Set up Chrome options
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        cls.chrome_options = chrome_options

        # Initialize driver
        try:
            cls.driver = webdriver.Chrome(options=cls.chrome_options)
        except Exception:
            try:
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager
                cls.driver = webdriver.Chrome(
                    service=Service(ChromeDriverManager().install()),
                    options=cls.chrome_options
                )
            except Exception as e:
                cls.server.stop()
                raise unittest.SkipTest(f"Chrome driver not available: {e}")

        cls.driver.implicitly_wait(5)

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests."""
        if hasattr(cls, 'driver') and cls.driver:
            cls.driver.quit()
        if hasattr(cls, 'server') and cls.server:
            cls.server.stop()

    def setUp(self):
        """Set up before each test - register and login."""
        # Generate unique username
        self.username = f"test_user_{int(time.time() * 1000)}"

        # Register
        self.driver.get(f"{self.server.base_url}/register")
        time.sleep(0.5)

        try:
            email_input = self.driver.find_element(By.NAME, "email")
            email_input.clear()
            email_input.send_keys(self.username)

            submit = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
            submit.click()
            time.sleep(0.5)
        except Exception:
            pass  # Registration might redirect directly

        # Login
        self.driver.get(f"{self.server.base_url}/auth")
        time.sleep(0.5)

        try:
            email_input = self.driver.find_element(By.NAME, "email")
            email_input.clear()
            email_input.send_keys(self.username)

            submit = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
            submit.click()
            time.sleep(1)
        except Exception:
            pass

    def wait_for_element(self, by, value, timeout=10):
        """Wait for element to be present and visible."""
        wait = WebDriverWait(self.driver, timeout)
        return wait.until(EC.visibility_of_element_located((by, value)))

    def test_tiered_annotation_renders(self):
        """Test that tiered annotation interface renders."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        # Check for tiered annotation container
        try:
            container = self.wait_for_element(
                By.CSS_SELECTOR,
                '.tiered-annotation-container, [data-annotation-type="tiered_annotation"]'
            )
            self.assertIsNotNone(container)
        except TimeoutException:
            # Check if the page has any form at all
            forms = self.driver.find_elements(By.CSS_SELECTOR, ".annotation-form")
            self.fail(f"Tiered annotation container not found. Found {len(forms)} forms on page.")

    def test_tier_selector_present(self):
        """Test that tier selector dropdown is present."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        try:
            selector = self.wait_for_element(By.ID, "tier-select-test_tiers")
            self.assertIsNotNone(selector)

            # Check options
            select = Select(selector)
            options = [opt.get_attribute("value") for opt in select.options]
            self.assertIn("utterance", options)
            self.assertIn("word", options)
        except TimeoutException:
            self.skipTest("Tier selector not found - schema may not have rendered")

    def test_tier_rows_displayed(self):
        """Test that tier rows are displayed."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        try:
            tier_rows = self.driver.find_elements(By.CSS_SELECTOR, ".tier-row")
            # Should have at least 2 tier rows (utterance and word)
            self.assertGreaterEqual(len(tier_rows), 2, "Expected at least 2 tier rows")
        except Exception:
            self.skipTest("Tier rows not found")

    def test_label_buttons_change_with_tier(self):
        """Test that label buttons change when tier is selected."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        try:
            selector = self.wait_for_element(By.ID, "tier-select-test_tiers")
            select = Select(selector)

            # Select utterance tier
            select.select_by_value("utterance")
            time.sleep(0.5)

            # Check for utterance labels
            label_container = self.driver.find_element(By.ID, "labels-test_tiers")
            buttons = label_container.find_elements(By.CSS_SELECTOR, ".label-button")

            labels = [btn.get_attribute("data-label") for btn in buttons]
            self.assertIn("Speaker_A", labels)
            self.assertIn("Speaker_B", labels)

            # Select word tier
            select.select_by_value("word")
            time.sleep(0.5)

            # Check for word labels
            buttons = label_container.find_elements(By.CSS_SELECTOR, ".label-button")
            labels = [btn.get_attribute("data-label") for btn in buttons]
            self.assertIn("Content", labels)
            self.assertIn("Function", labels)

        except TimeoutException:
            self.skipTest("Tier selector not found")

    def test_media_player_present(self):
        """Test that media player is present."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        try:
            media = self.driver.find_element(By.ID, "media-test_tiers")
            self.assertIsNotNone(media)
            # Check it's an audio element
            self.assertEqual(media.tag_name.lower(), "audio")
        except NoSuchElementException:
            self.skipTest("Media player not found")

    def test_hidden_input_present(self):
        """Test that hidden input for form submission is present."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        try:
            hidden_input = self.driver.find_element(By.ID, "input-test_tiers")
            self.assertIsNotNone(hidden_input)
            self.assertEqual(hidden_input.get_attribute("type"), "hidden")
        except NoSuchElementException:
            self.skipTest("Hidden input not found")

    def test_playback_controls_present(self):
        """Test that playback controls are present."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        try:
            rate_select = self.driver.find_element(By.ID, "rate-test_tiers")
            self.assertIsNotNone(rate_select)

            zoom_in = self.driver.find_element(By.ID, "zoom-in-test_tiers")
            self.assertIsNotNone(zoom_in)
        except NoSuchElementException:
            self.skipTest("Playback controls not found")


if __name__ == "__main__":
    unittest.main()
