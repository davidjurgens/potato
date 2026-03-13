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

        # Wait for span manager to be fully initialized (including positioning strategy)
        WebDriverWait(self.driver, 15).until(
            lambda d: d.execute_script(
                "return window.spanManager && window.spanManager.isInitialized === true;"
            )
        )
        WebDriverWait(self.driver, 15).until(
            lambda d: d.execute_script(
                "return window.spanManager.positioningStrategy "
                "&& window.spanManager.positioningStrategy.isInitialized === true;"
            )
        )

        print("Page loaded and span manager initialized")

        # Check if span label checkboxes exist (using the shadcn-span-checkbox class)
        try:
            span_checkboxes = self.driver.find_elements(By.CSS_SELECTOR, ".shadcn-span-checkbox")
            print(f"Found {len(span_checkboxes)} span form checkboxes")
            for checkbox in span_checkboxes:
                value = checkbox.get_attribute('value')
                id_attr = checkbox.get_attribute('id')
                print(f"   - id='{id_attr}', value='{value}': displayed={checkbox.is_displayed()}")
        except Exception as e:
            print(f"Span form checkboxes not found: {e}")

        # Try to select a label by clicking the checkbox (triggers changeSpanLabel)
        schema = "emotion_spans"
        label_name = "positive"
        label_id = f"{schema}_{label_name}"
        try:
            label_el = self.driver.find_element(By.ID, label_id)
            self.driver.execute_script("arguments[0].click()", label_el)
            time.sleep(0.3)
            print(f"Clicked label checkbox '{label_id}'")

            # Verify the span manager picked up the selection
            selected = self.driver.execute_script(
                "return window.spanManager ? window.spanManager.selectedLabel : null;"
            )
            print(f"SpanManager selectedLabel after click: {selected}")
        except Exception as e:
            print(f"Could not click label checkbox: {e}")

        # Check if text content exists
        try:
            text_content = self.driver.find_element(By.ID, "text-content")
            text = text_content.text
            print(f"Text content found: '{text[:80]}...'")
        except Exception as e:
            print(f"Text content not found: {e}")
            return

        # Try to create a span using the proper flow:
        # 1. Create selection via JS
        # 2. Dispatch mouseup event in the same JS call to prevent selection clearing
        try:
            target_text = "thrilled"
            if target_text not in text:
                target_text = text.strip()[:8]

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
                if (startIndex === -1) return {success: false, error: 'text not found', fullText: fullText};
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
                    // Dispatch mouseup immediately while selection is active
                    el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                    return {success: true, startIndex: startIndex, endIndex: endIndex};
                }
                return {success: false, error: 'could not find text nodes'};
            """, text_content, target_text)

            print(f"Text selection result: {result}")

            if result.get('success'):
                # Wait for span creation + async save
                time.sleep(0.5)

                # Check if span overlays were created
                span_overlays = self.driver.find_element(By.ID, "span-overlays")
                overlay_elements = span_overlays.find_elements(By.CSS_SELECTOR, ".span-overlay-pure")
                print(f"Found {len(overlay_elements)} span overlays")

                if len(overlay_elements) > 0:
                    print("Span creation successful!")
                    # Check labels and delete buttons
                    labels = span_overlays.find_elements(By.CSS_SELECTOR, ".span-label")
                    print(f"Found {len(labels)} span labels")
                    for lbl in labels:
                        print(f"   Label text: '{lbl.text}'")
                    delete_btns = span_overlays.find_elements(By.CSS_SELECTOR, ".span-delete-btn")
                    print(f"Found {len(delete_btns)} delete buttons")
                else:
                    print("No span overlays created - checking SpanManager state")
                    state = self.driver.execute_script("""
                        return {
                            spanCount: window.spanManager?.annotations?.spans?.length || 0,
                            selectedLabel: window.spanManager?.selectedLabel || null,
                            currentSchema: window.spanManager?.currentSchema || null,
                            posReady: window.spanManager?.positioningStrategy?.isInitialized || false
                        };
                    """)
                    print(f"SpanManager state: {state}")
            else:
                print(f"Text selection failed: {result.get('error')}")

        except Exception as e:
            print(f"Error during span creation: {e}")


if __name__ == "__main__":
    unittest.main()
