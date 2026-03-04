#!/usr/bin/env python3
"""
Selenium tests for radio and multiselect annotation persistence bugs.

Bug: When a user selects a radio button, changes their selection, and refreshes,
the OLD (first) selection reappears. This is because:
1. handleInputChange() adds new radio selection without clearing old entry
2. syncAnnotationsFromDOM() only adds checked radios, never removes unchecked ones
3. Server stores each label independently without clearing stale radio labels

These tests verify the fix for all three defects.
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


class TestRadioMultiselectPersistence(unittest.TestCase):
    """Test that radio and multiselect annotations persist correctly after changes."""

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server with radio and multiselect annotation types."""
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory,
            create_test_config,
            create_test_data_file,
            cleanup_test_directory
        )
        from tests.helpers.port_manager import find_free_port

        # Create a test directory
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(tests_dir, "output", f"radio_multiselect_persist_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create test data with 3 items (need >1 for navigation tests)
        test_data = [
            {"id": f"item_{i+1}", "text": f"Test item {i+1} for radio/multiselect persistence testing."}
            for i in range(3)
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        # Create annotation schemes: one radio, one multiselect
        annotation_schemes = [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "Select the sentiment"
            },
            {
                "name": "topics",
                "annotation_type": "multiselect",
                "labels": ["quality", "price", "service"],
                "description": "Select all applicable topics"
            }
        ]

        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Radio Multiselect Persistence Test",
            require_password=False
        )

        # Start the server
        port = find_free_port(preferred_port=9020)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
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
        if hasattr(cls, 'test_dir'):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        """Set up for each test: create driver and login."""
        self.driver = webdriver.Chrome(options=self.chrome_options)

        # Generate unique test user
        timestamp = int(time.time() * 1000)
        self.test_user = f"test_user_{timestamp}"
        self._login_user()

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login_user(self):
        """Login with passwordless mode."""
        self.driver.get(f"{self.server.base_url}/")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )

        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(self.test_user)

        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()

        # Wait for annotation interface to load
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

    def _wait_for_save(self, seconds=2.0):
        """Wait for debounced auto-save to complete."""
        time.sleep(seconds)

    def _get_radio_state(self, schema_name):
        """Get the selected radio value for a schema, or None if nothing selected."""
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, f"input[type='radio'][schema='{schema_name}']"
        )
        for radio in radios:
            if radio.is_selected():
                return radio.get_attribute('label_name')
        return None

    def _click_radio(self, schema_name, label_name):
        """Click a specific radio button via its label (more reliable in headless mode)."""
        radio = self.driver.find_element(
            By.CSS_SELECTOR,
            f"input[type='radio'][schema='{schema_name}'][label_name='{label_name}']"
        )
        # Use the associated label for click — works even when input is styled/hidden
        radio_id = radio.get_attribute('id')
        label = self.driver.find_element(By.CSS_SELECTOR, f"label[for='{radio_id}']")
        label.click()

    def _get_checked_checkboxes(self, schema_name):
        """Get list of checked checkbox label_names for a schema."""
        checkboxes = self.driver.find_elements(
            By.CSS_SELECTOR, f"input[type='checkbox'][schema='{schema_name}']"
        )
        return [cb.get_attribute('label_name') for cb in checkboxes if cb.is_selected()]

    def _click_checkbox(self, schema_name, label_name):
        """Click a specific checkbox via its label (more reliable in headless mode)."""
        checkbox = self.driver.find_element(
            By.CSS_SELECTOR,
            f"input[type='checkbox'][schema='{schema_name}'][label_name='{label_name}']"
        )
        # Use the associated label for click — works even when input is styled/hidden
        cb_id = checkbox.get_attribute('id')
        label = self.driver.find_element(By.CSS_SELECTOR, f"label[for='{cb_id}']")
        label.click()

    def _get_current_annotations_js(self):
        """Get the currentAnnotations JS object.
        Note: currentAnnotations is declared with 'let' so it's NOT on window.
        Access it directly in the global scope."""
        return self.driver.execute_script(
            "try { return JSON.parse(JSON.stringify(currentAnnotations)); } "
            "catch(e) { return {}; }"
        )

    def _click_next(self):
        """Click the Next button."""
        next_btn = self.driver.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(1.5)

    def _click_prev(self):
        """Click the Previous button."""
        prev_btn = self.driver.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(1.5)

    # ---- Tests ----

    def test_radio_change_persists_after_navigate_away_and_back(self):
        """
        Bug reproduction: Select radio, change selection, navigate away and back.
        The UPDATED selection (not the original) should be restored.

        This is the most reliable persistence test per CLAUDE.md — avoids
        browser form-state caching that can give false positives on refresh.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        # Step 1: Select "positive"
        self._click_radio("sentiment", "positive")
        self._wait_for_save()

        # Verify "positive" is selected
        self.assertEqual(self._get_radio_state("sentiment"), "positive")

        # Step 2: Change to "negative"
        self._click_radio("sentiment", "negative")
        self._wait_for_save()

        # Verify "negative" is now selected in DOM
        self.assertEqual(self._get_radio_state("sentiment"), "negative")

        # Verify JS state only has "negative"
        annotations = self._get_current_annotations_js()
        if "sentiment" in annotations:
            self.assertNotIn("positive", annotations["sentiment"],
                             "Old radio selection should NOT be in currentAnnotations")
            self.assertIn("negative", annotations["sentiment"],
                          "New radio selection should be in currentAnnotations")

        # Step 3: Navigate away (Next) and back (Previous)
        self._click_next()
        self._click_prev()

        time.sleep(1.0)

        # Step 4: Verify "negative" is restored, "positive" is NOT selected
        selected = self._get_radio_state("sentiment")
        self.assertEqual(selected, "negative",
                         f"Expected 'negative' after nav-back, got '{selected}'")

        # Make sure "positive" is definitely not selected
        positive_radio = self.driver.find_element(
            By.CSS_SELECTOR, "input[type='radio'][schema='sentiment'][label_name='positive']"
        )
        self.assertFalse(positive_radio.is_selected(),
                         "'positive' radio should NOT be selected after changing to 'negative'")

    def test_radio_change_persists_after_full_page_reload(self):
        """
        Select radio, change selection, do a full page reload.
        The updated selection should persist.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        # Step 1: Select "positive", then change to "negative"
        self._click_radio("sentiment", "positive")
        self._wait_for_save()
        self._click_radio("sentiment", "negative")
        self._wait_for_save()

        # Step 2: Full page reload (not just refresh — navigate away entirely)
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(1.0)

        # Step 3: Verify "negative" is restored
        selected = self._get_radio_state("sentiment")
        self.assertEqual(selected, "negative",
                         f"Expected 'negative' after reload, got '{selected}'")

        # Verify "positive" is NOT selected
        positive_radio = self.driver.find_element(
            By.CSS_SELECTOR, "input[type='radio'][schema='sentiment'][label_name='positive']"
        )
        self.assertFalse(positive_radio.is_selected(),
                         "'positive' radio should NOT be selected after page reload")

    def test_multiselect_deselect_persists_after_navigate_away_and_back(self):
        """
        Check two checkboxes, uncheck one, navigate away and back.
        Only the still-checked box should remain.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        # Step 1: Check "quality" and "price"
        self._click_checkbox("topics", "quality")
        self._click_checkbox("topics", "price")
        self._wait_for_save()

        checked = self._get_checked_checkboxes("topics")
        self.assertIn("quality", checked)
        self.assertIn("price", checked)

        # Step 2: Uncheck "quality"
        self._click_checkbox("topics", "quality")
        self._wait_for_save()

        checked = self._get_checked_checkboxes("topics")
        self.assertNotIn("quality", checked)
        self.assertIn("price", checked)

        # Step 3: Navigate away and back
        self._click_next()
        self._click_prev()
        time.sleep(1.0)

        # Step 4: Verify "price" is checked, "quality" is NOT
        checked = self._get_checked_checkboxes("topics")
        self.assertIn("price", checked,
                       "'price' should still be checked after navigate-back")
        self.assertNotIn("quality", checked,
                         "'quality' should NOT be checked after uncheck + navigate-back")

    def test_radio_server_state_only_has_selected_label(self):
        """
        Rapidly change radio selection multiple times. Verify that the JS
        currentAnnotations object only contains the final selection.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        # Click through all three options
        self._click_radio("sentiment", "positive")
        time.sleep(0.3)
        self._click_radio("sentiment", "negative")
        time.sleep(0.3)
        self._click_radio("sentiment", "neutral")
        self._wait_for_save()

        # Verify JS state has exactly 1 entry for sentiment
        annotations = self._get_current_annotations_js()
        self.assertIn("sentiment", annotations,
                       "sentiment schema should exist in currentAnnotations")
        sentiment = annotations["sentiment"]
        self.assertEqual(len(sentiment), 1,
                         f"Radio schema should have exactly 1 entry, got {len(sentiment)}: {sentiment}")
        self.assertIn("neutral", sentiment,
                       "Only 'neutral' (last selection) should be in annotations")

        # Now navigate away and back to verify server persisted correctly
        self._click_next()
        self._click_prev()
        time.sleep(1.0)

        # Verify only "neutral" is selected
        selected = self._get_radio_state("sentiment")
        self.assertEqual(selected, "neutral",
                         f"Expected 'neutral' after nav-back, got '{selected}'")

        # Verify the other two are NOT selected
        for label in ["positive", "negative"]:
            radio = self.driver.find_element(
                By.CSS_SELECTOR,
                f"input[type='radio'][schema='sentiment'][label_name='{label}']"
            )
            self.assertFalse(radio.is_selected(),
                             f"'{label}' radio should NOT be selected after choosing 'neutral'")


if __name__ == '__main__':
    unittest.main()
