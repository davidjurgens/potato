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

    def test_checkbox_selection_bug_reproduction(self):
        """Test to reproduce the checkbox selection bug."""
        # Navigate to the annotation page (user is already logged in via BaseSeleniumTest.setUp)
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for the page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to initialize
        time.sleep(0.05)

        # Find the span label checkboxes
        checkboxes = self.driver.find_elements(By.CSS_SELECTOR, 'input[name*="span_label"]')

        if len(checkboxes) == 0:
            # Try alternative selector
            checkboxes = self.driver.find_elements(By.CSS_SELECTOR, '.span-label-checkbox')

        assert len(checkboxes) >= 1, f"Expected at least 1 checkbox, found {len(checkboxes)}"

        # Get the first checkbox
        first_checkbox = checkboxes[0]
        checkbox_id = first_checkbox.get_attribute("id")

        # Check the initial state
        initial_checked = first_checkbox.is_selected()
        print(f"Initial checkbox state for {checkbox_id}: {initial_checked}")

        # Click the checkbox
        print(f"Clicking checkbox {checkbox_id}...")
        first_checkbox.click()

        # Wait a moment for any JavaScript to execute
        time.sleep(0.1)

        # Check the state after clicking
        after_click_checked = first_checkbox.is_selected()
        print(f"Checkbox state after click: {after_click_checked}")

        # The bug is reproduced if the checkbox is unchecked after being clicked
        if not after_click_checked and not initial_checked:
            print("❌ BUG REPRODUCED: Checkbox was unchecked after being clicked!")
            assert False, "Checkbox selection bug is still present - checkbox was unchecked after being clicked"
        else:
            print("✅ No bug detected: Checkbox state changed correctly")

    def test_checkbox_selection_works_correctly(self):
        """Test that checkbox selection works correctly after the fix."""
        # Navigate to the annotation page (user is already logged in via BaseSeleniumTest.setUp)
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for the page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to initialize
        time.sleep(0.05)

        # Find the span label checkboxes
        checkboxes = self.driver.find_elements(By.CSS_SELECTOR, 'input[name*="span_label"]')

        if len(checkboxes) == 0:
            # Try alternative selector
            checkboxes = self.driver.find_elements(By.CSS_SELECTOR, '.span-label-checkbox')

        if len(checkboxes) == 0:
            pytest.skip("No span label checkboxes found - test not applicable for this config")

        # Test each checkbox
        for i, checkbox in enumerate(checkboxes[:3]):  # Test up to 3 checkboxes
            checkbox_id = checkbox.get_attribute('id') or f"checkbox_{i}"
            print(f"Testing checkbox {i+1}: {checkbox_id}")

            # Check initial state
            initial_checked = checkbox.is_selected()

            # Click the checkbox
            checkbox.click()
            time.sleep(0.1)

            # Verify it's now checked (or toggled if it was already checked)
            after_click_checked = checkbox.is_selected()

            if initial_checked:
                # If it was checked, it should now be unchecked
                assert not after_click_checked, f"Checkbox {checkbox_id} should be unchecked after clicking when initially checked"
            else:
                # If it was unchecked, it should now be checked
                assert after_click_checked, f"Checkbox {checkbox_id} should be checked after clicking"

            print(f"✅ Checkbox {checkbox_id} works correctly")
