"""
Test for span annotation overlap selection issue.

This test reproduces the bug where:
1. Create a first span annotation
2. Create a second span that partially overlaps with the first
3. The second span should appear but doesn't
"""

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.selenium.test_base import BaseSeleniumTest


class TestSpanOverlapSelection(BaseSeleniumTest):
    """Test span annotation with overlapping selections."""

    def test_partially_overlapping_spans(self):
        """Test that partially overlapping spans can be created correctly."""
        # Navigate to the annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for the page to load
        text_element = self.wait_for_element(By.ID, "instance-text")
        original_text = text_element.text
        print(f"Original text: {original_text}")

        # Wait for span manager to be ready
        time.sleep(0.05)
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        self.assertTrue(span_manager_ready, "Span manager should be initialized")

        # Select the first label (happy)
        happy_label = self.driver.find_element(By.CSS_SELECTOR, '[data-label="happy"]')
        happy_label.click()

        # Create first span: "artificial intelligence"
        first_span_text = "artificial intelligence"
        self._create_span_by_text_selection(first_span_text)

        # Wait for the first span to be created
        time.sleep(0.05)

        # Verify first span was created
        spans = self.driver.find_elements(By.CLASS_NAME, "annotation-span")
        self.assertEqual(len(spans), 1, f"Expected 1 span, found {len(spans)}")
        print(f"First span created successfully: {spans[0].text}")

        # Store information about the first span for later verification
        first_span_label = spans[0].get_attribute("data-label")
        first_span_text_content = spans[0].text.strip()
        print(f"First span label: {first_span_label}, text: {first_span_text_content}")

        # Select the second label (sad)
        sad_label = self.driver.find_element(By.CSS_SELECTOR, '[data-label="sad"]')
        sad_label.click()

        # Create second span that partially overlaps: "intelligence model"
        second_span_text = "intelligence model"
        self._create_span_by_text_selection(second_span_text)

        # Wait for the second span to be created
        time.sleep(0.1)

        # Verify both spans were created and the first span still exists
        spans = self.driver.find_elements(By.CLASS_NAME, "annotation-span")
        print(f"Found {len(spans)} spans after creating overlapping span")

        # Check if we have at least 2 spans (the overlapping ones)
        self.assertGreaterEqual(len(spans), 2,
                               f"Expected at least 2 spans after creating overlapping span, found {len(spans)}")

        # Verify the spans contain the expected text
        span_texts = [span.text.strip() for span in spans]
        span_labels = [span.get_attribute("data-label") for span in spans]
        print(f"Span texts: {span_texts}")
        print(f"Span labels: {span_labels}")

        # Check that both original texts are present in some form
        self.assertTrue(any(first_span_text.lower() in text.lower() for text in span_texts),
                       f"First span text '{first_span_text}' not found in spans: {span_texts}")
        self.assertTrue(any(second_span_text.lower() in text.lower() for text in span_texts),
                       f"Second span text '{second_span_text}' not found in spans: {span_texts}")

        # Verify that the first span's label is still present
        self.assertTrue(first_span_label in span_labels,
                       f"First span label '{first_span_label}' not found in span labels: {span_labels}")

        # Verify that both labels are present
        self.assertTrue('happy' in span_labels, f"'happy' label not found in: {span_labels}")
        self.assertTrue('sad' in span_labels, f"'sad' label not found in: {span_labels}")

        print("✅ Both overlapping spans created successfully and first span persisted")

    def _create_span_by_text_selection(self, text_to_select):
        """Helper method to create a span by selecting text."""
        # Use JavaScript to select the text
        script = f"""
        const container = document.getElementById('instance-text');
        const text = container.textContent;
        const startIndex = text.indexOf('{text_to_select}');
        if (startIndex === -1) {{
            throw new Error('Text "{text_to_select}" not found');
        }}

        const range = document.createRange();
        const walker = document.createTreeWalker(
            container,
            NodeFilter.SHOW_TEXT,
            null,
            false
        );

        let currentNode;
        let currentPos = 0;
        let startNode = null;
        let startOffset = 0;
        let endNode = null;
        let endOffset = 0;

        while (currentNode = walker.nextNode()) {{
            const nodeText = currentNode.textContent;
            const nodeLength = nodeText.length;

            // Check if this node contains the start of our selection
            if (!startNode && currentPos + nodeLength > startIndex) {{
                startNode = currentNode;
                startOffset = startIndex - currentPos;
            }}

            // Check if this node contains the end of our selection
            if (currentPos + nodeLength >= startIndex + {len(text_to_select)}) {{
                endNode = currentNode;
                endOffset = startIndex + {len(text_to_select)} - currentPos;
                break;
            }}

            currentPos += nodeLength;
        }}

        if (!startNode || !endNode) {{
            throw new Error('Could not find text nodes for selection');
        }}

        range.setStart(startNode, startOffset);
        range.setEnd(endNode, endOffset);

        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);

        return true;
        """

        try:
            self.driver.execute_script(script)
            time.sleep(0.1)  # Wait for selection to be applied

            # Trigger the text selection handler
            self.driver.execute_script("""
                // Simulate the text selection event
                const event = new Event('mouseup');
                document.getElementById('instance-text').dispatchEvent(event);
            """)

            print(f"Created span for text: {text_to_select}")

        except Exception as e:
            print(f"Error creating span for '{text_to_select}': {e}")
            raise

    def test_disjoint_spans_work(self):
        """Test that disjoint spans work correctly (control test)."""
        # Navigate to the annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for the page to load
        text_element = self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be ready
        time.sleep(0.05)
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        self.assertTrue(span_manager_ready, "Span manager should be initialized")

        # Select the first label (happy)
        happy_label = self.driver.find_element(By.CSS_SELECTOR, '[data-label="happy"]')
        happy_label.click()

        # Create first span: "artificial intelligence"
        self._create_span_by_text_selection("artificial intelligence")
        time.sleep(0.05)

        # Select the second label (sad)
        sad_label = self.driver.find_element(By.CSS_SELECTOR, '[data-label="sad"]')
        sad_label.click()

        # Create second span: "natural language processing" (disjoint)
        self._create_span_by_text_selection("natural language processing")
        time.sleep(0.05)

        # Verify both spans were created
        spans = self.driver.find_elements(By.CLASS_NAME, "annotation-span")
        self.assertEqual(len(spans), 2, f"Expected 2 spans for disjoint selection, found {len(spans)}")
        print("Disjoint spans test passed")

    def test_fully_nested_spans_work(self):
        """Test that fully nested spans work correctly (control test)."""
        # Navigate to the annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for the page to load
        text_element = self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be ready
        time.sleep(0.05)
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        self.assertTrue(span_manager_ready, "Span manager should be initialized")

        # Select the first label (happy)
        happy_label = self.driver.find_element(By.CSS_SELECTOR, '[data-label="happy"]')
        happy_label.click()

        # Create first span: "artificial intelligence model"
        self._create_span_by_text_selection("artificial intelligence model")
        time.sleep(0.05)

        # Select the second label (sad)
        sad_label = self.driver.find_element(By.CSS_SELECTOR, '[data-label="sad"]')
        sad_label.click()

        # Create second span: "intelligence" (fully nested)
        self._create_span_by_text_selection("intelligence")
        time.sleep(0.05)

        # Verify both spans were created
        spans = self.driver.find_elements(By.CLASS_NAME, "annotation-span")
        self.assertEqual(len(spans), 2, f"Expected 2 spans for nested selection, found {len(spans)}")
        print("Nested spans test passed")