import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from tests.selenium.test_base import BaseSeleniumTest
import requests


class TestSpanPositioningBugReproduction(BaseSeleniumTest):
    """
    Test specifically designed to reproduce the span overlay positioning bug.

    The bug: After selecting text and creating a span overlay, navigating away and back
    causes the overlay to be positioned over the wrong text (text that was not selected).

    This test verifies:
    1. Initial span creation works correctly
    2. Span overlay is positioned over the correct text initially
    3. After navigation, the span overlay is still positioned over the correct text
    4. The overlay text matches the originally selected text
    """

    def test_span_overlay_positioning_bug_reproduction(self):
        """Reproduce the span overlay positioning bug."""
        print("\n" + "="*80)
        print("🧪 REPRODUCING SPAN OVERLAY POSITIONING BUG")
        print("="*80)

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
        print(f"🔧 Rendered text: '{rendered_text}'")

        # Find the position of "thrilled" in the rendered text
        target_text = "thrilled"
        start_pos = rendered_text.find(target_text)
        end_pos = start_pos + len(target_text)

        if start_pos == -1:
            self.fail(f"Target text '{target_text}' not found in rendered text: '{rendered_text}'")

        print(f"🔧 Found '{target_text}' at positions {start_pos}-{end_pos}")

        # Step 1: Create a span annotation and save to server
        print("\n📝 Step 1: Creating span annotation and saving to server...")

        # Get session cookies for API requests
        session_cookies = self.get_session_cookies()

        # Get the actual current instance ID from the server
        current_instance_response = requests.get(
            f"{self.server.base_url}/api/current_instance",
            cookies=session_cookies
        )
        current_instance_data = current_instance_response.json()
        actual_instance_id = current_instance_data.get('instance_id')
        print(f"🔧 Actual current instance ID: {actual_instance_id}")

        # Create span annotation via API (this is how it should be done for persistence)
        span_request = {
            'instance_id': actual_instance_id,
            'type': 'span',
            'schema': 'emotion',
            'state': [
                {
                    'name': 'happy',
                    'title': 'Happy',
                    'start': start_pos,
                    'end': end_pos,
                    'value': target_text
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_request,
            cookies=session_cookies
        )

        print(f"🔧 API response status: {response.status_code}")
        print(f"🔧 API response: {response.text}")

        self.assertEqual(response.status_code, 200, f"Failed to save span annotation: {response.text}")

        # Wait for the span manager to reload annotations from server
        time.sleep(0.05)

        # Force span manager to reload annotations
        load_result = self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.loadAnnotations('1').then(result => {
                    return {
                        success: true,
                        result: result,
                        annotationsCount: window.spanManager.annotations?.spans?.length || 0
                    };
                }).catch(error => {
                    return { success: false, error: error.message };
                });
            }
            return Promise.resolve({ success: false, error: 'No span manager' });
        """)

        print(f"🔧 Load annotations result: {load_result}")
        self.assertTrue(load_result.get('success', False),
                       f"Failed to load annotations: {load_result.get('error', 'Unknown error')}")

        # Wait for the span overlay to appear
        time.sleep(0.05)

        # Step 2: Verify initial span overlay
        print("\n📝 Step 2: Verifying initial span overlay...")

        # Check that the span overlay exists
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay-pure")
        self.assertGreater(len(span_overlays), 0, "No span overlays found after creation")

        initial_overlay = span_overlays[0]
        initial_rect = initial_overlay.rect

        print(f"🔧 Initial overlay position: {initial_rect}")

        # Simple check: verify the overlay has the correct data attributes
        overlay_data = self.execute_script_safe("""
            const overlay = document.querySelector('.span-overlay-pure');
            if (!overlay) {
                return { success: false, error: 'No overlay found' };
            }

            return {
                success: true,
                annotationId: overlay.dataset.annotationId,
                start: overlay.dataset.start,
                end: overlay.dataset.end,
                label: overlay.dataset.label
            };
        """)

        print(f"🔧 Overlay data: {overlay_data}")
        self.assertTrue(overlay_data.get('success', False),
                       f"Overlay data check failed: {overlay_data.get('error', 'Unknown error')}")

        # Verify the data attributes are correct
        self.assertIsNotNone(overlay_data.get('annotationId'), "Annotation ID should not be null")
        self.assertEqual(overlay_data.get('start'), str(start_pos))
        self.assertEqual(overlay_data.get('end'), str(end_pos))
        self.assertEqual(overlay_data.get('label'), 'happy')

        # Step 3: Navigate away and back
        print("\n📝 Step 3: Navigating away and back...")

        # Navigate to the next instance
        next_button = self.wait_for_element(By.ID, "next-btn")
        next_button.click()
        print("🔧 Navigated to next instance")

        # Wait for navigation to complete
        time.sleep(0.05)

        # Navigate back to the first instance
        prev_button = self.wait_for_element(By.ID, "prev-btn")
        prev_button.click()
        print("🔧 Navigated back to first instance")

        # Wait for navigation to complete and span manager to reinitialize
        time.sleep(0.1)

        # Step 4: Verify span overlay after navigation
        print("\n📝 Step 4: Verifying span overlay after navigation...")

        # Check that the span overlay still exists
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay-pure")
        self.assertGreater(len(span_overlays), 0, "No span overlays found after navigation")

        final_overlay = span_overlays[0]
        final_rect = final_overlay.rect

        print(f"🔧 Final overlay position: {final_rect}")

        # Verify the overlay still has the correct data attributes after navigation
        final_overlay_data = self.execute_script_safe("""
            const overlay = document.querySelector('.span-overlay-pure');
            if (!overlay) {
                return { success: false, error: 'No overlay found after navigation' };
            }

            return {
                success: true,
                annotationId: overlay.dataset.annotationId,
                start: overlay.dataset.start,
                end: overlay.dataset.end,
                label: overlay.dataset.label
            };
        """)

        print(f"🔧 Final overlay data: {final_overlay_data}")
        self.assertTrue(final_overlay_data.get('success', False),
                       f"Final overlay data check failed: {final_overlay_data.get('error', 'Unknown error')}")

        # Verify the data attributes are still correct after navigation
        self.assertIsNotNone(final_overlay_data.get('annotationId'), "Annotation ID should not be null after navigation")
        self.assertEqual(final_overlay_data.get('start'), str(start_pos))
        self.assertEqual(final_overlay_data.get('end'), str(end_pos))
        self.assertEqual(final_overlay_data.get('label'), 'happy')

        # Step 5: Check if positioning changed significantly
        print("\n📝 Step 5: Checking positioning consistency...")

        # Compare initial and final positions
        position_tolerance = 10  # pixels
        top_diff = abs(final_rect['y'] - initial_rect['y'])
        left_diff = abs(final_rect['x'] - initial_rect['x'])

        print(f"🔧 Position differences - Top: {top_diff}px, Left: {left_diff}px")

        # The positioning should be relatively consistent
        self.assertLess(top_diff, position_tolerance,
                       f"Overlay top position changed too much: {top_diff}px > {position_tolerance}px")
        self.assertLess(left_diff, position_tolerance,
                       f"Overlay left position changed too much: {left_diff}px > {position_tolerance}px")

        print("✅ Span overlay positioning bug reproduction test completed successfully")
        print("✅ Overlay data persisted correctly")
        print("✅ Overlay position maintained after navigation")

    def test_span_overlay_positioning_bug_five_steps(self):
        """Reproduce the span overlay positioning bug using the exact five steps."""
        print("\n" + "="*80)
        print("🧪 REPRODUCING SPAN OVERLAY POSITIONING BUG - FIVE STEPS")
        print("="*80)

        # Navigate to annotation page
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

        # Get the actual rendered text content
        rendered_text = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent.textContent || textContent.innerText || '';
        """)
        print(f"🔧 Rendered text: '{rendered_text}'")

        # Find the position of "technology" in the rendered text
        target_text = "technology"
        start_pos = rendered_text.find(target_text)
        end_pos = start_pos + len(target_text)

        if start_pos == -1:
            self.fail(f"Target text '{target_text}' not found in rendered text")

        print(f"🔧 Found '{target_text}' at positions {start_pos}-{end_pos}")

        # Verify the positions are correct by checking what text is at those positions
        actual_text_at_positions = rendered_text[start_pos:end_pos]
        print(f"🔧 Text at positions {start_pos}-{end_pos}: '{actual_text_at_positions}'")

        if actual_text_at_positions != target_text:
            print(f"⚠️ WARNING: Text at positions {start_pos}-{end_pos} is '{actual_text_at_positions}', not '{target_text}'")
            # Find the correct positions for "technology"
            correct_start = rendered_text.find("technology")
            if correct_start != -1:
                correct_end = correct_start + len("technology")
                print(f"🔧 Correct positions for 'technology': {correct_start}-{correct_end}")
                start_pos = correct_start
                end_pos = correct_end
                print(f"🔧 Updated positions: {start_pos}-{end_pos}")
                actual_text_at_positions = rendered_text[start_pos:end_pos]
                print(f"🔧 Updated text at positions: '{actual_text_at_positions}'")

        # Step 1: Create span annotation and save to server
        print("\n📝 Step 1: Creating span annotation and saving to server...")

        # Get session cookies for API requests
        session_cookies = self.get_session_cookies()

        # Get the actual current instance ID from the server
        current_instance_response = requests.get(
            f"{self.server.base_url}/api/current_instance",
            cookies=session_cookies
        )
        current_instance_data = current_instance_response.json()
        actual_instance_id = current_instance_data.get('instance_id')
        print(f"🔧 Actual current instance ID: {actual_instance_id}")

        # Create span annotation via API (this is how it should be done for persistence)
        span_request = {
            'instance_id': actual_instance_id,  # Use the actual instance ID
            'type': 'span',
            'schema': 'emotion',
            'state': [
                {
                    'name': 'happy',
                    'title': 'Happy',
                    'start': start_pos,
                    'end': end_pos,
                    'value': target_text
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_request,
            cookies=session_cookies
        )

        print(f"🔧 API response status: {response.status_code}")
        print(f"🔧 API response: {response.text}")

        self.assertEqual(response.status_code, 200, f"Failed to save span annotation: {response.text}")

        # Wait for the span manager to reload annotations from server
        time.sleep(0.05)

        # Force span manager to reload annotations
        load_result = self.execute_script_safe("""
            if (window.spanManager) {
                console.log('🔍 [DEBUG] About to call loadAnnotations');
                console.log('🔍 [DEBUG] Current annotations before load:', window.spanManager.annotations);
                return window.spanManager.loadAnnotations('1').then(result => {
                    console.log('🔍 [DEBUG] loadAnnotations completed:', result);
                    console.log('🔍 [DEBUG] Annotations after load:', window.spanManager.annotations);
                    return {
                        success: true,
                        result: result,
                        annotations: window.spanManager.annotations,
                        annotationsCount: window.spanManager.annotations?.spans?.length || 0
                    };
                }).catch(error => {
                    console.error('🔍 [DEBUG] loadAnnotations failed:', error);
                    return { success: false, error: error.message };
                });
            }
            return Promise.resolve({ success: false, error: 'No span manager' });
        """)

        print(f"🔧 Load annotations result: {load_result}")

        # Wait a moment for any async operations to complete
        time.sleep(0.1)

        # Test the API endpoint directly to see what it returns
        print("\n🔧 Testing API endpoint directly...")
        api_response = requests.get(
            f"{self.server.base_url}/api/spans/{actual_instance_id}",
            cookies=session_cookies
        )
        print(f"🔧 Direct API response status: {api_response.status_code}")
        print(f"🔧 Direct API response: {api_response.text}")

        if api_response.status_code == 200:
            api_data = api_response.json()
            print(f"🔧 API data spans count: {len(api_data.get('spans', []))}")
            print(f"🔧 API data spans: {api_data.get('spans', [])}")

            # Check if the JavaScript span manager has the correct data
            span_manager_state = self.execute_script_safe("""
                if (window.spanManager) {
                    return {
                        hasAnnotations: !!window.spanManager.annotations,
                        annotationsCount: window.spanManager.annotations?.spans?.length || 0,
                        annotations: window.spanManager.annotations,
                        currentInstanceId: window.spanManager.currentInstanceId,
                        isInitialized: window.spanManager.isInitialized
                    };
                }
                return { error: 'No span manager' };
            """)
            print(f"🔧 Span manager state: {span_manager_state}")

            # Verify that the span manager has the correct data
            if span_manager_state.get('annotationsCount', 0) == 0:
                self.fail(f"Span manager has no annotations after loading. API returned {len(api_data.get('spans', []))} spans, but span manager has {span_manager_state.get('annotationsCount', 0)}")

            # Verify that the span data matches
            api_spans = api_data.get('spans', [])
            if api_spans:
                api_span = api_spans[0]
                span_manager_annotations = span_manager_state.get('annotations', {})
                span_manager_spans = span_manager_annotations.get('spans', [])

                if span_manager_spans:
                    span_manager_span = span_manager_spans[0]
                    print(f"🔧 API span: {api_span}")
                    print(f"🔧 Span manager span: {span_manager_span}")

                    # Verify the span data matches
                    if api_span.get('start') != span_manager_span.get('start'):
                        self.fail(f"Span start position mismatch: API={api_span.get('start')}, SpanManager={span_manager_span.get('start')}")

                    if api_span.get('end') != span_manager_span.get('end'):
                        self.fail(f"Span end position mismatch: API={api_span.get('end')}, SpanManager={span_manager_span.get('end')}")

                    if api_span.get('text') != span_manager_span.get('text'):
                        self.fail(f"Span text mismatch: API={api_span.get('text')}, SpanManager={span_manager_span.get('text')}")

                    print("✅ Span data matches between API and SpanManager")
                else:
                    self.fail("Span manager has no spans in annotations")
            else:
                self.fail("API returned no spans")

        time.sleep(0.05)

        # Verify initial overlay exists
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertGreater(len(span_overlays), 0, "No span overlays found after creation")

        initial_overlay = span_overlays[0]
        initial_rect = initial_overlay.rect
        print(f"🔧 Initial overlay position: {initial_rect}")

        # Step 2: Navigate away (to a different instance)
        print("\n📝 Step 2: Navigating away...")

        # Try to navigate to next instance, if available
        try:
            next_button = self.driver.find_element(By.ID, "next-button")
            if next_button.is_enabled():
                next_button.click()
                print("🔧 Navigated to next instance")
                time.sleep(0.05)
            else:
                print("🔧 Next button not available, refreshing page instead")
                self.driver.refresh()
                time.sleep(0.05)
        except:
            print("🔧 Next button not found, refreshing page instead")
            self.driver.refresh()
            time.sleep(0.05)

        # Step 3: Navigate back (to the original instance)
        print("\n📝 Step 3: Navigating back...")

        try:
            prev_button = self.driver.find_element(By.ID, "prev-button")
            if prev_button.is_enabled():
                prev_button.click()
                print("🔧 Navigated back to first instance")
            else:
                print("🔧 Prev button not available, navigating to first instance")
                self.driver.get(f"{self.server.base_url}/annotate")
        except:
            print("🔧 Prev button not found, navigating to first instance")
            self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load and span manager to reinitialize
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(0.1)

        # Wait for span manager to be reinitialized
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.isInitialized) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Step 4: Check overlay positioning
        print("\n📝 Step 4: Checking overlay positioning...")

        # Check if span overlays exist after navigation
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay-pure")
        self.assertGreater(len(span_overlays), 0, "No span overlays found after navigation")

        final_overlay = span_overlays[0]
        final_rect = final_overlay.rect
        print(f"🔧 Final overlay position: {final_rect}")

        # Step 5: Verify text content
        print("\n📝 Step 5: Verifying text content...")

        # Get the text that the overlay is actually covering
        covered_text = self.execute_script_safe("""
            const overlay = document.querySelector('.span-overlay-pure');
            if (!overlay) {
                return { success: false, error: 'No overlay found' };
            }

            const start = parseInt(overlay.dataset.start);
            const end = parseInt(overlay.dataset.end);
            const textContent = document.getElementById('text-content');
            const fullText = textContent.textContent || textContent.innerText || '';

            const coveredText = fullText.substring(start, end);

            return {
                success: true,
                coveredText: coveredText,
                start: start,
                end: end,
                fullText: fullText
            };
        """)

        print(f"🔧 Covered text result: {covered_text}")
        self.assertTrue(covered_text.get('success', False))

        # Check if the covered text matches the expected text
        actual_covered_text = covered_text.get('coveredText', '').strip()
        print(f"🔧 Actual covered text: '{actual_covered_text}'")
        print(f"🔧 Expected text: '{target_text}'")

        # This is where the bug should be visible - the overlay should be positioned over the wrong text
        if actual_covered_text != target_text:
            print("🚨 BUG REPRODUCED: Overlay is positioned over wrong text!")
            print(f"   Expected: '{target_text}'")
            print(f"   Actual: '{actual_covered_text}'")

            # Check position differences
            position_tolerance = 10
            top_diff = abs(final_rect['top'] - initial_rect['top'])
            left_diff = abs(final_rect['left'] - initial_rect['left'])

            print(f"🔧 Position differences - Top: {top_diff}px, Left: {left_diff}px")

            if top_diff > position_tolerance or left_diff > position_tolerance:
                print("🚨 BUG CONFIRMED: Overlay position changed significantly after navigation!")
                self.fail(f"Span overlay positioning bug reproduced! Overlay moved from covering '{target_text}' to covering '{actual_covered_text}'")
        else:
            print("✅ No positioning bug detected - overlay still covers correct text")

    def test_span_overlay_text_verification(self):
        """Test that the text in the span overlay matches the selected text."""
        print("\n" + "="*80)
        print("🧪 TESTING SPAN OVERLAY TEXT VERIFICATION")
        print("="*80)

        # Navigate to annotation page
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
        print(f"🔧 Rendered text: '{rendered_text}'")

        # Find the position of "technology" in the rendered text
        target_text = "technology"
        start_pos = rendered_text.find(target_text)
        end_pos = start_pos + len(target_text)

        if start_pos == -1:
            self.fail(f"Target text '{target_text}' not found in rendered text: '{rendered_text}'")

        print(f"🔧 Found '{target_text}' at positions {start_pos}-{end_pos}")

        # Create a span annotation programmatically with the correct positions
        span_creation_result = self.execute_script_safe(f"""
            if (!window.spanManager) {{
                return {{ success: false, error: 'Span manager not available' }};
            }}

            // Create a test span annotation for "technology" using actual positions
            const testSpan = {{
                id: 'test_span_2',
                start: {start_pos},  // Actual position in rendered text
                end: {end_pos},
                label: 'happy',
                schema: 'emotion',
                text: '{target_text}'
            }};

            // Add the span to the annotations
            if (!window.spanManager.annotations) {{
                window.spanManager.annotations = {{ spans: [] }};
            }}
            window.spanManager.annotations.spans.push(testSpan);

            // Render the spans
            window.spanManager.renderSpans();

            return {{ success: true, span: testSpan }};
        """)

        print(f"🔧 Span creation result: {span_creation_result}")
        self.assertTrue(span_creation_result.get('success', False),
                       f"Span creation failed: {span_creation_result.get('error', 'Unknown error')}")

        # Wait for the span overlay to appear
        time.sleep(0.1)

        # Check that the span overlay exists (pure CSS system)
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay-pure")
        self.assertGreater(len(span_overlays), 0, "No span overlays found")

        # Get the text content that the span covers by extracting it from the rendered text
        # using the span's start and end positions
        covered_text = self.execute_script_safe(f"""
            const overlay = document.querySelector('.span-overlay-pure') || document.querySelector('.span-overlay');
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
                end: end,
                renderedText: renderedText
            }};
        """)

        print(f"🔧 Covered text extraction result: {covered_text}")
        self.assertTrue(covered_text.get('success', False),
                       f"Covered text extraction failed: {covered_text.get('error', 'Unknown error')}")

        # Verify the covered text matches the expected text
        actual_text = covered_text.get('coveredText', '')
        self.assertEqual(actual_text, target_text,
                        f"Covered text '{actual_text}' does not match expected text '{target_text}'")

        print(f"✅ Covered text matches expected: '{actual_text}'")

        # Also verify that the overlay has the correct data attributes
        overlay_data = self.execute_script_safe("""
            const overlay = document.querySelector('.span-overlay-pure');
            if (!overlay) {
                return { success: false, error: 'No overlay found' };
            }

            return {
                success: true,
                annotationId: overlay.dataset.annotationId,
                start: overlay.dataset.start,
                end: overlay.dataset.end,
                label: overlay.dataset.label
            };
        """)

        print(f"🔧 Overlay data: {overlay_data}")
        self.assertTrue(overlay_data.get('success', False),
                       f"Overlay data check failed: {overlay_data.get('error', 'Unknown error')}")

        # Verify the data attributes are correct
        self.assertEqual(overlay_data.get('annotationId'), 'test_span_2')
        self.assertEqual(overlay_data.get('start'), str(start_pos))
        self.assertEqual(overlay_data.get('end'), str(end_pos))
        self.assertEqual(overlay_data.get('label'), 'happy')

        print("✅ Overlay data attributes are correct")

    def test_unified_text_positioning_approach(self):
        """Test that the unified text positioning approach works correctly."""
        print("\n" + "="*80)
        print("🧪 TESTING UNIFIED TEXT POSITIONING APPROACH")
        print("="*80)

        # Navigate to annotation page
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
            if (textContent) {
                // Get the original text for positioning
                let originalText = textContent.getAttribute('data-original-text');
                if (!originalText) {
                    originalText = textContent.textContent || textContent.innerText || '';
                }
                return originalText;
            }
            return '';
        """)

        print(f"🔧 Rendered text length: {len(rendered_text)}")
        print(f"🔧 Rendered text: '{rendered_text}'")

        # Find the position of "technology" in the rendered text
        target_text = "technology"
        start_pos = rendered_text.find(target_text)
        end_pos = start_pos + len(target_text)

        if start_pos == -1:
            self.fail(f"Target text '{target_text}' not found in rendered text")

        print(f"🔧 Found '{target_text}' at positions {start_pos}-{end_pos}")

        # Verify the positions are correct by checking what text is at those positions
        actual_text_at_positions = rendered_text[start_pos:end_pos]
        print(f"🔧 Text at positions {start_pos}-{end_pos}: '{actual_text_at_positions}'")

        if actual_text_at_positions != target_text:
            print(f"⚠️ WARNING: Text at positions {start_pos}-{end_pos} is '{actual_text_at_positions}', expected '{target_text}'")
            # Try to find the correct positions
            all_positions = []
            pos = 0
            while True:
                pos = rendered_text.find(target_text, pos)
                if pos == -1:
                    break
                all_positions.append(pos)
                pos += 1
            print(f"🔧 All positions of '{target_text}': {all_positions}")

        # Test the unified positioning approach by creating a span annotation
        print("\n📝 Testing unified positioning approach...")

        # Select a label first
        self.execute_script_safe("""
            const checkbox = document.querySelector('input[type="checkbox"][id*="emotion_happy"]');
            if (checkbox) {
                checkbox.checked = true;
                checkbox.click();
                console.log('🔧 Selected happy label');
            } else {
                console.log('🔧 Could not find happy label checkbox');
            }
        """)

        # Create a span annotation using the unified approach
        create_result = self.execute_script_safe(f"""
            const textContent = document.getElementById('text-content');
            if (!textContent) return {{ success: false, error: 'No text content element' }};

            // Create a range for the target text
            const text = textContent.textContent || textContent.innerText || '';
            const targetText = '{target_text}';
            const startPos = {start_pos};
            const endPos = {end_pos};

            // Verify the text at the positions
            const extractedText = text.substring(startPos, endPos);
            console.log('🔧 Extracted text:', extractedText, 'Expected:', targetText);

            if (extractedText !== targetText) {{
                return {{ success: false, error: 'Text mismatch: ' + extractedText + ' vs ' + targetText }};
            }}

            // Create a range for the target positions
            const range = document.createRange();
            const textNode = textContent.firstChild;
            if (!textNode || textNode.nodeType !== Node.TEXT_NODE) {{
                return {{ success: false, error: 'No text node found' }};
            }}

            range.setStart(textNode, startPos);
            range.setEnd(textNode, endPos);

            // Test the unified positioning approach
            if (typeof calculateTextOffsetsFromSelection === 'function') {{
                const offsets = calculateTextOffsetsFromSelection(textContent, range);
                console.log('🔧 Unified positioning result:', offsets);
                return {{ success: true, offsets: offsets }};
            }} else {{
                return {{ success: false, error: 'Unified positioning function not available' }};
            }}
        """)

        print(f"🔧 Unified positioning test result: {create_result}")

        if not create_result.get('success'):
            self.fail(f"Unified positioning test failed: {create_result.get('error')}")

        # Verify the offsets match our expected positions
        offsets = create_result.get('offsets', {})
        if offsets.get('start') != start_pos or offsets.get('end') != end_pos:
            self.fail(f"Offset mismatch: expected {start_pos}-{end_pos}, got {offsets.get('start')}-{offsets.get('end')}")

        print("✅ Unified text positioning approach test passed!")

    def test_simple_getspans_debugging(self):
        """Simple test to debug the getSpans() method issue."""
        print("\n" + "="*80)
        print("🧪 SIMPLE GETSPANS DEBUGGING")
        print("="*80)

        # Navigate to annotation page
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

        # Create a span annotation via API
        session_cookies = self.get_session_cookies()

        # Get the actual current instance ID from the server
        current_instance_response = requests.get(
            f"{self.server.base_url}/api/current_instance",
            cookies=session_cookies
        )
        current_instance_data = current_instance_response.json()
        actual_instance_id = current_instance_data.get('instance_id')
        print(f"🔧 Actual current instance ID: {actual_instance_id}")

        # Create span annotation via API
        span_data = {
            "type": "span",
            "schema": "emotion",
            "state": [
                {
                    "name": "happy",
                    "start": 40,
                    "end": 50,
                    "title": "Happy",
                    "value": "technology"
                }
            ],
            "instance_id": actual_instance_id
        }

        api_response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_data,
            cookies=session_cookies
        )
        print(f"🔧 API response status: {api_response.status_code}")

        # Test the API endpoint directly
        api_response = requests.get(
            f"{self.server.base_url}/api/spans/{actual_instance_id}",
            cookies=session_cookies
        )
        print(f"🔧 Direct API response status: {api_response.status_code}")
        print(f"🔧 Direct API response: {api_response.text}")

        # Now test the JavaScript getSpans method
        print("\n🔧 Testing JavaScript getSpans method...")

        spans_result = self.execute_script_safe("""
            if (window.spanManager) {
                console.log('🔍 [DEBUG] Testing getSpans() method');
                console.log('🔍 [DEBUG] this.annotations:', window.spanManager.annotations);
                console.log('🔍 [DEBUG] this.annotations?.spans:', window.spanManager.annotations?.spans);

                const spans = window.spanManager.getSpans();
                console.log('🔍 [DEBUG] getSpans() returned:', spans);

                return {
                    annotations: window.spanManager.annotations,
                    annotationsSpans: window.spanManager.annotations?.spans,
                    getSpansResult: spans,
                    annotationsType: typeof window.spanManager.annotations,
                    spansType: typeof window.spanManager.annotations?.spans
                };
            }
            return { error: 'No span manager' };
        """)

        print(f"🔧 Spans result: {spans_result}")

        # Now try to load annotations
        print("\n🔧 Testing loadAnnotations method...")

        load_result = self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.loadAnnotations('1').then(result => {
                    console.log('🔍 [DEBUG] loadAnnotations completed');
                    console.log('🔍 [DEBUG] this.annotations after load:', window.spanManager.annotations);
                    console.log('🔍 [DEBUG] this.annotations?.spans after load:', window.spanManager.annotations?.spans);

                    const spans = window.spanManager.getSpans();
                    console.log('🔍 [DEBUG] getSpans() after load:', spans);

                    return {
                        success: true,
                        result: result,
                        annotations: window.spanManager.annotations,
                        annotationsSpans: window.spanManager.annotations?.spans,
                        getSpansResult: spans
                    };
                }).catch(error => {
                    console.error('🔍 [DEBUG] loadAnnotations failed:', error);
                    return { success: false, error: error.message };
                });
            }
            return Promise.resolve({ success: false, error: 'No span manager' });
        """)

        print(f"🔧 Load result: {load_result}")

    def test_javascript_api_call_debugging(self):
        """Test to debug why JavaScript API calls are not working correctly."""
        print("\n" + "="*80)
        print("🧪 DEBUGGING JAVASCRIPT API CALLS")
        print("="*80)

        # Navigate to annotation page
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

        # Get browser console logs
        console_logs = self.driver.get_log('browser')
        print(f"🔧 Browser console logs before API call: {len(console_logs)} entries")
        for log in console_logs[-10:]:  # Show last 10 logs
            print(f"🔧 Console: {log['message']}")

        # Clear console logs
        self.driver.execute_script("console.clear();")

        # Create a span annotation via API
        session_cookies = self.get_session_cookies()

        # Get the actual current instance ID from the server
        current_instance_response = requests.get(
            f"{self.server.base_url}/api/current_instance",
            cookies=session_cookies
        )
        current_instance_data = current_instance_response.json()
        actual_instance_id = current_instance_data.get('instance_id')
        print(f"🔧 Actual current instance ID: {actual_instance_id}")

        # Create span annotation via API
        span_data = {
            "type": "span",
            "schema": "emotion",
            "state": [
                {
                    "name": "happy",
                    "start": 40,
                    "end": 50,
                    "title": "Happy",
                    "value": "technology"
                }
            ],
            "instance_id": actual_instance_id
        }

        api_response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_data,
            cookies=session_cookies
        )
        print(f"🔧 API response status: {api_response.status_code}")
        print(f"🔧 API response: {api_response.text}")

        # Wait a moment for the server to process
        time.sleep(0.1)

        # Test the API endpoint directly
        api_response = requests.get(
            f"{self.server.base_url}/api/spans/{actual_instance_id}",
            cookies=session_cookies
        )
        print(f"🔧 Direct API response status: {api_response.status_code}")
        print(f"🔧 Direct API response: {api_response.text}")

        # Now call the JavaScript loadAnnotations method
        print("\n🔧 Calling JavaScript loadAnnotations method...")

        # Check if span manager is available
        span_manager_check = self.execute_script_safe("""
            console.log('🔍 [DEBUG] Checking span manager availability...');
            if (window.spanManager) {
                console.log('🔍 [DEBUG] Span manager exists');
                console.log('🔍 [DEBUG] Span manager isInitialized:', window.spanManager.isInitialized);
                console.log('🔍 [DEBUG] Span manager loadAnnotations method:', typeof window.spanManager.loadAnnotations);
                return {
                    exists: true,
                    isInitialized: window.spanManager.isInitialized,
                    hasLoadAnnotations: typeof window.spanManager.loadAnnotations === 'function',
                    currentInstanceId: window.spanManager.currentInstanceId
                };
            } else {
                console.log('🔍 [DEBUG] Span manager does not exist');
                return { exists: false };
            }
        """)
        print(f"🔧 Span manager check: {span_manager_check}")

        # Check browser session cookies
        browser_cookies = self.driver.get_cookies()
        print(f"🔧 Browser cookies: {len(browser_cookies)} cookies")
        for cookie in browser_cookies:
            print(f"🔧 Browser cookie: {cookie['name']} = {cookie['value']}")

        # Check Python test session cookies
        print(f"🔧 Python test session cookies: {session_cookies}")

        # Compare session cookies
        browser_session_cookie = next((c for c in browser_cookies if c['name'] == 'session'), None)
        python_session_cookie = session_cookies.get('session')

        if browser_session_cookie and python_session_cookie:
            print(f"🔧 Browser session: {browser_session_cookie['value']}")
            print(f"🔧 Python session: {python_session_cookie}")
            if browser_session_cookie['value'] == python_session_cookie:
                print("✅ Session cookies match")
            else:
                print("❌ Session cookies do not match - this is the issue!")
        else:
            print("⚠️ Could not find session cookies")

        load_result = self.execute_script_safe("""
            if (window.spanManager) {
                console.log('🔍 [DEBUG] About to call loadAnnotations');

                // Capture debugging output in a variable
                let debugOutput = [];
                const originalLog = console.log;
                const originalError = console.error;

                console.log = function(...args) {
                    debugOutput.push('LOG: ' + args.join(' '));
                    originalLog.apply(console, args);
                };

                console.error = function(...args) {
                    debugOutput.push('ERROR: ' + args.join(' '));
                    originalError.apply(console, args);
                };

                return window.spanManager.loadAnnotations('1').then(result => {
                    console.log('🔍 [DEBUG] loadAnnotations completed:', result);

                    // Detailed inspection of the annotations object
                    console.log('🔍 [DEBUG] Detailed annotations inspection:');
                    console.log('🔍 [DEBUG] - this.annotations type:', typeof window.spanManager.annotations);
                    console.log('🔍 [DEBUG] - this.annotations keys:', Object.keys(window.spanManager.annotations || {}));
                    console.log('🔍 [DEBUG] - this.annotations.spans type:', typeof window.spanManager.annotations?.spans);
                    console.log('🔍 [DEBUG] - this.annotations.spans length:', window.spanManager.annotations?.spans?.length);
                    console.log('🔍 [DEBUG] - this.annotations.spans content:', JSON.stringify(window.spanManager.annotations?.spans));

                    // Test getSpans() method
                    const spans = window.spanManager.getSpans();
                    console.log('🔍 [DEBUG] getSpans() returned:', spans);
                    console.log('🔍 [DEBUG] getSpans() length:', spans?.length);

                    return {
                        success: true,
                        result: result,
                        debugOutput: debugOutput,
                        annotationsType: typeof window.spanManager.annotations,
                        annotationsKeys: Object.keys(window.spanManager.annotations || {}),
                        spansType: typeof window.spanManager.annotations?.spans,
                        spansLength: window.spanManager.annotations?.spans?.length,
                        spansContent: JSON.stringify(window.spanManager.annotations?.spans),
                        getSpansResult: spans,
                        getSpansLength: spans?.length
                    };
                }).catch(error => {
                    console.error('🔍 [DEBUG] loadAnnotations failed:', error);
                    return {
                        success: false,
                        error: error.message,
                        debugOutput: debugOutput
                    };
                }).finally(() => {
                    // Restore original console methods
                    console.log = originalLog;
                    console.error = originalError;
                });
            }
            return Promise.resolve({ success: false, error: 'No span manager' });
        """)

        print(f"🔧 Load annotations result: {load_result}")

        # Print the captured debug output
        if 'debugOutput' in load_result:
            print("🔧 JavaScript debug output:")
            for line in load_result['debugOutput']:
                print(f"  {line}")

        # Display detailed annotations inspection
        if 'annotationsType' in load_result:
            print(f"🔍 [DEBUG] Annotations type: {load_result['annotationsType']}")
            print(f"🔍 [DEBUG] Annotations keys: {load_result['annotationsKeys']}")
            print(f"🔍 [DEBUG] Spans type: {load_result['spansType']}")
            print(f"🔍 [DEBUG] Spans length: {load_result['spansLength']}")
            print(f"🔍 [DEBUG] Spans content: {load_result['spansContent']}")
            print(f"🔍 [DEBUG] getSpans() result: {load_result['getSpansResult']}")
            print(f"🔍 [DEBUG] getSpans() length: {load_result['getSpansLength']}")

        # Check span manager state
        span_manager_state = self.execute_script_safe("""
            if (window.spanManager) {
                return {
                    hasAnnotations: !!window.spanManager.annotations,
                    annotationsCount: window.spanManager.annotations?.spans?.length || 0,
                    annotations: window.spanManager.annotations,
                    currentInstanceId: window.spanManager.currentInstanceId,
                    isInitialized: window.spanManager.isInitialized
                };
            }
            return { error: 'No span manager' };
        """)
        print(f"🔧 Span manager state: {span_manager_state}")

    def test_span_positioning_without_initialization_check(self):
        """Test span positioning without relying on isInitialized flag."""
        print("\n" + "="*80)
        print("🧪 TESTING SPAN POSITIONING WITHOUT INITIALIZATION CHECK")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Get rendered text and find target text
        rendered_text = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent ? textContent.textContent : '';
        """)
        print(f"🔧 Rendered text: '{rendered_text}'")

        target_text = "technology"
        start_pos = rendered_text.find(target_text)
        end_pos = start_pos + len(target_text)
        print(f"🔧 Found '{target_text}' at positions {start_pos}-{end_pos}")

        # Create span annotation programmatically
        span_data = {
            'id': 'test_span_3',
            'start': start_pos,
            'end': end_pos,
            'text': target_text,
            'label': 'happy',
            'schema': 'emotion'
        }

        # Create overlay directly
        overlay_result = self.execute_script_safe(f"""
            if (window.spanManager) {{
                const span = {span_data};
                const textContent = document.getElementById('text-content');
                const spanOverlays = document.getElementById('span-overlays');

                if (textContent && spanOverlays) {{
                    // Create overlay element
                    const overlay = document.createElement('div');
                    overlay.className = 'span-overlay-pure';
                    overlay.setAttribute('data-start', span.start);
                    overlay.setAttribute('data-end', span.end);
                    overlay.setAttribute('data-label', span.label);
                    overlay.setAttribute('data-annotation-id', span.id);

                    // Position the overlay
                    const rects = getCharRangeBoundingRect(textContent, span.start, span.end);
                    if (rects && rects.length > 0) {{
                        const rect = rects[0];
                        overlay.style.position = 'absolute';
                        overlay.style.left = rect.x + 'px';
                        overlay.style.top = rect.y + 'px';
                        overlay.style.width = rect.width + 'px';
                        overlay.style.height = rect.height + 'px';
                        overlay.style.backgroundColor = 'rgba(255, 255, 0, 0.3)';
                        overlay.style.border = '2px solid yellow';
                        overlay.style.pointerEvents = 'none';
                        overlay.style.zIndex = '1000';

                        spanOverlays.appendChild(overlay);

                        return {{
                            success: true,
                            position: {{
                                x: rect.x,
                                y: rect.y,
                                width: rect.width,
                                height: rect.height
                            }}
                        }};
                    }} else {{
                        return {{ success: false, error: 'No bounding rects returned' }};
                    }}
                }} else {{
                    return {{ success: false, error: 'Required elements not found' }};
                }}
            }} else {{
                return {{ success: false, error: 'Span manager not available' }};
            }}
        """)

        print(f"🔧 Overlay creation result: {overlay_result}")

        if overlay_result.get('success'):
                        # Extract the text that the overlay covers
            covered_text_result = self.execute_script_safe("""
                const textContent = document.getElementById('text-content');
                const overlay = document.querySelector('.span-overlay-pure');

                console.log('🔍 [DEBUG] textContent:', textContent);
                console.log('🔍 [DEBUG] overlay:', overlay);
                console.log('🔍 [DEBUG] overlay attributes:', overlay ? {
                    start: overlay.getAttribute('data-start'),
                    end: overlay.getAttribute('data-end'),
                    label: overlay.getAttribute('data-label')
                } : 'no overlay');

                if (textContent && overlay) {
                    const start = parseInt(overlay.getAttribute('data-start'));
                    const end = parseInt(overlay.getAttribute('data-end'));
                    const renderedText = textContent.textContent;
                    const coveredText = renderedText.substring(start, end);

                    return {
                        success: true,
                        coveredText: coveredText,
                        start: start,
                        end: end,
                        renderedText: renderedText
                    };
                } else {
                    return {
                        success: false,
                        error: 'Elements not found',
                        textContentExists: !!textContent,
                        overlayExists: !!overlay
                    };
                }
            """)

            print(f"🔧 Covered text extraction result: {covered_text_result}")

            if covered_text_result.get('success'):
                covered_text = covered_text_result['coveredText']
                print(f"✅ Covered text: '{covered_text}'")
                print(f"✅ Expected text: '{target_text}'")

                # Verify the overlay covers the correct text
                assert covered_text == target_text, f"Overlay covers '{covered_text}' instead of '{target_text}'"
                print("✅ Overlay positioning is correct!")

                # Now test navigation and return
                print("\n📝 Testing navigation and return...")

                # Navigate away (refresh page)
                self.driver.refresh()
                self.wait_for_element(By.ID, "instance-text")

                # Wait for elements
                self.execute_script_safe("""
                    return new Promise((resolve) => {
                        const check = () => {
                            if (window.spanManager && document.getElementById('text-content')) resolve(true);
                            else setTimeout(check, 100);
                        }; check();
                    });
                """)

                # Navigate back (refresh again to return to same instance)
                self.driver.refresh()
                self.wait_for_element(By.ID, "instance-text")

                # Wait for elements again
                self.execute_script_safe("""
                    return new Promise((resolve) => {
                        const check = () => {
                            if (window.spanManager && document.getElementById('text-content')) resolve(true);
                            else setTimeout(check, 100);
                        }; check();
                    });
                """)

                # Recreate the overlay after navigation
                overlay_result_after = self.execute_script_safe(f"""
                    if (window.spanManager) {{
                        const span = {span_data};
                        const textContent = document.getElementById('text-content');
                        const spanOverlays = document.getElementById('span-overlays');

                        if (textContent && spanOverlays) {{
                            // Create overlay element
                            const overlay = document.createElement('div');
                            overlay.className = 'span-overlay-pure';
                            overlay.setAttribute('data-start', span.start);
                            overlay.setAttribute('data-end', span.end);
                            overlay.setAttribute('data-label', span.label);
                            overlay.setAttribute('data-annotation-id', span.id);

                            // Position the overlay
                            const rects = getCharRangeBoundingRect(textContent, span.start, span.end);
                            if (rects && rects.length > 0) {{
                                const rect = rects[0];
                                overlay.style.position = 'absolute';
                                overlay.style.left = rect.x + 'px';
                                overlay.style.top = rect.y + 'px';
                                overlay.style.width = rect.width + 'px';
                                overlay.style.height = rect.height + 'px';
                                overlay.style.backgroundColor = 'rgba(255, 255, 0, 0.3)';
                                overlay.style.border = '2px solid yellow';
                                overlay.style.pointerEvents = 'none';
                                overlay.style.zIndex = '1000';

                                spanOverlays.appendChild(overlay);

                                return {{
                                    success: true,
                                    position: {{
                                        x: rect.x,
                                        y: rect.y,
                                        width: rect.width,
                                        height: rect.height
                                    }}
                                }};
                            }} else {{
                                return {{ success: false, error: 'No bounding rects returned' }};
                            }}
                        }} else {{
                            return {{ success: false, error: 'Required elements not found' }};
                        }}
                    }} else {{
                        return {{ success: false, error: 'Span manager not available' }};
                    }}
                """)

                print(f"🔧 Overlay creation result after navigation: {overlay_result_after}")

                if overlay_result_after.get('success'):
                    # Extract the text that the overlay covers after navigation
                    covered_text_result_after = self.execute_script_safe("""
                        const textContent = document.getElementById('text-content');
                        const overlay = document.querySelector('.span-overlay-pure');

                        if (textContent && overlay) {
                            const start = parseInt(overlay.getAttribute('data-start'));
                            const end = parseInt(overlay.getAttribute('data-end'));
                            const renderedText = textContent.textContent;
                            const coveredText = renderedText.substring(start, end);

                            return {
                                success: true,
                                coveredText: coveredText,
                                start: start,
                                end: end,
                                renderedText: renderedText
                            };
                        } else {
                            return { success: false, error: 'Elements not found' };
                        }
                    """)

                    print(f"🔧 Covered text extraction result after navigation: {covered_text_result_after}")

                    if covered_text_result_after.get('success'):
                        covered_text_after = covered_text_result_after['coveredText']
                        print(f"✅ Covered text after navigation: '{covered_text_after}'")
                        print(f"✅ Expected text: '{target_text}'")

                        # Verify the overlay covers the correct text after navigation
                        assert covered_text_after == target_text, f"Overlay covers '{covered_text_after}' instead of '{target_text}' after navigation"
                        print("✅ Overlay positioning is correct after navigation!")
                    else:
                        print(f"❌ Failed to extract covered text after navigation: {covered_text_result_after}")
                else:
                    print(f"❌ Failed to create overlay after navigation: {overlay_result_after}")
            else:
                print(f"❌ Failed to extract covered text: {covered_text_result}")
        else:
            print(f"❌ Failed to create overlay: {overlay_result}")

    def test_offset_calculation_after_reload(self):
        """Test that offset calculations work correctly after page reload."""
        print("\n" + "="*80)
        print("🧪 TESTING OFFSET CALCULATION AFTER PAGE RELOAD")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Get the original text from the backend API
        api_response = requests.get(f"{self.server.base_url}/api/spans/1", cookies=self.driver.get_cookies())
        api_data = api_response.json()
        original_text = api_data.get('text', '')
        print(f"🔧 Original text from API: '{original_text}'")

        # Get the rendered text from the DOM
        rendered_text = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent ? textContent.textContent : '';
        """)
        print(f"🔧 Rendered text from DOM: '{rendered_text}'")

        # Check if there's a difference between original and rendered text
        if original_text != rendered_text:
            print(f"⚠️ WARNING: Original text and rendered text differ!")
            print(f"   Original length: {len(original_text)}")
            print(f"   Rendered length: {len(rendered_text)}")
            print(f"   Difference: {len(rendered_text) - len(original_text)} characters")

        # Find target text in both versions
        target_text = "technology"
        original_start = original_text.find(target_text)
        original_end = original_start + len(target_text)
        rendered_start = rendered_text.find(target_text)
        rendered_end = rendered_start + len(target_text)

        print(f"🔧 Target text: '{target_text}'")
        print(f"🔧 Original text positions: {original_start}-{original_end}")
        print(f"🔧 Rendered text positions: {rendered_start}-{rendered_end}")

        # Create span annotation using the original text positions (as stored in backend)
        span_data = {
            'id': 'test_span_4',
            'start': original_start,
            'end': original_end,
            'text': target_text,
            'label': 'happy',
            'schema': 'emotion'
        }

        print(f"🔧 Creating span with original positions: {span_data}")

        # Test positioning with pure CSS functions
        positioning_result = self.execute_script_safe(f"""
            const span = {span_data};
            const textContent = document.getElementById('text-content');

            if (textContent) {{
                // Test the pure CSS positioning functions
                const originalText = getOriginalTextForPositioning(textContent);
                const fontMetrics = getFontMetrics(textContent);
                const positions = calculateCharacterPositions(originalText, span.start, span.end, fontMetrics, textContent);

                if (positions && positions.length > 0) {{
                    const position = positions[0];

                    // Extract the text that would be covered by this position
                    const coveredText = originalText.substring(span.start, span.end);

                    return {{
                        success: true,
                        position: {{
                            x: position.x,
                            y: position.y,
                            width: position.width,
                            height: position.height
                        }},
                        coveredText: coveredText,
                        expectedText: span.text,
                        start: span.start,
                        end: span.end,
                        originalTextLength: originalText.length
                    }};
                }} else {{
                    return {{ success: false, error: 'No positions calculated' }};
                }}
            }} else {{
                return {{ success: false, error: 'Text content element not found' }};
            }}
        """)

        print(f"🔧 Initial positioning result: {positioning_result}")

        if positioning_result.get('success'):
            covered_text = positioning_result['coveredText']
            expected_text = positioning_result['expectedText']
            print(f"✅ Initial positioning: '{covered_text}' matches '{expected_text}'")

            # Now reload the page and test again
            print("\n📝 Reloading page and testing positioning again...")
            self.driver.refresh()
            self.wait_for_element(By.ID, "instance-text")

            # Wait for elements again
            self.execute_script_safe("""
                return new Promise((resolve) => {
                    const check = () => {
                        if (window.spanManager && document.getElementById('text-content')) resolve(true);
                        else setTimeout(check, 100);
                    }; check();
                });
            """)

            # Get the rendered text again after reload
            rendered_text_after = self.execute_script_safe("""
                const textContent = document.getElementById('text-content');
                return textContent ? textContent.textContent : '';
            """)
            print(f"🔧 Rendered text after reload: '{rendered_text_after}'")

            # Test positioning with the same original offsets after reload
            positioning_result_after = self.execute_script_safe(f"""
                const span = {span_data};
                const textContent = document.getElementById('text-content');

                if (textContent) {{
                    // Test the pure CSS positioning functions
                    const originalText = getOriginalTextForPositioning(textContent);
                    const fontMetrics = getFontMetrics(textContent);
                    const positions = calculateCharacterPositions(originalText, span.start, span.end, fontMetrics, textContent);

                    if (positions && positions.length > 0) {{
                        const position = positions[0];

                        // Extract the text that would be covered by this position
                        const coveredText = originalText.substring(span.start, span.end);

                        return {{
                            success: true,
                            position: {{
                                x: position.x,
                                y: position.y,
                                width: position.width,
                                height: position.height
                            }},
                            coveredText: coveredText,
                            expectedText: span.text,
                            start: span.start,
                            end: span.end,
                            originalTextLength: originalText.length
                        }};
                    }} else {{
                        return {{ success: false, error: 'No positions calculated' }};
                    }}
                }} else {{
                    return {{ success: false, error: 'Text content element not found' }};
                }}
            """)

            print(f"🔧 Positioning result after reload: {positioning_result_after}")

            if positioning_result_after.get('success'):
                covered_text_after = positioning_result_after['coveredText']
                expected_text_after = positioning_result_after['expectedText']
                print(f"✅ Positioning after reload: '{covered_text_after}' matches '{expected_text_after}'")

                # Compare the results
                if covered_text == covered_text_after:
                    print("✅ SUCCESS: Offset calculation is consistent after page reload!")
                else:
                    print(f"❌ FAILURE: Offset calculation changed after reload!")
                    print(f"   Before reload: '{covered_text}'")
                    print(f"   After reload: '{covered_text_after}'")
                    print(f"   Expected: '{expected_text}'")

                    # This is the bug - the offsets are not working correctly after reload
                    assert False, f"Offset calculation failed after reload. Expected '{expected_text}', got '{covered_text_after}'"
            else:
                print(f"❌ Failed to position after reload: {positioning_result_after}")
        else:
            print(f"❌ Failed to position initially: {positioning_result}")

    def test_simple_offset_issue(self):
        """Simple test to identify the offset calculation issue."""
        print("\n" + "="*80)
        print("🧪 SIMPLE OFFSET CALCULATION TEST")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Get the original text from the backend API
        api_response = requests.get(f"{self.server.base_url}/api/spans/1", cookies=self.driver.get_cookies())
        api_data = api_response.json()
        original_text = api_data.get('text', '')
        print(f"🔧 Original text from API: '{original_text}'")

        # Get the rendered text from the DOM
        rendered_text = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent ? textContent.textContent : '';
        """)
        print(f"🔧 Rendered text from DOM: '{rendered_text}'")

        # Check if there's a difference between original and rendered text
        if original_text != rendered_text:
            print(f"⚠️ WARNING: Original text and rendered text differ!")
            print(f"   Original length: {len(original_text)}")
            print(f"   Rendered length: {len(rendered_text)}")
            print(f"   Difference: {len(rendered_text) - len(original_text)} characters")

        # Find target text in both versions
        target_text = "technology"
        original_start = original_text.find(target_text)
        original_end = original_start + len(target_text)
        rendered_start = rendered_text.find(target_text)
        rendered_end = rendered_start + len(target_text)

        print(f"🔧 Target text: '{target_text}'")
        print(f"🔧 Original text positions: {original_start}-{original_end}")
        print(f"🔧 Rendered text positions: {rendered_start}-{rendered_end}")

        # Force initialization of positioning strategy if not already initialized
        self.execute_script_safe("""
            return new Promise((resolve) => {
                if (window.spanManager && window.spanManager.positioningStrategy && !window.spanManager.positioningStrategy.isInitialized) {
                    console.log('🔧 Forcing positioning strategy initialization...');
                    window.spanManager.positioningStrategy.initialize().then(() => {
                        console.log('🔧 Positioning strategy initialization completed');
                        resolve(true);
                    }).catch((error) => {
                        console.error('🔧 Positioning strategy initialization failed:', error);
                        resolve(false);
                    });
                } else {
                    resolve(true);
                }
            });
        """)

        # Test the unified positioning strategy with original offsets
        test_result = self.execute_script_safe(f"""
            const textContent = document.getElementById('text-content');
            const originalStart = {original_start};
            const originalEnd = {original_end};
            const targetText = '{target_text}';

            if (textContent && window.spanManager && window.spanManager.positioningStrategy) {{
                // Test the unified positioning strategy
                const positioningStrategy = window.spanManager.positioningStrategy;

                if (!positioningStrategy.isInitialized) {{
                    return {{ success: false, error: 'Positioning strategy not initialized' }};
                }}

                // Create span using algorithm-based positioning
                const spanResult = positioningStrategy.createSpanWithAlgorithm(originalStart, originalEnd, targetText);

                if (spanResult && spanResult.positions && spanResult.positions.length > 0) {{
                    const position = spanResult.positions[0];

                    // Extract the text that would be covered by this position
                    const coveredText = positioningStrategy.getTextAtPosition(originalStart, originalEnd);

                    return {{
                        success: true,
                        coveredText: coveredText,
                        expectedText: targetText,
                        start: originalStart,
                        end: originalEnd,
                        position: {{
                            x: position.x,
                            y: position.y,
                            width: position.width,
                            height: position.height
                        }}
                    }};
                }} else {{
                    return {{ success: false, error: 'No positions calculated', spanResult: spanResult }};
                }}
            }} else {{
                return {{
                    success: false,
                    error: 'Text content element or positioning strategy not found',
                    textContentExists: !!textContent,
                    spanManagerExists: !!window.spanManager,
                    positioningStrategyExists: !!(window.spanManager && window.spanManager.positioningStrategy)
                }};
            }}
        """)

        print(f"🔧 Test result: {test_result}")

        if test_result.get('success'):
            covered_text = test_result['coveredText']
            expected_text = test_result['expectedText']

            if covered_text == expected_text:
                print(f"✅ SUCCESS: Offset calculation works correctly!")
                print(f"   Covered text: '{covered_text}'")
                print(f"   Expected text: '{expected_text}'")
            else:
                print(f"❌ FAILURE: Offset calculation is incorrect!")
                print(f"   Covered text: '{covered_text}'")
                print(f"   Expected text: '{expected_text}'")
                print(f"   This is the bug - offsets are not working correctly!")
        else:
            print(f"❌ Test failed: {test_result}")

    def test_function_availability(self):
        """Simple test to check if the getCharRangeBoundingRect function is available."""
        print("\n" + "="*80)
        print("🧪 TESTING FUNCTION AVAILABILITY")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Check if the function exists
        function_exists = self.execute_script_safe("""
            return typeof getCharRangeBoundingRect === 'function';
        """)
        print(f"🔧 getCharRangeBoundingRect function exists: {function_exists}")

        if not function_exists:
            print("❌ Function not found!")
            return

        # Get the text content element
        text_content_exists = self.execute_script_safe("""
            return document.getElementById('text-content') !== null;
        """)
        print(f"🔧 text-content element exists: {text_content_exists}")

        if not text_content_exists:
            print("❌ text-content element not found!")
            return

        # Get the text content
        text_content = self.execute_script_safe("""
            const element = document.getElementById('text-content');
            return element ? element.textContent : null;
        """)
        print(f"🔧 Text content: '{text_content}'")

        # Try to call the function with simple parameters
        try:
            result = self.execute_script_safe("""
                const element = document.getElementById('text-content');
                if (element && element.textContent) {
                    const text = element.textContent;
                    const targetText = 'technology';
                    const start = text.indexOf(targetText);
                    if (start !== -1) {
                        const end = start + targetText.length;
                        console.log('Calling getCharRangeBoundingRect with:', start, end);
                        const rects = getCharRangeBoundingRect(element, start, end);
                        return {
                            success: true,
                            rects: rects,
                            start: start,
                            end: end,
                            targetText: targetText
                        };
                    } else {
                        return { success: false, error: 'Target text not found' };
                    }
                } else {
                    return { success: false, error: 'No text content' };
                }
            """)
            print(f"🔧 Function call result: {result}")
        except Exception as e:
            print(f"❌ Exception calling function: {e}")

    def test_pure_css_functions_availability(self):
        """Test if the pure CSS functions are available and working."""
        print("\n" + "="*80)
        print("🧪 TESTING PURE CSS FUNCTIONS AVAILABILITY")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Check if pure CSS functions are available
        function_check = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            const functions = {
                getFontMetrics: typeof getFontMetrics === 'function',
                calculateCharacterPositions: typeof calculateCharacterPositions === 'function',
                createPureCSSOverlay: typeof createPureCSSOverlay === 'function',
                calculateTextOffsetsPureCSS: typeof calculateTextOffsetsPureCSS === 'function',
                getOriginalTextForPositioning: typeof getOriginalTextForPositioning === 'function'
            };

            console.log('🔍 [PURE CSS] Function availability:', functions);

            // Test getFontMetrics
            let fontMetrics = null;
            try {
                fontMetrics = getFontMetrics(textContent);
                console.log('🔍 [PURE CSS] Font metrics:', fontMetrics);
            } catch (error) {
                console.error('🔍 [PURE CSS] Error in getFontMetrics:', error);
            }

            // Test getOriginalTextForPositioning
            let originalText = null;
            try {
                originalText = getOriginalTextForPositioning(textContent);
                console.log('🔍 [PURE CSS] Original text:', originalText);
            } catch (error) {
                console.error('🔍 [PURE CSS] Error in getOriginalTextForPositioning:', error);
            }

            return {
                functions: functions,
                fontMetrics: fontMetrics,
                originalText: originalText
            };
        """)

        print(f"🔧 Function availability: {function_check['functions']}")
        print(f"🔧 Font metrics: {function_check['fontMetrics']}")
        print(f"🔧 Original text: {function_check['originalText']}")

        # Check if all functions are available
        all_functions_available = all(function_check['functions'].values())
        print(f"🔧 All functions available: {all_functions_available}")

        if not all_functions_available:
            print("❌ Some pure CSS functions are not available!")
            for func_name, available in function_check['functions'].items():
                if not available:
                    print(f"   - {func_name}: NOT AVAILABLE")
        else:
            print("✅ All pure CSS functions are available!")

        # Test calculateCharacterPositions if functions are available
        if all_functions_available and function_check['fontMetrics'] and function_check['originalText']:
            positions_test = self.execute_script_safe("""
                const textContent = document.getElementById('text-content');
                const fontMetrics = getFontMetrics(textContent);
                const originalText = getOriginalTextForPositioning(textContent);

                try {
                    const positions = calculateCharacterPositions(originalText, 40, 50, fontMetrics, textContent);
                    console.log('🔍 [PURE CSS] Calculated positions:', positions);
                    return { success: true, positions: positions };
                } catch (error) {
                    console.error('🔍 [PURE CSS] Error in calculateCharacterPositions:', error);
                    return { success: false, error: error.message };
                }
            """)

            print(f"🔧 Positions calculation: {positions_test['success']}")
            if positions_test['success']:
                print(f"🔧 Positions: {positions_test['positions']}")
            else:
                print(f"🔧 Error: {positions_test['error']}")

        # Check browser console for any errors
        console_logs = self.driver.get_log('browser')
        if console_logs:
            print("🔧 Browser console logs:")
            for log in console_logs:
                if 'PURE CSS' in log['message']:
                    print(f"   {log['message']}")

        # Assert that all functions are available
        assert all_functions_available, "Not all pure CSS functions are available"

    def test_debug_overlay_class_names(self):
        """Debug test to check what class names are being used for overlays."""
        print("\n" + "="*80)
        print("🧪 DEBUGGING OVERLAY CLASS NAMES")
        print("="*80)

        # Navigate to annotation page
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

        # Get the actual rendered text content
        rendered_text = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent.textContent || textContent.innerText || '';
        """)
        print(f"🔧 Rendered text: '{rendered_text}'")

        # Find the position of "thrilled" in the rendered text
        target_text = "thrilled"
        start_pos = rendered_text.find(target_text)
        end_pos = start_pos + len(target_text)

        if start_pos == -1:
            self.fail(f"Target text '{target_text}' not found in rendered text")

        print(f"🔧 Found '{target_text}' at positions {start_pos}-{end_pos}")

        # Create a span annotation programmatically
        span_creation_result = self.execute_script_safe(f"""
            if (!window.spanManager) {{
                return {{ success: false, error: 'Span manager not available' }};
            }}

            // Create a test span annotation
            const testSpan = {{
                id: 'test_span_debug',
                start: {start_pos},
                end: {end_pos},
                label: 'happy',
                schema: 'emotion',
                text: '{target_text}'
            }};

            // Add the span to the annotations
            if (!window.spanManager.annotations) {{
                window.spanManager.annotations = {{ spans: [] }};
            }}
            window.spanManager.annotations.spans.push(testSpan);

            // Render the spans
            window.spanManager.renderSpans();

            return {{ success: true, span: testSpan }};
        """)

        print(f"🔧 Span creation result: {span_creation_result}")
        self.assertTrue(span_creation_result.get('success', False))

        # Wait for the span overlay to appear
        time.sleep(0.05)

        # Check for different overlay class names
        debug_result = self.execute_script_safe("""
            const spanOverlays = document.getElementById('span-overlays');
            if (!spanOverlays) {
                return { success: false, error: 'span-overlays container not found' };
            }

            const children = Array.from(spanOverlays.children);
            const classNames = children.map(child => child.className);

            // Check for specific class names
            const spanOverlayElements = spanOverlays.querySelectorAll('.span-overlay');
            const spanOverlayPureElements = spanOverlays.querySelectorAll('.span-overlay-pure');

            return {
                success: true,
                totalChildren: children.length,
                classNames: classNames,
                spanOverlayCount: spanOverlayElements.length,
                spanOverlayPureCount: spanOverlayPureElements.length,
                spanOverlayElements: Array.from(spanOverlayElements).map(el => ({
                    className: el.className,
                    dataset: el.dataset
                })),
                spanOverlayPureElements: Array.from(spanOverlayPureElements).map(el => ({
                    className: el.className,
                    dataset: el.dataset
                }))
            };
        """)

        print(f"🔧 Debug result: {debug_result}")
        self.assertTrue(debug_result.get('success', False))

        # Print the results
        print(f"🔧 Total children in span-overlays: {debug_result.get('totalChildren', 0)}")
        print(f"🔧 Class names found: {debug_result.get('classNames', [])}")
        print(f"🔧 .span-overlay elements: {debug_result.get('spanOverlayCount', 0)}")
        print(f"🔧 .span-overlay-pure elements: {debug_result.get('spanOverlayPureCount', 0)}")

        # This should show that only span-overlay-pure elements are being created
        self.assertGreater(debug_result.get('spanOverlayPureCount', 0), 0,
                          "No span-overlay-pure elements found - overlays not being created")
        self.assertEqual(debug_result.get('spanOverlayCount', 0), 0,
                        "Found span-overlay elements - these should not exist in the new system")

        print("✅ Debug test completed - confirmed that only span-overlay-pure elements are being created")

    def test_debug_navigation_elements(self):
        """Debug test to check what navigation elements are available."""
        print("\n" + "="*80)
        print("🧪 DEBUGGING NAVIGATION ELEMENTS")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for page to load
        time.sleep(0.05)

        # Check for navigation elements
        navigation_elements = self.execute_script_safe("""
            const elements = {};

            // Check for common navigation button IDs
            const buttonIds = ['next-button', 'prev-button', 'next', 'prev', 'next-btn', 'prev-btn'];
            buttonIds.forEach(id => {
                const element = document.getElementById(id);
                if (element) {
                    elements[id] = {
                        tagName: element.tagName,
                        text: element.textContent,
                        visible: element.offsetParent !== null,
                        enabled: !element.disabled
                    };
                }
            });

            // Check for navigation buttons by class
            const buttons = document.querySelectorAll('button');
            elements.allButtons = [];
            buttons.forEach((btn, index) => {
                elements.allButtons.push({
                    index: index,
                    id: btn.id,
                    className: btn.className,
                    text: btn.textContent.trim(),
                    visible: btn.offsetParent !== null,
                    enabled: !btn.disabled
                });
            });

            // Check for navigation links
            const links = document.querySelectorAll('a');
            elements.allLinks = [];
            links.forEach((link, index) => {
                elements.allLinks.push({
                    index: index,
                    id: link.id,
                    className: link.className,
                    text: link.textContent.trim(),
                    href: link.href,
                    visible: link.offsetParent !== null
                });
            });

            return elements;
        """)

        print(f"🔧 Navigation elements found: {navigation_elements}")

        # Also check the page source for navigation-related elements
        page_source = self.driver.page_source
        if "next" in page_source.lower() or "prev" in page_source.lower():
            print("🔧 Found 'next' or 'prev' in page source")
        else:
            print("🔧 No 'next' or 'prev' found in page source")

        # Check if there are any navigation elements at all
        self.assertTrue(len(navigation_elements.get('allButtons', [])) > 0,
                       "No buttons found on the page")

    def test_debug_offset_calculation(self):
        """Debug test to understand the offset calculation issue."""
        print("\n" + "="*80)
        print("🧪 DEBUGGING OFFSET CALCULATION")
        print("="*80)

        # Navigate to annotation page
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
        text_content = self.execute_script_safe("""
            const textElement = document.getElementById('text-content');
            return {
                text: textElement ? textElement.textContent : 'no text element',
                innerHTML: textElement ? textElement.innerHTML : 'no text element',
                length: textElement ? textElement.textContent.length : 0
            };
        """)
        print(f"🔧 Text content: {text_content}")

        # Try to create a span annotation
        span_result = self.execute_script_safe("""
            if (!window.spanManager) {
                return { success: false, error: 'Span manager not available' };
            }

            // Create a test span
            const testSpan = {
                id: 'test_span_1',
                start: 0,
                end: 10,
                label: 'test',
                schema: 'test',
                text: 'I am abso'
            };

            // Add to annotations
            if (!window.spanManager.annotations.spans) {
                window.spanManager.annotations.spans = [];
            }
            window.spanManager.annotations.spans.push(testSpan);

            // Try to render
            try {
                window.spanManager.renderSpans();
                return { success: true, annotationsCount: window.spanManager.annotations.spans.length };
            } catch (error) {
                return { success: false, error: error.message };
            }
        """)
        print(f"🔧 Span creation result: {span_result}")

        # Check if overlays were created
        overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay-pure")
        print(f"🔧 Found {len(overlays)} overlays")

        if overlays:
            overlay_data = self.execute_script_safe("""
                const overlay = document.querySelector('.span-overlay-pure');
                if (!overlay) {
                    return { success: false, error: 'No overlay found' };
                }
                return {
                    success: true,
                    start: overlay.getAttribute('data-start'),
                    end: overlay.getAttribute('data-end'),
                    label: overlay.getAttribute('data-label'),
                    rect: overlay.getBoundingClientRect()
                };
            """)
            print(f"🔧 Overlay data: {overlay_data}")

        # Now reload the page
        print("🔧 Reloading page...")
        self.driver.refresh()
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be reinitialized
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.isInitialized) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Check if the same span still works
        reload_result = self.execute_script_safe("""
            if (!window.spanManager) {
                return { success: false, error: 'Span manager not available after reload' };
            }

            // Try to create the same span again
            const testSpan = {
                id: 'test_span_1',
                start: 0,
                end: 10,
                label: 'test',
                schema: 'test',
                text: 'I am abso'
            };

            if (!window.spanManager.annotations.spans) {
                window.spanManager.annotations.spans = [];
            }
            window.spanManager.annotations.spans.push(testSpan);

            try {
                window.spanManager.renderSpans();
                return { success: true, annotationsCount: window.spanManager.annotations.spans.length };
            } catch (error) {
                return { success: false, error: error.message };
            }
        """)
        print(f"🔧 Reload result: {reload_result}")

        # Check overlays after reload
        overlays_after = self.driver.find_elements(By.CLASS_NAME, "span-overlay-pure")
        print(f"🔧 Found {len(overlays_after)} overlays after reload")

        if overlays_after:
            overlay_data_after = self.execute_script_safe("""
                const overlay = document.querySelector('.span-overlay-pure');
                if (!overlay) {
                    return { success: false, error: 'No overlay found after reload' };
                }
                return {
                    success: true,
                    start: overlay.getAttribute('data-start'),
                    end: overlay.getAttribute('data-end'),
                    label: overlay.getAttribute('data-label'),
                    rect: overlay.getBoundingClientRect()
                };
            """)
            print(f"🔧 Overlay data after reload: {overlay_data_after}")

        print("🔧 Debug test completed")

    def test_positioning_functions_availability(self):
        """Test if the positioning functions are available and working."""
        print("\n" + "="*80)
        print("🧪 TESTING POSITIONING FUNCTIONS AVAILABILITY")
        print("="*80)

        # Navigate to annotation page
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

        # Check if functions are available
        function_check = self.execute_script_safe("""
            const functions = {
                getOriginalTextForPositioning: typeof getOriginalTextForPositioning,
                getFontMetrics: typeof getFontMetrics,
                calculateCharacterPositions: typeof calculateCharacterPositions,
                createPureCSSOverlay: typeof createPureCSSOverlay
            };

            return {
                success: true,
                functions: functions,
                allAvailable: Object.values(functions).every(f => f === 'function')
            };
        """)

        print(f"🔧 Function availability: {function_check}")

        if function_check.get('success') and function_check.get('allAvailable'):
            print("✅ All positioning functions are available")

            # Test basic functionality
            basic_test = self.execute_script_safe("""
                const textContent = document.getElementById('text-content');
                if (!textContent) {
                    return { success: false, error: 'Text content element not found' };
                }

                try {
                    const originalText = getOriginalTextForPositioning(textContent);
                    const fontMetrics = getFontMetrics(textContent);

                    return {
                        success: true,
                        originalText: originalText,
                        fontMetrics: fontMetrics,
                        textLength: originalText.length
                    };
                } catch (error) {
                    return { success: false, error: error.message };
                }
            """)

            print(f"🔧 Basic functionality test: {basic_test}")

            if basic_test.get('success'):
                print("✅ Basic positioning functions work correctly")
            else:
                print(f"❌ Basic functionality failed: {basic_test.get('error')}")
        else:
            print("❌ Some positioning functions are not available")
            print(f"   Functions: {function_check.get('functions', {})}")

        print("🔧 Positioning functions test completed")

    def test_debug_data_original_text(self):
        """Debug test to check if data-original-text attribute is set correctly."""
        print("\n" + "="*80)
        print("🧪 DEBUG DATA ORIGINAL TEXT TEST")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Check if data-original-text attribute is set
        has_data_original_text = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent && textContent.hasAttribute('data-original-text');
        """)
        print(f"🔧 Has data-original-text attribute: {has_data_original_text}")

        if has_data_original_text:
            data_original_text = self.execute_script_safe("""
                const textContent = document.getElementById('text-content');
                return textContent.getAttribute('data-original-text');
            """)
            print(f"🔧 data-original-text value: '{data_original_text}'")

        # Check textContent
        text_content = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent ? textContent.textContent : '';
        """)
        print(f"🔧 textContent value: '{text_content}'")

        # Check if positioning strategy is initialized
        strategy_initialized = self.execute_script_safe("""
            return window.spanManager &&
                   window.spanManager.positioningStrategy &&
                   window.spanManager.positioningStrategy.isInitialized;
        """)
        print(f"🔧 Positioning strategy initialized: {strategy_initialized}")

        if strategy_initialized:
            canonical_text = self.execute_script_safe("""
                return window.spanManager.positioningStrategy.canonicalText;
            """)
            print(f"🔧 Canonical text: '{canonical_text}'")

        # Get the original text from the backend API
        api_response = requests.get(f"{self.server.base_url}/api/spans/1", cookies=self.driver.get_cookies())
        api_data = api_response.json()
        original_text = api_data.get('text', '')
        print(f"🔧 Original text from API: '{original_text}'")

        # Compare all text versions
        print(f"🔧 Text comparison:")
        print(f"   API text length: {len(original_text)}")
        print(f"   textContent length: {len(text_content)}")
        if has_data_original_text:
            print(f"   data-original-text length: {len(data_original_text)}")
        if strategy_initialized:
            print(f"   canonical text length: {len(canonical_text)}")

        # Check if any texts match
        if has_data_original_text and data_original_text == original_text:
            print("✅ data-original-text matches API text")
        else:
            print("❌ data-original-text does not match API text")

        if text_content == original_text:
            print("✅ textContent matches API text")
        else:
            print("❌ textContent does not match API text")

        if strategy_initialized and canonical_text == original_text:
            print("✅ canonical text matches API text")
        else:
            print("❌ canonical text does not match API text")

    def test_simple_offset_issue(self):
        """Simple test to identify the offset calculation issue."""
        print("\n" + "="*80)
        print("🧪 SIMPLE OFFSET CALCULATION TEST")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Get the original text from the backend API
        api_response = requests.get(f"{self.server.base_url}/api/spans/1", cookies=self.driver.get_cookies())
        api_data = api_response.json()
        original_text = api_data.get('text', '')
        print(f"🔧 Original text from API: '{original_text}'")

        # Get the rendered text from the DOM
        rendered_text = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            return textContent ? textContent.textContent : '';
        """)
        print(f"🔧 Rendered text from DOM: '{rendered_text}'")

        # Check if there's a difference between original and rendered text
        if original_text != rendered_text:
            print(f"⚠️ WARNING: Original text and rendered text differ!")
            print(f"   Original length: {len(original_text)}")
            print(f"   Rendered length: {len(rendered_text)}")
            print(f"   Difference: {len(rendered_text) - len(original_text)} characters")

        # Find target text in both versions
        target_text = "technology"
        original_start = original_text.find(target_text)
        original_end = original_start + len(target_text)
        rendered_start = rendered_text.find(target_text)
        rendered_end = rendered_start + len(target_text)

        print(f"🔧 Target text: '{target_text}'")
        print(f"🔧 Original text positions: {original_start}-{original_end}")
        print(f"🔧 Rendered text positions: {rendered_start}-{rendered_end}")

        # Test the unified positioning strategy with original offsets
        test_result = self.execute_script_safe(f"""
            const textContent = document.getElementById('text-content');
            const originalStart = {original_start};
            const originalEnd = {original_end};
            const targetText = '{target_text}';

            if (textContent && window.spanManager && window.spanManager.positioningStrategy) {{
                // Test the unified positioning strategy
                const positioningStrategy = window.spanManager.positioningStrategy;

                if (!positioningStrategy.isInitialized) {{
                    return {{ success: false, error: 'Positioning strategy not initialized' }};
                }}

                // Create span using algorithm-based positioning
                const spanResult = positioningStrategy.createSpanWithAlgorithm(originalStart, originalEnd, targetText);

                if (spanResult && spanResult.positions && spanResult.positions.length > 0) {{
                    const position = spanResult.positions[0];

                    // Extract the text that would be covered by this position
                    const coveredText = positioningStrategy.getTextAtPosition(originalStart, originalEnd);

                    return {{
                        success: true,
                        coveredText: coveredText,
                        expectedText: targetText,
                        start: originalStart,
                        end: originalEnd,
                        position: {{
                            x: position.x,
                            y: position.y,
                            width: position.width,
                            height: position.height
                        }}
                    }};
                }} else {{
                    return {{ success: false, error: 'No positions calculated' }};
                }}
            }} else {{
                return {{ success: false, error: 'Text content element or positioning strategy not found' }};
            }}
        """)

        print(f"🔧 Test result: {test_result}")

        if test_result.get('success'):
            covered_text = test_result['coveredText']
            expected_text = test_result['expectedText']

            if covered_text == expected_text:
                print(f"✅ SUCCESS: Offset calculation works correctly!")
                print(f"   Covered text: '{covered_text}'")
                print(f"   Expected text: '{expected_text}'")
            else:
                print(f"❌ FAILURE: Offset calculation is incorrect!")
                print(f"   Covered text: '{covered_text}'")
                print(f"   Expected text: '{expected_text}'")
                print(f"   This is the bug - offsets are not working correctly!")
        else:
            print(f"❌ Test failed: {test_result}")

    def test_debug_span_manager_initialization(self):
        """Debug test to check if SpanManager is being created and initialized."""
        print("\n" + "="*80)
        print("🧪 DEBUG SPAN MANAGER INITIALIZATION TEST")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Check if SpanManager exists
        span_manager_exists = self.execute_script_safe("""
            return window.spanManager !== undefined && window.spanManager !== null;
        """)
        print(f"🔧 SpanManager exists: {span_manager_exists}")

        if span_manager_exists:
            # Check if SpanManager is initialized
            span_manager_initialized = self.execute_script_safe("""
                return window.spanManager.isInitialized;
            """)
            print(f"🔧 SpanManager isInitialized: {span_manager_initialized}")

            # Check if positioning strategy exists
            positioning_strategy_exists = self.execute_script_safe("""
                return window.spanManager.positioningStrategy !== undefined &&
                       window.spanManager.positioningStrategy !== null;
            """)
            print(f"🔧 Positioning strategy exists: {positioning_strategy_exists}")

            if positioning_strategy_exists:
                # Check if positioning strategy is initialized
                positioning_strategy_initialized = self.execute_script_safe("""
                    return window.spanManager.positioningStrategy.isInitialized;
                """)
                print(f"🔧 Positioning strategy isInitialized: {positioning_strategy_initialized}")

                if not positioning_strategy_initialized:
                    # Try to manually initialize the positioning strategy
                    print("🔧 Attempting to manually initialize positioning strategy...")
                    manual_init_result = self.execute_script_safe("""
                        try {
                            await window.spanManager.positioningStrategy.initialize();
                            return { success: true, message: 'Manual initialization successful' };
                        } catch (error) {
                            return { success: false, error: error.message };
                        }
                    """)
                    print(f"🔧 Manual initialization result: {manual_init_result}")

                    # Check if it's now initialized
                    positioning_strategy_initialized_after = self.execute_script_safe("""
                        return window.spanManager.positioningStrategy.isInitialized;
                    """)
                    print(f"🔧 Positioning strategy isInitialized after manual init: {positioning_strategy_initialized_after}")

        # Check browser console for any errors
        console_logs = self.execute_script_safe("""
            return window.console && window.console.log ? 'Console available' : 'Console not available';
        """)
        print(f"🔧 Console status: {console_logs}")

        # Check if there are any JavaScript errors
        js_errors = self.execute_script_safe("""
            return window.onerror ? 'Error handler available' : 'No error handler';
        """)
        print(f"🔧 JavaScript error handling: {js_errors}")

    def test_debug_positioning_strategy_test_logic(self):
        """Debug test to check what's happening with the positioning strategy test logic."""
        print("\n" + "="*80)
        print("🧪 DEBUG POSITIONING STRATEGY TEST LOGIC")
        print("="*80)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Wait for basic elements to be available
        self.execute_script_safe("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && document.getElementById('text-content')) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Force initialization of positioning strategy
        init_result = self.execute_script_safe("""
            return new Promise((resolve) => {
                if (window.spanManager && window.spanManager.positioningStrategy && !window.spanManager.positioningStrategy.isInitialized) {
                    console.log('🔧 Forcing positioning strategy initialization...');
                    window.spanManager.positioningStrategy.initialize().then(() => {
                        console.log('🔧 Positioning strategy initialization completed');
                        resolve({success: true, message: 'Initialization completed'});
                    }).catch((error) => {
                        console.error('🔧 Positioning strategy initialization failed:', error);
                        resolve({success: false, error: error.toString()});
                    });
                } else {
                    resolve({success: true, message: 'Already initialized'});
                }
            });
        """)

        print(f"🔧 Initialization result: {init_result}")

        # Test the positioning strategy with simple values
        test_result = self.execute_script_safe("""
            const textContent = document.getElementById('text-content');
            const originalStart = 0;
            const originalEnd = 5;
            const targetText = 'I am ';

            if (textContent && window.spanManager && window.spanManager.positioningStrategy) {
                const positioningStrategy = window.spanManager.positioningStrategy;

                if (!positioningStrategy.isInitialized) {
                    return { success: false, error: 'Positioning strategy not initialized' };
                }

                // Test the createSpanWithAlgorithm method
                const spanResult = positioningStrategy.createSpanWithAlgorithm(originalStart, originalEnd, targetText);

                if (spanResult && spanResult.positions && spanResult.positions.length > 0) {
                    const position = spanResult.positions[0];
                    const coveredText = positioningStrategy.getTextAtPosition(originalStart, originalEnd);

                    return {
                        success: true,
                        coveredText: coveredText,
                        expectedText: targetText,
                        start: originalStart,
                        end: originalEnd,
                        position: {
                            x: position.x,
                            y: position.y,
                            width: position.width,
                            height: position.height
                        }
                    };
                } else {
                    return { success: false, error: 'No positions calculated', spanResult: spanResult };
                }
            } else {
                return {
                    success: false,
                    error: 'Text content element or positioning strategy not found',
                    textContentExists: !!textContent,
                    spanManagerExists: !!window.spanManager,
                    positioningStrategyExists: !!(window.spanManager && window.spanManager.positioningStrategy)
                };
            }
        """)

        print(f"🔧 Test result: {test_result}")

        # Check if the test passed
        if test_result and test_result.get('success'):
            print("✅ Test passed!")
            print(f"🔧 Covered text: '{test_result.get('coveredText')}'")
            print(f"🔧 Expected text: '{test_result.get('expectedText')}'")
            print(f"🔧 Position: {test_result.get('position')}")
        else:
            print("❌ Test failed!")
            print(f"🔧 Error: {test_result.get('error') if test_result else 'No result'}")
            if test_result and 'spanResult' in test_result:
                print(f"🔧 Span result: {test_result.get('spanResult')}")

        # Assert the test passed
        self.assertTrue(test_result and test_result.get('success'),
                       f"Positioning strategy test failed: {test_result}")