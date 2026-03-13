#!/usr/bin/env python3
"""
Debug test for interval-based span rendering.
"""

import time
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.selenium.test_base import BaseSeleniumTest


class TestIntervalRenderingDebug(BaseSeleniumTest):
    """Debug test for interval-based span rendering."""

    def test_debug_span_creation(self):
        """Debug test to understand span creation process."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to initialize
        WebDriverWait(self.driver, 10).until(
            lambda driver: driver.execute_script("return window.spanManager && window.spanManager.isInitialized")
        )

        print("✅ Page loaded and span manager initialized")

        # Check if span label selector exists
        try:
            span_selector = self.driver.find_element(By.ID, "span-label-selector")
            print(f"✅ Span label selector found: {span_selector.is_displayed()}")
        except Exception as e:
            print(f"❌ Span label selector not found: {e}")

        # Check if label buttons exist
        try:
            label_buttons = self.driver.find_elements(By.CSS_SELECTOR, "#label-buttons input[type='checkbox']")
            print(f"✅ Found {len(label_buttons)} label checkboxes")
            for btn in label_buttons:
                print(f"   - {btn.get_attribute('value')}: {btn.is_displayed()}")
        except Exception as e:
            print(f"❌ Label buttons not found: {e}")

        # Check what span form checkboxes exist
        try:
            span_checkboxes = self.driver.find_elements(By.CSS_SELECTOR, ".annotation-form.span input[type='checkbox']")
            print(f"✅ Found {len(span_checkboxes)} span form checkboxes")
            for checkbox in span_checkboxes:
                value = checkbox.get_attribute('value')
                id_attr = checkbox.get_attribute('id')
                print(f"   - id='{id_attr}', value='{value}': {checkbox.is_displayed()}")
        except Exception as e:
            print(f"❌ Span form checkboxes not found: {e}")

        # Try to select a label
        try:
            positive_checkbox = self.driver.find_element(By.CSS_SELECTOR, "input[type='checkbox'][value='positive']")
            positive_checkbox.click()
            print("✅ Clicked positive checkbox")
        except Exception as e:
            print(f"❌ Could not click positive checkbox: {e}")

        # Check if text content exists
        try:
            text_content = self.driver.find_element(By.ID, "text-content")
            text = text_content.text
            print(f"✅ Text content found: '{text[:50]}...'")
        except Exception as e:
            print(f"❌ Text content not found: {e}")

        # Try to create a span
        try:
            # Select text using JavaScript
            self.driver.execute_script("""
                const textContent = document.getElementById('text-content');
                const textNode = textContent.firstChild;
                const range = document.createRange();
                range.setStart(textNode, 10);
                range.setEnd(textNode, 18);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            """)
            print("✅ Text selection created")

            # Wait a moment
            time.sleep(0.1)

            # Check if span overlays were created
            span_overlays = self.driver.find_element(By.ID, "span-overlays")
            overlay_elements = span_overlays.find_elements(By.CLASS_NAME, "span-overlay-pure")
            print(f"✅ Found {len(overlay_elements)} span overlays")

            if len(overlay_elements) > 0:
                print("✅ Span creation successful!")
            else:
                print("❌ No span overlays created")

        except Exception as e:
            print(f"❌ Error during span creation: {e}")

        # Print page source for debugging
        print("\n📄 Page source snippet:")
        page_source = self.driver.page_source
        print(page_source[:1000] + "...")


if __name__ == "__main__":
    unittest.main()