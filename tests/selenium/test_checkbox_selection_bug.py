"""
Selenium test to reproduce the checkbox selection bug.

This test simulates the exact user interaction that causes checkboxes
to be unchecked immediately after being checked.
"""

import pytest
import time
import json
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from tests.selenium.test_base import BaseSeleniumTest


class TestCheckboxSelectionBug(BaseSeleniumTest):
    """Test to reproduce and verify the checkbox selection bug is fixed."""

    def setup_method(self):
        """Set up the test environment."""
        super().setup_method()

        # Create test data with span annotation scheme
        self.test_data = [
            {
                "id": "test_item_01",
                "text": "This is a happy text with some sad moments.",
                "displayed_text": "Test Item 1"
            }
        ]

        # Create config with span annotation scheme
        self.config = {
            "debug": False,
            "max_annotations_per_user": 10,
            "max_annotations_per_item": 3,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Checkbox Selection Bug Test",
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": ["test_data.jsonl"],
            "item_properties": {
                "text_key": "text",
                "id_key": "id"
            },
            "annotation_schemes": [
                {
                    "annotation_type": "span",
                    "name": "emotion",
                    "description": "Mark the emotion spans in the text.",
                    "labels": [
                        {"name": "happy", "title": "Happy"},
                        {"name": "sad", "title": "Sad"},
                        {"name": "angry", "title": "Angry"}
                    ],
                    "colors": {
                        "happy": "#FFE6E6",
                        "sad": "#E6F3FF",
                        "angry": "#FFE6CC"
                    }
                }
            ],
            "site_file": "base_template.html",
            "output_annotation_dir": "output",
            "task_dir": ".",
            "alert_time_each_instance": 0
        }

    def test_checkbox_selection_bug_reproduction(self):
        """Test to reproduce the checkbox selection bug."""
        # Start the server
        self.start_server()

        try:
            # Register a new user
            username = f"test_user_{int(time.time())}"
            self.register_user(username)

            # Navigate to the annotation page
            self.driver.get(f"http://localhost:{self.server_port}")

            # Wait for the page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "instance-text"))
            )

            # Wait for span manager to initialize
            time.sleep(2)

            # Find the span label checkboxes
            checkboxes = self.driver.find_elements(By.CSS_SELECTOR, 'input[name*="span_label"]')
            assert len(checkboxes) >= 3, f"Expected at least 3 checkboxes, found {len(checkboxes)}"

            # Get the first checkbox (happy)
            happy_checkbox = checkboxes[0]
            assert happy_checkbox.get_attribute("id") == "emotion_happy"

            # Check the initial state
            initial_checked = happy_checkbox.is_selected()
            print(f"Initial checkbox state: {initial_checked}")

            # Click the checkbox
            print("Clicking the happy checkbox...")
            happy_checkbox.click()

            # Wait a moment for any JavaScript to execute
            time.sleep(0.5)

            # Check the state after clicking
            after_click_checked = happy_checkbox.is_selected()
            print(f"Checkbox state after click: {after_click_checked}")

            # Get console logs to see what happened
            console_logs = self.driver.get_log('browser')
            relevant_logs = [log for log in console_logs if 'onlyOne' in log['message'] or 'changeSpanLabel' in log['message'] or 'checkbox' in log['message'].lower()]

            print("Relevant console logs:")
            for log in relevant_logs:
                print(f"  {log['message']}")

            # The bug is reproduced if the checkbox is unchecked after being clicked
            if not after_click_checked:
                print("❌ BUG REPRODUCED: Checkbox was unchecked after being clicked!")
                assert False, "Checkbox selection bug is still present - checkbox was unchecked after being clicked"
            else:
                print("✅ No bug detected: Checkbox remained checked after being clicked")

        finally:
            self.stop_server()

    def test_checkbox_selection_works_correctly(self):
        """Test that checkbox selection works correctly after the fix."""
        # Start the server
        self.start_server()

        try:
            # Register a new user
            username = f"test_user_{int(time.time())}"
            self.register_user(username)

            # Navigate to the annotation page
            self.driver.get(f"http://localhost:{self.server_port}")

            # Wait for the page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "instance-text"))
            )

            # Wait for span manager to initialize
            time.sleep(2)

            # Find the span label checkboxes
            checkboxes = self.driver.find_elements(By.CSS_SELECTOR, 'input[name*="span_label"]')
            assert len(checkboxes) >= 3, f"Expected at least 3 checkboxes, found {len(checkboxes)}"

            # Test each checkbox
            for i, checkbox in enumerate(checkboxes):
                print(f"Testing checkbox {i+1}: {checkbox.get_attribute('id')}")

                # Check initial state
                initial_checked = checkbox.is_selected()

                # Click the checkbox
                checkbox.click()
                time.sleep(0.5)

                # Verify it's now checked
                after_click_checked = checkbox.is_selected()
                assert after_click_checked, f"Checkbox {checkbox.get_attribute('id')} should be checked after clicking"

                # Click another checkbox to test mutual exclusivity
                if i < len(checkboxes) - 1:
                    next_checkbox = checkboxes[i + 1]
                    next_checkbox.click()
                    time.sleep(0.5)

                    # Verify the first checkbox is now unchecked
                    first_checkbox_after = checkbox.is_selected()
                    assert not first_checkbox_after, f"Checkbox {checkbox.get_attribute('id')} should be unchecked when another is selected"

                    # Verify the second checkbox is checked
                    second_checkbox_after = next_checkbox.is_selected()
                    assert second_checkbox_after, f"Checkbox {next_checkbox.get_attribute('id')} should be checked after clicking"

                print(f"✅ Checkbox {checkbox.get_attribute('id')} works correctly")

        finally:
            self.stop_server()