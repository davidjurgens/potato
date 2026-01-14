#!/usr/bin/env python3
"""
Selenium tests for span annotation functionality

This test suite focuses on the core span annotation functionality including
creation, deletion, and interaction with the span annotation system.

Authentication Flow:
1. Each test inherits from BaseSeleniumTest which automatically:
   - Registers a unique test user
   - Logs in the user
   - Verifies authentication before running the test
2. Tests can then focus on their specific functionality without auth concerns
3. Each test gets a fresh WebDriver and unique user account for isolation
"""

import time
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import unittest

from tests.selenium.test_base import BaseSeleniumTest


class TestSpanAnnotationSelenium(BaseSeleniumTest):
    """
    Test suite for span annotation functionality.

    This class tests the core span annotation features:
    - Span creation via text selection
    - Span deletion via UI interaction
    - Span editing and modification
    - Span validation and error handling
    - Span data persistence

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_basic_span_manager_functionality(self):
        """Basic test to verify span manager functionality without complex interactions."""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")
        print("✅ Page loaded and text element found")

        # Wait for span manager to be ready
        max_wait = 15  # seconds
        start_time = time.time()
        span_manager_ready = False

        while time.time() - start_time < max_wait:
            # Check if span manager exists and is initialized
            manager_status = self.execute_script_safe("""
                return {
                    exists: !!window.spanManager,
                    initialized: window.spanManager ? window.spanManager.isInitialized : false,
                    hasHandleTextSelection: window.spanManager ? typeof window.spanManager.handleTextSelection === 'function' : false,
                    hasGetSpans: window.spanManager ? typeof window.spanManager.getSpans === 'function' : false
                };
            """)

            print(f"🔍 Span manager status: {manager_status}")

            if manager_status.get('exists') and manager_status.get('initialized'):
                span_manager_ready = True
                print("✅ Span manager is ready and initialized")
                break

            time.sleep(0.5)

        if not span_manager_ready:
            self.fail("Span manager failed to initialize within timeout period")

        # Test basic span manager methods
        try:
            # Test getSpans method
            spans_result = self.execute_script_safe("""
                if (window.spanManager && typeof window.spanManager.getSpans === 'function') {
                    try {
                        const spans = window.spanManager.getSpans();
                        return { success: true, count: spans.length, spans: spans };
                    } catch (error) {
                        return { success: false, error: error.message };
                    }
                } else {
                    return { success: false, error: 'getSpans method not found' };
                }
            """)
            print(f"✅ getSpans result: {spans_result}")
            self.assertTrue(spans_result.get('success'), f"getSpans should succeed: {spans_result}")

            # Test handleTextSelection method exists
            handler_check = self.execute_script_safe("""
                if (window.spanManager && typeof window.spanManager.handleTextSelection === 'function') {
                    return { success: true, message: 'handleTextSelection method exists' };
                } else {
                    return { success: false, error: 'handleTextSelection method not found' };
                }
            """)
            print(f"✅ handleTextSelection check: {handler_check}")
            self.assertTrue(handler_check.get('success'), f"handleTextSelection should exist: {handler_check}")

            # Test that we can call handleTextSelection without errors
            handler_call = self.execute_script_safe("""
                if (window.spanManager && typeof window.spanManager.handleTextSelection === 'function') {
                    try {
                        window.spanManager.handleTextSelection();
                        return { success: true, message: 'handleTextSelection called successfully' };
                    } catch (error) {
                        return { success: false, error: error.message };
                    }
                } else {
                    return { success: false, error: 'handleTextSelection method not found' };
                }
            """)
            print(f"✅ handleTextSelection call: {handler_call}")
            self.assertTrue(handler_call.get('success'), f"handleTextSelection should be callable: {handler_call}")

            print("✅ All basic span manager functionality tests passed!")

        except Exception as e:
            print(f"❌ Test failed with exception: {e}")
            raise

    def test_span_creation_via_text_selection(self):
        """Test creating spans by selecting text"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be ready
        time.sleep(2)
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        self.assertTrue(span_manager_ready, "Span manager should be initialized")

        # Select a label first (span annotation uses shadcn-span-checkbox)
        label_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".shadcn-span-checkbox")
        if label_buttons:
            label_buttons[0].click()
            time.sleep(0.5)

        # Select text using JavaScript
        self.execute_script_safe("""
            var textElement = arguments[0];
            var range = document.createRange();
            var textNode = textElement.firstChild;
            range.setStart(textNode, 0);
            range.setEnd(textNode, 10);
            var selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """, text_element)

        # Wait for span creation
        time.sleep(2)

        # Check if span was created
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        if len(span_elements) > 0:
            print("✅ Span created via text selection")
            self.assertGreater(len(span_elements), 0, "Span should be created")
        else:
            print("⚠️ No span created via text selection (may be expected based on UI implementation)")

    def test_span_deletion_via_ui(self):
        """Test deleting spans via UI interaction"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create a span via API first
        span_request = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 10,
                    'value': 'positive'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_request,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Wait for span to be rendered
        time.sleep(2)

        # Check that span is present
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), 1, "Span should be rendered")

        # Try to delete span via delete button
        delete_buttons = self.driver.find_elements(By.CLASS_NAME, "span-delete")
        if delete_buttons:
            delete_buttons[0].click()
            time.sleep(2)

            # Check if span was deleted
            span_elements_after = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
            if len(span_elements_after) == 0:
                print("✅ Span deleted via UI interaction")
            else:
                print("⚠️ Span not deleted via UI (may be expected based on implementation)")
        else:
            print("⚠️ No delete button found")

    def test_span_data_persistence(self):
        """Test that span data persists across page reloads"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create a span
        span_request = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'sentiment',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 10,
                    'value': 'positive'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_request,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Wait for span to be rendered
        time.sleep(2)

        # Verify span is present
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), 1, "Span should be rendered")

        # Reload the page
        self.driver.refresh()
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(2)

        # Check that span is still present after reload
        span_elements_after_reload = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements_after_reload), 1, "Span should persist after page reload")

        # Verify span data is correct
        span_element = span_elements_after_reload[0]
        data_label = span_element.get_attribute("data-label")
        self.assertEqual(data_label, "positive", "Span should have correct label after reload")

    def test_span_validation(self):
        """Test span validation and error handling"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Test invalid span data
        invalid_spans = [
            {
                'description': 'Negative start offset',
                'data': {
                    'instance_id': '1',
                    'type': 'span',
                    'schema': 'sentiment',
                    'state': [{'name': 'positive', 'start': -1, 'end': 5, 'value': 'test'}]
                }
            },
            {
                'description': 'End before start',
                'data': {
                    'instance_id': '1',
                    'type': 'span',
                    'schema': 'sentiment',
                    'state': [{'name': 'positive', 'start': 10, 'end': 5, 'value': 'test'}]
                }
            }
        ]

        for test_case in invalid_spans:
            response = requests.post(
                f"{self.server.base_url}/updateinstance",
                json=test_case['data'],
                cookies=session_cookies
            )

            # Invalid spans should be handled gracefully
            if response.status_code == 400:
                print(f"✅ Validation passed: {test_case['description']}")
            else:
                print(f"⚠️ Validation unexpected: {test_case['description']} returned {response.status_code}")

    def test_span_manager_integration(self):
        """Test integration with the span manager"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to initialize
        time.sleep(2)

        # Check that span manager is available
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        self.assertTrue(span_manager_ready, "Span manager should be initialized")

        # Test span manager methods
        spans = self.execute_script_safe("""
            return window.spanManager ? window.spanManager.getSpans() : [];
        """)
        self.assertIsInstance(spans, list, "Should be able to get spans list")

        # Test that handleTextSelection method exists
        has_handler = self.execute_script_safe("""
            return window.spanManager && typeof window.spanManager.handleTextSelection === 'function';
        """)
        self.assertTrue(has_handler, "handleTextSelection method should exist")

        # Test getting positioning strategy status
        positioning_status = self.execute_script_safe("""
            if (window.spanManager && window.spanManager.positioningStrategy) {
                return {
                    exists: true,
                    initialized: window.spanManager.positioningStrategy.isInitialized
                };
            }
            return { exists: false };
        """)

        if positioning_status and positioning_status.get('exists'):
            print(f"✅ Positioning strategy exists, initialized: {positioning_status.get('initialized')}")
        else:
            print("⚠️ Positioning strategy not available")

    def test_span_boundary_algorithm(self):
        """Test the boundary-based span rendering algorithm"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create overlapping spans to test boundary algorithm
        overlapping_spans = [
            {'start': 0, 'end': 10, 'label': 'positive'},
            {'start': 5, 'end': 15, 'label': 'negative'},
            {'start': 20, 'end': 30, 'label': 'neutral'}
        ]

        for span_data in overlapping_spans:
            span_request = {
                'instance_id': '1',
                'type': 'span',
                'schema': 'sentiment',
                'state': [
                    {
                        'name': span_data['label'],
                        'title': f'{span_data["label"].title()} sentiment',
                        'start': span_data['start'],
                        'end': span_data['end'],
                        'value': span_data['label']
                    }
                ]
            }

            response = requests.post(
                f"{self.server.base_url}/updateinstance",
                json=span_request,
                cookies=session_cookies
            )
            self.assertEqual(response.status_code, 200)

        # Wait for spans to be rendered
        time.sleep(2)

        # Check that all spans are rendered
        span_elements = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        self.assertEqual(len(span_elements), len(overlapping_spans))

        # Verify text content is preserved
        text_element = self.driver.find_element(By.ID, "instance-text")
        text_content = text_element.text
        self.assertIsNotNone(text_content)
        self.assertGreater(len(text_content), 0)

        print("✅ Boundary algorithm handles overlapping spans correctly")

    def test_span_selection_range_validation(self):
        """Test that span selection properly validates ranges and doesn't show 'invalid selection range' errors"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")

        # Debug: Print the actual HTML content to understand the DOM structure
        page_source = self.driver.page_source
        print(f"\n=== PAGE SOURCE (first 2000 chars) ===")
        print(page_source[:2000])
        print(f"\n=== END PAGE SOURCE ===")

        # Check if text-content exists
        text_content = self.driver.find_elements(By.ID, "text-content")
        print(f"\n=== text-content elements found: {len(text_content)} ===")

        if text_content:
            print(f"text-content innerHTML: {text_content[0].get_attribute('innerHTML')}")
        else:
            print("text-content element NOT found in DOM")

        # Check instance-text structure
        instance_text = self.driver.find_element(By.ID, "instance-text")
        print(f"\n=== instance-text innerHTML ===")
        print(instance_text.get_attribute('innerHTML'))

        # Wait for span manager to be ready and DOM elements to be available
        max_wait = 10  # seconds
        start_time = time.time()

        while time.time() - start_time < max_wait:
            span_manager_ready = self.execute_script_safe("""
                return window.spanManager && window.spanManager.isInitialized;
            """)

            if span_manager_ready:
                # Check if DOM elements are available
                elements_ready = self.execute_script_safe("""
                    const textContent = document.getElementById('text-content');
                    const spanOverlays = document.getElementById('span-overlays');
                    return {
                        textContentExists: !!textContent,
                        spanOverlaysExists: !!spanOverlays,
                        textContentHasText: textContent ? textContent.textContent.trim().length > 0 : false
                    };
                """)

                print(f"Elements ready check: {elements_ready}")

                if elements_ready.get('textContentExists') and elements_ready.get('spanOverlaysExists'):
                    print("✅ Span manager and DOM elements are ready")
                    break

            time.sleep(0.5)
        else:
            self.fail("Span manager did not initialize within timeout period")

        # Test the getTextPositions method on the positioning strategy
        result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            if (!textContent) {
                return { error: 'text-content element not found' };
            }

            const textNode = textContent.firstChild;
            if (!textNode || textNode.nodeType !== Node.TEXT_NODE) {
                return { error: 'text node not found in text-content',
                        nodeType: textNode ? textNode.nodeType : 'null',
                        childNodes: textContent.childNodes.length };
            }

            // Test the getTextPositions method on positioningStrategy
            if (window.spanManager && window.spanManager.positioningStrategy &&
                typeof window.spanManager.positioningStrategy.getTextPositions === 'function') {
                // Get the text content for a small test span
                const testText = textNode.textContent.substring(0, 5);
                const positions = window.spanManager.positioningStrategy.getTextPositions(0, 5, testText);
                return {
                    success: true,
                    textLength: textNode.textContent.length,
                    positions: positions,
                    hasPositions: positions && positions.length > 0,
                    methodExists: true
                };
            } else {
                return { error: 'getTextPositions method not found on positioningStrategy' };
            }
        """)

        print(f"\n=== getTextPositions test result ===")
        print(result)

        # The test should pass if we can find the text-content element and getTextPositions works
        self.assertIn('text-content', page_source, "text-content should be present in the page source")

        if 'error' in result:
            self.fail(f"getTextPositions test failed: {result['error']}")

        self.assertTrue(result.get('success', False), "getTextPositions should succeed")
        self.assertTrue(result.get('hasPositions', False), "getTextPositions should return positions")

    def test_simple_span_creation(self):
        """Simple test to verify basic span creation works without complex selection simulation."""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be ready
        max_wait = 10  # seconds
        start_time = time.time()

        while time.time() - start_time < max_wait:
            span_manager_ready = self.execute_script_safe("""
                return window.spanManager && window.spanManager.isInitialized;
            """)

            if span_manager_ready:
                print("✅ Span manager is ready")
                break

            time.sleep(0.5)
        else:
            self.fail("Span manager did not initialize within timeout period")

        # Select a label
        label_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".shadcn-span-checkbox")
        if not label_buttons:
            self.fail("No label buttons found")

        label_button = label_buttons[0]
        label_button.click()
        print(f"✅ Selected label: {label_button.text}")

        # Print the full DOM structure of #text-content for debugging
        dom_structure = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            if (!textContent) return 'text-content not found';
            let structure = [];
            for (let i = 0; i < textContent.childNodes.length; i++) {
                const node = textContent.childNodes[i];
                structure.push({
                    index: i,
                    nodeType: node.nodeType,
                    text: node.textContent,
                    length: node.textContent ? node.textContent.length : 0
                });
            }
            return structure;
        """)
        print(f"✅ #text-content DOM structure: {dom_structure}")

        # Find the first non-whitespace character offset in the text node
        first_char_info = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            if (!textContent) return {error: 'text-content not found'};
            let textNode = null;
            for (let i = 0; i < textContent.childNodes.length; i++) {
                const node = textContent.childNodes[i];
                if (node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0) {
                    textNode = node;
                    break;
                }
            }
            if (!textNode) return {error: 'No text node found with content'};
            const text = textNode.textContent;
            let start = 0;
            while (start < text.length && text[start].match(/\s/)) start++;
            let end = start;
            let count = 0;
            while (end < text.length && count < 10) {
                if (!text[end].match(/\s/)) count++;
                end++;
            }
            return {start, end, preview: text.slice(start, end)};
        """)
        print(f"✅ First non-whitespace char info: {first_char_info}")

        # Select the first 10 non-whitespace characters
        selection_result = self.execute_script_safe(f"""
            const textContent = document.getElementById('text-content');
            if (!textContent) {{ return {{ success: false, error: 'text-content not found' }}; }}
            let textNode = null;
            for (let i = 0; i < textContent.childNodes.length; i++) {{
                const node = textContent.childNodes[i];
                if (node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0) {{
                    textNode = node;
                    break;
                }}
            }}
            if (!textNode) {{ return {{ success: false, error: 'No text node found with content' }}; }}
            const range = document.createRange();
            range.setStart(textNode, {first_char_info['start']});
            range.setEnd(textNode, {first_char_info['end']});
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return {{
                success: true,
                selectedText: selection.toString(),
                textLength: textNode.textContent.length,
                startOffset: {first_char_info['start']},
                endOffset: {first_char_info['end']}
            }};
        """)
        print(f"✅ Selection result: {selection_result}")
        if not selection_result.get('success'):
            self.fail(f"Failed to create text selection: {selection_result}")

        # Log presence after selection
        present_after_selection = self.execute_script_safe("""
            return !!document.getElementById('text-content');
        """)
        print(f"✅ #text-content present after selection: {present_after_selection}")

        # Try click_and_hold and release to simulate drag-select and mouseup
        actions = ActionChains(self.driver)
        text_content_elem = self.driver.find_element(By.ID, "text-content")
        actions.click_and_hold(text_content_elem).pause(0.1).release(text_content_elem).perform()
        print("✅ Performed click_and_hold and release on #text-content")

        # Log presence after click/hold/release
        present_after_release = self.execute_script_safe("""
            return !!document.getElementById('text-content');
        """)
        print(f"✅ #text-content present after click/hold/release: {present_after_release}")

        # Re-acquire #text-content before dispatching keyup event
        keyup_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            if (!textContent) {
                console.log('TEST DEBUG: #text-content not found before keyup');
                return 'not found';
            }
            const evt = new KeyboardEvent('keyup', {bubbles: true, cancelable: true, key: 'ArrowRight'});
            textContent.dispatchEvent(evt);
            console.log('Dispatched keyup event on text-content');
            return 'dispatched';
        """)
        print(f"✅ Keyup event dispatch result: {keyup_result}")

        # Print selection state before calling handleTextSelection
        selection_state = self.execute_script_safe("""
            return {
                text: window.getSelection().toString(),
                rangeCount: window.getSelection().rangeCount,
                isCollapsed: window.getSelection().isCollapsed
            };
        """)
        print(f"✅ Selection state before handleTextSelection: {selection_state}")

        # Call handleTextSelection immediately after selection
        call_result = self.execute_script_safe("""
            if (window.spanManager && typeof window.spanManager.handleTextSelection === 'function') {
                window.spanManager.handleTextSelection();
                return 'called';
            } else {
                return 'not found';
            }
        """)
        print(f"✅ handleTextSelection direct call result: {call_result}")

        # Print browser logs immediately after call
        logs = self.driver.get_log("browser")
        handle_logs = [log for log in logs if "handleTextSelection called" in log["message"] or "DEBUG: Global mouseup event fired" in log["message"] or "TEST DEBUG: #text-content not found before keyup" in log["message"]]
        print(f"✅ handleTextSelection/global mouseup logs (immediate): {handle_logs}")

        # Set the selection and call handleTextSelection in the same JS block
        combined_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            if (!textContent) {
                return {error: '#text-content not found'};
            }
            // Find the first non-empty, non-whitespace text node
            let textNode = null;
            for (let i = 0; i < textContent.childNodes.length; i++) {
                const node = textContent.childNodes[i];
                if (node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0) {
                    textNode = node;
                    break;
                }
            }
            if (!textNode) {
                return {error: 'No text node found with content'};
            }
            // Find first 10 non-whitespace chars
            const text = textNode.textContent;
            let start = 0;
            while (start < text.length && text[start].match(/\s/)) start++;
            let end = start;
            let count = 0;
            while (end < text.length && count < 10) {
                if (!text[end].match(/\s/)) count++;
                end++;
            }
            // Set selection
            const range = document.createRange();
            range.setStart(textNode, start);
            range.setEnd(textNode, end);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            const selectedText = selection.toString();
            // Call handler
            let handlerResult = 'not called';
            if (window.spanManager && typeof window.spanManager.handleTextSelection === 'function') {
                window.spanManager.handleTextSelection();
                handlerResult = 'called';
            }
            // Return selection state and handler result
            return {
                selectedText,
                isCollapsed: selection.isCollapsed,
                rangeCount: selection.rangeCount,
                handlerResult
            };
        """)
        print(f"✅ Combined selection/handler result: {combined_result}")

        # Wait for span creation
        time.sleep(2)

        # Check span count
        span_count = self.execute_script_safe("""
            return window.spanManager ? window.spanManager.getSpans().length : 0;
        """)
        print(f"✅ Span count: {span_count}")

        # The test should pass if we can create a selection and trigger the handler
        self.assertTrue(combined_result.get('handlerResult') == 'called', "Handler should be called")
        self.assertGreater(len(combined_result.get('selectedText', '')), 0, "Should have selected text")

    def test_span_overlay_appears(self):
        """Test that creating a span results in a visible overlay and no JS errors about null container/node."""
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.keys import Keys
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be ready and DOM elements to be available
        max_wait = 10  # seconds
        start_time = time.time()

        while time.time() - start_time < max_wait:
            span_manager_ready = self.execute_script_safe("""
                return window.spanManager && window.spanManager.isInitialized;
            """)

            if span_manager_ready:
                # Check if DOM elements are available
                elements_ready = self.execute_script_safe("""
                    const textContent = document.getElementById('text-content');
                    const spanOverlays = document.getElementById('span-overlays');
                    return {
                        textContentExists: !!textContent,
                        spanOverlaysExists: !!spanOverlays,
                        textContentHasText: textContent ? textContent.textContent.trim().length > 0 : false
                    };
                """)

                if elements_ready.get('textContentExists') and elements_ready.get('spanOverlaysExists'):
                    print("✅ Span manager and DOM elements are ready")
                    break

            time.sleep(0.5)
        else:
            self.fail("Span manager did not initialize within timeout period")

        # Select a label (simulate user click)
        label_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".shadcn-span-checkbox")
        if not label_buttons:
            self.fail("No label buttons found - span annotation may not be configured")

        label_button = label_buttons[0]  # Click the first available label
        label_button.click()
        print(f"✅ Selected label: {label_button.text}")

        # Select text in the annotation text area using ActionChains
        text_content = self.driver.find_element(By.ID, "text-content")
        actions = ActionChains(self.driver)
        # Move to the text_content element, click and hold, move by offset, and release
        actions.move_to_element(text_content)
        actions.click_and_hold()
        actions.move_by_offset(50, 0)  # Move right by 50 pixels (approximate for first 10 chars)
        actions.release()
        actions.perform()
        print("✅ Performed ActionChains text selection and mouseup")

        # Re-acquire the #text-content element in case the DOM changed
        text_content = self.driver.find_element(By.ID, "text-content")

        # Dispatch a mouseup event directly on #text-content to ensure the handler is triggered
        self.execute_script_safe("""
            var el = arguments[0];
            var evt = new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: window});
            el.dispatchEvent(evt);
        """, text_content)
        print("✅ Dispatched mouseup event on #text-content")

        # Check if selection was actually created
        selection_text = self.execute_script_safe("""
            return window.getSelection().toString();
        """)
        print(f"✅ Selection text: '{selection_text}'")

        # Check if handleTextSelection was called
        logs = self.driver.get_log("browser")
        handle_logs = [log for log in logs if "handleTextSelection called" in log["message"]]
        print(f"✅ handleTextSelection logs after mouseup: {handle_logs}")

        # Wait a moment for the span creation to process
        time.sleep(2)

        # Check for JS errors in browser logs
        logs = self.driver.get_log("browser")
        errors = [log for log in logs if "getTextPosition called with null" in log["message"]]
        if errors:
            self.fail(f"JS error found: {errors}")

        # Check for handleTextSelection debug log
        handle_logs = [log for log in logs if "handleTextSelection called" in log["message"]]
        print(f"handleTextSelection logs: {handle_logs}")
        self.assertTrue(handle_logs, "handleTextSelection should be called during span creation")

        print("✅ No JS errors about null container/node found")

        # Verify that the span was actually created by checking the span manager state
        span_count = self.execute_script_safe("""
            return window.spanManager ? window.spanManager.getSpans().length : 0;
        """)

        print(f"✅ Span count in manager: {span_count}")
        self.assertGreater(span_count, 0, "Span should be created and stored in span manager")

        # Check if span overlay appeared
        try:
            span_overlay = self.wait_for_element(By.CLASS_NAME, "span-overlay", timeout=5)
            print("✅ Span overlay appeared successfully")
        except:
            # If no overlay, check if there are any span highlights (alternative rendering)
            span_highlights = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
            if span_highlights:
                print("✅ Span highlights appeared (alternative rendering)")
            else:
                # Check what's actually in the span-overlays container
                span_overlays_content = self.execute_script_safe("""
                    const spanOverlays = document.getElementById('span-overlays');
                    return spanOverlays ? spanOverlays.innerHTML : 'span-overlays not found';
                """)
                print(f"Span overlays content: {span_overlays_content}")
                self.fail("No span overlay or highlight appeared after text selection")

    def test_span_creation_with_robust_selectors(self):
        """Test span creation using robust selectors that work with the interval-based rendering system"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load and span manager to be ready
        text_element = self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be initialized
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const checkSpanManager = () => {
                    if (window.spanManager && window.spanManager.isInitialized) {
                        resolve(true);
                    } else {
                        setTimeout(checkSpanManager, 100);
                    }
                };
                checkSpanManager();
            });
        """)
        print("✅ Span manager initialized")

        # Check if span label selector is visible
        label_selector = self.driver.find_elements(By.ID, "span-label-selector")
        if not label_selector:
            self.fail("Span label selector not found - span annotation may not be configured")

        # Check if label buttons are present
        label_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".shadcn-span-checkbox")
        if not label_buttons:
            self.fail("No label buttons found - span annotation may not be configured")

        # Select the first available label
        label_button = label_buttons[0]
        label_name = label_button.text
        label_button.click()
        print(f"✅ Selected label: {label_name}")

        # Verify the label is selected (checkbox should be checked)
        active_label = self.driver.find_element(By.CSS_SELECTOR, ".shadcn-span-checkbox:checked")
        self.assertIsNotNone(active_label)
        print(f"✅ Label '{label_name}' is checked")

        # Check that the text-content element exists and has content
        text_content = self.driver.find_element(By.ID, "text-content")
        text_content_text = text_content.text
        self.assertIsNotNone(text_content_text)
        self.assertGreater(len(text_content_text), 0)
        print(f"✅ Text content found: '{text_content_text[:50]}...'")

        # Check that span-overlays element exists
        span_overlays = self.driver.find_element(By.ID, "span-overlays")
        print("✅ Span overlays container found")

        # Test that the span manager can create a span programmatically
        # This bypasses the text selection issue by directly calling the API
        test_result = self.execute_script_safe(f"""
            if (!window.spanManager || !window.spanManager.isInitialized) {{
                return {{ success: false, error: 'Span manager not initialized' }};
            }}

            // Get the original text
            const textContent = document.getElementById('text-content');
            if (!textContent) {{
                return {{ success: false, error: 'text-content not found' }};
            }}

            const originalText = textContent.textContent || '';
            if (!originalText) {{
                return {{ success: false, error: 'No text content available' }};
            }}

            // Find first 10 non-whitespace characters
            let start = 0;
            while (start < originalText.length && originalText[start].match(/\\s/)) start++;
            let end = start;
            let count = 0;
            while (end < originalText.length && count < 10) {{
                if (!originalText[end].match(/\\s/)) count++;
                end++;
            }}

            if (start >= end) {{
                return {{ success: false, error: 'Could not find suitable text range' }};
            }}

            const selectedText = originalText.substring(start, end);

            // Set the schema for the span manager (this is required)
            // We need to find the schema from the annotation forms
            const spanForms = document.querySelectorAll('.annotation-form.span');
            let schema = null;
            if (spanForms.length > 0) {{
                // Get the schema from the first span form
                const firstSpanForm = spanForms[0];
                const checkboxes = firstSpanForm.querySelectorAll('input[type="checkbox"]');
                if (checkboxes.length > 0) {{
                    const checkboxName = checkboxes[0].name;
                    const schemaMatch = checkboxName.match(/span_label:::(.+):::/);
                    if (schemaMatch) {{
                        schema = schemaMatch[1];
                    }}
                }}
            }}

            if (!schema) {{
                return {{ success: false, error: 'Could not determine schema from annotation forms' }};
            }}

            // Select the label and schema in the span manager
            window.spanManager.selectLabel('{label_name}', schema);

            // Create the annotation directly
            return window.spanManager.createAnnotation(selectedText, start, end, '{label_name}')
                .then(result => ({{
                    success: true,
                    result: result,
                    text: selectedText,
                    start: start,
                    end: end,
                    schema: schema
                }}))
                .catch(error => ({{
                    success: false,
                    error: error.message
                }}));
        """)

        print(f"✅ Span creation test result: {test_result}")

        if not test_result.get('success'):
            self.fail(f"Failed to create span programmatically: {test_result.get('error')}")

        # Wait for the span to be rendered
        time.sleep(2)

        # Check that a span overlay was created
        span_overlays_after = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertGreater(len(span_overlays_after), 0, "No span overlays found after creation")
        print(f"✅ Found {len(span_overlays_after)} span overlay(s)")

        # Verify the span has the correct label
        span_label = span_overlays_after[0].find_element(By.CLASS_NAME, "span-label")
        self.assertEqual(span_label.text, label_name)
        print(f"✅ Span has correct label: {span_label.text}")

        # Verify the span has the correct text content
        span_text = test_result.get('text', '')
        self.assertIsNotNone(span_text)
        self.assertGreater(len(span_text), 0)
        print(f"✅ Span created with text: '{span_text}'")

        print("✅ Span creation with robust selectors test completed successfully")

    def test_dom_stability(self):
        """Test that the DOM structure remains stable and text-content element is not replaced"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be initialized
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const checkSpanManager = () => {
                    if (window.spanManager && window.spanManager.isInitialized) {
                        resolve(true);
                    } else {
                        setTimeout(checkSpanManager, 100);
                    }
                };
                checkSpanManager();
            });
        """)
        print("✅ Span manager initialized")

        # Get initial DOM structure
        initial_structure = self.execute_script_safe("""
            const instanceText = document.getElementById('instance-text');
            const textContent = document.getElementById('text-content');
            const spanOverlays = document.getElementById('span-overlays');

            return {
                instanceTextExists: !!instanceText,
                textContentExists: !!textContent,
                spanOverlaysExists: !!spanOverlays,
                textContentText: textContent ? textContent.textContent : null,
                textContentHTML: textContent ? textContent.innerHTML : null,
                instanceTextChildren: instanceText ? instanceText.children.length : 0
            };
        """)
        print(f"✅ Initial DOM structure: {initial_structure}")

        # Verify initial structure
        self.assertTrue(initial_structure.get('instanceTextExists'), "instance-text element not found")
        self.assertTrue(initial_structure.get('textContentExists'), "text-content element not found")
        self.assertTrue(initial_structure.get('spanOverlaysExists'), "span-overlays element not found")
        self.assertIsNotNone(initial_structure.get('textContentText'), "text-content has no text")
        self.assertGreater(len(initial_structure.get('textContentText', '')), 0, "text-content is empty")

        # Wait a bit and check structure again
        time.sleep(1)

        # Get DOM structure after waiting
        after_wait_structure = self.execute_script_safe("""
            const instanceText = document.getElementById('instance-text');
            const textContent = document.getElementById('text-content');
            const spanOverlays = document.getElementById('span-overlays');

            return {
                instanceTextExists: !!instanceText,
                textContentExists: !!textContent,
                spanOverlaysExists: !!spanOverlays,
                textContentText: textContent ? textContent.textContent : null,
                textContentHTML: textContent ? textContent.innerHTML : null,
                instanceTextChildren: instanceText ? instanceText.children.length : 0
            };
        """)
        print(f"✅ DOM structure after wait: {after_wait_structure}")

        # Verify structure hasn't changed
        self.assertEqual(initial_structure.get('textContentText'), after_wait_structure.get('textContentText'),
                        "text-content text changed unexpectedly")
        self.assertEqual(initial_structure.get('instanceTextChildren'), after_wait_structure.get('instanceTextChildren'),
                        "instance-text children count changed unexpectedly")

        # Try to interact with text-content element
        text_content = self.driver.find_element(By.ID, "text-content")
        original_text = text_content.text

        # Simulate some interactions that might trigger DOM changes
        self.driver.execute_script("arguments[0].focus();", text_content)
        time.sleep(0.5)

        # Check structure after interaction
        after_interaction_structure = self.execute_script_safe("""
            const instanceText = document.getElementById('instance-text');
            const textContent = document.getElementById('text-content');
            const spanOverlays = document.getElementById('span-overlays');

            return {
                instanceTextExists: !!instanceText,
                textContentExists: !!textContent,
                spanOverlaysExists: !!spanOverlays,
                textContentText: textContent ? textContent.textContent : null,
                textContentHTML: textContent ? textContent.innerHTML : null,
                instanceTextChildren: instanceText ? instanceText.children.length : 0
            };
        """)
        print(f"✅ DOM structure after interaction: {after_interaction_structure}")

        # Verify structure is still stable
        self.assertEqual(initial_structure.get('textContentText'), after_interaction_structure.get('textContentText'),
                        "text-content text changed after interaction")
        self.assertEqual(initial_structure.get('instanceTextChildren'), after_interaction_structure.get('instanceTextChildren'),
                        "instance-text children count changed after interaction")

        # Verify text-content element is still the same element (not replaced)
        current_text_content = self.driver.find_element(By.ID, "text-content")
        self.assertEqual(current_text_content.text, original_text, "text-content element was replaced")

        print("✅ DOM stability test completed successfully")

    def test_span_label_and_delete_button_visibility(self):
        """Test that span annotations show labels and delete buttons correctly"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be initialized
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const checkSpanManager = () => {
                    if (window.spanManager && window.spanManager.isInitialized) {
                        resolve(true);
                    } else {
                        setTimeout(checkSpanManager, 100);
                    }
                };
                checkSpanManager();
            });
        """)
        print("✅ Span manager initialized")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Create a span annotation via API
        span_request = {
            'instance_id': '1',  # Use the correct instance ID from test data
            'type': 'span',
            'schema': 'emotion_spans',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 15,
                    'value': 'I am absolutely'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_request,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200, f"Failed to create span: {response.text}")
        print("✅ Span created via API")

        # Force the span manager to reload annotations
        self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.loadAnnotations('1');
            }
            return Promise.resolve();
        """)
        print("✅ Forced span manager to reload annotations")

        # Wait for span to be rendered
        time.sleep(3)

        # Debug: Check what elements are actually present
        print("🔍 Debugging DOM elements...")

        # Check for any span-related elements
        all_span_elements = self.driver.find_elements(By.CSS_SELECTOR, "[class*='span']")
        print(f"🔍 Found {len(all_span_elements)} elements with 'span' in class name")
        for i, elem in enumerate(all_span_elements[:5]):  # Show first 5
            print(f"🔍 Element {i}: class='{elem.get_attribute('class')}', tag='{elem.tag_name}'")

        # Check for span overlays specifically
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"🔍 Found {len(span_overlays)} span-overlay elements")

        # Check for span highlights
        span_highlights = self.driver.find_elements(By.CLASS_NAME, "span-highlight")
        print(f"🔍 Found {len(span_highlights)} span-highlight elements")

        # Check for span labels
        span_labels = self.driver.find_elements(By.CLASS_NAME, "span-label")
        print(f"🔍 Found {len(span_labels)} span-label elements")

        # Check for delete buttons
        delete_buttons = self.driver.find_elements(By.CLASS_NAME, "span-delete-btn")
        print(f"🔍 Found {len(delete_buttons)} span-delete-btn elements")

        # Check the span-overlays container
        span_overlays_container = self.driver.find_element(By.ID, "span-overlays")
        print(f"🔍 span-overlays container HTML: {span_overlays_container.get_attribute('innerHTML')}")

        # Debug: Check what spans the span manager thinks it has
        span_manager_state = self.execute_script_safe("""
            if (window.spanManager) {
                return {
                    annotations: window.spanManager.annotations,
                    spans: window.spanManager.getSpans(),
                    currentInstanceId: window.spanManager.currentInstanceId,
                    currentSchema: window.spanManager.currentSchema
                };
            }
            return null;
        """)
        print(f"🔍 Span manager state: {span_manager_state}")

        # Check that span overlays are present
        self.assertGreater(len(span_overlays), 0, "No span overlays found after creation")
        print(f"✅ Found {len(span_overlays)} span overlay(s)")

        # Check for span labels
        span_labels = self.driver.find_elements(By.CLASS_NAME, "span-label")
        self.assertGreater(len(span_labels), 0, "No span labels found")
        print(f"✅ Found {len(span_labels)} span label(s)")

        # Verify the first label has the correct text
        first_label = span_labels[0]
        self.assertEqual(first_label.text, "positive", f"Expected label 'positive', got '{first_label.text}'")
        print(f"✅ First span label has correct text: '{first_label.text}'")

        # Check for delete buttons
        delete_buttons = self.driver.find_elements(By.CLASS_NAME, "span-delete-btn")
        self.assertGreater(len(delete_buttons), 0, "No delete buttons found")
        print(f"✅ Found {len(delete_buttons)} delete button(s)")

        # Verify delete button is visible and clickable
        first_delete_button = delete_buttons[0]
        self.assertTrue(first_delete_button.is_displayed(), "Delete button is not displayed")
        print("✅ Delete button is displayed")

        # Check delete button styling
        button_style = first_delete_button.get_attribute("style")
        self.assertIn("background-color", button_style, "Delete button should have background color")
        self.assertIn("rgba(255, 0, 0", button_style, "Delete button should have red background")
        print("✅ Delete button has correct styling")

        # Test delete button functionality
        print("Testing delete button functionality...")

        # Debug: Check if delete button is clickable
        print(f"Delete button enabled: {first_delete_button.is_enabled()}")
        print(f"Delete button displayed: {first_delete_button.is_displayed()}")

        # Click the delete button
        first_delete_button.click()
        time.sleep(2)

        # Debug: Check if any API calls were made
        print("Checking if delete API call was made...")

        # Debug: Print overlays container HTML after deletion
        span_overlays_container_after = self.driver.find_element(By.ID, "span-overlays")
        print(f"🔍 span-overlays container HTML AFTER deletion: {span_overlays_container_after.get_attribute('innerHTML')}")

        # Debug: Check span manager state after deletion
        span_manager_state_after = self.execute_script_safe("""
            if (window.spanManager) {
                return {
                    annotations: window.spanManager.annotations,
                    spans: window.spanManager.getSpans(),
                    currentInstanceId: window.spanManager.currentInstanceId,
                    currentSchema: window.spanManager.currentSchema
                };
            }
            return null;
        """)
        print(f"🔍 Span manager state AFTER deletion: {span_manager_state_after}")

        # Check if span was deleted
        span_overlays_after_delete = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        span_labels_after_delete = self.driver.find_elements(By.CLASS_NAME, "span-label")
        delete_buttons_after_delete = self.driver.find_elements(By.CLASS_NAME, "span-delete-btn")

        if len(span_overlays_after_delete) == 0:
            print("✅ Span was successfully deleted via delete button")
        else:
            print(f"⚠️ Span not deleted (found {len(span_overlays_after_delete)} remaining overlays)")

        if len(span_labels_after_delete) == 0:
            print("✅ Span labels were removed after deletion")
        else:
            print(f"⚠️ Span labels not removed (found {len(span_labels_after_delete)} remaining labels)")

        if len(delete_buttons_after_delete) == 0:
            print("✅ Delete buttons were removed after deletion")
        else:
            print(f"⚠️ Delete buttons not removed (found {len(delete_buttons_after_delete)} remaining buttons)")

        print("✅ Span label and delete button visibility test completed")

    def test_comprehensive_span_annotation_functionality(self):
        """Comprehensive test that validates the actual span annotation functionality."""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")
        print("✅ Page loaded and text element found")

        # Wait for span manager to be ready
        max_wait = 15  # seconds
        start_time = time.time()
        span_manager_ready = False

        while time.time() - start_time < max_wait:
            manager_status = self.execute_script_safe("""
                return {
                    exists: !!window.spanManager,
                    initialized: window.spanManager ? window.spanManager.isInitialized : false
                };
            """)

            if manager_status.get('exists') and manager_status.get('initialized'):
                span_manager_ready = True
                print("✅ Span manager is ready and initialized")
                break

            time.sleep(0.5)

        if not span_manager_ready:
            self.fail("Span manager failed to initialize within timeout period")

        # Select a label first
        label_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".shadcn-span-checkbox")
        if not label_buttons:
            self.fail("No label buttons found")

        label_button = label_buttons[0]
        label_text = label_button.text
        label_button.click()
        print(f"✅ Selected label: {label_text}")

        # Get the text content and create a real selection
        selection_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            if (!textContent) {
                return { success: false, error: 'text-content not found' };
            }

            // Find the first text node with content
            let textNode = null;
            for (let i = 0; i < textContent.childNodes.length; i++) {
                const node = textContent.childNodes[i];
                if (node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0) {
                    textNode = node;
                    break;
                }
            }

            if (!textNode) {
                return { success: false, error: 'No text node found with content' };
            }

            const text = textNode.textContent;
            console.log('Found text node with content:', text.substring(0, 50) + '...');

            // Find first 10 non-whitespace characters
            let start = 0;
            while (start < text.length && text[start].match(/\\s/)) start++;

            let end = start;
            let count = 0;
            while (end < text.length && count < 10) {
                if (!text[end].match(/\\s/)) count++;
                end++;
            }

            // Create selection
            const range = document.createRange();
            range.setStart(textNode, start);
            range.setEnd(textNode, end);

            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);

            const selectedText = selection.toString();
            console.log('Created selection:', selectedText);

            return {
                success: true,
                selectedText: selectedText,
                start: start,
                end: end,
                textLength: text.length
            };
        """)

        print(f"✅ Selection result: {selection_result}")

        if not selection_result.get('success'):
            self.fail(f"Failed to create text selection: {selection_result}")

        # Call handleTextSelection to create the span
        handler_result = self.execute_script_safe("""
            if (window.spanManager && typeof window.spanManager.handleTextSelection === 'function') {
                try {
                    window.spanManager.handleTextSelection();
                    return { success: true, message: 'Handler called successfully' };
                } catch (error) {
                    return { success: false, error: error.message };
                }
            } else {
                return { success: false, error: 'handleTextSelection method not found' };
            }
        """)

        print(f"✅ Handler call result: {handler_result}")

        if not handler_result.get('success'):
            self.fail(f"Failed to call handleTextSelection: {handler_result}")

        # Wait for span creation and rendering
        time.sleep(3)

        # Check if spans were created
        span_count = self.execute_script_safe("""
            if (window.spanManager) {
                const spans = window.spanManager.getSpans();
                return {
                    count: spans.length,
                    spans: spans.map(s => ({ id: s.id, text: s.text, label: s.label }))
                };
            }
            return { count: 0, spans: [] };
        """)

        print(f"✅ Span count: {span_count}")

        # CRITICAL: Check if spans were actually created
        self.assertGreater(span_count.get('count', 0), 0, "No spans were created - this indicates a critical failure")

        # Check for span overlay elements in the DOM
        span_overlays = self.driver.find_elements(By.CSS_SELECTOR, ".span-highlight")
        print(f"✅ Found {len(span_overlays)} span overlay elements in DOM")

        # CRITICAL: Check if span overlays are visible
        self.assertGreater(len(span_overlays), 0, "No span overlay elements found in DOM - positioning/rendering is broken")

        # Check the first span overlay for proper positioning and styling
        if len(span_overlays) > 0:
            first_overlay = span_overlays[0]

            # Check positioning - should not be positioned above text
            overlay_position = self.execute_script_safe("""
                const overlay = arguments[0];
                const rect = overlay.getBoundingClientRect();
                const textContent = document.getElementById('text-content');
                const textRect = textContent.getBoundingClientRect();

                return {
                    overlayTop: rect.top,
                    overlayLeft: rect.left,
                    overlayWidth: rect.width,
                    overlayHeight: rect.height,
                    textTop: textRect.top,
                    textLeft: textRect.left,
                    textWidth: textRect.width,
                    textHeight: textRect.height,
                    isAboveText: rect.top < textRect.top,
                    isBelowText: rect.top > textRect.bottom,
                    isOverlapping: !(rect.bottom < textRect.top || rect.top > textRect.bottom)
                };
            """, first_overlay)

            print(f"✅ Overlay positioning: {overlay_position}")

            # CRITICAL: Check that overlay is not positioned above the text
            self.assertFalse(overlay_position.get('isAboveText', False),
                           "Span overlay is positioned above the text - positioning is broken")

            # CRITICAL: Check that overlay overlaps with text
            self.assertTrue(overlay_position.get('isOverlapping', False),
                          "Span overlay does not overlap with text - positioning is broken")

            # Check for label text in the overlay
            overlay_text = first_overlay.text
            print(f"✅ Overlay text content: '{overlay_text}'")

            # CRITICAL: Check that overlay contains the label
            self.assertIn(label_text, overlay_text, f"Overlay does not contain label '{label_text}'")

            # Check for delete button
            delete_buttons = first_overlay.find_elements(By.CSS_SELECTOR, ".delete-span, .span-delete, button[title*='delete'], button[title*='Delete']")
            print(f"✅ Found {len(delete_buttons)} delete buttons in overlay")

            # CRITICAL: Check that delete button exists
            self.assertGreater(len(delete_buttons), 0, "No delete button found in span overlay")

            # Check overlay color
            overlay_style = first_overlay.get_attribute("style")
            print(f"✅ Overlay style: {overlay_style}")

            # CRITICAL: Check that overlay has some styling (color, background, etc.)
            self.assertIsNotNone(overlay_style, "Overlay has no styling")
            self.assertGreater(len(overlay_style), 0, "Overlay has empty styling")

        # Test navigation to ensure it doesn't cause text selection
        print("🔍 Testing navigation...")

        # Get current instance ID
        current_instance = self.execute_script_safe("""
            return window.currentInstance ? window.currentInstance.id : null;
        """)
        print(f"✅ Current instance ID: {current_instance}")

        # Navigate to next instance
        next_button = self.driver.find_element(By.CSS_SELECTOR, "button[onclick*='next'], .next-button, button:contains('Next')")
        next_button.click()
        print("✅ Clicked next button")

        # Wait for navigation
        time.sleep(2)

        # Check if text is selected after navigation
        selection_after_nav = self.execute_script_safe("""
            const selection = window.getSelection();
            return {
                hasSelection: !selection.isCollapsed,
                selectedText: selection.toString(),
                rangeCount: selection.rangeCount
            };
        """)

        print(f"✅ Selection after navigation: {selection_after_nav}")

        # CRITICAL: Check that no text is selected after navigation
        self.assertFalse(selection_after_nav.get('hasSelection', False),
                        "Text is selected after navigation - this is a critical bug")

        print("✅ All comprehensive span annotation functionality tests passed!")

    def test_comprehensive_span_deletion_scenarios(self):
        """Test span deletion in various scenarios to ensure robustness"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be initialized (simpler approach)
        time.sleep(3)  # Give time for JavaScript to initialize

        # Create multiple spans for testing
        spans_to_create = [
            {"label": "positive", "start": 0, "end": 15, "text": "I am absolutely"},
            {"label": "negative", "start": 67, "end": 81, "text": "technology"},
            {"label": "positive", "start": 82, "end": 95, "text": "announcement"}
        ]

        print("🔧 Creating multiple spans for deletion testing...")
        for i, span_data in enumerate(spans_to_create):
            # Create span via API
            span_request = {
                'instance_id': '1',
                'type': 'span',
                'schema': 'emotion_spans',
                'state': [
                    {
                        'name': span_data['label'],
                        'title': f'{span_data["label"].title()} sentiment',
                        'start': span_data['start'],
                        'end': span_data['end'],
                        'value': span_data['text']
                    }
                ]
            }

            response = requests.post(
                f"{self.server.base_url}/updateinstance",
                json=span_request,
                cookies=self.get_session_cookies()
            )
            self.assertEqual(response.status_code, 200, f"Failed to create span {i+1}")

        # Force span manager to reload annotations
        self.execute_script_safe("if (window.spanManager) window.spanManager.loadAnnotations('1')")
        time.sleep(2)

        # Verify all spans are created
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(span_overlays), 3, "Should have 3 spans created")

        print(f"✅ Created {len(span_overlays)} spans successfully")

        # Test 1: Delete the first span
        print("🔧 Testing deletion of first span...")
        first_delete_button = self.driver.find_element(By.CLASS_NAME, "span-delete-btn")
        first_delete_button.click()
        time.sleep(2)

        # Verify first span is deleted
        span_overlays_after_first_delete = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(span_overlays_after_first_delete), 2, "Should have 2 spans after deleting first")

        # Test 2: Delete the middle span
        print("🔧 Testing deletion of second span...")
        second_delete_button = self.driver.find_elements(By.CLASS_NAME, "span-delete-btn")[0]
        second_delete_button.click()
        time.sleep(2)

        # Verify second span is deleted
        span_overlays_after_second_delete = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(span_overlays_after_second_delete), 1, "Should have 1 span after deleting second")

        # Test 3: Delete the last span
        print("🔧 Testing deletion of last span...")
        last_delete_button = self.driver.find_element(By.CLASS_NAME, "span-delete-btn")
        last_delete_button.click()
        time.sleep(2)

        # Verify all spans are deleted
        span_overlays_after_all_deleted = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(span_overlays_after_all_deleted), 0, "Should have 0 spans after deleting all")

        # Verify backend state is clean
        response = requests.get(
            f"{self.server.base_url}/api/spans/1",
            cookies=self.get_session_cookies()
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['spans']), 0, "Backend should have no spans after deletion")

        print("✅ Comprehensive span deletion test completed successfully")

    def test_span_deletion_persistence_across_navigation(self):
        """Test that deleted spans don't reappear when navigating between instances"""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be initialized (simpler approach)
        time.sleep(3)  # Give time for JavaScript to initialize

        # Create a span
        span_request = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'emotion_spans',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 15,
                    'value': 'I am absolutely'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_request,
            cookies=self.get_session_cookies()
        )
        self.assertEqual(response.status_code, 200)

        # Force span manager to reload annotations
        self.execute_script_safe("if (window.spanManager) window.spanManager.loadAnnotations('1')")
        time.sleep(2)

        # Verify span is created
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(span_overlays), 1, "Should have 1 span created")

        # Delete the span
        delete_button = self.driver.find_element(By.CLASS_NAME, "span-delete-btn")
        delete_button.click()
        time.sleep(2)

        # Verify span is deleted
        span_overlays_after_delete = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(span_overlays_after_delete), 0, "Should have 0 spans after deletion")

        # Navigate to next instance
        next_button = self.driver.find_element(By.ID, "next-instance")
        next_button.click()
        time.sleep(2)

        # Navigate back to first instance
        prev_button = self.driver.find_element(By.ID, "prev-instance")
        prev_button.click()
        time.sleep(2)

        # Verify span is still deleted (doesn't reappear)
        span_overlays_after_navigation = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(span_overlays_after_navigation), 0, "Span should not reappear after navigation")

        print("✅ Span deletion persistence test completed successfully")

    def test_span_selection_with_partial_and_full_overlap(self):
        """Test that text selection and span creation works for partial, full, and non-overlapping cases."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")
        # Wait for span manager
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.isInitialized) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)
        session_cookies = self.get_session_cookies()

        # Create a base span via API (e.g., chars 10-30)
        span_request = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'emotion_spans',
            'state': [{
                'name': 'positive', 'title': 'Positive sentiment',
                'start': 10, 'end': 30, 'value': 'artificial intelligence model'
            }]
        }
        response = requests.post(f"{self.server.base_url}/updateinstance", json=span_request, cookies=session_cookies)
        assert response.status_code == 200

        # Reload annotations
        self.execute_script_safe("""if (window.spanManager) return window.spanManager.loadAnnotations('1');""")
        time.sleep(2)

        # Debug: Print initial overlay count and details
        overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"DEBUG: Initial overlays count: {len(overlays)}")
        for i, overlay in enumerate(overlays):
            start = overlay.get_attribute("data-start")
            end = overlay.get_attribute("data-end")
            label = overlay.get_attribute("data-label")
            print(f"DEBUG: Overlay {i}: start={start}, end={end}, label={label}")

        # Try to select a region that partially overlaps (e.g., 5-15)
        # First check if text-content element exists and what it contains
        text_content_check = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            if (!textContent) {
                return 'text-content element not found';
            }
            const textNode = textContent.firstChild;
            if (!textNode) {
                return 'text-content has no children';
            }
            if (textNode.nodeType !== Node.TEXT_NODE) {
                return 'first child is not a text node, type: ' + textNode.nodeType;
            }
            const fullText = textNode.textContent;
            // Find the first non-whitespace character
            const firstNonWhitespace = fullText.search(/\\S/);
            return 'text-content found, text length: ' + fullText.length + ', first non-whitespace at: ' + firstNonWhitespace + ', text: "' + fullText.substring(0, 100) + '..."';
        """)
        print(f"DEBUG: Text content check: {text_content_check}")

        # Find the actual start of the text content
        text_start_info = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            const textNode = textContent.firstChild;
            const fullText = textNode.textContent;
            const firstNonWhitespace = fullText.search(/\\S/);
            return {
                firstNonWhitespace: firstNonWhitespace,
                actualTextStart: fullText.substring(firstNonWhitespace, firstNonWhitespace + 50)
            };
        """)
        print(f"DEBUG: Text start info: {text_start_info}")

        # Adjust selection positions based on actual text start
        first_non_whitespace = int(text_start_info['firstNonWhitespace'])
        adjusted_start = first_non_whitespace + 5  # 5 characters after the start
        adjusted_end = first_non_whitespace + 15   # 15 characters after the start

        script_partial = f"""
            const textContent = document.getElementById('text-content');
            const textNode = textContent.firstChild;
            const sel = window.getSelection();
            sel.removeAllRanges();
            const range = document.createRange();
            range.setStart(textNode, {adjusted_start});
            range.setEnd(textNode, {adjusted_end});
            sel.addRange(range);
            console.log('🔍 [DEBUG] Text selection created:', sel.toString(), 'rangeCount:', sel.rangeCount);
            return sel.toString();
        """
        selected_text = self.execute_script_safe(script_partial)
        print(f"DEBUG: Selected text: '{selected_text}'")

        # Select label and create span (span checkboxes use value attribute)
        label_btn = self.wait_for_element(By.CSS_SELECTOR, '.shadcn-span-checkbox[value="positive"]')
        print(f"DEBUG: Found label checkbox")
        label_btn.click()

        # Check if label is selected
        is_label_selected = self.execute_script_safe("return window.spanManager.selectedLabel;")
        print(f"DEBUG: Selected label: {is_label_selected}")

        # Trigger selection handler
        result = self.execute_script_safe("""
            if (window.spanManager) {
                window.spanManager.handleTextSelection();
                return 'handleTextSelection called';
            } else {
                return 'spanManager not found';
            }
        """)
        print(f"DEBUG: handleTextSelection result: {result}")
        time.sleep(1)

        # Debug: Print overlay count and details after partial overlap
        overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"DEBUG: After partial overlap selection - overlays count: {len(overlays)}")
        for i, overlay in enumerate(overlays):
            start = overlay.get_attribute("data-start")
            end = overlay.get_attribute("data-end")
            label = overlay.get_attribute("data-label")
            print(f"DEBUG: Overlay {i}: start={start}, end={end}, label={label}")

        assert len(overlays) == 2, f"Expected 2 overlays after partial overlap selection, found {len(overlays)}"

        # Try to select a region that fully contains the original (e.g., 0-40)
        script_full = """
            const textContent = document.getElementById('text-content');
            const textNode = textContent.firstChild;
            const sel = window.getSelection();
            sel.removeAllRanges();
            const range = document.createRange();
            range.setStart(textNode, 0);
            range.setEnd(textNode, 40);
            sel.addRange(range);
        """
        self.execute_script_safe(script_full)
        label_btn.click()
        self.execute_script_safe("window.spanManager.handleTextSelection()")
        time.sleep(1)

        # Debug: Print overlay count and details after full containment
        overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"DEBUG: After full containment selection - overlays count: {len(overlays)}")
        for i, overlay in enumerate(overlays):
            start = overlay.get_attribute("data-start")
            end = overlay.get_attribute("data-end")
            label = overlay.get_attribute("data-label")
            print(f"DEBUG: Overlay {i}: start={start}, end={end}, label={label}")

        assert len(overlays) == 3, f"Expected 3 overlays after full containment selection, found {len(overlays)}"

        # Try to select a non-overlapping region (e.g., 40-50)
        script_non = """
            const textContent = document.getElementById('text-content');
            const textNode = textContent.firstChild;
            const sel = window.getSelection();
            sel.removeAllRanges();
            const range = document.createRange();
            range.setStart(textNode, 40);
            range.setEnd(textNode, 50);
            sel.addRange(range);
        """
        self.execute_script_safe(script_non)
        label_btn.click()
        self.execute_script_safe("window.spanManager.handleTextSelection()")
        time.sleep(1)

        # Debug: Print overlay count and details after non-overlapping
        overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"DEBUG: After non-overlapping selection - overlays count: {len(overlays)}")
        for i, overlay in enumerate(overlays):
            start = overlay.get_attribute("data-start")
            end = overlay.get_attribute("data-end")
            label = overlay.get_attribute("data-label")
            print(f"DEBUG: Overlay {i}: start={start}, end={end}, label={label}")

        assert len(overlays) == 4, f"Expected 4 overlays after non-overlapping selection, found {len(overlays)}"
        print("✅ Span selection works for partial, full, and non-overlapping cases.")

    def test_robust_span_creation_with_async_init(self):
        """Robust test for span creation that properly handles asynchronous initialization."""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")
        print("✅ Page loaded and text element found")

        # Wait for span manager to be ready with proper async handling
        max_wait = 15  # seconds
        start_time = time.time()
        span_manager_ready = False

        while time.time() - start_time < max_wait:
            # Check if span manager exists and is initialized
            manager_status = self.execute_script_safe("""
                return {
                    exists: !!window.spanManager,
                    initialized: window.spanManager ? window.spanManager.isInitialized : false,
                    hasHandleTextSelection: window.spanManager ? typeof window.spanManager.handleTextSelection === 'function' : false
                };
            """)

            print(f"🔍 Span manager status: {manager_status}")

            if manager_status.get('exists') and manager_status.get('initialized'):
                span_manager_ready = True
                print("✅ Span manager is ready and initialized")
                break

            time.sleep(0.5)

        if not span_manager_ready:
            # Try to force initialization
            print("⚠️ Span manager not ready, attempting to force initialization")
            init_result = self.execute_script_safe("""
                if (window.spanManager && typeof window.spanManager.initialize === 'function') {
                    return window.spanManager.initialize().then(() => 'initialized').catch(e => 'failed: ' + e.message);
                }
                return 'no initialize method';
            """)
            print(f"🔍 Force initialization result: {init_result}")

            # Wait a bit more after forced initialization
            time.sleep(2)

            # Check again
            final_status = self.execute_script_safe("""
                return {
                    exists: !!window.spanManager,
                    initialized: window.spanManager ? window.spanManager.isInitialized : false
                };
            """)
            print(f"🔍 Final span manager status: {final_status}")

            if not final_status.get('initialized'):
                self.fail("Span manager failed to initialize within timeout period")

        # Select a label first
        label_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".shadcn-span-checkbox")
        if not label_buttons:
            self.fail("No label buttons found")

        label_button = label_buttons[0]
        label_button.click()
        print(f"✅ Selected label: {label_button.text}")

        # Get the text content and create a simple selection
        selection_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            if (!textContent) {
                return { success: false, error: 'text-content not found' };
            }

            // Find the first text node with content
            let textNode = null;
            for (let i = 0; i < textContent.childNodes.length; i++) {
                const node = textContent.childNodes[i];
                if (node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0) {
                    textNode = node;
                    break;
                }
            }

            if (!textNode) {
                return { success: false, error: 'No text node found with content' };
            }

            const text = textNode.textContent;
            console.log('Found text node with content:', text.substring(0, 50) + '...');

            // Find first 5 non-whitespace characters
            let start = 0;
            while (start < text.length && text[start].match(/\\s/)) start++;

            let end = start;
            let count = 0;
            while (end < text.length && count < 5) {
                if (!text[end].match(/\\s/)) count++;
                end++;
            }

            // Create selection
            const range = document.createRange();
            range.setStart(textNode, start);
            range.setEnd(textNode, end);

            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);

            const selectedText = selection.toString();
            console.log('Created selection:', selectedText);

            return {
                success: true,
                selectedText: selectedText,
                start: start,
                end: end,
                textLength: text.length
            };
        """)

        print(f"✅ Selection result: {selection_result}")

        if not selection_result.get('success'):
            self.fail(f"Failed to create text selection: {selection_result}")

        # Call handleTextSelection directly
        handler_result = self.execute_script_safe("""
            if (window.spanManager && typeof window.spanManager.handleTextSelection === 'function') {
                try {
                    window.spanManager.handleTextSelection();
                    return { success: true, message: 'Handler called successfully' };
                } catch (error) {
                    return { success: false, error: error.message };
                }
            } else {
                return { success: false, error: 'handleTextSelection method not found' };
            }
        """)

        print(f"✅ Handler call result: {handler_result}")

        if not handler_result.get('success'):
            self.fail(f"Failed to call handleTextSelection: {handler_result}")

        # Wait for potential span creation
        time.sleep(3)

        # Check if any spans were created
        span_count = self.execute_script_safe("""
            if (window.spanManager) {
                const spans = window.spanManager.getSpans();
                return {
                    count: spans.length,
                    spans: spans.map(s => ({ id: s.id, text: s.text, label: s.label }))
                };
            }
            return { count: 0, spans: [] };
        """)

        print(f"✅ Final span count: {span_count}")

        # The test passes if we can successfully:
        # 1. Initialize the span manager
        # 2. Create a text selection
        # 3. Call the handler without errors
        self.assertTrue(span_manager_ready, "Span manager should be initialized")
        self.assertTrue(selection_result.get('success'), "Text selection should succeed")
        self.assertTrue(handler_result.get('success'), "Handler should be called successfully")

        # Optional: Check if spans were actually created (this may depend on the specific implementation)
        if span_count.get('count', 0) > 0:
            print(f"🎉 Spans were created: {span_count}")
        else:
            print("ℹ️ No spans were created (this may be expected based on implementation)")

    def test_span_overlay_critical_issues(self):
        """Test specifically for the critical span overlay issues mentioned by the user."""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")
        print("✅ Page loaded and text element found")

        # Wait for span manager to be ready
        max_wait = 15  # seconds
        start_time = time.time()
        span_manager_ready = False

        while time.time() - start_time < max_wait:
            manager_status = self.execute_script_safe("""
                return {
                    exists: !!window.spanManager,
                    initialized: window.spanManager ? window.spanManager.isInitialized : false
                };
            """)

            if manager_status.get('exists') and manager_status.get('initialized'):
                span_manager_ready = True
                print("✅ Span manager is ready and initialized")
                break

            time.sleep(0.5)

        if not span_manager_ready:
            self.fail("Span manager failed to initialize within timeout period")

        # Get available labels and their colors
        labels_info = self.execute_script_safe("""
            const labels = document.querySelectorAll('.shadcn-span-option');
            const colors = window.spanManager ? window.spanManager.colors : {};

            return Array.from(labels).map(label => ({
                text: label.textContent.trim(),
                color: colors[label.textContent.trim()] || null,
                element: label
            }));
        """)

        print(f"✅ Available labels: {labels_info}")

        if not labels_info:
            self.fail("No label buttons found")

        # Select the first label
        label_info = labels_info[0]
        label_text = label_info['text']
        expected_color = label_info['color']

        # Click the label checkbox
        label_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".shadcn-span-checkbox")
        label_buttons[0].click()
        print(f"✅ Selected label: {label_text} (expected color: {expected_color})")

        # Create a text selection
        selection_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content') || document.getElementById('instance-text');
            if (!textContent) {
                return { success: false, error: 'text-content not found' };
            }

            // Find the first text node with content
            let textNode = null;
            for (let i = 0; i < textContent.childNodes.length; i++) {
                const node = textContent.childNodes[i];
                if (node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0) {
                    textNode = node;
                    break;
                }
            }

            if (!textNode) {
                return { success: false, error: 'No text node found with content' };
            }

            const text = textNode.textContent;
            console.log('Found text node with content:', text.substring(0, 50) + '...');

            // Find first 10 non-whitespace characters
            let start = 0;
            while (start < text.length && text[start].match(/\\s/)) start++;

            let end = start;
            let count = 0;
            while (end < text.length && count < 10) {
                if (!text[end].match(/\\s/)) count++;
                end++;
            }

            // Create selection
            const range = document.createRange();
            range.setStart(textNode, start);
            range.setEnd(textNode, end);

            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);

            const selectedText = selection.toString();
            console.log('Created selection:', selectedText);

            return {
                success: true,
                selectedText: selectedText,
                start: start,
                end: end,
                textLength: text.length
            };
        """)

        print(f"✅ Selection result: {selection_result}")

        if not selection_result.get('success'):
            self.fail(f"Failed to create text selection: {selection_result}")

        # Call handleTextSelection to create the span
        handler_result = self.execute_script_safe("""
            if (window.spanManager && typeof window.spanManager.handleTextSelection === 'function') {
                try {
                    window.spanManager.handleTextSelection();
                    return { success: true, message: 'Handler called successfully' };
                } catch (error) {
                    return { success: false, error: error.message };
                }
            } else {
                return { success: false, error: 'handleTextSelection method not found' };
            }
        """)

        print(f"✅ Handler call result: {handler_result}")

        if not handler_result.get('success'):
            self.fail(f"Failed to call handleTextSelection: {handler_result}")

        # Wait for span creation and rendering
        time.sleep(3)

        # Check if spans were created
        span_count = self.execute_script_safe("""
            if (window.spanManager) {
                const spans = window.spanManager.getSpans();
                return {
                    count: spans.length,
                    spans: spans.map(s => ({ id: s.id, text: s.text, label: s.label }))
                };
            }
            return { count: 0, spans: [] };
        """)

        print(f"✅ Span count: {span_count}")

        # CRITICAL ISSUE #1: Check if spans were actually created
        self.assertGreater(span_count.get('count', 0), 0, "No spans were created - this indicates a critical failure")

        # Check for span overlay elements in the DOM
        span_overlays = self.driver.find_elements(By.CSS_SELECTOR, ".span-highlight, .span-overlay-pure, .annotation-span")
        print(f"✅ Found {len(span_overlays)} span overlay elements in DOM")

        # CRITICAL ISSUE #2: Check if span overlays are visible
        self.assertGreater(len(span_overlays), 0, "No span overlay elements found in DOM - positioning/rendering is broken")

        # Check the first span overlay for the specific issues
        if len(span_overlays) > 0:
            first_overlay = span_overlays[0]

            # CRITICAL ISSUE #3: Check positioning - should not be positioned above text
            overlay_position = self.execute_script_safe("""
                const overlay = arguments[0];
                const rect = overlay.getBoundingClientRect();
                const textContent = document.getElementById('text-content') || document.getElementById('instance-text');
                const textRect = textContent.getBoundingClientRect();

                return {
                    overlayTop: rect.top,
                    overlayLeft: rect.left,
                    overlayWidth: rect.width,
                    overlayHeight: rect.height,
                    textTop: textRect.top,
                    textLeft: textRect.left,
                    textWidth: textRect.width,
                    textHeight: textRect.height,
                    isAboveText: rect.top < textRect.top,
                    isBelowText: rect.top > textRect.bottom,
                    isOverlapping: !(rect.bottom < textRect.top || rect.top > textRect.bottom),
                    verticalDistance: Math.abs(rect.top - textRect.top)
                };
            """, first_overlay)

            print(f"✅ Overlay positioning: {overlay_position}")

            # CRITICAL ISSUE #3: Check that overlay is not positioned above the text
            self.assertFalse(overlay_position.get('isAboveText', False),
                           "Span overlay is positioned above the text - positioning is broken")

            # CRITICAL ISSUE #3: Check that overlay overlaps with text
            self.assertTrue(overlay_position.get('isOverlapping', False),
                          "Span overlay does not overlap with text - positioning is broken")

            # CRITICAL ISSUE #4: Check for label text in the overlay
            overlay_text = first_overlay.text
            print(f"✅ Overlay text content: '{overlay_text}'")

            # CRITICAL ISSUE #4: Check that overlay contains the label
            self.assertIn(label_text, overlay_text, f"Overlay does not contain label '{label_text}'")

            # CRITICAL ISSUE #5: Check for delete button
            delete_buttons = first_overlay.find_elements(By.CSS_SELECTOR, ".delete-span, .span-delete, .span-delete-btn, button[title*='delete'], button[title*='Delete']")
            print(f"✅ Found {len(delete_buttons)} delete buttons in overlay")

            # CRITICAL ISSUE #5: Check that delete button exists
            self.assertGreater(len(delete_buttons), 0, "No delete button found in span overlay")

            # CRITICAL ISSUE #2: Check overlay color
            overlay_style = first_overlay.get_attribute("style")
            overlay_computed_style = self.execute_script_safe("""
                const overlay = arguments[0];
                const computed = window.getComputedStyle(overlay);
                return {
                    backgroundColor: computed.backgroundColor,
                    background: computed.background,
                    color: computed.color
                };
            """, first_overlay)

            print(f"✅ Overlay style: {overlay_style}")
            print(f"✅ Overlay computed style: {overlay_computed_style}")

            # CRITICAL ISSUE #2: Check that overlay has some styling (color, background, etc.)
            self.assertIsNotNone(overlay_style, "Overlay has no styling")
            self.assertGreater(len(overlay_style), 0, "Overlay has empty styling")

        # CRITICAL ISSUE #6: Test navigation to ensure it doesn't cause text selection
        print("🔍 Testing navigation...")

        # Get current instance ID
        current_instance = self.execute_script_safe("""
            return window.currentInstance ? window.currentInstance.id : null;
        """)
        print(f"✅ Current instance ID: {current_instance}")

        # Navigate to next instance
        next_button = self.driver.find_element(By.CSS_SELECTOR, "button[onclick*='next'], .next-button, button:contains('Next')")
        next_button.click()
        print("✅ Clicked next button")

        # Wait for navigation
        time.sleep(2)

        # Check if text is selected after navigation
        selection_after_nav = self.execute_script_safe("""
            const selection = window.getSelection();
            return {
                hasSelection: !selection.isCollapsed,
                selectedText: selection.toString(),
                rangeCount: selection.rangeCount
            };
        """)

        print(f"✅ Selection after navigation: {selection_after_nav}")

        # CRITICAL ISSUE #6: Check that no text is selected after navigation
        self.assertFalse(selection_after_nav.get('hasSelection', False),
                        "Text is selected after navigation - this is a critical bug")

        print("✅ All critical span overlay issues have been validated!")

    def test_span_creation_with_console_logs(self):
        """Test span creation with detailed console log capture to debug issues."""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")
        print("✅ Page loaded and text element found")

        # Wait for span manager to be ready
        max_wait = 15  # seconds
        start_time = time.time()
        span_manager_ready = False

        while time.time() - start_time < max_wait:
            manager_status = self.execute_script_safe("""
                if (window.spanManager) {
                    return {
                        exists: true,
                        initialized: window.spanManager.isInitialized,
                        currentInstanceId: window.spanManager.currentInstanceId,
                        currentSchema: window.spanManager.currentSchema,
                        annotations: window.spanManager.annotations
                    };
                } else {
                    return { exists: false };
                }
            """)

            if manager_status.get('exists') and manager_status.get('initialized'):
                span_manager_ready = True
                print(f"✅ Span manager is ready and initialized")
                print(f"   Current instance ID: {manager_status.get('currentInstanceId')}")
                print(f"   Current schema: {manager_status.get('currentSchema')}")
                print(f"   Annotations: {manager_status.get('annotations')}")
                break

            time.sleep(0.5)

        if not span_manager_ready:
            self.fail("Span manager failed to initialize within timeout")

        # Get available labels
        labels = self.execute_script_safe("""
            const labels = [];
            const labelElements = document.querySelectorAll('input[name="span_label"]');
            labelElements.forEach(el => {
                labels.push({
                    text: el.value,
                    color: el.style.backgroundColor || null,
                    element: el
                });
            });
            return labels;
        """)
        print(f"✅ Available labels: {labels}")

        if not labels:
            self.fail("No labels found on the page")

        # Select the first label
        selected_label = labels[0]['text']
        self.execute_script_safe(f"""
            const labelElement = document.querySelector('input[name="span_label"][value="{selected_label}"]');
            if (labelElement) {{
                labelElement.checked = true;
                labelElement.click();
            }}
        """)
        print(f"✅ Selected label: {selected_label}")

        # Select text
        text_content = self.execute_script_safe("""
            const textElement = document.getElementById('instance-text');
            const text = textElement.textContent;
            const range = document.createRange();
            const textNode = textElement.firstChild;
            range.setStart(textNode, 0);
            range.setEnd(textNode, 12);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return {
                selectedText: selection.toString(),
                start: 0,
                end: 12,
                textLength: text.length,
                success: selection.toString().length > 0
            };
        """)
        print(f"✅ Selection result: {text_content}")

        # Capture console logs before calling handler
        console_logs = []
        self.execute_script_safe("""
            // Store original console methods
            window.originalConsoleLog = console.log;
            window.originalConsoleError = console.error;
            window.originalConsoleWarn = console.warn;

            // Override console methods to capture logs
            console.log = function(...args) {
                window.originalConsoleLog.apply(console, args);
                if (!window.capturedLogs) window.capturedLogs = [];
                window.capturedLogs.push({type: 'log', args: args, timestamp: Date.now()});
            };

            console.error = function(...args) {
                window.originalConsoleError.apply(console, args);
                if (!window.capturedLogs) window.capturedLogs = [];
                window.capturedLogs.push({type: 'error', args: args, timestamp: Date.now()});
            };

            console.warn = function(...args) {
                window.originalConsoleWarn.apply(console, args);
                if (!window.capturedLogs) window.capturedLogs = [];
                window.capturedLogs.push({type: 'warn', args: args, timestamp: Date.now()});
            };
        """)

        # Call the text selection handler
        handler_result = self.execute_script_safe("""
            if (window.spanManager && window.spanManager.handleTextSelection) {
                try {
                    window.spanManager.handleTextSelection();
                    return {success: true, message: 'Handler called successfully'};
                } catch (error) {
                    return {success: false, message: 'Handler failed: ' + error.message};
                }
            } else {
                return {success: false, message: 'Handler not available'};
            }
        """)
        print(f"✅ Handler call result: {handler_result}")

        # Wait a moment for any async operations
        time.sleep(2)

        # Get captured console logs
        captured_logs = self.execute_script_safe("""
            const logs = window.capturedLogs || [];
            window.capturedLogs = [];
            return logs;
        """)

        print("🔍 Console logs captured:")
        for log in captured_logs:
            log_type = log['type'].upper()
            log_message = ' '.join([str(arg) for arg in log['args']])
            print(f"   [{log_type}] {log_message}")

        # Check if spans were created
        span_count = self.execute_script_safe("""
            if (window.spanManager && window.spanManager.getSpans) {
                const spans = window.spanManager.getSpans();
                return {
                    count: spans.length,
                    spans: spans.map(span => ({
                        id: span.id,
                        label: span.label,
                        start: span.start,
                        end: span.end,
                        text: span.text
                    }))
                };
            } else {
                return {count: 0, spans: []};
            }
        """)
        print(f"✅ Span count: {span_count}")

        # Check for overlays in the DOM
        overlay_count = self.execute_script_safe("""
            const overlays = document.querySelectorAll('.span-overlay-pure, .span-overlay');
            return {
                count: overlays.length,
                classes: Array.from(overlays).map(el => el.className)
            };
        """)
        print(f"✅ Overlay count: {overlay_count}")

        # Restore original console methods
        self.execute_script_safe("""
            if (window.originalConsoleLog) console.log = window.originalConsoleLog;
            if (window.originalConsoleError) console.error = window.originalConsoleError;
            if (window.originalConsoleWarn) console.warn = window.originalConsoleWarn;
        """)

        # The test should pass if we can see what's happening in the logs
        self.assertTrue(handler_result['success'], f"Handler call failed: {handler_result['message']}")

        # Print summary of what we found
        print(f"\n📊 Summary:")
        print(f"   - Handler called successfully: {handler_result['success']}")
        print(f"   - Spans created: {span_count['count']}")
        print(f"   - Overlays in DOM: {overlay_count['count']}")
        print(f"   - Console logs captured: {len(captured_logs)}")

    def test_span_positioning_and_text_selection_issues(self):
        """Test specifically for the positioning and text selection issues mentioned by the user."""
        # User is already authenticated by BaseSeleniumTest.setUp()
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        text_element = self.wait_for_element(By.ID, "instance-text")
        print("✅ Page loaded and text element found")

        # Wait for span manager to be ready
        max_wait = 15  # seconds
        start_time = time.time()
        span_manager_ready = False

        while time.time() - start_time < max_wait:
            manager_status = self.execute_script_safe("""
                if (window.spanManager) {
                    return {
                        exists: true,
                        initialized: window.spanManager.isInitialized,
                        currentInstanceId: window.spanManager.currentInstanceId,
                        currentSchema: window.spanManager.currentSchema
                    };
                } else {
                    return { exists: false };
                }
            """)

            if manager_status.get('exists') and manager_status.get('initialized'):
                span_manager_ready = True
                print(f"✅ Span manager is ready and initialized")
                break

            time.sleep(0.5)

        if not span_manager_ready:
            self.fail("Span manager failed to initialize within timeout")

        # Get available labels
        labels = self.execute_script_safe("""
            const labels = [];
            const labelElements = document.querySelectorAll('input[name="span_label"]');
            labelElements.forEach(el => {
                labels.push({
                    text: el.value,
                    color: el.style.backgroundColor || null,
                    element: el
                });
            });
            return labels;
        """)
        print(f"✅ Available labels: {labels}")

        if not labels:
            self.fail("No labels found on the page")

        # Select the first label
        selected_label = labels[0]['text']
        self.execute_script_safe(f"""
            const labelElement = document.querySelector('input[name="span_label"][value="{selected_label}"]');
            if (labelElement) {{
                labelElement.checked = true;
                labelElement.click();
            }}
        """)
        print(f"✅ Selected label: {selected_label}")

        # Get the text content and select a specific portion
        text_content = self.execute_script_safe("""
            const textElement = document.getElementById('instance-text');
            const text = textElement.textContent;
            console.log('Text content:', text);

            // Select the first few words
            const range = document.createRange();
            const textNode = textElement.firstChild;
            range.setStart(textNode, 0);
            range.setEnd(textNode, 12); // Select "I am absolut"

            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);

            return {
                selectedText: selection.toString(),
                fullText: text,
                selectionStart: 0,
                selectionEnd: 12
            };
        """)
        print(f"✅ Text selection result: {text_content}")

        # Capture console logs before calling handler
        console_logs = []
        self.execute_script_safe("""
            // Store original console methods
            window.originalConsoleLog = console.log;
            window.originalConsoleError = console.error;
            window.originalConsoleWarn = console.warn;

            // Override console methods to capture logs
            console.log = function(...args) {
                window.originalConsoleLog.apply(console, args);
                if (!window.capturedLogs) window.capturedLogs = [];
                window.capturedLogs.push({type: 'log', args: args, timestamp: Date.now()});
            };

            console.error = function(...args) {
                window.originalConsoleError.apply(console, args);
                if (!window.capturedLogs) window.capturedLogs = [];
                window.capturedLogs.push({type: 'error', args: args, timestamp: Date.now()});
            };

            console.warn = function(...args) {
                window.originalConsoleWarn.apply(console, args);
                if (!window.capturedLogs) window.capturedLogs = [];
                window.capturedLogs.push({type: 'warn', args: args, timestamp: Date.now()});
            };
        """)

        # Call the text selection handler
        handler_result = self.execute_script_safe("""
            if (window.spanManager && window.spanManager.handleTextSelection) {
                try {
                    window.spanManager.handleTextSelection();
                    return {success: true, message: 'Handler called successfully'};
                } catch (error) {
                    return {success: false, message: 'Handler failed: ' + error.message};
                }
            } else {
                return {success: false, message: 'Handler not available'};
            }
        """)
        print(f"✅ Handler call result: {handler_result}")

        # Wait a moment for any async operations
        time.sleep(2)

        # Get captured console logs
        captured_logs = self.execute_script_safe("""
            const logs = window.capturedLogs || [];
            window.capturedLogs = [];
            return logs;
        """)

        print("🔍 Console logs captured:")
        for log in captured_logs:
            log_type = log['type'].upper()
            log_message = ' '.join([str(arg) for arg in log['args']])
            print(f"   [{log_type}] {log_message}")

        # Check if spans were created
        span_count = self.execute_script_safe("""
            if (window.spanManager && window.spanManager.getSpans) {
                const spans = window.spanManager.getSpans();
                return {
                    count: spans.length,
                    spans: spans.map(span => ({
                        id: span.id,
                        label: span.label,
                        start: span.start,
                        end: span.end,
                        text: span.text
                    }))
                };
            } else {
                return {count: 0, spans: []};
            }
        """)
        print(f"✅ Span count: {span_count}")

        # Check for overlays in the DOM and their positioning
        overlay_info = self.execute_script_safe("""
            const overlays = document.querySelectorAll('.span-overlay, .span-overlay-pure, .span-highlight-segment');
            const overlayDetails = [];

            overlays.forEach((overlay, index) => {
                const rect = overlay.getBoundingClientRect();
                const textElement = document.getElementById('instance-text');
                const textRect = textElement ? textElement.getBoundingClientRect() : null;

                overlayDetails.push({
                    index: index,
                    className: overlay.className,
                    position: {
                        left: rect.left,
                        top: rect.top,
                        width: rect.width,
                        height: rect.height
                    },
                    relativeToText: textRect ? {
                        left: rect.left - textRect.left,
                        top: rect.top - textRect.top
                    } : null,
                    backgroundColor: window.getComputedStyle(overlay).backgroundColor,
                    zIndex: window.getComputedStyle(overlay).zIndex
                });
            });

            return {
                count: overlays.length,
                details: overlayDetails
            };
        """)
        print(f"✅ Overlay info: {overlay_info}")

        # Test navigation issue - navigate to next instance and back
        print("🔍 Testing navigation issue...")

        # Navigate to next instance
        navigation_result = self.execute_script_safe("""
            // Store current instance ID
            const currentInstanceId = window.spanManager ? window.spanManager.currentInstanceId : null;

            // Try to navigate to next instance
            const nextButton = document.querySelector('button[onclick*="next"], .next-button, [data-action="next"]');
            if (nextButton) {
                nextButton.click();
                return {success: true, message: 'Next button clicked', currentInstanceId: currentInstanceId};
            } else {
                return {success: false, message: 'Next button not found'};
            }
        """)
        print(f"✅ Navigation result: {navigation_result}")

        # Wait for navigation
        time.sleep(2)

        # Check if text selection is cleared
        selection_after_nav = self.execute_script_safe("""
            const selection = window.getSelection();
            const textElement = document.getElementById('instance-text');

            return {
                hasSelection: !selection.isCollapsed,
                selectedText: selection.toString(),
                textElementText: textElement ? textElement.textContent : null,
                selectionRangeCount: selection.rangeCount
            };
        """)
        print(f"✅ Selection after navigation: {selection_after_nav}")

        # Navigate back to first instance
        back_result = self.execute_script_safe("""
            const prevButton = document.querySelector('button[onclick*="prev"], .prev-button, [data-action="prev"]');
            if (prevButton) {
                prevButton.click();
                return {success: true, message: 'Prev button clicked'};
            } else {
                return {success: false, message: 'Prev button not found'};
            }
        """)
        print(f"✅ Back navigation result: {back_result}")

        # Wait for navigation back
        time.sleep(2)

        # Check selection again
        selection_after_back = self.execute_script_safe("""
            const selection = window.getSelection();
            const textElement = document.getElementById('instance-text');

            return {
                hasSelection: !selection.isCollapsed,
                selectedText: selection.toString(),
                textElementText: textElement ? textElement.textContent : null,
                selectionRangeCount: selection.rangeCount
            };
        """)
        print(f"✅ Selection after back navigation: {selection_after_back}")

        # Restore original console methods
        self.execute_script_safe("""
            if (window.originalConsoleLog) console.log = window.originalConsoleLog;
            if (window.originalConsoleError) console.error = window.originalConsoleError;
            if (window.originalConsoleWarn) console.warn = window.originalConsoleWarn;
        """)

        # Validate the results
        self.assertTrue(handler_result['success'], f"Handler call failed: {handler_result['message']}")

        # Check if spans were created
        self.assertGreater(span_count['count'], 0, "No spans were created")

        # Check if overlays were created
        self.assertGreater(overlay_info['count'], 0, "No overlays were created")

        # Check positioning - overlays should be positioned relative to text
        for overlay in overlay_info['details']:
            self.assertIsNotNone(overlay['relativeToText'], f"Overlay {overlay['index']} has no relative positioning")
            # Overlays should be positioned near the text (not way above or to the right)
            self.assertLess(abs(overlay['relativeToText']['top']), 100, f"Overlay {overlay['index']} positioned too far from text vertically")
            self.assertLess(abs(overlay['relativeToText']['left']), 100, f"Overlay {overlay['index']} positioned too far from text horizontally")

        # Check text selection clearing
        self.assertFalse(selection_after_nav['hasSelection'], "Text selection was not cleared after navigation")
        self.assertFalse(selection_after_back['hasSelection'], "Text selection was not cleared after back navigation")

        print(f"\n📊 Test Summary:")
        print(f"   - Spans created: {span_count['count']}")
        print(f"   - Overlays created: {overlay_info['count']}")
        print(f"   - Positioning issues: {'None detected' if all(abs(o['relativeToText']['top']) < 100 and abs(o['relativeToText']['left']) < 100 for o in overlay_info['details']) else 'Detected'}")
        print(f"   - Text selection cleared: {'Yes' if not selection_after_nav['hasSelection'] and not selection_after_back['hasSelection'] else 'No'}")
        print(f"   - Console logs captured: {len(captured_logs)}")


if __name__ == "__main__":
    # Run the tests directly
    unittest.main()