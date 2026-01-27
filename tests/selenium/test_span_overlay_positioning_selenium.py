import time
from selenium.webdriver.common.by import By
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

    def test_span_overlay_text_matches_selection(self):
        """Test that the text in the span overlay matches the selected text."""
        # Navigate to annotation page (user is already authenticated)
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be initialized
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.isInitialized) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Debug: Check span manager state
        span_manager_state = self.execute_script_safe("""
            return {
                spanManagerExists: !!window.spanManager,
                isInitialized: window.spanManager ? window.spanManager.isInitialized : false,
                positioningStrategy: window.spanManager ? !!window.spanManager.positioningStrategy : false,
                selectedLabel: window.spanManager ? window.spanManager.selectedLabel : null
            };
        """)
        print(f"DEBUG: Span manager state: {span_manager_state}")

        # Get the actual rendered text content (without HTML formatting)
        rendered_text = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent.textContent || textContent.innerText || '';
        """)
        print(f"Original text: '{rendered_text}'")

        # Select a specific text span (e.g., "thrilled" from the test data)
        target_text = "thrilled"
        start_pos = rendered_text.find(target_text)
        end_pos = start_pos + len(target_text)

        if start_pos == -1:
            self.fail(f"Target text '{target_text}' not found in rendered text: '{rendered_text}'")

        print(f"Target text: '{target_text}' (positions {start_pos}-{end_pos})")

        # Create a range and select the text
        self.execute_script_safe(f"""
            const textContent = document.getElementById('text-content');
            const range = document.createRange();
            const textNode = textContent.firstChild;
            range.setStart(textNode, {start_pos});
            range.setEnd(textNode, {end_pos});

            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """)

        # Debug: Check if text selection worked
        selection_info = self.execute_script_safe("""
            const selection = window.getSelection();
            return {
                rangeCount: selection.rangeCount,
                isCollapsed: selection.isCollapsed,
                selectedText: selection.toString(),
                selectedTextTrimmed: selection.toString().trim()
            };
        """)
        print(f"DEBUG: Text selection info: {selection_info}")

        # Wait a moment for selection to be processed
        time.sleep(0.5)

        # Select the "positive" label checkbox to enable span creation
        positive_checkbox = self.wait_for_element(By.ID, "emotion_spans_positive")
        positive_checkbox.click()

        # Debug: Check if label selection worked
        label_selection_info = self.execute_script_safe("""
            const checkedCheckbox = document.querySelector('.annotation-form.span input[type="checkbox"]:checked');
            return {
                checkedCheckboxExists: !!checkedCheckbox,
                checkedCheckboxId: checkedCheckbox ? checkedCheckbox.id : null,
                spanManagerSelectedLabel: window.spanManager ? window.spanManager.selectedLabel : null,
                getSelectedLabelResult: window.spanManager ? window.spanManager.getSelectedLabel() : null
            };
        """)
        print(f"DEBUG: Label selection info: {label_selection_info}")

        # Wait a moment for label selection to be processed
        time.sleep(0.5)

        # Trigger the span creation by calling handleTextSelection
        span_creation_result = self.execute_script_safe("""
            if (window.spanManager && window.spanManager.handleTextSelection) {
                try {
                    window.spanManager.handleTextSelection();
                    return { success: true, error: null };
                } catch (error) {
                    return { success: false, error: error.message };
                }
            } else {
                return { success: false, error: 'Span manager or handleTextSelection method not available' };
            }
        """)
        print(f"DEBUG: Span creation result: {span_creation_result}")

        # Debug: Check DOM structure for positioning
        dom_structure = self.execute_script_safe("""
            const textContainer = document.getElementById('text-container');
            const textContent = document.getElementById('text-content');
            const instanceText = document.getElementById('instance-text');

            return {
                textContainerExists: !!textContainer,
                textContentExists: !!textContent,
                instanceTextExists: !!instanceText,
                textContainerRect: textContainer ? textContainer.getBoundingClientRect() : null,
                textContentRect: textContent ? textContent.getBoundingClientRect() : null,
                instanceTextRect: instanceText ? instanceText.getBoundingClientRect() : null,
                textContainerPosition: textContainer ? textContainer.style.position : null,
                textContentPosition: textContent ? textContent.style.position : null,
                instanceTextPosition: instanceText ? instanceText.style.position : null
            };
        """)
        print(f"DEBUG: DOM structure: {dom_structure}")

        # Wait for the span overlay to appear
        time.sleep(1)

        # Debug: Check if any overlays were created
        overlay_debug = self.execute_script_safe("""
            const overlays = document.querySelectorAll('.span-overlay-pure');
            const textContent = document.getElementById('text-content');
            const instanceText = document.getElementById('instance-text');

            return {
                overlayCount: overlays.length,
                textContentExists: !!textContent,
                instanceTextExists: !!instanceText,
                textContentText: textContent ? textContent.textContent : null,
                instanceTextText: instanceText ? instanceText.textContent : null,
                textContentDataOriginalText: textContent ? textContent.getAttribute('data-original-text') : null,
                instanceTextDataOriginalText: instanceText ? instanceText.getAttribute('data-original-text') : null
            };
        """)
        print(f"DEBUG: Overlay debug info: {overlay_debug}")

        # Check that the span overlay exists (pure CSS system)
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay-pure")
        self.assertGreater(len(span_overlays), 0, "No span overlays found")

        # Get the actual text content that the span covers
        covered_text = self.execute_script_safe(f"""
            const overlay = document.querySelector('.span-overlay-pure');
            if (!overlay) {{
                return {{ success: false, error: 'No overlay found' }};
            }}

            const start = parseInt(overlay.dataset.start);
            const end = parseInt(overlay.dataset.end);
            const textContent = document.getElementById('text-content');

            // Use the original text content, not the rendered content (which includes overlays)
            const originalText = textContent.getAttribute('data-original-text') || textContent.textContent || textContent.innerText || '';

            const coveredText = originalText.substring(start, end);

            return {{
                success: true,
                coveredText: coveredText,
                start: start,
                end: end,
                originalText: originalText
            }};
        """)

        print(f"Covered text: '{covered_text.get('coveredText', '')}'")

        # Verify the covered text matches the selected text
        actual_text = covered_text.get('coveredText', '')
        self.assertEqual(actual_text, target_text,
                        f"Covered text '{actual_text}' does not match selected text '{target_text}'")

        # Verify the overlay is positioned correctly
        overlay_rect = span_overlays[0].rect
        text_content = self.driver.find_element(By.ID, "text-content")
        text_rect = text_content.rect

        print(f"DEBUG: Overlay rect: {overlay_rect}")
        print(f"DEBUG: Text content rect: {text_rect}")

        # Check that overlay is within the text content area
        self.assertGreaterEqual(overlay_rect['top'], text_rect['top'],
                               "Overlay positioned above text content")
        self.assertLessEqual(overlay_rect['bottom'], text_rect['bottom'],
                            "Overlay positioned below text content")

        print(f"✅ Covered text matches selection: '{actual_text}'")
        print(f"✅ Overlay positioned correctly within text area")

    def test_span_overlay_persistence_after_navigation(self):
        """Test that span overlays maintain correct positioning after navigation."""
        # Navigate to annotation page (user is already authenticated)
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be initialized
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.isInitialized) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Get the text content
        text_content = self.driver.find_element(By.ID, "text-content")
        original_text = text_content.text
        print(f"Original text: '{original_text}'")

        # Select a specific text span
        target_text = "thrilled"
        start_pos = original_text.find(target_text)
        end_pos = start_pos + len(target_text)

        print(f"Target text: '{target_text}' (positions {start_pos}-{end_pos})")

        # Create a range and select the text
        self.execute_script_safe(f"""
            const textContent = document.getElementById('text-content');
            const range = document.createRange();
            const textNode = textContent.firstChild;
            range.setStart(textNode, {start_pos});
            range.setEnd(textNode, {end_pos});

            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """)

        # Wait a moment for selection to be processed
        time.sleep(0.5)

        # Select the "positive" label checkbox to enable span creation
        positive_checkbox = self.wait_for_element(By.ID, "emotion_spans_positive")
        positive_checkbox.click()

        # Wait a moment for label selection to be processed
        time.sleep(0.5)

        # Trigger the span creation by calling handleTextSelection
        self.execute_script_safe("""
            if (window.spanManager && window.spanManager.handleTextSelection) {
                window.spanManager.handleTextSelection();
            } else {
                console.error('Span manager or handleTextSelection method not available');
            }
        """)

        # Wait for the span overlay to appear
        time.sleep(1)

        # Get the initial overlay position
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay-pure")
        self.assertGreater(len(span_overlays), 0, "No span overlays found")

        initial_overlay = span_overlays[0]
        initial_text = initial_overlay.text.strip()
        initial_rect = initial_overlay.rect

        print(f"Initial overlay text: '{initial_text}'")
        print(f"Initial overlay position: {initial_rect}")

        # Navigate to the next instance
        next_button = self.wait_for_element(By.ID, "next-button")
        next_button.click()

        # Wait for navigation to complete
        time.sleep(1)

        # Navigate back to the first instance
        prev_button = self.wait_for_element(By.ID, "prev-button")
        prev_button.click()

        # Wait for navigation to complete
        time.sleep(1)

        # Check that the span overlay still exists and has the correct text
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay-pure")
        self.assertGreater(len(span_overlays), 0, "No span overlays found after navigation")

        final_overlay = span_overlays[0]
        final_text = final_overlay.text.strip()
        final_rect = final_overlay.rect

        print(f"Final overlay text: '{final_text}'")
        print(f"Final overlay position: {final_rect}")

        # Verify the overlay text is still correct
        self.assertEqual(final_text, target_text,
                        f"Overlay text changed after navigation: '{final_text}' != '{target_text}'")

        # Verify the overlay is still positioned within the text content area
        text_content = self.driver.find_element(By.ID, "text-content")
        text_rect = text_content.rect

        self.assertGreaterEqual(final_rect['top'], text_rect['top'],
                               "Overlay positioned above text content after navigation")
        self.assertLessEqual(final_rect['bottom'], text_rect['bottom'],
                            "Overlay positioned below text content after navigation")

        # Verify the overlay position is reasonable (should be similar to initial position)
        # Allow some tolerance for minor rendering differences
        position_tolerance = 10  # pixels
        self.assertLess(abs(final_rect['top'] - initial_rect['top']), position_tolerance,
                        f"Overlay top position changed too much: {final_rect['top']} vs {initial_rect['top']}")
        self.assertLess(abs(final_rect['left'] - initial_rect['left']), position_tolerance,
                        f"Overlay left position changed too much: {final_rect['left']} vs {initial_rect['left']}")

        print(f"✅ Overlay text persisted correctly: '{final_text}'")
        print(f"✅ Overlay position maintained after navigation")

    def test_multiple_span_overlays_positioning(self):
        """Test that multiple span overlays are positioned correctly."""
        # Navigate to annotation page (user is already authenticated)
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be initialized
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.isInitialized) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Get the actual rendered text content (without HTML formatting)
        rendered_text = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent.textContent || textContent.innerText || '';
        """)
        print(f"Original text: '{rendered_text}'")

        # Create multiple span annotations
        span_data = [
            {"text": "thrilled", "label": "emotion_spans_positive"},
            {"text": "technology", "label": "emotion_spans_positive"},
            {"text": "revolutionize", "label": "emotion_spans_positive"}
        ]

        created_overlays = []

        for span_info in span_data:
            target_text = span_info["text"]
            start_pos = rendered_text.find(target_text)
            end_pos = start_pos + len(target_text)

            if start_pos == -1:
                self.fail(f"Target text '{target_text}' not found in rendered text: '{rendered_text}'")

            print(f"Creating span for: '{target_text}' (positions {start_pos}-{end_pos})")

            # Create a range and select the text
            self.execute_script_safe(f"""
                const textContent = document.getElementById('text-content');
                const range = document.createRange();
                const textNode = textContent.firstChild;
                range.setStart(textNode, {start_pos});
                range.setEnd(textNode, {end_pos});

                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            """)

            # Wait a moment for selection to be processed
            time.sleep(0.5)

            # Select the label checkbox to enable span creation
            label = self.wait_for_element(By.ID, span_info["label"])
            label.click()

            # Wait a moment for label selection to be processed
            time.sleep(0.5)

            # Trigger the span creation by calling handleTextSelection
            self.execute_script_safe("""
                if (window.spanManager && window.spanManager.handleTextSelection) {
                    window.spanManager.handleTextSelection();
                } else {
                    console.error('Span manager or handleTextSelection method not available');
                }
            """)

            # Wait for the span overlay to appear
            time.sleep(1)

            # Store overlay info
            span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay-pure")
            if span_overlays:
                latest_overlay = span_overlays[-1]  # Get the most recent overlay

                # Get the actual text content that the span covers
                covered_text = self.execute_script_safe(f"""
                    const overlay = document.querySelector('.span-overlay-pure:last-child');
                    if (!overlay) {{
                        return {{ success: false, error: 'No overlay found' }};
                    }}

                    const start = parseInt(overlay.dataset.start);
                    const end = parseInt(overlay.dataset.end);
                    const textContent = document.getElementById('text-content');
                    const renderedText = textContent.textContent || textContent.innerText || '';

                    const coveredText = renderedText.substring(start, end);

                    return {{
                        success: true,
                        coveredText: coveredText,
                        start: start,
                        end: end
                    }};
                """)

                created_overlays.append({
                    "text": target_text,
                    "covered_text": covered_text.get('coveredText', ''),
                    "rect": latest_overlay.rect
                })

        # Verify all overlays were created with correct text
        self.assertEqual(len(created_overlays), len(span_data),
                        f"Expected {len(span_data)} overlays, got {len(created_overlays)}")

        for i, overlay_info in enumerate(created_overlays):
            self.assertEqual(overlay_info["covered_text"], overlay_info["text"],
                           f"Overlay {i} text mismatch: '{overlay_info['covered_text']}' != '{overlay_info['text']}'")
            print(f"✅ Overlay {i} text correct: '{overlay_info['covered_text']}'")

        # Verify overlays are positioned within text content area
        text_content = self.driver.find_element(By.ID, "text-content")
        text_rect = text_content.rect
        for i, overlay_info in enumerate(created_overlays):
            rect = overlay_info["rect"]
            self.assertGreaterEqual(rect['top'], text_rect['top'],
                                  f"Overlay {i} positioned above text content")
            self.assertLessEqual(rect['bottom'], text_rect['bottom'],
                               f"Overlay {i} positioned below text content")
            print(f"✅ Overlay {i} positioned correctly within text area")

        # Verify overlays don't overlap significantly (they should be at different positions)
        for i in range(len(created_overlays)):
            for j in range(i + 1, len(created_overlays)):
                rect1 = created_overlays[i]["rect"]
                rect2 = created_overlays[j]["rect"]

                # Check if overlays overlap significantly
                overlap_horizontal = not (rect1['right'] < rect2['left'] or rect2['right'] < rect1['left'])
                overlap_vertical = not (rect1['bottom'] < rect2['top'] or rect2['bottom'] < rect1['top'])

                if overlap_horizontal and overlap_vertical:
                    # Calculate overlap area
                    overlap_width = min(rect1['right'], rect2['right']) - max(rect1['left'], rect2['left'])
                    overlap_height = min(rect1['bottom'], rect2['bottom']) - max(rect1['top'], rect2['top'])
                    overlap_area = overlap_width * overlap_height

                    # Calculate total area of both overlays
                    area1 = (rect1['right'] - rect1['left']) * (rect1['bottom'] - rect1['top'])
                    area2 = (rect2['right'] - rect2['left']) * (rect2['bottom'] - rect2['top'])
                    total_area = area1 + area2

                    # Overlap should be less than 50% of the smaller overlay
                    overlap_ratio = overlap_area / min(area1, area2)
                    self.assertLess(overlap_ratio, 0.5,
                                  f"Overlays {i} and {j} overlap too much: {overlap_ratio:.2f}")

        print("✅ All overlays positioned correctly without significant overlap")


if __name__ == "__main__":
    import unittest
    unittest.main()