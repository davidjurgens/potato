#!/usr/bin/env python3
"""
Selenium test to verify multiple non-overlapping spans render correctly.

This test ensures that when multiple spans are added (even adjacent ones),
they all render correctly without corrupting each other's display.
"""

import pytest
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from tests.selenium.test_base import BaseSeleniumTest


class TestMultipleSpansRendering(BaseSeleniumTest):
    """
    Test suite for verifying multiple span rendering behavior.

    This test suite focuses on ensuring that multiple spans can be added
    without corrupting the rendering of existing spans.

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_multiple_non_overlapping_spans(self):
        """Test that multiple non-overlapping spans render correctly."""
        print("\n" + "="*80)
        print("🧪 TESTING MULTIPLE NON-OVERLAPPING SPANS")
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

        # Debug: Check if createAnnotation method exists
        create_annotation_exists = self.execute_script_safe("""
            return window.spanManager && typeof window.spanManager.createAnnotation === 'function';
        """)
        print(f"🔧 createAnnotation method exists: {create_annotation_exists}")

        # Debug: Check current instance ID
        current_instance_id = self.execute_script_safe("""
            return window.spanManager ? window.spanManager.currentInstanceId : null;
        """)
        print(f"🔧 Current instance ID: {current_instance_id}")

        # Debug: Test simple JavaScript execution
        test_result = self.execute_script_safe("""
            console.log('Test JavaScript execution');
            return 'JavaScript execution works';
        """)
        print(f"🔧 JavaScript test result: {test_result}")

        # Debug: Test calling a simple method on spanManager
        span_manager_test = self.execute_script_safe("""
            if (window.spanManager) {
                console.log('Testing spanManager method call');
                return window.spanManager.getSpans ? window.spanManager.getSpans().length : 'getSpans not found';
            }
            return 'spanManager not found';
        """)
        print(f"🔧 spanManager test result: {span_manager_test}")

        # Debug: Test calling createAnnotation with minimal arguments
        # create_annotation_test = self.execute_script_safe("""
        #     if (window.spanManager && window.spanManager.createAnnotation) {
        #         console.log('Testing createAnnotation call');
        #         try {
        #             const result = window.spanManager.createAnnotation('test', 0, 4, 'test');
        #             console.log('createAnnotation test result:', result);
        #             return 'createAnnotation called successfully';
        #         } catch (error) {
        #             console.error('createAnnotation test error:', error);
        #             return 'ERROR: ' + error.message;
        #         }
        #     }
        #     return 'createAnnotation method not found';
        # """)
        # print(f"🔧 createAnnotation test result: {create_annotation_test}")

        text_element = self.driver.find_element(By.ID, "instance-text")
        full_text = text_element.text
        print(f"🔧 Full text: '{full_text[:100]}...'")

        # Define test spans (non-overlapping)
        test_spans = [
            {
                "text": "I am absolutely thrilled",
                "label": "positive",
                "expected_start": 0,
                "expected_end": 22
            },
            {
                "text": "new technology announcement",
                "label": "topic",
                "expected_start": 23,
                "expected_end": 50
            },
            {
                "text": "revolutionize how we work",
                "label": "impact",
                "expected_start": 51,
                "expected_end": 75
            }
        ]

        # Create spans one by one
        for i, span_info in enumerate(test_spans):
            print(f"\n📝 Creating span {i+1}: '{span_info['text']}' ({span_info['label']})")

            # Find the text in the full text
            start_index = full_text.find(span_info['text'])
            if start_index == -1:
                print(f"⚠️  Text '{span_info['text']}' not found, skipping")
                continue

            end_index = start_index + len(span_info['text'])
            print(f"🔧 Positions: {start_index}-{end_index}")

            # Create span using the span manager
            create_result = self.execute_script_safe("""
                console.log('About to call createAnnotation');
                console.log('window.spanManager:', window.spanManager);
                console.log('window.spanManager.createAnnotation:', window.spanManager.createAnnotation);
                console.log('Arguments:', arguments[0], arguments[1], arguments[2], arguments[3]);

                const result = window.spanManager.createAnnotation(arguments[0], arguments[1], arguments[2], arguments[3]);
                console.log('createAnnotation returned:', result);
                console.log('Result type:', typeof result);
                console.log('Result instanceof Promise:', result instanceof Promise);
                return result;
            """, span_info['text'], start_index, end_index, span_info['label'])

            print(f"🔧 Span creation result: {create_result}")
            print(f"🔧 Result type: {type(create_result)}")

            # Manually call loadAnnotations to refresh the spans
            load_result = self.execute_script_safe("""
                if (window.spanManager) {
                    console.log('Manually calling loadAnnotations');
                    return window.spanManager.loadAnnotations(arguments[0]);
                }
                return null;
            """, 1)
            print(f"🔧 Load annotations result: {load_result}")

            # Wait for the span to be created and rendered
            time.sleep(2)

            # Verify all existing spans are still present and correct
            self._verify_all_spans_present(test_spans[:i+1], full_text)

        print("\n✅ All spans created successfully!")

    def test_adjacent_spans(self):
        """Test that adjacent spans (touching at boundaries) render correctly."""
        print("\n" + "="*80)
        print("🧪 TESTING ADJACENT SPANS")
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
        print(f"🔧 Full text: '{full_text[:100]}...'")

        # Define adjacent spans (touching at boundaries)
        adjacent_spans = [
            {
                "text": "I am absolutely",
                "label": "subject",
                "expected_start": 0,
                "expected_end": 15
            },
            {
                "text": " thrilled about",
                "label": "emotion",
                "expected_start": 15,
                "expected_end": 28
            },
            {
                "text": " the new",
                "label": "topic",
                "expected_start": 28,
                "expected_end": 36
            }
        ]

        # Create adjacent spans
        for i, span_info in enumerate(adjacent_spans):
            print(f"\n📝 Creating adjacent span {i+1}: '{span_info['text']}' ({span_info['label']})")

            # Find the text in the full text
            start_index = full_text.find(span_info['text'])
            if start_index == -1:
                print(f"⚠️  Text '{span_info['text']}' not found, skipping")
                continue

            end_index = start_index + len(span_info['text'])
            print(f"🔧 Positions: {start_index}-{end_index}")

            # Create span using the span manager
            create_result = self.execute_script_safe("""
                if (window.spanManager) {
                    return window.spanManager.createAnnotation(arguments[0], arguments[1], arguments[2], arguments[3]);
                }
                return null;
            """, span_info['text'], start_index, end_index, span_info['label'])

            print(f"🔧 Span creation result: {create_result}")

            # Wait for the span to be created and rendered
            time.sleep(2)

            # Verify all existing spans are still present and correct
            self._verify_all_spans_present(adjacent_spans[:i+1], full_text)

        print("\n✅ All adjacent spans created successfully!")

    def test_span_deletion_preserves_others(self):
        """Test that deleting one span doesn't corrupt the others."""
        print("\n" + "="*80)
        print("🧪 TESTING SPAN DELETION PRESERVES OTHERS")
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

        # Create two spans
        spans = [
            {
                "text": "I am absolutely thrilled",
                "label": "positive"
            },
            {
                "text": "new technology announcement",
                "label": "topic"
            }
        ]

        # Create both spans
        for span_info in spans:
            start_index = full_text.find(span_info['text'])
            if start_index == -1:
                continue
            end_index = start_index + len(span_info['text'])

            self.execute_script_safe("""
                if (window.spanManager) {
                    return window.spanManager.createAnnotation(arguments[0], arguments[1], arguments[2], arguments[3]);
                }
                return null;
            """, span_info['text'], start_index, end_index, span_info['label'])

            time.sleep(1)

        # Verify both spans are present
        span_elements = text_element.find_elements(By.CLASS_NAME, "annotation-span")
        print(f"🔧 Created {len(span_elements)} spans")

        assert len(span_elements) >= 2, f"Expected at least 2 spans, found {len(span_elements)}"

        # Delete the first span
        first_span = span_elements[0]
        delete_button = first_span.find_element(By.CLASS_NAME, "span-delete-btn")
        print("🔧 Deleting first span...")
        delete_button.click()

        # Wait for deletion to complete
        time.sleep(2)

        # Verify the second span is still present and correct
        remaining_spans = text_element.find_elements(By.CLASS_NAME, "annotation-span")
        print(f"🔧 Remaining spans after deletion: {len(remaining_spans)}")

        assert len(remaining_spans) == 1, f"Expected 1 remaining span, found {len(remaining_spans)}"

        # Verify the remaining span is the second one
        remaining_span = remaining_spans[0]
        remaining_text = remaining_span.text
        remaining_label = remaining_span.get_attribute("data-label")

        print(f"🔧 Remaining span text: '{remaining_text}'")
        print(f"🔧 Remaining span label: '{remaining_label}'")

        assert spans[1]['text'] in remaining_text, f"Remaining span should contain '{spans[1]['text']}', got '{remaining_text}'"
        assert remaining_label == spans[1]['label'], f"Remaining span should have label '{spans[1]['label']}', got '{remaining_label}'"

        print("✅ Span deletion preserves other spans correctly!")

    def test_offset_calculation_with_ui_elements(self):
        """Test that offset calculations are correct when UI elements (delete buttons, labels) are present."""
        print("\n" + "="*80)
        print("🧪 TESTING OFFSET CALCULATION WITH UI ELEMENTS")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        # Wait for span manager to be ready
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        print(f"🔧 SpanManager ready: {span_manager_ready}")

        if not span_manager_ready:
            pytest.skip("SpanManager not ready")

        # Get the full text for reference
        full_text = self.execute_script_safe("""
            return window.currentInstance ? window.currentInstance.text : '';
        """)
        print(f"🔧 Full text: '{full_text[:50]}...'")

        # Create first span to add UI elements to the DOM
        print("\n📝 Creating first span to add UI elements to DOM...")
        first_span_result = self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.createAnnotation('I am absolutely thrilled', 0, 24, 'positive');
            }
            return null;
        """)
        print(f"🔧 First span creation result: {first_span_result}")

        # Wait for rendering
        time.sleep(2)

        # Now test offset calculation for a later position
        print("\n📝 Testing offset calculation for position after first span...")

        # Get the text container
        text_container = self.driver.find_element(By.ID, "instance-text")

        # Test offset calculation for position 35 (start of "new technology announcement")
        offset_test = self.execute_script_safe("""
            const textContainer = document.getElementById('instance-text');
            const walker = document.createTreeWalker(
                textContainer,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );

            let currentNode;
            let textSoFar = '';
            let nodeCount = 0;
            let uiElementCount = 0;

            console.log('=== OFFSET CALCULATION DEBUG ===');

            while (currentNode = walker.nextNode()) {
                nodeCount++;
                const parent = currentNode.parentElement;
                const isUIElement = parent && (
                    parent.classList.contains('span-delete-btn') ||
                    parent.classList.contains('span-label') ||
                    parent.closest('.span-delete-btn') ||
                    parent.closest('.span-label')
                );

                if (isUIElement) {
                    uiElementCount++;
                    console.log(`Node ${nodeCount}: UI ELEMENT - "${currentNode.textContent}" (skipped)`);
                    continue;
                }

                console.log(`Node ${nodeCount}: TEXT NODE - "${currentNode.textContent}" (length: ${currentNode.textContent.length})`);
                textSoFar += currentNode.textContent;
            }

            console.log(`Total nodes: ${nodeCount}, UI elements: ${uiElementCount}`);
            console.log(`Total text length: ${textSoFar.length}`);
            console.log(`Expected position 35 text: "${textSoFar.substring(30, 40)}"`);

            return {
                totalNodes: nodeCount,
                uiElements: uiElementCount,
                textLength: textSoFar.length,
                textAt35: textSoFar.substring(30, 40),
                fullTextSoFar: textSoFar
            };
        """)

        print(f"🔧 Offset calculation debug: {offset_test}")

        # Now try to create a span at position 35
        print("\n📝 Creating second span at position 35...")
        second_span_result = self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.createAnnotation('new technology announcement', 35, 62, 'topic');
            }
            return null;
        """)
        print(f"🔧 Second span creation result: {second_span_result}")

        # Wait for rendering
        time.sleep(2)

        # Check if both spans are rendered correctly
        span_elements = self.driver.find_elements(By.CLASS_NAME, "annotation-span")
        print(f"🔧 Found {len(span_elements)} span elements after second span")

        # Verify the spans
        if len(span_elements) >= 2:
            span1_text = span_elements[0].text.replace('×', '').replace('positive', '').strip()
            span2_text = span_elements[1].text.replace('×', '').replace('topic', '').strip()
            print(f"🔧 Span 1 text: '{span1_text}'")
            print(f"🔧 Span 2 text: '{span2_text}'")

            # Check if the second span has the correct text
            expected_text = "new technology announcement"
            if span2_text == expected_text:
                print("✅ Second span has correct text - offset calculation is working!")
            else:
                print(f"❌ Second span has incorrect text. Expected: '{expected_text}', Got: '{span2_text}'")
        else:
            print(f"❌ Expected 2 spans, found {len(span_elements)}")

        print("✅ Offset calculation test completed!")

    def _verify_all_spans_present(self, expected_spans, full_text):
        """Helper method to verify all expected spans are present and correct."""
        text_element = self.driver.find_element(By.ID, "instance-text")
        span_elements = text_element.find_elements(By.CLASS_NAME, "annotation-span")

        print(f"🔧 Found {len(span_elements)} span elements, expected {len(expected_spans)}")

        # Verify we have the right number of spans
        assert len(span_elements) == len(expected_spans), \
            f"Expected {len(expected_spans)} spans, found {len(span_elements)}"

        # Verify each span is present and correct
        for i, expected_span in enumerate(expected_spans):
            span_element = span_elements[i]
            span_text = span_element.text
            span_label = span_element.get_attribute("data-label")

            print(f"🔧 Span {i+1}: text='{span_text}', label='{span_label}'")

            # Verify the span contains the expected text
            assert expected_span['text'] in span_text, \
                f"Span {i+1} should contain '{expected_span['text']}', got '{span_text}'"

            # Verify the span has the expected label
            assert span_label == expected_span['label'], \
                f"Span {i+1} should have label '{expected_span['label']}', got '{span_label}'"

        print(f"✅ All {len(expected_spans)} spans verified correctly!")


if __name__ == "__main__":
    # Run the tests directly
    pytest.main([__file__, "-v", "-s"])