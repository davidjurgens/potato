#!/usr/bin/env python3
"""
Selenium diagnostics for frontend span offset calculation.

This test directly exercises the selection-to-offset mapping logic in
span-manager.js and annotation.js, and checks for negative/invalid offsets.

Authentication Flow:
1. Each test inherits from BaseSeleniumTest which automatically:
   - Registers a unique test user
   - Logs in the user
   - Verifies authentication before running the test
2. Tests can then focus on their specific functionality without auth concerns
3. Each test gets a fresh WebDriver and unique user account for isolation
"""

import time
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from tests.selenium.test_base import BaseSeleniumTest


class TestSpanOffsetDiagnostics(BaseSeleniumTest):
    """
    Test suite for diagnosing frontend span offset calculation issues.

    This test suite focuses on the specific problem where offsets are negative
    or incorrect, particularly for selections at the start of text.

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_selection_offset_at_start(self):
        """Test offset calculation for selection at the start of the text."""
        print("\n" + "="*80)
        print("🧪 TESTING SELECTION OFFSET AT START")
        print("="*80)

        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)  # Wait for JS to initialize

        # Get the text content
        text_element = self.driver.find_element(By.ID, "instance-text")
        full_text = text_element.text
        print(f"🔧 Full text: '{full_text[:100]}...'")

        target_text = "The new artificial intelligence"
        start_index = full_text.find(target_text)

        if start_index == -1:
            # Fallback to first few words
            target_text = " ".join(full_text.split()[:3])
            start_index = 0

        end_index = start_index + len(target_text)
        print(f"🔧 Target text: '{target_text}' (positions {start_index}-{end_index})")

        # Select the text using JavaScript
        selection_success = self.execute_script_safe("""
            var textElement = arguments[0];
            var text = textElement.textContent;
            var range = document.createRange();
            var textNode = textElement.firstChild;
            range.setStart(textNode, arguments[1]);
            range.setEnd(textNode, arguments[2]);
            var selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return selection.toString();
        """, text_element, start_index, end_index)

        print(f"🔧 Selection result: '{selection_success}'")
        assert selection_success == target_text, f"Selection failed: expected '{target_text}', got '{selection_success}'"

        # Call the offset calculation function in span-manager.js
        offset_result = self.execute_script_safe("""
            var container = document.getElementById('instance-text');
            var selection = window.getSelection();
            if (window.spanManager && selection.rangeCount > 0) {
                var range = selection.getRangeAt(0);
                return window.spanManager.getOriginalTextPosition(container, range.startContainer, range.startOffset);
            }
            return null;
        """)
        print(f"🔧 SpanManager offset result: {offset_result}")

        # Check if spanManager exists and is initialized
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        print(f"🔧 SpanManager ready: {span_manager_ready}")

        if span_manager_ready:
            assert offset_result is not None, "Offset result should not be null"
            assert offset_result >= 0, f"Offset should not be negative, got {offset_result}"
            assert offset_result == start_index, f"Expected offset {start_index}, got {offset_result}"
        else:
            print("⚠️  SpanManager not ready, skipping offset validation")

    def test_selection_offset_negative(self):
        """Test that negative offsets are never returned for valid selections."""
        print("\n" + "="*80)
        print("🧪 TESTING NEGATIVE OFFSET PREVENTION")
        print("="*80)

        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        text_element = self.driver.find_element(By.ID, "instance-text")
        full_text = text_element.text
        print(f"🔧 Full text: '{full_text[:100]}...'")

        # Select a word in the middle
        words = full_text.split()
        if len(words) < 10:
            pytest.skip("Not enough words in test instance")

        target_text = words[5]
        start_index = full_text.find(target_text)
        end_index = start_index + len(target_text)

        print(f"🔧 Target text: '{target_text}' (positions {start_index}-{end_index})")

        # Select the word using JavaScript
        selection_success = self.execute_script_safe("""
            var textElement = arguments[0];
            var text = textElement.textContent;
            var range = document.createRange();
            var textNode = textElement.firstChild;
            var start = arguments[1];
            var end = arguments[2];
            range.setStart(textNode, start);
            range.setEnd(textNode, end);
            var selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return selection.toString();
        """, text_element, start_index, end_index)

        print(f"🔧 Selection result: '{selection_success}'")
        assert selection_success == target_text, f"Selection failed: expected '{target_text}', got '{selection_success}'"

        # Call the offset calculation function
        offset_result = self.execute_script_safe("""
            var container = document.getElementById('instance-text');
            var selection = window.getSelection();
            if (window.spanManager && selection.rangeCount > 0) {
                var range = selection.getRangeAt(0);
                return window.spanManager.getOriginalTextPosition(container, range.startContainer, range.startOffset);
            }
            return null;
        """)
        print(f"🔧 Offset result: {offset_result}")

        assert offset_result is not None, "Offset result should not be null"
        assert offset_result >= 0, f"Offset should not be negative, got {offset_result}"
        assert offset_result == start_index, f"Expected offset {start_index}, got {offset_result}"

    def test_selection_offset_overlay_function(self):
        """Test the overlay system's getSelectionIndicesOverlay for valid selection."""
        print("\n" + "="*80)
        print("🧪 TESTING OVERLAY OFFSET FUNCTION")
        print("="*80)

        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        text_element = self.driver.find_element(By.ID, "instance-text")
        full_text = text_element.text
        print(f"🔧 Full text: '{full_text[:100]}...'")

        # Select a phrase at the end
        target_text = "significant margin."
        start_index = full_text.find(target_text)

        if start_index == -1:
            # Fallback to last few words
            words = full_text.split()
            target_text = " ".join(words[-2:])
            start_index = full_text.find(target_text)

        end_index = start_index + len(target_text)
        print(f"🔧 Target text: '{target_text}' (positions {start_index}-{end_index})")

        # Select the text using JavaScript
        selection_success = self.execute_script_safe("""
            var textElement = arguments[0];
            var text = textElement.textContent;
            var range = document.createRange();
            var textNode = textElement.firstChild;
            var start = arguments[1];
            var end = arguments[2];
            range.setStart(textNode, start);
            range.setEnd(textNode, end);
            var selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return selection.toString();
        """, text_element, start_index, end_index)

        print(f"🔧 Selection result: '{selection_success}'")
        assert selection_success == target_text, f"Selection failed: expected '{target_text}', got '{selection_success}'"

        # Call the overlay offset function in annotation.js
        offset_result = self.execute_script_safe("""
            if (typeof getSelectionIndicesOverlay === 'function') {
                return getSelectionIndicesOverlay();
            }
            return null;
        """)
        print(f"🔧 Overlay offset result: {offset_result}")

        if offset_result is not None:
            assert offset_result['start'] >= 0, f"Start offset should not be negative, got {offset_result['start']}"
            assert offset_result['end'] > offset_result['start'], f"End should be greater than start, got {offset_result}"
            assert offset_result['start'] == start_index, f"Expected start {start_index}, got {offset_result['start']}"
            assert offset_result['end'] == end_index, f"Expected end {end_index}, got {offset_result['end']}"
        else:
            print("⚠️  getSelectionIndicesOverlay function not found")

    def test_production_bug_reproduction(self):
        """Reproduce the specific production bug with negative offsets."""
        print("\n" + "="*80)
        print("🧪 REPRODUCING PRODUCTION BUG")
        print("="*80)

        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        text_element = self.driver.find_element(By.ID, "instance-text")
        full_text = text_element.text
        print(f"🔧 Full text: '{full_text}'")

        # Look for the exact production text
        target_text = "The new artificial intelligence"
        start_index = full_text.find(target_text)

        if start_index == -1:
            print("⚠️  Production text not found, using first few words")
            target_text = " ".join(full_text.split()[:3])
            start_index = 0

        end_index = start_index + len(target_text)
        print(f"🔧 Target text: '{target_text}' (positions {start_index}-{end_index})")

        # Select the text using JavaScript
        selection_success = self.execute_script_safe("""
            var textElement = arguments[0];
            var text = textElement.textContent;
            var range = document.createRange();
            var textNode = textElement.firstChild;
            range.setStart(textNode, arguments[1]);
            range.setEnd(textNode, arguments[2]);
            var selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return selection.toString();
        """, text_element, start_index, end_index)

        print(f"🔧 Selection result: '{selection_success}'")
        assert selection_success == target_text, f"Selection failed: expected '{target_text}', got '{selection_success}'"

        # Test only the new span manager system (not the old overlay system)
        span_manager_offset = self.execute_script_safe("""
            var container = document.getElementById('instance-text');
            var selection = window.getSelection();
            if (window.spanManager && selection.rangeCount > 0) {
                var range = selection.getRangeAt(0);
                return window.spanManager.getOriginalTextPosition(container, range.startContainer, range.startOffset);
            }
            return null;
        """)

        print(f"🔧 SpanManager offset: {span_manager_offset}")

        # Check for negative offsets (the production bug)
        assert span_manager_offset is not None, "SpanManager offset should not be null"
        assert span_manager_offset >= 0, f"PRODUCTION BUG: SpanManager returned negative offset {span_manager_offset}"
        assert span_manager_offset == start_index, f"SpanManager offset mismatch: expected {start_index}, got {span_manager_offset}"

        print("✅ Production bug fixed! SpanManager now returns correct offsets")

    def test_span_creation_with_calculated_offsets(self):
        """Test creating a span using the calculated offsets."""
        print("\n" + "="*80)
        print("🧪 TESTING SPAN CREATION WITH CALCULATED OFFSETS")
        print("="*80)

        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        # Wait for span manager to be ready
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        print(f"🔧 SpanManager ready: {span_manager_ready}")

        if not span_manager_ready:
            pytest.skip("SpanManager not ready")

        text_element = self.driver.find_element(By.ID, "instance-text")
        full_text = text_element.text
        target_text = "artificial intelligence"
        start_index = full_text.find(target_text)

        if start_index == -1:
            target_text = full_text.split()[0]
            start_index = 0

        end_index = start_index + len(target_text)
        print(f"🔧 Creating span for: '{target_text}' (positions {start_index}-{end_index})")

        # Create span using the span manager
        create_result = self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.createAnnotation(arguments[0], arguments[1], arguments[2], arguments[3]);
            }
            return null;
        """, target_text, start_index, end_index, "positive")

        print(f"🔧 Span creation result: {create_result}")

        # Wait for the span to be created and rendered
        time.sleep(3)

        # Check if span elements are present
        span_elements = text_element.find_elements(By.CLASS_NAME, "span-highlight")
        print(f"🔧 Found {len(span_elements)} span elements")

        if len(span_elements) > 0:
            span = span_elements[0]
            span_text = span.text
            span_label = span.get_attribute("data-label")
            print(f"🔧 Span text: '{span_text}'")
            print(f"🔧 Span label: '{span_label}'")

            # Verify the span contains the correct text
            assert target_text in span_text, f"Span should contain '{target_text}', got '{span_text}'"
            assert span_label == "positive", f"Span should have label 'positive', got '{span_label}'"
        else:
            print("⚠️  No span elements found after creation")


if __name__ == "__main__":
    # Run the tests directly
    pytest.main([__file__, "-v", "-s"])