#!/usr/bin/env python3
"""
Test span overlap rendering fix.

This test verifies that the new interval-based rendering approach correctly
handles various types of span overlaps including:
- Partial overlaps
- Full overlaps
- Nested spans
- Multiple overlapping spans
- Edge cases

The test uses the base class for proper authentication and server setup.
"""

import time
import unittest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from tests.selenium.test_base import BaseSeleniumTest


class TestSpanOverlapFix(BaseSeleniumTest):
    """
    Test suite for span overlap rendering fix.

    This test verifies that partially overlapping spans are correctly displayed
    and that all spans remain visible and functional.
    """

    def test_basic_span_functionality(self):
        """
        Test basic span functionality to verify the setup is working.
        """
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to initialize
        self.wait_for_span_manager()

        # Check if span label checkboxes exist
        try:
            # Look for span label checkboxes
            span_checkboxes = self.driver.find_elements(By.CSS_SELECTOR, "input[for_span='true']")
            print(f"Found {len(span_checkboxes)} span checkboxes")

            if len(span_checkboxes) == 0:
                # Try alternative selector
                span_checkboxes = self.driver.find_elements(By.CSS_SELECTOR, ".shadcn-span-checkbox")
                print(f"Found {len(span_checkboxes)} span checkboxes with alternative selector")

            # Check if we can find the positive label
            positive_label = self.driver.find_element(By.XPATH, "//label[.//span[text()='positive']]")
            print("Found positive label")

            # Click the positive label
            positive_label.click()
            print("Clicked positive label")

            # Check if the checkbox is now checked
            checkbox = self.driver.find_element(By.CSS_SELECTOR, "input[for_span='true']:checked")
            print("Found checked checkbox")

            # Verify span manager has the correct schema
            span_manager_schema = self.driver.execute_script("return window.spanManager ? window.spanManager.currentSchema : 'not found'")
            print(f"Span manager schema: {span_manager_schema}")

            self.assertTrue(len(span_checkboxes) > 0, "Should find span checkboxes")
            self.assertEqual(span_manager_schema, "emotion_spans", "Span manager should have correct schema")

        except Exception as e:
            print(f"Error in basic span functionality test: {e}")
            # Take a screenshot for debugging
            self.driver.save_screenshot("debug_span_test.png")
            raise

    def test_partial_overlap_rendering(self):
        """
        Test that partially overlapping spans are both visible.

        Creates two spans that partially overlap and verifies both are displayed.
        """
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to initialize
        self.wait_for_span_manager()

        # Get the instance text
        instance_text = self.driver.find_element(By.ID, "instance-text")
        text_content = instance_text.text
        print(f"Instance text: {text_content}")

        # Find a good position for creating overlapping spans
        # Look for a phrase that's long enough to create partial overlaps
        words = text_content.split()
        if len(words) < 6:
            self.skipTest("Text too short for overlap testing")

        # Create first span: select first few words
        first_span_text = " ".join(words[:3])
        self.create_span_by_text_selection(first_span_text, "positive")

        # Wait for first span to be created
        time.sleep(0.1)

        # Debug: Check what span elements are present
        print("Checking for span elements after first span creation...")
        all_spans = self.driver.find_elements(By.CSS_SELECTOR, "span")
        print(f"Found {len(all_spans)} span elements")
        for i, span in enumerate(all_spans[:5]):  # Show first 5 spans
            print(f"Span {i}: class='{span.get_attribute('class')}', text='{span.text[:50]}'")

        # Look for span-overlay-pure elements (current overlay system)
        overlay_spans = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        print(f"Found {len(overlay_spans)} span-overlay-pure elements")
        for i, span in enumerate(overlay_spans):
            print(f"Overlay span {i}: label='{span.get_attribute('data-label')}', id='{span.get_attribute('data-annotation-id')}'")

        # Create second span: select words that overlap with first span
        second_span_text = " ".join(words[2:5])  # Overlaps with first span
        print(f"Attempting to create second span with text: '{second_span_text}'")
        self.create_span_by_text_selection(second_span_text, "negative")

        # Wait for second span to be created
        time.sleep(0.1)

        # Debug: Check what span overlay elements are present after second span
        print("Checking for span overlay elements after second span creation...")
        overlay_spans_after = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        print(f"Found {len(overlay_spans_after)} span-overlay-pure elements after second span")
        for i, span in enumerate(overlay_spans_after):
            print(f"Overlay span {i}: label='{span.get_attribute('data-label')}', id='{span.get_attribute('data-annotation-id')}'")

        # Verify both spans are visible (using the correct class name)
        spans = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreaterEqual(len(spans), 2, "Both spans should be created and visible")

        # Verify span labels are visible
        labels = self.driver.find_elements(By.CSS_SELECTOR, ".span-label")
        label_texts = [label.text for label in labels]
        self.assertIn("positive", label_texts, "First span label should be visible")
        self.assertIn("negative", label_texts, "Second span label should be visible")

    def test_full_overlap_rendering(self):
        """
        Test that fully overlapping spans are both visible.

        Creates two spans that completely overlap and verifies both are displayed.
        """
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to initialize
        self.wait_for_span_manager()

        # Get the instance text
        instance_text = self.driver.find_element(By.ID, "instance-text")
        text_content = instance_text.text

        # Find a phrase for full overlap
        words = text_content.split()
        if len(words) < 3:
            self.skipTest("Text too short for overlap testing")

        # Create first span: select a phrase
        span_text = " ".join(words[:3])
        self.create_span_by_text_selection(span_text, "positive")

        # Wait for first span to be created
        time.sleep(0.1)

        # Create second span: select the same phrase (full overlap)
        self.create_span_by_text_selection(span_text, "negative")

        # Wait for second span to be created
        time.sleep(0.1)

        # Verify both spans are visible
        spans = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreaterEqual(len(spans), 2, "Both overlapping spans should be visible")

        # Verify both labels are visible
        labels = self.driver.find_elements(By.CSS_SELECTOR, ".span-label")
        label_texts = [label.text for label in labels]
        self.assertIn("positive", label_texts, "First span label should be visible")
        self.assertIn("negative", label_texts, "Second span label should be visible")

    def test_multiple_overlapping_spans(self):
        """
        Test that multiple overlapping spans are all visible.

        Creates three or more spans with various overlap patterns.
        """
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to initialize
        self.wait_for_span_manager()

        # Get the instance text
        instance_text = self.driver.find_element(By.ID, "instance-text")
        text_content = instance_text.text

        # Find a good position for multiple overlaps
        words = text_content.split()
        if len(words) < 8:
            self.skipTest("Text too short for multiple overlap testing")

        # Create three overlapping spans
        span1_text = " ".join(words[:4])  # First 4 words
        span2_text = " ".join(words[2:6])  # Words 3-6 (overlaps with span1)
        span3_text = " ".join(words[4:8])  # Words 5-8 (overlaps with span2)

        # Create spans
        self.create_span_by_text_selection(span1_text, "positive")
        time.sleep(0.1)
        self.create_span_by_text_selection(span2_text, "negative")
        time.sleep(0.1)
        self.create_span_by_text_selection(span3_text, "neutral")
        time.sleep(0.1)

        # Verify all three spans are visible
        spans = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreaterEqual(len(spans), 3, "All three spans should be visible")

        # Verify all labels are visible
        labels = self.driver.find_elements(By.CSS_SELECTOR, ".span-label")
        label_texts = [label.text for label in labels]
        self.assertIn("positive", label_texts, "First span label should be visible")
        self.assertIn("negative", label_texts, "Second span label should be visible")
        self.assertIn("neutral", label_texts, "Third span label should be visible")

    def test_span_deletion_with_overlaps(self):
        """
        Test that span deletion works correctly with overlapping spans.

        Creates overlapping spans and verifies that deleting one doesn't affect the others.
        """
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to initialize
        self.wait_for_span_manager()

        # Get the instance text
        instance_text = self.driver.find_element(By.ID, "instance-text")
        text_content = instance_text.text

        # Find a good position for overlaps
        words = text_content.split()
        if len(words) < 4:
            self.skipTest("Text too short for deletion testing")

        # Create two overlapping spans
        span1_text = " ".join(words[:3])
        span2_text = " ".join(words[1:4])  # Overlaps with span1

        self.create_span_by_text_selection(span1_text, "positive")
        time.sleep(0.1)
        self.create_span_by_text_selection(span2_text, "negative")
        time.sleep(0.1)

        # Verify both spans exist
        spans = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreaterEqual(len(spans), 2, "Both spans should be created")

        # Delete the first span
        delete_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".span-delete-btn")
        if len(delete_buttons) > 0:
            delete_buttons[0].click()
            time.sleep(0.1)

        # Verify second span still exists
        remaining_spans = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreaterEqual(len(remaining_spans), 1, "Second span should still exist after deletion")

        # Verify second span label is still visible
        remaining_labels = self.driver.find_elements(By.CSS_SELECTOR, ".span-label")
        label_texts = [label.text for label in remaining_labels]
        self.assertIn("negative", label_texts, "Second span label should still be visible")

    def test_span_persistence_with_overlaps(self):
        """
        Test that overlapping spans persist correctly when navigating.

        Creates overlapping spans, navigates away and back, and verifies they're still there.
        """
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to initialize
        self.wait_for_span_manager()

        # Get the instance text
        instance_text = self.driver.find_element(By.ID, "instance-text")
        text_content = instance_text.text

        # Find a good position for overlaps
        words = text_content.split()
        if len(words) < 4:
            self.skipTest("Text too short for persistence testing")

        # Create two overlapping spans
        span1_text = " ".join(words[:3])
        span2_text = " ".join(words[1:4])  # Overlaps with span1

        self.create_span_by_text_selection(span1_text, "positive")
        time.sleep(0.1)
        self.create_span_by_text_selection(span2_text, "negative")
        time.sleep(0.1)

        # Verify both spans exist
        spans = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreaterEqual(len(spans), 2, "Both spans should be created")

        # Navigate to next instance
        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()

        # Wait for navigation
        time.sleep(0.5)

        # Navigate back to previous instance
        prev_button = self.driver.find_element(By.ID, "prev-btn")
        prev_button.click()

        # Wait for navigation and span overlay rendering
        time.sleep(1.0)

        # Verify spans are still there
        spans_after_navigation = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreaterEqual(len(spans_after_navigation), 2,
                               "Both spans should persist after navigation")

        # Verify labels are still visible
        labels_after_navigation = self.driver.find_elements(By.CSS_SELECTOR, ".span-label")
        label_texts = [label.text for label in labels_after_navigation]
        self.assertIn("positive", label_texts, "First span label should persist")
        self.assertIn("negative", label_texts, "Second span label should persist")

    def test_edge_case_overlaps(self):
        """
        Test edge cases with overlapping spans.

        Tests scenarios like:
        - Spans that start at the same position
        - Spans that end at the same position
        - Spans that are completely contained within others
        """
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to initialize
        self.wait_for_span_manager()

        # Get the instance text
        instance_text = self.driver.find_element(By.ID, "instance-text")
        text_content = instance_text.text

        # Find a good position for edge case testing
        words = text_content.split()
        if len(words) < 6:
            self.skipTest("Text too short for edge case testing")

        # Test 1: Spans that start at the same position
        same_start_text = " ".join(words[:3])
        self.create_span_by_text_selection(same_start_text, "positive")
        time.sleep(0.1)
        self.create_span_by_text_selection(same_start_text, "negative")
        time.sleep(0.1)

        # Verify both spans are visible
        spans = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreaterEqual(len(spans), 2, "Spans with same start should both be visible")

        # Test 2: Spans that are completely contained within others
        # First create a longer span
        long_span_text = " ".join(words[:5])
        self.create_span_by_text_selection(long_span_text, "neutral")
        time.sleep(0.1)

        # Then create a shorter span within it
        short_span_text = " ".join(words[1:4])
        self.create_span_by_text_selection(short_span_text, "positive")
        time.sleep(0.1)

        # Verify all spans are visible
        all_spans = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreaterEqual(len(all_spans), 4, "All spans including contained ones should be visible")

    def test_multiple_non_overlapping_spans(self):
        """
        Test that multiple non-overlapping spans can be created successfully.
        """
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Wait for span manager to initialize
        self.wait_for_span_manager()

        # Get the instance text
        instance_text = self.driver.find_element(By.ID, "instance-text")
        text_content = instance_text.text

        # Find a good position for non-overlapping spans
        words = text_content.split()
        if len(words) < 6:
            self.skipTest("Text too short for multiple span testing")

        # Create first span: select first few words
        first_span_text = " ".join(words[:2])
        self.create_span_by_text_selection(first_span_text, "positive")

        # Wait for first span to be created
        time.sleep(0.1)

        # Create second span: select different words (no overlap)
        second_span_text = " ".join(words[3:5])
        self.create_span_by_text_selection(second_span_text, "negative")

        # Wait for second span to be created
        time.sleep(0.1)

        # Debug: Check what span overlay elements are present after second span
        print("Checking for span overlay elements after second span creation...")
        overlay_spans_after = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        print(f"Found {len(overlay_spans_after)} span-overlay-pure elements after second span")
        for i, span in enumerate(overlay_spans_after):
            print(f"Overlay span {i}: label='{span.get_attribute('data-label')}', id='{span.get_attribute('data-annotation-id')}'")

        # Verify both spans are visible
        spans = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreaterEqual(len(spans), 2, "Both spans should be created and visible")

        # Verify span labels are visible
        labels = self.driver.find_elements(By.CSS_SELECTOR, ".span-label")
        label_texts = [label.text for label in labels]
        self.assertIn("positive", label_texts, "First span label should be visible")
        self.assertIn("negative", label_texts, "Second span label should be visible")

    def wait_for_span_manager(self):
        """Wait for the span manager to be initialized."""
        try:
            # Wait for span manager to be available
            WebDriverWait(self.driver, 10).until(
                lambda driver: driver.execute_script("return window.spanManager && window.spanManager.isInitialized")
            )
            print("Span manager initialized")
        except Exception as e:
            print(f"Warning: Span manager not initialized: {e}")

    def create_span_by_text_selection(self, text_to_select, label):
        """
        Create a span by selecting text and applying a label.

        Args:
            text_to_select: The text to select
            label: The label to apply (positive, negative, neutral)
        """
        # Click the label checkbox by ID to activate (triggers changeSpanLabel -> selectLabel)
        schema = "emotion_spans"  # BaseSeleniumTest default schema
        label_id = f"{schema}_{label}"
        label_el = self.driver.find_element(By.ID, label_id)
        self.driver.execute_script("arguments[0].click()", label_el)
        time.sleep(0.3)

        # Select text AND dispatch mouseup in one JS call to prevent selection clearing
        text_el = self.driver.find_element(By.CSS_SELECTOR, "[id^='text-content']")
        result = self.driver.execute_script(f"""
        var el = arguments[0];
        var textNodes = [];
        var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
        var fullText = '';
        var node;
        while (node = walker.nextNode()) {{
            textNodes.push({{node: node, start: fullText.length, end: fullText.length + node.textContent.length}});
            fullText += node.textContent;
        }}

        var startIndex = fullText.indexOf('{text_to_select}');
        if (startIndex === -1) return false;
        var endIndex = startIndex + {len(text_to_select)};

        var startNode = null, startOffset = 0, endNode = null, endOffset = 0;
        for (var i = 0; i < textNodes.length; i++) {{
            var pos = textNodes[i];
            if (startIndex >= pos.start && startIndex < pos.end) {{
                startNode = pos.node;
                startOffset = startIndex - pos.start;
            }}
            if (endIndex > pos.start && endIndex <= pos.end) {{
                endNode = pos.node;
                endOffset = endIndex - pos.start;
                break;
            }}
        }}

        if (startNode && endNode) {{
            var range = document.createRange();
            range.setStart(startNode, startOffset);
            range.setEnd(endNode, endOffset);
            var selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            // Dispatch mouseup immediately while selection is active
            el.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true}}));
            return true;
        }}
        return false;
        """, text_el)

        if not result:
            raise Exception(f"Could not find text '{text_to_select}' in document")

        time.sleep(0.5)  # Wait for span creation + async save


if __name__ == '__main__':
    unittest.main()