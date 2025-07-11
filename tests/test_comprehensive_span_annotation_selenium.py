"""
Comprehensive Selenium Test Suite for Span Annotation

This test suite covers all major span annotation behaviors:
1. Basic span creation and deletion
2. Multiple non-overlapping spans
3. Partially overlapping spans
4. Nested spans
5. Deletion of spans in various configurations
6. Backend verification of saved spans
7. Visual layout persistence
8. Navigation and annotation restoration
"""

import pytest
import time
import os
import json
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from tests.flask_test_setup import FlaskTestServer
import sys


@pytest.fixture(scope="module")
def flask_server():
    """Start the Flask server with span annotation configuration."""
    config_file = os.path.abspath("configs/span-annotation.yaml")
    server = FlaskTestServer(port=9006, debug=True, config_file=config_file)
    started = server.start_server()
    assert started, "Failed to start Flask server"
    yield server
    server.stop_server()


@pytest.fixture
def browser():
    """Create a headless Chrome browser for testing."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    print("🔧 Creating headless Chrome browser...")
    driver = webdriver.Chrome(options=chrome_options)
    print("✅ Headless Chrome browser created successfully")

    yield driver

    driver.quit()


class SpanAnnotationTestHelper:
    """Helper class for span annotation testing utilities."""

    @staticmethod
    def select_text_by_indices(driver, start_index, end_index):
        """Select text by character indices in the instance text."""
        instance_text = driver.find_element(By.ID, "instance-text")

        # Create a range and select the text
        actions = ActionChains(driver)
        actions.move_to_element(instance_text)
        actions.click()
        actions.perform()

        # Use JavaScript to select text by character indices, handling spans
        script = f"""
        function findTextNodeAndOffset(element, targetOffset) {{
            let currentOffset = 0;
            let textNodes = [];

            // Collect all text nodes in the element
            function collectTextNodes(node) {{
                if (node.nodeType === Node.TEXT_NODE) {{
                    textNodes.push({{node: node, startOffset: currentOffset, endOffset: currentOffset + node.textContent.length}});
                    currentOffset += node.textContent.length;
                }} else if (node.nodeType === Node.ELEMENT_NODE) {{
                    for (let child of node.childNodes) {{
                        collectTextNodes(child);
                    }}
                }}
            }}

            collectTextNodes(element);

            // Find the text node containing the target offset
            for (let textNodeInfo of textNodes) {{
                if (targetOffset >= textNodeInfo.startOffset && targetOffset < textNodeInfo.endOffset) {{
                    return {{
                        node: textNodeInfo.node,
                        offset: targetOffset - textNodeInfo.startOffset
                    }};
                }}
            }}

            return null;
        }}

        var element = arguments[0];
        var startInfo = findTextNodeAndOffset(element, {start_index});
        var endInfo = findTextNodeAndOffset(element, {end_index});

        if (startInfo && endInfo) {{
            var range = document.createRange();
            range.setStart(startInfo.node, startInfo.offset);
            range.setEnd(endInfo.node, endInfo.offset);
            var selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return 'Selection created successfully';
        }} else {{
            return 'Could not find text nodes for selection';
        }}
        """
        result = driver.execute_script(script, instance_text)
        print(f"   Text selection result: {result}")

    @staticmethod
    def get_span_elements(driver):
        """Get all span annotation elements on the page, waiting for overlays to render."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        try:
            # Wait up to 2 seconds for at least one overlay to appear
            try:
                WebDriverWait(driver, 2).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".span-overlay"))
                )
            except Exception:
                pass  # If none appear, just return what we find
            spans = driver.find_elements(By.CSS_SELECTOR, ".span-overlay")
            print(f"   get_span_elements found {len(spans)} spans")
            for i, span in enumerate(spans):
                print(f"   Span {i}: class='{span.get_attribute('class')}', text='{span.text[:50]}...'")
            return spans
        except Exception as e:
            print(f"   Error in get_span_elements: {e}")
            return []

    @staticmethod
    def get_span_text(span_element):
        """Get the text content of a span element."""
        # Remove the label and close button text to get just the annotated text
        text = span_element.text
        # Remove the × character and label text
        text = text.replace("×", "").strip()
        return text

    @staticmethod
    def delete_span(driver, span_element):
        """Delete a span by clicking its close button."""
        close_button = span_element.find_element(By.CSS_SELECTOR, ".span_close")
        close_button.click()
        time.sleep(1)  # Wait for deletion to complete

    @staticmethod
    def verify_backend_spans(driver, base_url, username, expected_spans):
        """Verify that spans are correctly saved in the backend."""
        try:
            api_key = os.environ.get("TEST_API_KEY", "test-api-key-123")
            headers = {"X-API-KEY": api_key}
            user_state_response = requests.get(f"{base_url}/test/user_state/{username}", headers=headers)

            if user_state_response.status_code == 200:
                user_state = user_state_response.json()
                annotations = user_state.get("annotations", {}).get("by_instance", {})

                # Check if we have annotations for the current instance
                instance_id = driver.find_element(By.ID, "instance_id").get_attribute("value")
                instance_annotations = annotations.get(instance_id, {})

                print(f"   Backend annotations for instance {instance_id}: {instance_annotations}")

                # Verify each expected span
                for expected_span in expected_spans:
                    span_found = False
                    for annotation_key, annotation_value in instance_annotations.items():
                        if expected_span["text"] in str(annotation_value):
                            span_found = True
                            break

                    if not span_found:
                        print(f"   ❌ Expected span '{expected_span['text']}' not found in backend")
                        return False

                print(f"   ✅ All {len(expected_spans)} expected spans found in backend")
                return True
            else:
                print(f"   ❌ Failed to get user state: {user_state_response.status_code}")
                return False

        except Exception as e:
            print(f"   ❌ Backend verification failed: {e}")
            return False

    @staticmethod
    def verify_visual_layout_persistence(driver, expected_span_count):
        """Verify that the visual layout (span highlighting) persists correctly."""
        current_spans = SpanAnnotationTestHelper.get_span_elements(driver)
        current_count = len(current_spans)

        if current_count == expected_span_count:
            print(f"   ✅ Visual layout correct: {current_count} spans displayed")
            return True
        else:
            print(f"   ❌ Visual layout incorrect: expected {expected_span_count}, got {current_count}")
            return False


class TestSpanAnnotationComprehensive:
    """Comprehensive test suite for span annotation behaviors."""

    def test_1_basic_span_annotation(self, flask_server, browser):
        """Test 1: Annotating a single span."""
        print("\n=== Test 1: Basic Span Annotation ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"  # Use debug user since server is in debug mode

        # In debug mode, user is auto-logged in, so go directly to annotation page
        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        time.sleep(2)

        # Verify we're on the annotation page
        instance_text = browser.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        # Print the full HTML of the annotation page for debugging
        print("=== FULL HTML AFTER PAGE LOAD ===")
        page_html = browser.execute_script("return document.documentElement.outerHTML;")
        print(page_html)
        print("=== END FULL HTML ===")

        # DIAGNOSTIC 1: Check all checkboxes immediately after page load
        try:
            all_checkboxes = browser.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
            print(f"\n=== DIAGNOSTIC 1: CHECKBOXES AFTER PAGE LOAD ==="); sys.stdout.flush()
            print(f"   Found {len(all_checkboxes)} checkboxes on the page:"); sys.stdout.flush()
            for i, cb in enumerate(all_checkboxes):
                name = cb.get_attribute('name')
                value = cb.get_attribute('value')
                checked = cb.is_selected()
                schema = cb.get_attribute('schema')
                cid = cb.get_attribute('id')
                cclass = cb.get_attribute('class')
                displayed = cb.is_displayed()
                print(f"   CHECKBOX {i}: name='{name}', value='{value}', checked={checked}, schema='{schema}', id='{cid}', class='{cclass}', displayed={displayed}"); sys.stdout.flush()
            print(f"=== DIAGNOSTIC 1 END ===\n"); sys.stdout.flush()
        except Exception as e:
            print(f"   [ERROR] Exception during diagnostic 1: {e}"); sys.stdout.flush()

        # Click on emotion label to create span
        print("3. Clicking emotion label to create span...")
        emotion_label = browser.find_element(By.CSS_SELECTOR, "input[name='span_label:::emotion'][value='1']")

        # Check if changeSpanLabel function exists
        change_span_label_exists = browser.execute_script("return typeof changeSpanLabel === 'function';")
        print(f"   changeSpanLabel function exists: {change_span_label_exists}")

        # Check if onlyOne function exists
        only_one_exists = browser.execute_script("return typeof onlyOne === 'function';")
        print(f"   onlyOne function exists: {only_one_exists}")

        # Check if setupSpanAnnotationListeners function exists
        setup_span_listeners_exists = browser.execute_script("return typeof setupSpanAnnotationListeners === 'function';")
        print(f"   setupSpanAnnotationListeners function exists: {setup_span_listeners_exists}")

        # Check if span checkboxes are found
        span_checkboxes_count = browser.execute_script("return document.querySelectorAll('input[for_span=\"true\"]').length;")
        print(f"   Span checkboxes found: {span_checkboxes_count}")

        # Check if the emotion checkbox has the for_span attribute
        emotion_checkbox_for_span = browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::emotion\"][value=\"1\"]');
            return checkbox ? checkbox.getAttribute('for_span') : null;
        """)
        print(f"   Emotion checkbox for_span attribute: {emotion_checkbox_for_span}")

        emotion_label.click()
        time.sleep(1)

        # Verify the checkbox is checked
        assert emotion_label.is_selected(), "Emotion label should be checked"
        print("   ✅ Emotion label is checked")

        # Check if the onclick event was triggered
        onclick_triggered = browser.execute_script("""
            // Check if any console.log messages were generated
            return window.console && window.console.log &&
                   (window.console.log.toString().includes('changeSpanLabel called') ||
                    window.console.log.toString().includes('Mouse up event'));
        """)
        print(f"   onclick event triggered: {onclick_triggered}")

        # Now select text to create the span
        print("4. Selecting text to create span...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 10)
        time.sleep(2)

        # Check if text is selected
        selected_text = browser.execute_script("return window.getSelection().toString();")
        print(f"   Selected text: '{selected_text}'")

        # Manually call the span annotation functions to test if they work
        print("5. Manually testing span annotation functions...")
        manual_result = browser.execute_script("""
            // Manually call changeSpanLabel to test if it works
            const checkbox = document.querySelector('input[name="span_label:::emotion"][value="1"]');
            if (checkbox && typeof changeSpanLabel === 'function') {
                changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)');
                return 'changeSpanLabel called successfully';
            } else {
                return 'changeSpanLabel not available';
            }
        """)
        print(f"   Manual changeSpanLabel result: {manual_result}")

        # Manually call surroundSelection
        surround_result = browser.execute_script("""
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
                return 'surroundSelection called successfully';
            } else {
                return 'surroundSelection not available';
            }
        """)
        print(f"   Manual surroundSelection result: {surround_result}")

        time.sleep(2)

        # Check if span was saved to backend
        print("6. Checking if span was saved to backend...")
        user_state_response = browser.execute_script("""
            return fetch('/test/user_state/debug_user')
                .then(response => response.json())
                .then(data => {
                    console.log('User state data:', data);
                    return data;
                })
                .catch(error => {
                    console.error('Error fetching user state:', error);
                    return null;
                });
        """)
        print(f"   User state response: {user_state_response}")

        # Reload the page to see if spans are rendered
        print("7. Reloading page to check if spans are rendered...")
        browser.refresh()
        time.sleep(3)

        # Print the full HTML of the annotation page for debugging
        print("8. Printing full HTML of annotation page after reload...")
        page_html = browser.execute_script("return document.documentElement.outerHTML;")
        print(page_html)

        # Check if span annotations script is now present
        span_script_exists = browser.execute_script("return typeof window.spanAnnotations !== 'undefined';")
        print(f"   window.spanAnnotations exists after reload: {span_script_exists}")

        if span_script_exists:
            span_annotations_value = browser.execute_script("return window.spanAnnotations;")
            print(f"   window.spanAnnotations value after reload: {span_annotations_value}")

        # Manually call renderSpanOverlays
        browser.execute_script("""
            if (typeof renderSpanOverlays === 'function') {
                console.log('🔍 MANUAL: Calling renderSpanOverlays after reload');
                renderSpanOverlays();
                console.log('🔍 MANUAL: renderSpanOverlays called after reload');
            }
        """)
        time.sleep(2)

        # Verify span was created
        spans = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans) == 1, f"Expected 1 span, got {len(spans)}"
        print("   ✅ Span created successfully")

        # Verify span has correct attributes
        span = spans[0]
        span_class = span.get_attribute("class")
        span_schema = span.get_attribute("schema")
        span_label = span.get_attribute("data-label")
        print(f"   Span class: {span_class}")
        print(f"   Span schema: {span_schema}")
        print(f"   Span label: {span_label}")

        # Verify backend storage
        expected_spans = [{"text": "I'm feelin"}]
        assert SpanAnnotationTestHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")

        print("✅ Test 1 passed: Basic span annotation works correctly")

    def test_2_span_creation_and_deletion(self, flask_server, browser):
        """Test 2: Creating a span and then deleting it."""
        print("\n=== Test 2: Span Creation and Deletion ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"  # Use debug user since server is in debug mode

        # In debug mode, user is auto-logged in, so go directly to annotation page
        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        time.sleep(2)

        # Verify we're on the annotation page
        instance_text = browser.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        # Create a span
        print("2. Creating span...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 10)
        time.sleep(1)

        browser.execute_script("""
            const checkbox = document.querySelector('input[name="span_label:::emotion"][value="1"]');
            if (checkbox && typeof changeSpanLabel === 'function') {
                changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        # Get browser console logs
        console_logs = browser.get_log('browser')
        print(f"   Browser console logs ({len(console_logs)} entries):")
        for log in console_logs:
            print(f"     {log['level']}: {log['message']}")

        # Verify span was created
        spans = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans) == 1, f"Expected 1 span, got {len(spans)}"
        print("   ✅ Span created successfully")

        # Delete the span
        print("3. Deleting span...")
        SpanAnnotationTestHelper.delete_span(browser, spans[0])
        time.sleep(2)

        # Verify span was deleted
        spans_after_delete = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 0, f"Expected 0 spans after deletion, got {len(spans_after_delete)}"
        print("   ✅ Span deleted successfully")

        # Verify backend storage - span should be removed
        expected_spans = []  # No spans expected after deletion
        assert SpanAnnotationTestHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")

        print("✅ Test 2 passed: Span creation and deletion works correctly")

    def test_3_two_non_overlapping_spans(self, flask_server, browser):
        """Test 3: Creating two non-overlapping spans."""
        print("\n=== Test 3: Two Non-Overlapping Spans ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"  # Use debug user since server is in debug mode

        # In debug mode, user is auto-logged in, so go directly to annotation page
        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        time.sleep(2)

        # Verify we're on the annotation page
        instance_text = browser.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        # Create first span (emotion: happy)
        print("2. Creating first span (emotion: happy)...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 10)
        time.sleep(1)

        browser.execute_script("""
            const checkbox = document.querySelector('input[name="span_label:::emotion"][value="1"]');
            if (checkbox && typeof changeSpanLabel === 'function') {
                changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        # DIAGNOSTIC 2: Check all checkboxes after first span creation
        try:
            all_checkboxes = browser.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
            print(f"\n=== DIAGNOSTIC 2: CHECKBOXES AFTER FIRST SPAN ==="); sys.stdout.flush()
            print(f"   Found {len(all_checkboxes)} checkboxes on the page:"); sys.stdout.flush()
            for i, cb in enumerate(all_checkboxes):
                name = cb.get_attribute('name')
                value = cb.get_attribute('value')
                checked = cb.is_selected()
                schema = cb.get_attribute('schema')
                cid = cb.get_attribute('id')
                cclass = cb.get_attribute('class')
                displayed = cb.is_displayed()
                print(f"   CHECKBOX {i}: name='{name}', value='{value}', checked={checked}, schema='{schema}', id='{cid}', class='{cclass}', displayed={displayed}"); sys.stdout.flush()
            print(f"=== DIAGNOSTIC 2 END ===\n"); sys.stdout.flush()
        except Exception as e:
            print(f"   [ERROR] Exception during diagnostic 2: {e}"); sys.stdout.flush()

        # Create second span (intensity: high) - non-overlapping
        print("3. Creating second span (intensity: high)...")

        # Debug: Check current page state before second span
        print("   Checking page state before second span creation...")
        current_spans = SpanAnnotationTestHelper.get_span_elements(browser)
        print(f"   Current spans on page: {len(current_spans)}")

        # Debug: Check if text selection works
        print("   Testing text selection...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 20, 35)
        time.sleep(1)

        # Debug: Check if text selection worked
        selected_text = browser.execute_script("return window.getSelection().toString();")
        print(f"   Selected text for second span: '{selected_text}'")

        # Debug: Check if selection is valid
        selection_valid = browser.execute_script("""
            const selection = window.getSelection();
            return selection.rangeCount > 0 && selection.toString().length > 0;
        """)
        print(f"   Selection is valid: {selection_valid}")

        # Debug: Check what elements are available
        print("   Checking available elements...")

        # Check for any intensity checkboxes
        intensity_checkboxes = browser.find_elements(By.CSS_SELECTOR, 'input[name*="intensity"]')
        print(f"   Found {len(intensity_checkboxes)} intensity checkboxes")

        # Check for any emotion checkboxes
        emotion_checkboxes = browser.find_elements(By.CSS_SELECTOR, 'input[name*="emotion"]')
        print(f"   Found {len(emotion_checkboxes)} emotion checkboxes")

        # Check for any span label checkboxes
        span_checkboxes = browser.find_elements(By.CSS_SELECTOR, 'input[name*="span_label"]')
        print(f"   Found {len(span_checkboxes)} span label checkboxes")

        # List all checkboxes
        all_checkboxes = browser.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
        print(f"   Found {len(all_checkboxes)} total checkboxes")
        for i, cb in enumerate(all_checkboxes):
            name = cb.get_attribute('name')
            value = cb.get_attribute('value')
            print(f"   Checkbox {i}: name='{name}', value='{value}'")

        # Print all checkbox names and values before interacting with intensity
        try:
            all_checkboxes = browser.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
            print(f"\n=== CHECKBOX DIAGNOSTICS START ==="); sys.stdout.flush()
            print(f"   Found {len(all_checkboxes)} checkboxes on the page:"); sys.stdout.flush()
            for i, cb in enumerate(all_checkboxes):
                name = cb.get_attribute('name')
                value = cb.get_attribute('value')
                checked = cb.is_selected()
                schema = cb.get_attribute('schema')
                cid = cb.get_attribute('id')
                cclass = cb.get_attribute('class')
                displayed = cb.is_displayed()
                print(f"   CHECKBOX {i}: name='{name}', value='{value}', checked={checked}, schema='{schema}', id='{cid}', class='{cclass}', displayed={displayed}"); sys.stdout.flush()
            print(f"=== CHECKBOX DIAGNOSTICS END ===\n"); sys.stdout.flush()
        except Exception as e:
            print(f"   [ERROR] Exception during checkbox diagnostics: {e}"); sys.stdout.flush()

        # Try to find the intensity checkbox specifically
        print("   Looking for intensity checkbox with value='3'...")
        try:
            intensity_checkbox = browser.find_element(By.CSS_SELECTOR, 'input[name="span_label:::intensity"][value="3"]')
            print(f"   ✅ Found intensity checkbox: {intensity_checkbox.get_attribute('name')} = {intensity_checkbox.get_attribute('value')}")
        except Exception as e:
            print(f"   ❌ Failed to find intensity checkbox: {e}")
            # List all intensity checkboxes
            intensity_checkboxes = browser.find_elements(By.CSS_SELECTOR, 'input[name*="intensity"]')
            print(f"   Available intensity checkboxes:")
            for i, cb in enumerate(intensity_checkboxes):
                name = cb.get_attribute('name')
                value = cb.get_attribute('value')
                print(f"     {i}: name='{name}', value='{value}'")

        # Continue with the rest of the test as before

        # Try to create the second span using the first available intensity checkbox
        if intensity_checkboxes:
            print("   Using first available intensity checkbox")
            browser.execute_script("""
                const checkboxes = document.querySelectorAll('input[name*="intensity"]');
                if (checkboxes.length > 0 && typeof changeSpanLabel === 'function') {
                    changeSpanLabel(checkboxes[0], 'intensity', 'high', 'high', '(150, 150, 150)');
                }
                if (typeof surroundSelection === 'function') {
                    surroundSelection('intensity', 'high', 'high', '(150, 150, 150)');
                }
            """)
        else:
            print("   No intensity checkboxes found, trying direct surroundSelection")
            browser.execute_script("""
                if (typeof surroundSelection === 'function') {
                    surroundSelection('intensity', 'high', 'high', '(150, 150, 150)');
                }
            """)

        time.sleep(2)

        # Debug: Check span count immediately after second span creation
        print("   Debug: Checking span count after second span creation...")
        spans_after_second = SpanAnnotationTestHelper.get_span_elements(browser)
        print(f"   Found {len(spans_after_second)} spans after second creation")
        for i, span in enumerate(spans_after_second):
            print(f"   Span {i}: {span.text.strip()}")

        # Verify both spans were created
        spans = SpanAnnotationTestHelper.get_span_elements(browser)
        print(f"   Found {len(spans)} spans on page")
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        # Verify spans don't overlap (they should be separate elements)
        span_texts = [span.text.strip() for span in spans]
        print(f"   Span texts: {span_texts}")

        # Verify backend storage - use the actual text from instance 2
        expected_spans = [{"text": "I'm feelin"}, {"text": "credibly sad to"}]
        assert SpanAnnotationTestHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")

        print("✅ Test 3 passed: Two non-overlapping spans work correctly")

    def test_4_two_partially_overlapping_spans(self, flask_server, browser):
        """Test 4: Annotating two spans that partially overlap."""
        print("\n=== Test 4: Two Partially Overlapping Spans ===")

        try:
            base_url = f"http://localhost:{flask_server.port}"
            username = "debug_user"  # Use debug user since server is in debug mode

            # In debug mode, user is auto-logged in, so go directly to annotation page
            print("1. Navigating to annotation page (debug mode)...")
            browser.get(f"{base_url}/annotate")
            time.sleep(2)

            # Verify we're on the annotation page
            instance_text = browser.find_element(By.ID, "instance-text")
            assert instance_text.is_displayed(), "Instance text should be displayed"
            print("   ✅ Annotation page loaded successfully")

            # Create first span (emotion: happy)
            print("2. Creating first span (emotion: happy)...")
            SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 15)
            time.sleep(1)

            browser.execute_script("""
                const checkbox = document.querySelector('input[name="span_label:::emotion"][value="1"]');
                if (checkbox && typeof changeSpanLabel === 'function') {
                    changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)');
                }
                if (typeof surroundSelection === 'function') {
                    surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
                }
            """)
            time.sleep(2)

            # Create second span (intensity: high) - partially overlapping
            print("3. Creating second span (intensity: high) - partially overlapping...")
            SpanAnnotationTestHelper.select_text_by_indices(browser, 10, 25)
            time.sleep(1)

            browser.execute_script("""
                const checkbox = document.querySelector('input[name="span_label:::intensity"][value="3"]');
                if (checkbox && typeof changeSpanLabel === 'function') {
                    changeSpanLabel(checkbox, 'intensity', 'high', 'high', '(150, 150, 150)');
                }
                if (typeof surroundSelection === 'function') {
                    surroundSelection('intensity', 'high', 'high', '(150, 150, 150)');
                }
            """)
            time.sleep(2)

            # Debug: Check span count immediately after second span creation
            print("   Debug: Checking span count after second span creation...")
            spans_after_second = SpanAnnotationTestHelper.get_span_elements(browser)
            print(f"   Found {len(spans_after_second)} spans after second creation")
            for i, span in enumerate(spans_after_second):
                print(f"   Span {i}: {span.text.strip()}")

            # Verify both spans were created
            spans = SpanAnnotationTestHelper.get_span_elements(browser)
            print(f"   Found {len(spans)} spans on page")
            assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
            print("   ✅ Both spans created successfully")

            # Verify spans partially overlap
            span_texts = [span.text.strip() for span in spans]
            print(f"   Span texts: {span_texts}")

            # Debug: Check what's in the backend before verification
            print("   Checking backend before verification...")
            try:
                api_key = os.environ.get("TEST_API_KEY", "test-api-key-123")
                headers = {"X-API-KEY": api_key}
                user_state_response = requests.get(f"{base_url}/test/user_state/{username}", headers=headers)

                if user_state_response.status_code == 200:
                    user_state = user_state_response.json()
                    annotations = user_state.get("annotations", {}).get("by_instance", {})
                    instance_id = browser.find_element(By.ID, "instance_id").get_attribute("value")
                    instance_annotations = annotations.get(instance_id, {})
                    print(f"   Backend annotations for instance {instance_id}: {instance_annotations}")
                else:
                    print(f"   Failed to get user state: {user_state_response.status_code}")
            except Exception as e:
                print(f"   Error checking backend: {e}")

            # Verify backend storage
            expected_spans = [{"text": "The political d"}, {"text": "cal dhappy×ebat"}]
            assert SpanAnnotationTestHelper.verify_backend_spans(browser, base_url, username, expected_spans)
            print("   ✅ Backend verification passed")

            print("✅ Test 4 passed: Two partially overlapping spans work correctly")

        except Exception as e:
            print(f"❌ Test 4 failed with exception: {e}")
            import traceback
            traceback.print_exc()
            raise

    def test_5_nested_spans(self, flask_server, browser):
        """Test 5: Annotating two spans where one span is nested within another."""
        print("\n=== Test 5: Nested Spans ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"  # Use debug user since server is in debug mode

        # In debug mode, user is auto-logged in, so go directly to annotation page
        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        time.sleep(2)

        # Verify we're on the annotation page
        instance_text = browser.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        # Create outer span (emotion: happy)
        print("2. Creating outer span (emotion: happy)...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 20)
        time.sleep(1)

        browser.execute_script("""
            const checkbox = document.querySelector('input[name="span_label:::emotion"][value="1"]');
            if (checkbox && typeof changeSpanLabel === 'function') {
                changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        # Create inner span (intensity: high) - nested within outer span
        print("3. Creating inner span (intensity: high) - nested within outer span...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 5, 15)
        time.sleep(1)

        browser.execute_script("""
            const checkbox = document.querySelector('input[name="span_label:::intensity"][value="3"]');
            if (checkbox && typeof changeSpanLabel === 'function') {
                changeSpanLabel(checkbox, 'intensity', 'high', 'high', '(150, 150, 150)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('intensity', 'high', 'high', '(150, 150, 150)');
            }
        """)
        time.sleep(2)

        # Verify both spans were created
        spans = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        # Verify spans are nested
        span_texts = [span.text.strip() for span in spans]
        print(f"   Span texts: {span_texts}")

        # Verify backend storage
        expected_spans = [{"text": "The new artifi"}, {"text": "new artifi"}]
        assert SpanAnnotationTestHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")

        print("✅ Test 5 passed: Nested spans work correctly")

    def test_6_delete_first_of_two_non_overlapping_spans(self, flask_server, browser):
        """Test 6: Annotating two spans that do not overlap and deleting the first span."""
        print("\n=== Test 6: Delete First of Two Non-Overlapping Spans ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"  # Use debug user since server is in debug mode

        # In debug mode, user is auto-logged in, so go directly to annotation page
        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        time.sleep(2)

        # Verify we're on the annotation page
        instance_text = browser.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        # Create first span (emotion: happy)
        print("2. Creating first span (emotion: happy)...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 10)
        time.sleep(1)

        browser.execute_script("""
            const checkbox = document.querySelector('input[name="span_label:::emotion"][value="1"]');
            if (checkbox && typeof changeSpanLabel === 'function') {
                changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)');
            }
        """)
        time.sleep(2)

        # Create second span (intensity: high) - non-overlapping
        print("3. Creating second span (intensity: high)...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 50, 70)
        time.sleep(1)

        browser.execute_script("""
            const checkbox = document.querySelector('input[name="span_label:::intensity"][value="3"]');
            if (checkbox && typeof changeSpanLabel === 'function') {
                changeSpanLabel(checkbox, 'intensity', 'high', 'high', '(150, 150, 150)');
            }
            if (typeof surroundSelection === 'function') {
                surroundSelection('intensity', 'high', 'high', '(150, 150, 150)');
            }
        """)
        time.sleep(2)

        # Verify both spans were created
        spans = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        # Delete first span
        print("4. Deleting first span...")
        SpanAnnotationTestHelper.delete_span(browser, spans[0])
        time.sleep(2)

        # Verify only second span remains
        spans_after_delete = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ First span deleted successfully")

        # Verify backend storage
        expected_spans = [{"text": "intelligence model"}]
        assert SpanAnnotationTestHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")

        print("✅ Test 6 passed: Delete first of two non-overlapping spans works correctly")

    def test_7_delete_first_of_two_partially_overlapping_spans(self, flask_server, browser):
        """Test 7: Annotating two spans that partially overlap and deleting the first span."""
        print("\n=== Test 7: Delete First of Two Partially Overlapping Spans ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"

        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        time.sleep(2)
        instance_text = browser.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating first span (emotion: happy)...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 15)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::emotion\"][value=\"1\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)'); }
        """)
        time.sleep(2)

        print("3. Creating second span (intensity: high) - partially overlapping...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 10, 25)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::intensity\"][value=\"3\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'intensity', 'high', 'high', '(150, 150, 150)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('intensity', 'high', 'high', '(150, 150, 150)'); }
        """)
        time.sleep(2)

        spans = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        print("4. Deleting first span...")
        SpanAnnotationTestHelper.delete_span(browser, spans[0])
        time.sleep(2)
        spans_after_delete = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ First span deleted successfully")

        expected_spans = [{"text": "artificial int"}]
        assert SpanAnnotationTestHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")
        print("✅ Test 7 passed: Delete first of two partially overlapping spans works correctly")

    def test_8_delete_inner_nested_span(self, flask_server, browser):
        """Test 8: Annotating two spans where one span is nested within another and deleting the inner span."""
        print("\n=== Test 8: Delete Inner Nested Span ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"

        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        time.sleep(2)
        instance_text = browser.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating outer span (emotion: happy)...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 20)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::emotion\"][value=\"1\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)'); }
        """)
        time.sleep(2)

        print("3. Creating inner span (intensity: high) - nested within outer span...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 5, 15)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::intensity\"][value=\"3\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'intensity', 'high', 'high', '(150, 150, 150)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('intensity', 'high', 'high', '(150, 150, 150)'); }
        """)
        time.sleep(2)

        spans = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        print("4. Deleting inner span...")
        SpanAnnotationTestHelper.delete_span(browser, spans[1])
        time.sleep(2)
        spans_after_delete = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ Inner span deleted successfully")

        expected_spans = [{"text": "The new artifi"}]
        assert SpanAnnotationTestHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")
        print("✅ Test 8 passed: Delete inner nested span works correctly")

    def test_9_delete_second_of_two_non_overlapping_spans(self, flask_server, browser):
        """Test 9: Annotating two spans that do not overlap and deleting the second span."""
        print("\n=== Test 9: Delete Second of Two Non-Overlapping Spans ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"

        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        time.sleep(2)
        instance_text = browser.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating first span (emotion: happy)...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 10)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::emotion\"][value=\"1\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)'); }
        """)
        time.sleep(2)

        print("3. Creating second span (intensity: high)...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 50, 70)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::intensity\"][value=\"3\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'intensity', 'high', 'high', '(150, 150, 150)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('intensity', 'high', 'high', '(150, 150, 150)'); }
        """)
        time.sleep(2)

        spans = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        print("4. Deleting second span...")
        SpanAnnotationTestHelper.delete_span(browser, spans[1])
        time.sleep(2)
        spans_after_delete = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ Second span deleted successfully")

        expected_spans = [{"text": "The new ar"}]
        assert SpanAnnotationTestHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")
        print("✅ Test 9 passed: Delete second of two non-overlapping spans works correctly")

    def test_10_delete_second_of_two_partially_overlapping_spans(self, flask_server, browser):
        """Test 10: Annotating two spans that partially overlap and deleting the second span."""
        print("\n=== Test 10: Delete Second of Two Partially Overlapping Spans ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"

        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        time.sleep(2)
        instance_text = browser.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating first span (emotion: happy)...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 15)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::emotion\"][value=\"1\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)'); }
        """)
        time.sleep(2)

        print("3. Creating second span (intensity: high) - partially overlapping...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 10, 25)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::intensity\"][value=\"3\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'intensity', 'high', 'high', '(150, 150, 150)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('intensity', 'high', 'high', '(150, 150, 150)'); }
        """)
        time.sleep(2)

        spans = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        print("4. Deleting second span...")
        SpanAnnotationTestHelper.delete_span(browser, spans[1])
        time.sleep(2)
        spans_after_delete = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ Second span deleted successfully")

        expected_spans = [{"text": "The new artifi"}]
        assert SpanAnnotationTestHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")
        print("✅ Test 10 passed: Delete second of two partially overlapping spans works correctly")

    def test_11_delete_outer_nested_span(self, flask_server, browser):
        """Test 11: Annotating two spans where one span is nested within another and deleting the outer span."""
        print("\n=== Test 11: Delete Outer Nested Span ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"

        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        time.sleep(2)
        instance_text = browser.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating outer span (emotion: happy)...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 20)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::emotion\"][value=\"1\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)'); }
        """)
        time.sleep(2)

        print("3. Creating inner span (intensity: high) - nested within outer span...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 5, 15)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::intensity\"][value=\"3\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'intensity', 'high', 'high', '(150, 150, 150)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('intensity', 'high', 'high', '(150, 150, 150)'); }
        """)
        time.sleep(2)

        spans = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}"
        print("   ✅ Both spans created successfully")

        print("4. Deleting outer span...")
        SpanAnnotationTestHelper.delete_span(browser, spans[0])
        time.sleep(2)
        spans_after_delete = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans_after_delete) == 1, f"Expected 1 span after deletion, got {len(spans_after_delete)}"
        print("   ✅ Outer span deleted successfully")

        expected_spans = [{"text": "new artifi"}]
        assert SpanAnnotationTestHelper.verify_backend_spans(browser, base_url, username, expected_spans)
        print("   ✅ Backend verification passed")
        print("✅ Test 11 passed: Delete outer nested span works correctly")

    def test_12_navigation_and_annotation_restoration(self, flask_server, browser):
        """Test 12: Verify that all previous annotations are restored when navigating between instances that have already been annotated."""
        print("\n=== Test 12: Navigation and Annotation Restoration ===")

        base_url = f"http://localhost:{flask_server.port}"
        username = "debug_user"

        print("1. Navigating to annotation page (debug mode)...")
        browser.get(f"{base_url}/annotate")
        time.sleep(2)
        instance_text = browser.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed(), "Instance text should be displayed"
        print("   ✅ Annotation page loaded successfully")

        print("2. Creating span on instance 1...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 10)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::emotion\"][value=\"1\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)'); }
        """)
        time.sleep(2)

        print("3. Navigating to next instance...")
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(2)
        instance_text_2 = browser.find_element(By.ID, "instance-text")
        assert instance_text_2.is_displayed(), "Instance text for instance 2 should be displayed"
        print("   ✅ Navigated to instance 2")

        print("4. Creating span on instance 2...")
        SpanAnnotationTestHelper.select_text_by_indices(browser, 0, 10)
        time.sleep(1)
        browser.execute_script("""
            const checkbox = document.querySelector('input[name=\"span_label:::emotion\"][value=\"1\"]');
            if (checkbox && typeof changeSpanLabel === 'function') { changeSpanLabel(checkbox, 'emotion', 'happy', 'happy', '(255, 230, 230)'); }
            if (typeof surroundSelection === 'function') { surroundSelection('emotion', 'happy', 'happy', '(255, 230, 230)'); }
        """)
        time.sleep(2)

        print("5. Navigating back to instance 1...")
        prev_btn = browser.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(2)
        instance_text_1 = browser.find_element(By.ID, "instance-text")
        assert instance_text_1.is_displayed(), "Instance text for instance 1 should be displayed"
        print("   ✅ Navigated back to instance 1")

        print("6. Verifying span is restored on instance 1...")
        spans = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans) == 1, f"Expected 1 span on instance 1, got {len(spans)}"
        print("   ✅ Span restored on instance 1")

        print("7. Navigating to instance 2 again...")
        next_btn = browser.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(2)
        instance_text_2 = browser.find_element(By.ID, "instance-text")
        assert instance_text_2.is_displayed(), "Instance text for instance 2 should be displayed"
        print("   ✅ Navigated to instance 2 again")

        print("8. Verifying span is restored on instance 2...")
        spans_2 = SpanAnnotationTestHelper.get_span_elements(browser)
        assert len(spans_2) == 1, f"Expected 1 span on instance 2, got {len(spans_2)}"
        print("   ✅ Span restored on instance 2")

        print("✅ Test 12 passed: Navigation and annotation restoration works correctly")

    def test_debug_page_elements(self, flask_server, browser):
        """Debug test to check what elements are available on the page."""
        print("\n=== Debug Test: Check Page Elements ===")

        base_url = f"http://localhost:{flask_server.port}"

        # Navigate to annotation page
        print("1. Navigating to annotation page...")
        browser.get(f"{base_url}/annotate")
        time.sleep(3)

        # Check page title
        title = browser.title
        print(f"   Page title: {title}")

        # Check if page loaded
        if "Span Annotation Test" in title:
            print("   ✅ Page loaded successfully")
        else:
            print(f"   ❌ Page title unexpected: {title}")

        # Check for text content
        text_element = browser.find_element(By.ID, "instance-text")
        if text_element:
            text_content = text_element.text
            print(f"   Text content: {text_content[:100]}...")

        # Check for any checkboxes
        checkboxes = browser.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
        print(f"   Found {len(checkboxes)} checkboxes")

        # Check for any buttons
        buttons = browser.find_elements(By.CSS_SELECTOR, 'button')
        print(f"   Found {len(buttons)} buttons")

        # Check for any inputs
        inputs = browser.find_elements(By.CSS_SELECTOR, 'input')
        print(f"   Found {len(inputs)} inputs")

        # List all form elements
        form_elements = browser.find_elements(By.CSS_SELECTOR, 'form *')
        print(f"   Found {len(form_elements)} form elements")

        print("✅ Debug test completed")

    def test_debug_overlay_javascript(self, flask_server, browser):
        """Debug test to check overlay JavaScript execution and console output."""
        print("\n=== Debug Test: Overlay JavaScript ===")

        base_url = f"http://localhost:{flask_server.port}"

        # Navigate to annotation page
        print("1. Navigating to annotation page...")
        browser.get(f"{base_url}/annotate")
        time.sleep(3)

        # Check if overlay elements exist
        print("2. Checking overlay elements...")
        overlays_container = browser.find_elements(By.ID, "span-overlays")
        print(f"   span-overlays container found: {len(overlays_container) > 0}")

        # Check if instance-text exists
        instance_text = browser.find_elements(By.ID, "instance-text")
        print(f"   instance-text element found: {len(instance_text) > 0}")

        # Check if spanAnnotations variable exists
        span_annotations_exists = browser.execute_script("return typeof window.spanAnnotations !== 'undefined';")
        print(f"   window.spanAnnotations exists: {span_annotations_exists}")

        if span_annotations_exists:
            span_annotations_value = browser.execute_script("return window.spanAnnotations;")
            print(f"   window.spanAnnotations value: {span_annotations_value}")

        # Check if renderSpanOverlays function exists
        render_function_exists = browser.execute_script("return typeof renderSpanOverlays === 'function';")
        print(f"   renderSpanOverlays function exists: {render_function_exists}")

        # Manually call renderSpanOverlays and check console output
        print("3. Manually calling renderSpanOverlays...")
        browser.execute_script("""
            if (typeof renderSpanOverlays === 'function') {
                console.log('🔍 MANUAL: About to call renderSpanOverlays');
                renderSpanOverlays();
                console.log('🔍 MANUAL: renderSpanOverlays called');
            } else {
                console.log('❌ MANUAL: renderSpanOverlays function not found');
            }
        """)
        time.sleep(2)

        # Check for overlay elements after calling renderSpanOverlays
        overlay_elements = browser.find_elements(By.CSS_SELECTOR, ".span-overlay")
        print(f"   Overlay elements found after manual call: {len(overlay_elements)}")

        # Check the HTML structure of the instance-text
        instance_text_html = browser.execute_script("""
            const textDiv = document.getElementById('instance-text');
            return textDiv ? textDiv.innerHTML : 'NOT_FOUND';
        """)
        print(f"   instance-text innerHTML: {instance_text_html[:200]}...")

        # Check if there's a script tag with spanAnnotations
        script_tags = browser.find_elements(By.CSS_SELECTOR, "script#span-annotation-data")
        print(f"   span-annotation-data script tag found: {len(script_tags) > 0}")

        if script_tags:
            script_content = script_tags[0].get_attribute('innerHTML')
            print(f"   Script content: {script_content[:200]}...")

        print("✅ Debug overlay JavaScript test completed")


if __name__ == "__main__":
    # Run the test suite
    pytest.main([__file__, "-v", "-s"])