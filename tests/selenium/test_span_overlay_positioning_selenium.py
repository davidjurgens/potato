import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from tests.selenium.test_base import BaseSeleniumTest


class TestSpanOverlayPositioningSelenium(BaseSeleniumTest):
    """
    Test span overlay positioning in a real browser environment.

    Verifies that:
    1. The text selected for a span matches the overlay text
    2. Span overlays persist and maintain correct positioning after navigation
    3. Multiple span overlays are positioned correctly without excessive overlap

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def _wait_for_span_manager(self):
        """Wait for SpanManager to be fully initialized."""
        WebDriverWait(self.driver, 10).until(
            lambda d: d.execute_script(
                "return window.spanManager && window.spanManager.isInitialized === true;"
            )
        )

    def _select_word(self, word):
        """
        Select a word in the text-content element using TreeWalker for robustness.

        Uses TreeWalker to find the correct text node, which handles cases where
        the text content has multiple child nodes (e.g., from prior overlays or
        HTML formatting).

        Returns:
            dict with bounding rect keys (left, top, right, bottom, width, height),
            or None if the word was not found.
        """
        script = f'''
            const text = document.getElementById('text-content');
            const textContent = text.textContent || text.innerText;
            const wordIndex = textContent.indexOf("{word}");
            if (wordIndex === -1) return null;

            const walker = document.createTreeWalker(text, NodeFilter.SHOW_TEXT);
            let node;
            let offset = 0;
            while (node = walker.nextNode()) {{
                if (offset + node.length > wordIndex) {{
                    const range = document.createRange();
                    range.setStart(node, wordIndex - offset);
                    range.setEnd(node, wordIndex - offset + {len(word)});
                    const selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                    return range.getBoundingClientRect();
                }}
                offset += node.length;
            }}
            return null;
        '''
        return self.driver.execute_script(script)

    def _click_label_checkbox(self, label_value):
        """
        Click a span label checkbox by its value attribute.

        This triggers the onclick handler which calls changeSpanLabel(), which
        in turn calls spanManager.selectLabel() to set the active label.

        Args:
            label_value: The value attribute of the checkbox (e.g., "positive")
        """
        label_checkbox = self.driver.find_element(
            By.CSS_SELECTOR, f'.shadcn-span-checkbox[value="{label_value}"]'
        )
        if not label_checkbox.is_selected():
            label_checkbox.click()
            time.sleep(0.05)

    def _dispatch_mouseup_on_text(self):
        """
        Dispatch a mouseup event on the text-content element to trigger
        handleTextSelection via the event listener.

        Uses ActionChains to move to the text element and release, which
        generates a real mouseup event that the SpanManager listens for.
        """
        text_element = self.driver.find_element(By.ID, 'text-content')
        ActionChains(self.driver).move_to_element(text_element).release().perform()
        time.sleep(0.1)

    def _create_span_on_word(self, word, label_value):
        """
        Create a span annotation on a word using the proper UI flow:
        1. Click the label checkbox (sets active label via changeSpanLabel)
        2. Create a text selection via JavaScript
        3. Dispatch mouseup on the text container (triggers handleTextSelection)

        Args:
            word: The word to annotate
            label_value: The label to apply (e.g., "positive")

        Returns:
            dict with bounding rect of the selected text, or None if word not found
        """
        # Step 1: Click label checkbox (triggers changeSpanLabel -> selectLabel)
        self._click_label_checkbox(label_value)

        # Step 2: Create text selection via JavaScript
        selection_rect = self._select_word(word)
        self.assertIsNotNone(selection_rect, f"Could not find word '{word}' in text")

        # Step 3: Dispatch mouseup to trigger handleTextSelection
        self._dispatch_mouseup_on_text()

        return selection_rect

    def _wait_for_overlay(self, timeout=5):
        """Wait for at least one span overlay to appear."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, '.span-overlay-pure')
            )
        )

    def _count_overlays(self):
        """Count all span overlays currently in the DOM."""
        return len(self.driver.find_elements(By.CSS_SELECTOR, '.span-overlay-pure'))

    def test_span_overlay_text_matches_selection(self):
        """Test that the text in the span overlay matches the selected text."""
        # Navigate to annotation page (user is already authenticated)
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")
        self._wait_for_span_manager()

        # Get the actual rendered text content
        rendered_text = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent.textContent || textContent.innerText || '';
        """)

        target_text = "thrilled"
        start_pos = rendered_text.find(target_text)
        if start_pos == -1:
            self.fail(f"Target text '{target_text}' not found in rendered text: '{rendered_text}'")

        # Create span using proper UI flow: click label, select text, mouseup
        self._create_span_on_word(target_text, "positive")

        # Wait for the span overlay to appear
        self._wait_for_overlay()

        # Verify at least one overlay was created
        span_overlays = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreater(len(span_overlays), 0, "No span overlays found")

        # Get the actual text content that the span covers using data attributes
        covered_text = self.execute_script_safe("""
            const overlay = document.querySelector('.span-overlay-pure');
            if (!overlay) {
                return { success: false, error: 'No overlay found' };
            }

            const start = parseInt(overlay.dataset.start);
            const end = parseInt(overlay.dataset.end);
            const textContent = document.getElementById('text-content');
            const originalText = textContent.getAttribute('data-original-text')
                || textContent.textContent || textContent.innerText || '';

            return {
                success: true,
                coveredText: originalText.substring(start, end),
                start: start,
                end: end
            };
        """)

        # Verify the covered text matches the selected text
        actual_text = covered_text.get('coveredText', '')
        self.assertEqual(actual_text, target_text,
                        f"Covered text '{actual_text}' does not match selected text '{target_text}'")

        # Verify the overlay is positioned within the text content area
        overlay_rect = self.driver.execute_script(
            'return arguments[0].getBoundingClientRect();', span_overlays[0]
        )
        text_content_el = self.driver.find_element(By.ID, "text-content")
        text_rect = self.driver.execute_script(
            'return arguments[0].getBoundingClientRect();', text_content_el
        )

        self.assertGreaterEqual(overlay_rect['top'], text_rect['top'] - 1,
                               "Overlay positioned above text content")
        self.assertLessEqual(overlay_rect['bottom'], text_rect['bottom'] + 1,
                            "Overlay positioned below text content")

    def test_span_overlay_persistence_after_navigation(self):
        """Test that span overlays maintain correct positioning after navigation."""
        # Navigate to annotation page (user is already authenticated)
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")
        self._wait_for_span_manager()

        target_text = "thrilled"

        # Create span using proper UI flow
        self._create_span_on_word(target_text, "positive")

        # Wait for the span overlay to appear
        self._wait_for_overlay()

        # Get the initial overlay state
        span_overlays = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreater(len(span_overlays), 0, "No span overlays found")

        initial_rect = self.driver.execute_script(
            'return arguments[0].getBoundingClientRect();', span_overlays[0]
        )

        # Navigate to the next instance
        next_button = self.wait_for_element(By.ID, "next-btn")
        next_button.click()

        # Wait for navigation to complete
        time.sleep(0.5)

        # Navigate back to the first instance
        prev_button = self.wait_for_element(By.ID, "prev-btn")
        prev_button.click()

        # Wait for navigation and overlay rendering to complete
        time.sleep(0.5)

        # Wait for span manager to re-initialize after navigation
        self._wait_for_span_manager()

        # Check that the span overlay still exists
        span_overlays = self.driver.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
        self.assertGreater(len(span_overlays), 0, "No span overlays found after navigation")

        final_rect = self.driver.execute_script(
            'return arguments[0].getBoundingClientRect();', span_overlays[0]
        )

        # Verify the overlay is still positioned within the text content area
        text_content_el = self.driver.find_element(By.ID, "text-content")
        text_rect = self.driver.execute_script(
            'return arguments[0].getBoundingClientRect();', text_content_el
        )

        self.assertGreaterEqual(final_rect['top'], text_rect['top'] - 1,
                               "Overlay positioned above text content after navigation")
        self.assertLessEqual(final_rect['bottom'], text_rect['bottom'] + 1,
                            "Overlay positioned below text content after navigation")

        # Verify the overlay position is reasonable (should be similar to initial position)
        position_tolerance = 10  # pixels
        self.assertLess(abs(final_rect['top'] - initial_rect['top']), position_tolerance,
                        f"Overlay top position changed too much: {final_rect['top']} vs {initial_rect['top']}")
        self.assertLess(abs(final_rect['left'] - initial_rect['left']), position_tolerance,
                        f"Overlay left position changed too much: {final_rect['left']} vs {initial_rect['left']}")

    def test_multiple_span_overlays_positioning(self):
        """Test that multiple span overlays are positioned correctly."""
        # Navigate to annotation page (user is already authenticated)
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")
        self._wait_for_span_manager()

        # Get the actual rendered text content
        rendered_text = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent.textContent || textContent.innerText || '';
        """)

        # Create multiple span annotations using proper UI flow
        span_data = [
            {"text": "thrilled", "label": "positive"},
            {"text": "technology", "label": "positive"},
            {"text": "revolutionize", "label": "positive"}
        ]

        created_overlays = []

        for span_info in span_data:
            target_text = span_info["text"]

            if rendered_text.find(target_text) == -1:
                self.fail(f"Target text '{target_text}' not found in rendered text: '{rendered_text}'")

            # Create span using proper UI flow
            self._create_span_on_word(target_text, span_info["label"])

            # Wait for overlay to appear
            time.sleep(0.2)

            # Get the overlay count and latest overlay info
            overlay_count = self._count_overlays()
            if overlay_count > len(created_overlays):
                # Get info about the most recently created overlay
                overlay_info = self.execute_script_safe(f"""
                    const overlays = document.querySelectorAll('.span-overlay-pure');
                    const overlay = overlays[overlays.length - 1];
                    if (!overlay) return null;

                    const start = parseInt(overlay.dataset.start);
                    const end = parseInt(overlay.dataset.end);
                    const textContent = document.getElementById('text-content');
                    const originalText = textContent.getAttribute('data-original-text')
                        || textContent.textContent || textContent.innerText || '';

                    return {{
                        coveredText: originalText.substring(start, end),
                        start: start,
                        end: end,
                        rect: overlay.getBoundingClientRect()
                    }};
                """)

                if overlay_info:
                    created_overlays.append({
                        "text": target_text,
                        "covered_text": overlay_info.get('coveredText', ''),
                        "rect": overlay_info.get('rect', {})
                    })

        # Verify all overlays were created
        self.assertEqual(len(created_overlays), len(span_data),
                        f"Expected {len(span_data)} overlays, got {len(created_overlays)}")

        # Verify each overlay covers the correct text
        for i, overlay_info in enumerate(created_overlays):
            self.assertEqual(overlay_info["covered_text"], overlay_info["text"],
                           f"Overlay {i} text mismatch: '{overlay_info['covered_text']}' != '{overlay_info['text']}'")

        # Verify overlays are positioned within text content area
        text_content_el = self.driver.find_element(By.ID, "text-content")
        text_rect = self.driver.execute_script(
            'return arguments[0].getBoundingClientRect();', text_content_el
        )

        for i, overlay_info in enumerate(created_overlays):
            rect = overlay_info["rect"]
            self.assertGreaterEqual(rect['top'], text_rect['top'] - 1,
                                  f"Overlay {i} positioned above text content")
            self.assertLessEqual(rect['bottom'], text_rect['bottom'] + 1,
                               f"Overlay {i} positioned below text content")

        # Verify overlays don't overlap significantly (they annotate different words)
        for i in range(len(created_overlays)):
            for j in range(i + 1, len(created_overlays)):
                rect1 = created_overlays[i]["rect"]
                rect2 = created_overlays[j]["rect"]

                # Check if overlays overlap
                overlap_horizontal = not (rect1.get('right', 0) < rect2.get('left', 0)
                                        or rect2.get('right', 0) < rect1.get('left', 0))
                overlap_vertical = not (rect1.get('bottom', 0) < rect2.get('top', 0)
                                       or rect2.get('bottom', 0) < rect1.get('top', 0))

                if overlap_horizontal and overlap_vertical:
                    # Calculate overlap area
                    overlap_width = (min(rect1.get('right', 0), rect2.get('right', 0))
                                   - max(rect1.get('left', 0), rect2.get('left', 0)))
                    overlap_height = (min(rect1.get('bottom', 0), rect2.get('bottom', 0))
                                    - max(rect1.get('top', 0), rect2.get('top', 0)))
                    overlap_area = max(0, overlap_width) * max(0, overlap_height)

                    # Calculate areas of both overlays
                    area1 = ((rect1.get('right', 0) - rect1.get('left', 0))
                            * (rect1.get('bottom', 0) - rect1.get('top', 0)))
                    area2 = ((rect2.get('right', 0) - rect2.get('left', 0))
                            * (rect2.get('bottom', 0) - rect2.get('top', 0)))

                    min_area = min(area1, area2)
                    if min_area > 0:
                        # Overlap should be less than 50% of the smaller overlay
                        overlap_ratio = overlap_area / min_area
                        self.assertLess(overlap_ratio, 0.5,
                                      f"Overlays {i} and {j} overlap too much: {overlap_ratio:.2f}")


if __name__ == "__main__":
    import unittest
    unittest.main()
