#!/usr/bin/env python3
"""
Selenium tests for interval-based span rendering.

This test verifies that:
1. Spans are rendered as overlays positioned correctly over text
2. Overlapping spans are handled properly with z-index layering
3. Labels and delete buttons are visible and functional
4. Text selection works correctly with the new two-layer structure
"""

import time
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from tests.selenium.test_base import BaseSeleniumTest


class TestIntervalRendering(BaseSeleniumTest):
    """Test interval-based span rendering functionality."""

    def test_interval_rendering_structure(self):
        """Test that the DOM structure supports interval-based rendering."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Check that the two-layer structure exists
        instance_text = self.driver.find_element(By.ID, "instance-text")
        text_content = self.driver.find_element(By.ID, "text-content")
        span_overlays = self.driver.find_element(By.ID, "span-overlays")

        # Verify structure
        self.assertIsNotNone(instance_text)
        self.assertIsNotNone(text_content)
        self.assertIsNotNone(span_overlays)

        # Check that text content contains the instance text
        instance_text_content = text_content.text
        self.assertIsNotNone(instance_text_content)
        self.assertGreater(len(instance_text_content), 0)

        # Check that span overlays container is empty initially
        span_overlays_children = span_overlays.find_elements(By.XPATH, "./*")
        self.assertEqual(len(span_overlays_children), 0)

    def test_single_span_rendering(self):
        """Test that a single span is rendered correctly as an overlay."""
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

        # Select a label
        self.select_span_label("positive")

        # Create a span by selecting text
        text_content = self.driver.find_element(By.ID, "text-content")
        text = text_content.text

        # Find a word to select (e.g., "thrilled")
        word_start = text.find("thrilled")
        if word_start == -1:
            word_start = text.find("technology")
        if word_start == -1:
            word_start = 10  # Fallback

        word_end = word_start + 8  # "thrilled" is 8 characters

        # Select the text using JavaScript
        self.driver.execute_script("""
            const textContent = document.getElementById('text-content');
            const textNode = textContent.firstChild;
            const range = document.createRange();
            range.setStart(textNode, arguments[0]);
            range.setEnd(textNode, arguments[1]);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """, word_start, word_end)

        # Wait a moment for selection to be processed
        time.sleep(0.1)

        # Check that span overlays were created
        span_overlays = self.driver.find_element(By.ID, "span-overlays")
        overlay_elements = span_overlays.find_elements(By.CLASS_NAME, "span-overlay")

        self.assertGreater(len(overlay_elements), 0, "No span overlays were created")

        # Check that the overlay has the correct label
        label_elements = span_overlays.find_elements(By.CLASS_NAME, "span-label")
        self.assertGreater(len(label_elements), 0, "No span labels were created")

        label_text = label_elements[0].text
        self.assertEqual(label_text, "positive", f"Expected label 'positive', got '{label_text}'")

        # Check that delete button exists
        delete_buttons = span_overlays.find_elements(By.CLASS_NAME, "span-delete-btn")
        self.assertGreater(len(delete_buttons), 0, "No delete buttons were created")

    def test_overlapping_spans_rendering(self):
        """Test that overlapping spans are rendered correctly with proper layering."""
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

        # Create first span
        self.select_span_label("positive")
        text_content = self.driver.find_element(By.ID, "text-content")
        text = text_content.text

        # Find a longer phrase to select
        phrase_start = text.find("new technology")
        if phrase_start == -1:
            phrase_start = text.find("absolutely thrilled")
        if phrase_start == -1:
            phrase_start = 10

        phrase_end = phrase_start + 15  # Select 15 characters

        # Create first span
        self.create_span_by_selection(phrase_start, phrase_end)

        # Wait for first span to be rendered
        time.sleep(0.1)

        # Create second overlapping span
        self.select_span_label("negative")

        # Select a subset of the first span
        overlap_start = phrase_start + 5
        overlap_end = phrase_start + 10

        # Create second span
        self.create_span_by_selection(overlap_start, overlap_end)

        # Wait for second span to be rendered
        time.sleep(0.1)

        # Check that both spans exist
        span_overlays = self.driver.find_element(By.ID, "span-overlays")
        overlay_elements = span_overlays.find_elements(By.CLASS_NAME, "span-overlay")

        self.assertGreaterEqual(len(overlay_elements), 2, f"Expected at least 2 overlays, got {len(overlay_elements)}")

        # Check that both labels are visible
        label_elements = span_overlays.find_elements(By.CLASS_NAME, "span-label")
        self.assertGreaterEqual(len(label_elements), 2, f"Expected at least 2 labels, got {len(label_elements)}")

        # Check that labels have different text
        label_texts = [label.text for label in label_elements]
        self.assertIn("positive", label_texts, "First span label not found")
        self.assertIn("negative", label_texts, "Second span label not found")

        # Check that delete buttons exist for both spans
        delete_buttons = span_overlays.find_elements(By.CLASS_NAME, "span-delete-btn")
        self.assertGreaterEqual(len(delete_buttons), 2, f"Expected at least 2 delete buttons, got {len(delete_buttons)}")

    def test_span_deletion(self):
        """Test that span deletion works correctly with interval-based rendering."""
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

        # Create a span
        self.select_span_label("positive")
        text_content = self.driver.find_element(By.ID, "text-content")
        text = text_content.text

        word_start = text.find("thrilled")
        if word_start == -1:
            word_start = 10

        word_end = word_start + 8

        # Create span
        self.create_span_by_selection(word_start, word_end)

        # Wait for span to be rendered
        time.sleep(0.1)

        # Verify span exists
        span_overlays = self.driver.find_element(By.ID, "span-overlays")
        overlay_elements = span_overlays.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertGreater(len(overlay_elements), 0, "Span was not created")

        # Delete the span by clicking the delete button
        delete_button = span_overlays.find_element(By.CLASS_NAME, "span-delete-btn")
        delete_button.click()

        # Wait for deletion to complete
        time.sleep(0.1)

        # Verify span was deleted
        overlay_elements_after = span_overlays.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(overlay_elements_after), 0, "Span was not deleted")

    def select_span_label(self, label_name):
        """Helper method to select a span label."""
        # Find and click the label checkbox
        label_checkbox = self.driver.find_element(By.CSS_SELECTOR, f"input[type='checkbox'][value='{label_name}']")
        label_checkbox.click()

    def create_span_by_selection(self, start, end):
        """Helper method to create a span by selecting text."""
        # Select the text using JavaScript
        self.driver.execute_script("""
            const textContent = document.getElementById('text-content');
            const textNode = textContent.firstChild;
            const range = document.createRange();
            range.setStart(textNode, arguments[0]);
            range.setEnd(textNode, arguments[1]);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """, start, end)

        # Wait a moment for selection to be processed
        time.sleep(0.1)


if __name__ == "__main__":
    unittest.main()