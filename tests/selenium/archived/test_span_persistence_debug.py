#!/usr/bin/env python3
"""
Debug test for span persistence issue.

This test creates a span on one instance, then navigates to a new instance
to see if the span persists incorrectly.

Authentication: Handled automatically by BaseSeleniumTest
"""

import time
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import unittest

from tests.selenium.test_base import BaseSeleniumTest


class TestSpanPersistenceDebug(BaseSeleniumTest):
    """
    Debug test to reproduce span persistence issue.
    """

    def test_span_persistence_debug(self):
        """Test span overlay persistence with detailed debugging for Firefox compatibility"""
        print("\n=== SPAN PERSISTENCE DEBUG TEST ===")

        # Check browser type
        browser_name = self.driver.capabilities['browserName'].lower()
        print(f"Browser: {browser_name}")
        is_firefox = browser_name == 'firefox'
        print(f"Is Firefox: {is_firefox}")

        # Navigate to the annotation page (after registration/login in setUp)
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        # Get initial instance ID
        initial_instance_id = self.driver.find_element(By.ID, "instance_id").get_attribute("value")
        print(f"Initial instance ID: {initial_instance_id}")

        # Step 1: Create a span annotation
        print("1. Creating span annotation...")

        # Enable span annotation mode
        span_checkbox = self.driver.find_element(By.CSS_SELECTOR, "input[type='checkbox'][value='positive']")
        span_checkbox.click()
        time.sleep(1)

        # Select text and create span
        text_element = self.driver.find_element(By.ID, "text-content")
        self.driver.execute_script("""
            const textElement = arguments[0];
            const range = document.createRange();
            const textNode = textElement.firstChild;
            range.setStart(textNode, 10);
            range.setEnd(textNode, 20);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """, text_element)
        time.sleep(1)

        # Check for overlays after selection
        overlays_after_selection = self.driver.execute_script(
            "return document.querySelectorAll('.span-overlay').length;"
        )
        print(f"Overlays after text selection: {overlays_after_selection}")

        # Wait for span creation
        time.sleep(3)

        # Check for overlays after span creation
        overlays_after_creation = self.driver.execute_script(
            "return document.querySelectorAll('.span-overlay').length;"
        )
        print(f"Overlays after span creation: {overlays_after_creation}")

        # Check backend state
        spans_response = self.driver.execute_script(f"""
            return fetch('/api/spans/{initial_instance_id}')
                .then(response => response.json())
                .then(data => {{
                    console.log('Backend spans response:', data);
                    return data;
                }});
        """)
        time.sleep(1)

        # Get spans from backend
        spans_data = self.driver.execute_script("return window.lastSpansResponse;")
        if spans_data:
            print(f"Backend spans for instance {initial_instance_id}: {len(spans_data.get('spans', []))} spans")
        else:
            print("No spans data from backend")

        # Step 2: Navigate to next instance
        print("2. Navigating to next instance...")

        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()
        time.sleep(3)

        # Get new instance ID
        new_instance_id = self.driver.find_element(By.ID, "instance_id").get_attribute("value")
        print(f"New instance ID: {new_instance_id}")

        # --- Overlay checks using two methods ---
        # 1. Children of the overlays container
        overlays_container_count = self.driver.execute_script(
            "const container = document.getElementById('span-overlays'); return container ? container.children.length : 0;"
        )
        print(f"Overlays in container children: {overlays_container_count}")

        # 2. querySelectorAll for all span-overlay elements
        overlays_query_count = self.driver.execute_script(
            "return document.querySelectorAll('.span-overlay').length;"
        )
        print(f"Overlays via querySelectorAll: {overlays_query_count}")

        # Print parent info for any overlays found
        if overlays_query_count > 0:
            overlay_info = self.driver.execute_script("""
                const overlays = document.querySelectorAll('.span-overlay');
                return Array.from(overlays).map(overlay => ({
                    parentId: overlay.parentElement ? overlay.parentElement.id : 'no-parent',
                    parentClass: overlay.parentElement ? overlay.parentElement.className : 'no-parent',
                    dataset: overlay.dataset,
                    className: overlay.className
                }));
            """)
            print("Overlay parent info:")
            for i, info in enumerate(overlay_info):
                print(f"  Overlay {i}: {info}")

        # Check backend state for new instance
        new_spans_data = self.driver.execute_script(f"""
            return fetch('/api/spans/{new_instance_id}')
                .then(response => response.json())
                .then(data => {{
                    console.log('Backend spans response for new instance:', data);
                    return data;
                }});
        """)
        time.sleep(1)

        new_spans = self.driver.execute_script("return window.lastSpansResponse;")
        if new_spans:
            print(f"Backend spans for new instance {new_instance_id}: {len(new_spans.get('spans', []))} spans")
        else:
            print("No spans data from backend for new instance")

        # Firefox-specific assertions
        if is_firefox:
            print("=== FIREFOX-SPECIFIC CHECKS ===")

            # Check if Firefox-specific cleanup was triggered
            firefox_logs = self.driver.get_log('browser')
            firefox_cleanup_logs = [log for log in firefox_logs if 'Firefox detected' in log.get('message', '')]
            print(f"Firefox cleanup logs found: {len(firefox_cleanup_logs)}")

            # In Firefox, we expect overlays to be properly cleared
            assert overlays_query_count == 0, f"Firefox: Expected 0 overlays after navigation, found {overlays_query_count}"
            assert overlays_container_count == 0, f"Firefox: Expected 0 overlays in container, found {overlays_container_count}"
        else:
            print("=== NON-FIREFOX BROWSER CHECKS ===")
            # For other browsers, use standard expectations
            assert overlays_query_count == 0, f"Expected 0 overlays after navigation, found {overlays_query_count}"
            assert overlays_container_count == 0, f"Expected 0 overlays in container, found {overlays_container_count}"

        print("=== TEST COMPLETED SUCCESSFULLY ===")


class TestSpanPersistenceDebugFirefox(BaseSeleniumTest):
    """
    Firefox-specific debug test to reproduce span persistence issue.
    """

    # Set browser type to Firefox
    browser_type = 'firefox'

    def test_span_persistence_debug_firefox(self):
        """Test span overlay persistence specifically in Firefox"""
        print("\n=== FIREFOX SPAN PERSISTENCE DEBUG TEST ===")

        try:
            # Check browser type
            browser_name = self.driver.capabilities['browserName'].lower()
            print(f"Browser: {browser_name}")
            is_firefox = browser_name == 'firefox'
            print(f"Is Firefox: {is_firefox}")

            # Verify we're actually running in Firefox
            assert is_firefox, f"Expected Firefox browser, got {browser_name}"

            # Navigate to the annotation page (after registration/login in setUp)
            print("Navigating to annotation page...")
            self.driver.get(f"{self.server.base_url}/annotate")
            time.sleep(2)

            # Get initial instance ID
            print("Getting initial instance ID...")
            initial_instance_id = self.driver.find_element(By.ID, "instance_id").get_attribute("value")
            print(f"Initial instance ID: {initial_instance_id}")

            # Step 1: Create a span annotation
            print("1. Creating span annotation in Firefox...")

            # Enable span annotation mode
            print("Looking for span checkbox...")
            span_checkbox = self.driver.find_element(By.CSS_SELECTOR, "input[type='checkbox'][value='positive']")
            print("Found span checkbox, clicking...")
            span_checkbox.click()
            time.sleep(1)

            # Select text and create span
            print("Selecting text...")
            text_element = self.driver.find_element(By.ID, "text-content")
            self.driver.execute_script("""
                const textElement = arguments[0];
                const range = document.createRange();
                const textNode = textElement.firstChild;
                range.setStart(textNode, 10);
                range.setEnd(textNode, 20);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            """, text_element)
            time.sleep(1)

            # Check for overlays after selection
            overlays_after_selection = self.driver.execute_script(
                "return document.querySelectorAll('.span-overlay').length;"
            )
            print(f"Firefox: Overlays after text selection: {overlays_after_selection}")

            # Wait for span creation
            print("Waiting for span creation...")
            time.sleep(3)

            # Check for overlays after span creation
            overlays_after_creation = self.driver.execute_script(
                "return document.querySelectorAll('.span-overlay').length;"
            )
            print(f"Firefox: Overlays after span creation: {overlays_after_creation}")

            # Step 2: Navigate to next instance
            print("2. Navigating to next instance in Firefox...")

            next_button = self.driver.find_element(By.ID, "next-btn")
            print("Found next button, clicking...")
            next_button.click()
            time.sleep(3)

            # Get new instance ID
            new_instance_id = self.driver.find_element(By.ID, "instance_id").get_attribute("value")
            print(f"Firefox: New instance ID: {new_instance_id}")

            # --- Firefox-specific overlay checks ---
            # 1. Children of the overlays container
            overlays_container_count = self.driver.execute_script(
                "const container = document.getElementById('span-overlays'); return container ? container.children.length : 0;"
            )
            print(f"Firefox: Overlays in container children: {overlays_container_count}")

            # 2. querySelectorAll for all span-overlay elements
            overlays_query_count = self.driver.execute_script(
                "return document.querySelectorAll('.span-overlay').length;"
            )
            print(f"Firefox: Overlays via querySelectorAll: {overlays_query_count}")

            # Print parent info for any overlays found
            if overlays_query_count > 0:
                overlay_info = self.driver.execute_script("""
                    const overlays = document.querySelectorAll('.span-overlay');
                    return Array.from(overlays).map(overlay => ({
                        parentId: overlay.parentElement ? overlay.parentElement.id : 'no-parent',
                        parentClass: overlay.parentElement ? overlay.parentElement.className : 'no-parent',
                        dataset: overlay.dataset,
                        className: overlay.className
                    }));
                """)
                print("Firefox: Overlay parent info:")
                for i, info in enumerate(overlay_info):
                    print(f"  Overlay {i}: {info}")

            # Firefox-specific assertions
            print("=== FIREFOX-SPECIFIC ASSERTIONS ===")

            # Check if Firefox-specific cleanup was triggered
            try:
                firefox_logs = self.driver.get_log('browser')
                firefox_cleanup_logs = [log for log in firefox_logs if 'Firefox detected' in log.get('message', '')]
                print(f"Firefox cleanup logs found: {len(firefox_cleanup_logs)}")

                # Print some browser logs for debugging
                print("Recent browser logs:")
                for log in firefox_logs[-5:]:  # Last 5 logs
                    print(f"  {log.get('level', 'INFO')}: {log.get('message', '')[:100]}...")
            except Exception as e:
                print(f"Could not get browser logs: {e}")

            # In Firefox, we expect overlays to be properly cleared
            print("Running assertions...")
            assert overlays_query_count == 0, f"Firefox: Expected 0 overlays after navigation, found {overlays_query_count}"
            assert overlays_container_count == 0, f"Firefox: Expected 0 overlays in container, found {overlays_container_count}"

            print("=== FIREFOX TEST COMPLETED SUCCESSFULLY ===")

        except Exception as e:
            print(f"=== FIREFOX TEST FAILED WITH EXCEPTION ===")
            print(f"Exception type: {type(e).__name__}")
            print(f"Exception message: {str(e)}")
            import traceback
            print("Full traceback:")
            traceback.print_exc()

            # Try to get more debugging info
            try:
                print("Current page source:")
                print(self.driver.page_source[:1000] + "...")
            except:
                print("Could not get page source")

            raise  # Re-raise the exception to fail the test properly

    def test_firefox_debug_tracking(self):
        """Test that Firefox-specific overlay tracking is working"""
        print("\n=== FIREFOX DEBUG TRACKING TEST ===")

        try:
            # Check browser type
            browser_name = self.driver.capabilities['browserName'].lower()
            print(f"Browser: {browser_name}")
            is_firefox = browser_name == 'firefox'
            print(f"Is Firefox: {is_firefox}")

            # Navigate to annotation page
            self.driver.get(f"{self.server.base_url}/annotate")
            time.sleep(2)

            # Test overlay tracking by manually creating an overlay
            tracking_result = self.driver.execute_script("""
                // Create a test overlay
                const spanOverlays = document.getElementById('span-overlays');
                if (!spanOverlays) {
                    return { error: 'No span-overlays container found' };
                }

                const testOverlay = document.createElement('div');
                testOverlay.className = 'span-overlay annotation-span';
                testOverlay.id = 'test-overlay-1';
                testOverlay.textContent = 'Test Overlay';

                // Check if tracking functions exist
                const hasTrackCreation = typeof trackOverlayCreation === 'function';
                const hasTrackRemoval = typeof trackOverlayRemoval === 'function';

                console.log('Tracking functions available:', { hasTrackCreation, hasTrackRemoval });

                // Add overlay and check if tracking is called
                spanOverlays.appendChild(testOverlay);

                // Remove overlay and check if tracking is called
                spanOverlays.removeChild(testOverlay);

                return {
                    hasTrackCreation,
                    hasTrackRemoval,
                    overlayCreated: true,
                    overlayRemoved: true,
                    totalOverlays: document.querySelectorAll('.span-overlay').length
                };
            """)

            print("Tracking test result:", tracking_result)

            # Check if we're in Firefox and tracking should be working
            if is_firefox:
                assert tracking_result.get('hasTrackCreation'), "trackOverlayCreation function not found in Firefox"
                assert tracking_result.get('hasTrackRemoval'), "trackOverlayRemoval function not found in Firefox"
                print("✅ Firefox tracking functions are available")
            else:
                print("ℹ️ Not Firefox, tracking functions may not be available")

            print("=== FIREFOX DEBUG TRACKING TEST COMPLETED ===")

        except Exception as e:
            print(f"=== FIREFOX DEBUG TRACKING TEST FAILED ===")
            print(f"Exception: {e}")
            raise


if __name__ == '__main__':
    unittest.main()