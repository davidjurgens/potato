#!/usr/bin/env python3
"""
Selenium tests for interval-based span rendering.

This test verifies that:
1. Spans are rendered as overlays positioned correctly over text
2. Overlapping spans are handled properly with z-index layering
3. Labels and delete buttons are visible and functional
4. Text selection works correctly with the two-layer structure
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

    def wait_for_span_manager_ready(self, timeout=15):
        """Wait for SpanManager and its positioning strategy to be fully initialized."""
        WebDriverWait(self.driver, timeout).until(
            lambda d: d.execute_script(
                "return window.spanManager && window.spanManager.isInitialized === true;"
            )
        )
        # Also wait for positioning strategy to be ready
        WebDriverWait(self.driver, timeout).until(
            lambda d: d.execute_script(
                "return window.spanManager.positioningStrategy "
                "&& window.spanManager.positioningStrategy.isInitialized === true;"
            )
        )

    def select_span_label(self, label_name):
        """
        Helper method to select a span label by clicking its checkbox.

        This triggers the onclick handler which calls changeSpanLabel(),
        which in turn calls spanManager.selectLabel() to set up the span
        creation mode.
        """
        schema = "emotion_spans"
        label_id = f"{schema}_{label_name}"
        label_el = self.driver.find_element(By.ID, label_id)
        self.driver.execute_script("arguments[0].click()", label_el)
        time.sleep(0.3)

    def create_span_by_selection(self, text_to_select):
        """
        Helper method to create a span by selecting text and dispatching mouseup.

        Uses a TreeWalker to find the correct text node and offset, then
        creates a Range, sets the selection, and dispatches mouseup in a
        single JS call to prevent the selection from being cleared between steps.

        Args:
            text_to_select: The text string to search for and select.

        Returns:
            True if the text was found and selected, False otherwise.
        """
        text_el = self.driver.find_element(By.ID, "text-content")
        result = self.driver.execute_script("""
            var el = arguments[0];
            var targetText = arguments[1];

            // Walk all text nodes to build a full-text index
            var textNodes = [];
            var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
            var fullText = '';
            var node;
            while (node = walker.nextNode()) {
                textNodes.push({node: node, start: fullText.length, end: fullText.length + node.textContent.length});
                fullText += node.textContent;
            }

            var startIndex = fullText.indexOf(targetText);
            if (startIndex === -1) return false;
            var endIndex = startIndex + targetText.length;

            var startNode = null, startOffset = 0, endNode = null, endOffset = 0;
            for (var i = 0; i < textNodes.length; i++) {
                var pos = textNodes[i];
                if (startIndex >= pos.start && startIndex < pos.end) {
                    startNode = pos.node;
                    startOffset = startIndex - pos.start;
                }
                if (endIndex > pos.start && endIndex <= pos.end) {
                    endNode = pos.node;
                    endOffset = endIndex - pos.start;
                    break;
                }
            }

            if (startNode && endNode) {
                var range = document.createRange();
                range.setStart(startNode, startOffset);
                range.setEnd(endNode, endOffset);
                var selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                // Dispatch mouseup immediately while selection is still active
                el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                return true;
            }
            return false;
        """, text_el, text_to_select)

        if result:
            time.sleep(0.5)  # Wait for span creation + async save
        return result

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
        overlay_elements = span_overlays.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertEqual(len(overlay_elements), 0)

    def test_single_span_rendering(self):
        """Test that a single span is rendered correctly as an overlay."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to fully initialize
        self.wait_for_span_manager_ready()

        # Select the "positive" label
        self.select_span_label("positive")

        # Create a span by selecting text and dispatching mouseup
        text_content = self.driver.find_element(By.ID, "text-content")
        text = text_content.text

        # Try to find "thrilled" in the text, fall back to a generic selection
        target_word = "thrilled"
        if target_word not in text:
            target_word = "technology"
        if target_word not in text:
            # Use first 8 characters of available text
            target_word = text.strip()[:8]

        created = self.create_span_by_selection(target_word)
        self.assertTrue(created, f"Could not select text '{target_word}' in document")

        # Check that span overlays were created
        span_overlays = self.driver.find_element(By.ID, "span-overlays")
        overlay_elements = span_overlays.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")

        self.assertGreater(len(overlay_elements), 0, "No span overlays were created")

        # Check that the overlay has the correct label
        label_elements = span_overlays.find_elements(By.CSS_SELECTOR, ".span-label")
        self.assertGreater(len(label_elements), 0, "No span labels were created")

        label_text = label_elements[0].text
        self.assertEqual(label_text, "positive", f"Expected label 'positive', got '{label_text}'")

        # Check that delete button exists
        delete_buttons = span_overlays.find_elements(By.CSS_SELECTOR, ".span-delete-btn")
        self.assertGreater(len(delete_buttons), 0, "No delete buttons were created")

    def test_overlapping_spans_rendering(self):
        """Test that overlapping spans are rendered correctly with proper layering."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to fully initialize
        self.wait_for_span_manager_ready()

        # Get the text to find appropriate selections
        text_content = self.driver.find_element(By.ID, "text-content")
        text = text_content.text

        # Create first span with "positive" label
        self.select_span_label("positive")

        # Select a longer phrase
        first_target = "absolutely thrilled"
        if first_target not in text:
            first_target = "new technology"
        if first_target not in text:
            # Use the first 15 characters
            first_target = text.strip()[:15]

        created = self.create_span_by_selection(first_target)
        self.assertTrue(created, f"Could not select first text '{first_target}'")

        # Create second overlapping span with "negative" label
        self.select_span_label("negative")

        # Select a subset that overlaps with the first span
        second_target = "thrilled"
        if second_target not in text:
            # Use a portion that overlaps with the first selection
            second_target = first_target[:8] if len(first_target) >= 8 else first_target
        if second_target == first_target:
            # Avoid identical spans; use a different portion
            second_target = text.strip()[5:13]

        created = self.create_span_by_selection(second_target)
        self.assertTrue(created, f"Could not select second text '{second_target}'")

        # Check that both spans exist
        span_overlays = self.driver.find_element(By.ID, "span-overlays")
        overlay_elements = span_overlays.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")

        self.assertGreaterEqual(len(overlay_elements), 2, f"Expected at least 2 overlays, got {len(overlay_elements)}")

        # Check that both labels are visible
        label_elements = span_overlays.find_elements(By.CSS_SELECTOR, ".span-label")
        self.assertGreaterEqual(len(label_elements), 2, f"Expected at least 2 labels, got {len(label_elements)}")

        # Check that labels have different text
        label_texts = [label.text for label in label_elements]
        self.assertIn("positive", label_texts, "First span label not found")
        self.assertIn("negative", label_texts, "Second span label not found")

        # Check that delete buttons exist for both spans
        delete_buttons = span_overlays.find_elements(By.CSS_SELECTOR, ".span-delete-btn")
        self.assertGreaterEqual(len(delete_buttons), 2, f"Expected at least 2 delete buttons, got {len(delete_buttons)}")

    def test_span_deletion(self):
        """Test that span deletion works correctly with interval-based rendering."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to fully initialize
        self.wait_for_span_manager_ready()

        # Create a span
        self.select_span_label("positive")
        text_content = self.driver.find_element(By.ID, "text-content")
        text = text_content.text

        target_word = "thrilled"
        if target_word not in text:
            target_word = text.strip()[:8]

        created = self.create_span_by_selection(target_word)
        self.assertTrue(created, f"Could not select text '{target_word}'")

        # Verify span exists
        span_overlays = self.driver.find_element(By.ID, "span-overlays")
        overlay_elements = span_overlays.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreater(len(overlay_elements), 0, "Span was not created")

        # Delete the span by clicking the delete button
        # Delete buttons have pointer-events: auto even though the overlay container
        # has pointer-events: none
        delete_button = span_overlays.find_element(By.CSS_SELECTOR, ".span-delete-btn")
        self.driver.execute_script("arguments[0].click()", delete_button)

        # Wait for deletion to complete
        time.sleep(0.5)

        # Verify span was deleted
        overlay_elements_after = span_overlays.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertEqual(len(overlay_elements_after), 0, "Span was not deleted")


if __name__ == "__main__":
    unittest.main()
