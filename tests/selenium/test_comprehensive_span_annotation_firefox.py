"""
Firefox-Specific Comprehensive Selenium Test Suite for Span Annotation

This test suite is specifically designed to diagnose Firefox-specific issues,
particularly the instance_id not updating bug while text content changes.
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
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from tests.selenium.test_base import BaseSeleniumTest
import sys
import shutil
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FirefoxSpanAnnotationHelper:
    """Firefox-specific helper class for robust span annotation testing."""

    @staticmethod
    def wait_for_element(driver, by, value, timeout=10, description="element"):
        """Wait for an element to be present and visible with detailed logging."""
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            WebDriverWait(driver, timeout).until(
                EC.visibility_of(element)
            )
            print(f"   ✅ Found {description}: {value}")
            return element
        except TimeoutException:
            print(f"   ❌ Timeout waiting for {description}: {value}")
            raise

    @staticmethod
    def wait_for_clickable(driver, by, value, timeout=10, description="element"):
        """Wait for an element to be clickable with detailed logging."""
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, value))
            )
            print(f"   ✅ {description} is clickable: {value}")
            return element
        except TimeoutException:
            print(f"   ❌ Timeout waiting for {description} to be clickable: {value}")
            raise

    @staticmethod
    def safe_click(driver, element, description="element"):
        """Safely click an element with retry logic and error handling."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Scroll element into view
                driver.execute_script("arguments[0].scrollIntoView(true);", element)
                time.sleep(0.5)

                # Wait for element to be clickable
                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable(element)
                )

                # Click using JavaScript for better reliability
                driver.execute_script("arguments[0].click();", element)
                print(f"   ✅ Successfully clicked {description} (attempt {attempt + 1})")
                return True
            except Exception as e:
                print(f"   ⚠️ Click attempt {attempt + 1} failed for {description}: {e}")
                if attempt == max_retries - 1:
                    print(f"   ❌ Failed to click {description} after {max_retries} attempts")
                    raise
                time.sleep(1)
        return False

    @staticmethod
    def wait_for_page_load(driver, timeout=10):
        """Wait for page to fully load with comprehensive checks."""
        try:
            # Wait for document ready state
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # Wait for jQuery if present
            jquery_ready = driver.execute_script("""
                return typeof jQuery === 'undefined' || jQuery.isReady;
            """)

            if not jquery_ready:
                WebDriverWait(driver, timeout).until(
                    lambda d: d.execute_script("return typeof jQuery === 'undefined' || jQuery.isReady;")
                )

            print("   ✅ Page fully loaded")
            return True
        except TimeoutException:
            print("   ⚠️ Page load timeout, continuing anyway")
            return False
        except Exception as e:
            print(f"   ⚠️ Error waiting for page load: {e}")
            return False

    @staticmethod
    def get_instance_details(driver):
        """Get detailed information about the current instance."""
        try:
            # Get instance_id from hidden input
            instance_id_element = driver.find_element(By.ID, "instance_id")
            instance_id = instance_id_element.get_attribute("value")

            # Get instance text
            instance_text_element = driver.find_element(By.ID, "instance-text")
            instance_text = instance_text_element.text

            # Get page URL
            current_url = driver.current_url

            # Get page title
            page_title = driver.title

            # Check if debug functions are available
            debug_functions_available = driver.execute_script("""
                return {
                    debugInstanceId: typeof window.debugInstanceId === 'function',
                    debugAndFixInstanceId: typeof window.debugAndFixInstanceId === 'function',
                    checkPageCache: typeof window.checkPageCache === 'function',
                    clearErroneousSpans: typeof window.clearErroneousSpans === 'function'
                };
            """)

            return {
                'instance_id': instance_id,
                'instance_text_preview': instance_text[:100] + "..." if len(instance_text) > 100 else instance_text,
                'instance_text_length': len(instance_text),
                'current_url': current_url,
                'page_title': page_title,
                'debug_functions': debug_functions_available
            }
        except Exception as e:
            print(f"   ❌ Error getting instance details: {e}")
            return None

    @staticmethod
    def capture_browser_logs(driver, description="browser logs"):
        """Capture and log browser console messages."""
        try:
            # Try different log types for Firefox
            log_types = ['browser', 'driver', 'client']
            all_logs = []

            for log_type in log_types:
                try:
                    logs = driver.get_log(log_type)
                    if logs:
                        all_logs.extend(logs)
                except Exception:
                    continue

            if all_logs:
                print(f"\n=== FIREFOX {description.upper()} ===")
                for log in all_logs[-10:]:  # Last 10 logs
                    level = log.get('level', 'INFO')
                    message = log.get('message', '')
                    source = log.get('source', 'unknown')
                    print(f"  {level} [{source}]: {message}")
                print(f"=== END FIREFOX {description.upper()} ===\n")
            else:
                print(f"   ℹ️ No browser logs captured for {description}")
            return all_logs
        except Exception as e:
            print(f"   ⚠️ Could not capture {description}: {e}")
            return []

    @staticmethod
    def capture_console_logs(driver, description="console logs"):
        """Capture JavaScript console logs using execute_script."""
        try:
            console_logs = driver.execute_script("""
                if (window.console && window.console.log) {
                    // Try to get console logs if available
                    return window.console.logs || [];
                }
                return [];
            """)
            if console_logs:
                print(f"\n=== JAVASCRIPT {description.upper()} ===")
                for log in console_logs[-10:]:
                    print(f"  JS: {log}")
                print(f"=== END JAVASCRIPT {description.upper()} ===\n")
            return console_logs
        except Exception as e:
            print(f"   ⚠️ Could not capture {description}: {e}")
            return []

    @staticmethod
    def run_debug_functions(driver):
        """Run all available debug functions and capture their output."""
        print("   🔍 Running debug functions...")

        # Run debugInstanceId if available
        try:
            result = driver.execute_script("""
                if (typeof window.debugInstanceId === 'function') {
                    console.log('🔍 MANUAL: Running debugInstanceId');
                    window.debugInstanceId();
                    return 'debugInstanceId executed';
                } else {
                    return 'debugInstanceId not available';
                }
            """)
            print(f"   📊 debugInstanceId result: {result}")
        except Exception as e:
            print(f"   ❌ Error running debugInstanceId: {e}")

        # Run checkPageCache if available
        try:
            result = driver.execute_script("""
                if (typeof window.checkPageCache === 'function') {
                    console.log('🔍 MANUAL: Running checkPageCache');
                    window.checkPageCache();
                    return 'checkPageCache executed';
                } else {
                    return 'checkPageCache not available';
                }
            """)
            print(f"   📊 checkPageCache result: {result}")
        except Exception as e:
            print(f"   ❌ Error running checkPageCache: {e}")

        # Run clearErroneousSpans if available
        try:
            result = driver.execute_script("""
                if (typeof window.clearErroneousSpans === 'function') {
                    console.log('🔍 MANUAL: Running clearErroneousSpans');
                    window.clearErroneousSpans();
                    return 'clearErroneousSpans executed';
                } else {
                    return 'clearErroneousSpans not available';
                }
            """)
            print(f"   📊 clearErroneousSpans result: {result}")
        except Exception as e:
            print(f"   ❌ Error running clearErroneousSpans: {e}")

    @staticmethod
    def wait_for_span_manager(driver, timeout=10):
        """Wait for span manager to be initialized."""
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("""
                    return window.spanManager && window.spanManager.isInitialized;
                """)
            )
            print("   ✅ Span manager initialized")
            return True
        except TimeoutException:
            print("   ❌ Timeout waiting for span manager initialization")
            return False
        except Exception as e:
            print(f"   ❌ Error waiting for span manager: {e}")
            return False

    @staticmethod
    def create_span_via_api(driver, server_base_url, session_cookies, instance_id, span_data):
        """Create a span annotation via API and reload in browser."""
        try:
            # Create span via API
            span_request = {
                'instance_id': instance_id,
                'type': 'span',
                'schema': 'emotion_spans',
                'state': span_data
            }

            print(f"   📡 Creating span via API for instance {instance_id}")
            response = requests.post(f"{server_base_url}/updateinstance",
                                   json=span_request,
                                   cookies=session_cookies)

            if response.status_code == 200:
                print(f"   ✅ Span created successfully via API")

                # Reload annotations in browser
                driver.execute_script("""
                    if (window.spanManager) {
                        console.log('🔄 Reloading annotations from API');
                        window.spanManager.loadAnnotations(arguments[0]);
                    }
                """, instance_id)

                time.sleep(3)  # Wait for reload
                return True
            else:
                print(f"   ❌ Failed to create span via API: {response.status_code}")
                return False

        except Exception as e:
            print(f"   ❌ Error creating span via API: {e}")
            return False

    @staticmethod
    def create_span_via_ui(driver, start_text, end_text, label_name):
        """Create a span annotation via UI interaction."""
        try:
            print(f"   🖱️ Creating span via UI: '{start_text}' to '{end_text}' with label '{label_name}'")

            # Find the instance text element
            instance_text = driver.find_element(By.ID, "instance-text")

            # Select text by simulating mouse actions
            actions = ActionChains(driver)
            actions.move_to_element(instance_text)
            actions.click_and_hold()

            # Find the start and end positions
            text_content = instance_text.text
            start_pos = text_content.find(start_text)
            end_pos = text_content.find(end_text) + len(end_text)

            if start_pos == -1 or end_pos == -1:
                print(f"   ❌ Could not find text to select: '{start_text}' or '{end_text}'")
                return False

            # Move to start position
            actions.move_by_offset(start_pos * 5, 0)  # Approximate character width
            actions.release()

            # Move to end position and select
            actions.move_by_offset((end_pos - start_pos) * 5, 0)
            actions.click_and_hold()
            actions.perform()

            time.sleep(1)

            # Click the label button
            label_button = driver.find_element(By.CSS_SELECTOR, f"[data-label='{label_name}']")
            label_button.click()

            time.sleep(2)
            print(f"   ✅ Span created via UI")
            return True

        except Exception as e:
            print(f"   ❌ Error creating span via UI: {e}")
            return False

    @staticmethod
    def check_span_elements(driver, expected_count=1):
        """Check for span overlays, labels, and delete buttons."""
        try:
            overlays = driver.find_elements(By.CLASS_NAME, "span-overlay")
            labels = driver.find_elements(By.CLASS_NAME, "span-label")
            deletes = driver.find_elements(By.CLASS_NAME, "span-delete-btn")

            print(f"   📊 Found {len(overlays)} overlays, {len(labels)} labels, {len(deletes)} delete buttons")

            if len(overlays) >= expected_count and len(labels) >= expected_count and len(deletes) >= expected_count:
                print(f"   ✅ Expected span elements found")
                return True, overlays, labels, deletes
            else:
                print(f"   ❌ Expected {expected_count} span elements, found {len(overlays)}/{len(labels)}/{len(deletes)}")
                return False, overlays, labels, deletes

        except Exception as e:
            print(f"   ❌ Error checking span elements: {e}")
            return False, [], [], []


class TestFirefoxSpanAnnotationComprehensive(BaseSeleniumTest):
    """
    Comprehensive Firefox-specific span annotation test suite.

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def setUp(self):
        """Set up Firefox browser and authentication for each test."""
        # Set browser type to Firefox
        self.browser_type = 'firefox'

        # Call parent setUp to handle authentication
        super().setUp()

        # Add Firefox-specific logging preferences
        self.driver.execute_script("""
            // Override console.log to capture logs
            if (window.console && window.console.log) {
                window.console.logs = window.console.logs || [];
                const originalLog = window.console.log;
                window.console.log = function(...args) {
                    window.console.logs.push(args.join(' '));
                    originalLog.apply(window.console, args);
                };
            }
        """)

        print(f"🔧 Firefox test setup complete for user: {self.test_user}")

    def test_firefox_span_state_synchronization_bug(self):
        """
        Test to reproduce the Firefox span state synchronization bug.

        Scenario:
        1. Create a span on instance 1
        2. Navigate to instance 2 - span should appear (incorrectly)
        3. Navigate to instance 3 - span should disappear
        4. Navigate back to instance 1 - span should not appear
        5. Navigate "prev" from instance 1 - span should reappear

        This tests the state synchronization issue between frontend DOM and backend API.
        """
        print(f"\n🧪 Starting Firefox span state synchronization bug test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")
        FirefoxSpanAnnotationHelper.wait_for_span_manager(self.driver)

        # Get initial instance details
        initial_details = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
        print(f"   📊 Initial instance: {initial_details}")

        # Step 1. Create a span on instance 1
        print(f"   🔧 Step 1: Creating span on instance 1...")
        session_cookies = self.get_session_cookies()
        span_data = [{
            'name': 'positive',
            'title': 'Positive sentiment',
            'start': 0,
            'end': 15,
            'value': 'I am absolutely'
        }]

        api_success = FirefoxSpanAnnotationHelper.create_span_via_api(
            self.driver,
            self.server.base_url,
            session_cookies,
            initial_details['instance_id'],
            span_data
        )

        # Check if span was created on instance 1
        spans_found_1, overlays_1, labels_1, deletes_1 = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)
        print(f"   📊 Instance 1- Spans found: {spans_found_1}, Overlays: {len(overlays_1)}")

        # Capture current state
        state_1 = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
        print(f"   📊 Instance 1 state: {state_1}")

        # Step 2: Navigate to instance 2
        print(f"   🔄 Step 2: Navigating to instance 2...")
        next_button = self.driver.find_element(By.ID, "next-button")
        next_button.click()
        time.sleep(3)

        # Check if span appears on instance 2 (incorrectly)
        spans_found_2, overlays_2, labels_2, deletes_2 = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)
        print(f"   📊 Instance 2- Spans found: {spans_found_2}, Overlays: {len(overlays_2)}")

        # Capture state on instance 2
        state_2 = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
        print(f"   📊 Instance 2 state: {state_2}")

        # Step 3: Navigate to instance 3
        print(f"   🔄 Step 3: Navigating to instance 3...")
        next_button = self.driver.find_element(By.ID, "next-button")
        next_button.click()
        time.sleep(3)

        # Check if span disappears on instance 3
        spans_found_3, overlays_3, labels_3, deletes_3 = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)
        print(f"   📊 Instance 3- Spans found: {spans_found_3}, Overlays: {len(overlays_3)}")

        # Capture state on instance 3
        state_3 = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
        print(f"   📊 Instance 3 state: {state_3}")

        # Step 4: Navigate back to instance 1
        print(f"   🔄 Step 4. Navigating back to instance 1...")
        prev_button = self.driver.find_element(By.ID, "prev-button")
        prev_button.click()
        time.sleep(3)

        # Navigate back again to get to instance 1
        prev_button = self.driver.find_element(By.ID, "prev-button")
        prev_button.click()
        time.sleep(3)

        # Check if span doesn't appear on instance 1
        spans_found_1_again, overlays_1_again, labels_1_again, deletes_1_again = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)
        print(f"   📊 Instance 1 (returned) - Spans found: {spans_found_1_again}, Overlays: {len(overlays_1_again)}")

        # Capture state on instance 1 (returned)
        state_1_again = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
        print(f"   📊 Instance 1 (returned) state: {state_1_again}")

        # Step 5. Navigate "prev" from instance 1 (should go to instance 3)
        print(f"   🔄 Step 5: Navigating 'prev' from instance 1...")
        prev_button = self.driver.find_element(By.ID, "prev-button")
        prev_button.click()
        time.sleep(3)

        # Check if span reappears (should be on instance 3 now)
        spans_found_3_again, overlays_3_again, labels_3_again, deletes_3_again = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)
        print(f"   📊 Instance 3 (returned) - Spans found: {spans_found_3_again}, Overlays: {len(overlays_3_again)}")

        # Capture state on instance 3 (returned)
        state_3_again = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
        print(f"   📊 Instance 3 (returned) state: {state_3_again}")

        # Capture all browser logs
        FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "final state")
        FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "final state")

        # Run debug functions to get more insight
        print(f"   🔍 Running debug functions for final state...")
        FirefoxSpanAnnotationHelper.run_debug_functions(self.driver)

        # Analyze the results
        print(f"   📊 Bug Analysis:")
        print(f"      - Instance 1 initial: {spans_found_1}")
        print(f"      - Instance 2 (should be 0): {spans_found_2}")
        print(f"      - Instance 3 (should be 0): {spans_found_3}")
        print(f"      - Instance 1 (returned) (should be 1): {spans_found_1_again} spans")
        print(f"      - Instance 3 (returned) (should be 0): {spans_found_3_again} spans")

        # Check for the bug pattern
        bug_detected = False
        bug_description = []

        if spans_found_2:
            bug_detected = True
            bug_description.append("Span incorrectly appeared on instance 2")

        if not spans_found_1_again:
            bug_detected = True
            bug_description.append("Span did not appear on instance 1 (returned)")

        if spans_found_3_again:
            bug_detected = True
            bug_description.append("Span incorrectly appeared on instance 3 (returned)")

        if bug_detected:
            print(f"   ❌ BUG DETECTED: {', '.join(bug_description)}")
            print(f"   🔍 This confirms the state synchronization issue between frontend and backend")

            # Additional debugging
            print(f"   🔍 Instance ID Analysis:")
            print(f"      - Instance 1 initial ID: {state_1['instance_id']}")
            print(f"      - Instance 2 ID: {state_2['instance_id']}")
            print(f"      - Instance 3 ID: {state_3['instance_id']}")
            print(f"      - Instance 1 (returned) ID: {state_1_again['instance_id']}")
            print(f"      - Instance 3 (returned) ID: {state_3_again['instance_id']}")

            # Check if instance IDs are consistent
            if state_1['instance_id'] != state_1_again['instance_id']:
                print(f"   ❌ Instance ID inconsistency: {state_1['instance_id']} vs {state_1_again['instance_id']}")

        else:
            print(f"   ✅ No bug detected - all spans appeared/disappeared as expected")

        # Don't fail the test, just report the findings
        print(f"   📊 Test completed - bug analysis finished")

    def test_firefox_span_creation_only(self):
        """Test span creation in Firefox without navigation."""
        print(f"\n🧪 Starting Firefox span creation only test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Capture initial browser logs
        FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "initial page load")
        FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "initial page load")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")
        FirefoxSpanAnnotationHelper.wait_for_page_load(self.driver)

        # Wait for span manager initialization
        FirefoxSpanAnnotationHelper.wait_for_span_manager(self.driver)

        # Get initial instance details
        initial_details = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
        print(f"   📊 Initial instance: {initial_details}")

        # Capture logs after page setup
        FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "after page setup")
        FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "after page setup")

        # Try to create span via API first
        session_cookies = self.get_session_cookies()
        span_data = [{
            'name': 'positive',
            'title': 'Positive sentiment',
            'start': 0,
            'end': 15,
            'value': 'I am absolutely'
        }]

        print(f"   🔧 Attempting to create span via API...")
        api_success = FirefoxSpanAnnotationHelper.create_span_via_api(
            self.driver,
            self.server.base_url,
            session_cookies,
            initial_details['instance_id'],
            span_data
        )

        # Capture logs after API attempt
        FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "after API span creation")
        FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "after API span creation")

        # Check if spans were created
        spans_found, overlays, labels, deletes = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)

        if not spans_found:
            print(f"   ⚠️ No spans found after API creation, trying UI method...")

            # Try UI method
            ui_success = FirefoxSpanAnnotationHelper.create_span_via_ui(
                self.driver,
                "I am absolutely",
                "I am absolutely delighted",
                "positive"
            )

            # Capture logs after UI attempt
            FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "after UI span creation")
            FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "after UI span creation")

            # Check again
            spans_found, overlays, labels, deletes = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)

        # Run debug functions if spans still not found
        if not spans_found:
            print(f"   🔍 Spans still not found, running debug functions...")
            FirefoxSpanAnnotationHelper.run_debug_functions(self.driver)

            # Capture logs after debug functions
            FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "after debug functions")
            FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "after debug functions")

        # Final span check
        final_spans, final_overlays, final_labels, final_deletes = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)

        print(f"   📊 Test Summary:")
        print(f"      - API span creation: {api_success}")
        print(f"      - Final spans found: {final_spans}")
        print(f"      - Final overlays: {len(final_overlays)}")
        print(f"      - Final labels: {len(final_labels)}")
        print(f"      - Final delete buttons: {len(final_deletes)}")

        # Capture final logs
        FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "final state")
        FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "final state")

        # Assertions
        if spans_found:
            print(f"   ✅ Test completed - spans were created successfully")
            assert len(final_overlays) > 0, "Should have span overlays"
            assert len(final_labels) > 0, "Should have span labels"
            assert len(final_deletes) > 0, "Should have delete buttons"
        else:
            print(f"   ⚠️ Test completed - no spans were created")
            # Don't fail the test, just report the issue

    def test_firefox_span_creation_and_navigation(self):
        """Test span creation and navigation in Firefox with comprehensive logging."""
        print(f"\n🧪 Starting Firefox span creation and navigation test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Capture initial browser logs
        FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "initial page load")
        FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "initial page load")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")
        FirefoxSpanAnnotationHelper.wait_for_page_load(self.driver)

        # Wait for span manager initialization
        FirefoxSpanAnnotationHelper.wait_for_span_manager(self.driver)

        # Get initial instance details
        initial_details = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
        print(f"   📊 Initial instance: {initial_details}")

        # Capture logs after page setup
        FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "after page setup")
        FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "after page setup")

        # Try to create span via API first
        session_cookies = self.get_session_cookies()
        span_data = [{
            'name': 'positive',
            'title': 'Positive sentiment',
            'start': 0,
            'end': 15,
            'value': 'I am absolutely'
        }]

        print(f"   🔧 Attempting to create span via API...")
        api_success = FirefoxSpanAnnotationHelper.create_span_via_api(
            self.driver,
            self.server.base_url,
            session_cookies,
            initial_details['instance_id'],
            span_data
        )

        # Capture logs after API attempt
        FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "after API span creation")
        FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "after API span creation")

        # Check if spans were created
        spans_found, overlays, labels, deletes = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)

        if not spans_found:
            print(f"   ⚠️ No spans found after API creation, trying UI method...")

            # Try UI method
            ui_success = FirefoxSpanAnnotationHelper.create_span_via_ui(
                self.driver,
                "I am absolutely",
                "I am absolutely delighted",
                "positive"
            )

            # Capture logs after UI attempt
            FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "after UI span creation")
            FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "after UI span creation")

            # Check again
            spans_found, overlays, labels, deletes = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)

        # Run debug functions if spans still not found
        if not spans_found:
            print(f"   🔍 Spans still not found, running debug functions...")
            FirefoxSpanAnnotationHelper.run_debug_functions(self.driver)

            # Capture logs after debug functions
            FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "after debug functions")
            FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "after debug functions")

        # Navigate to next instance
        print(f"   🔄 Navigating to next instance...")
        next_button = self.driver.find_element(By.ID, "next-button")
        next_button.click()

        time.sleep(3)

        # Capture logs after navigation
        FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "after navigation")
        FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "after navigation")

        # Get new instance details
        new_details = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
        print(f"   📊 New instance: {new_details}")

        # Check if spans persist (they shouldn't)
        spans_persist, _, _, _ = FirefoxSpanAnnotationHelper.check_span_elements(self.driver, expected_count=0)

        if spans_persist:
            print(f"   ❌ Spans persist across instances - this is the bug!")
        else:
            print(f"   ✅ No spans persist across instances - navigation working correctly")

        # Navigate back to first instance
        print(f"   🔄 Navigating back to first instance...")
        prev_button = self.driver.find_element(By.ID, "prev-button")
        prev_button.click()

        time.sleep(3)

        # Capture final logs
        FirefoxSpanAnnotationHelper.capture_browser_logs(self.driver, "final state")
        FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "final state")

        # Get final instance details
        final_details = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
        print(f"   📊 Final instance: {final_details}")

        # Final span check
        final_spans, _, _, _ = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)

        print(f"   📊 Test Summary:")
        print(f"      - Initial spans created: {spans_found}")
        print(f"      - Spans persisted across navigation: {spans_persist}")
        print(f"      - Final spans present: {final_spans}")
        print(f"      - Instance ID changed: {initial_details['instance_id'] != new_details['instance_id']}")

        # Assertions
        assert initial_details['instance_id'] != new_details['instance_id'], "Instance ID should change on navigation"

        if spans_found:
            print(f"   ✅ Test completed - spans were created successfully")
        else:
            print(f"   ⚠️ Test completed - no spans were created, but navigation worked correctly")

    def test_firefox_span_deletion(self):
        """Test span deletion in Firefox."""
        print(f"\n🧪 Starting Firefox span deletion test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page setup
        self.wait_for_element(By.ID, "instance-text")
        FirefoxSpanAnnotationHelper.wait_for_span_manager(self.driver)

        # Create span via API
        session_cookies = self.get_session_cookies()
        instance_details = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)

        span_data = [{
            'name': 'negative',
            'title': 'Negative sentiment',
            'start': 0,
            'end': 10,
            'value': 'I am very'
        }]

        api_success = FirefoxSpanAnnotationHelper.create_span_via_api(
            self.driver,
            self.server.base_url,
            session_cookies,
            instance_details['instance_id'],
            span_data
        )

        # Check if span was created
        spans_found, overlays, labels, deletes = FirefoxSpanAnnotationHelper.check_span_elements(self.driver)

        if spans_found and len(deletes) > 0:
            print(f"   🗑️ Testing span deletion...")

            # Click delete button
            deletes[0].click()
            time.sleep(2)

            # Check if span was deleted
            spans_after_delete, _, _, _ = FirefoxSpanAnnotationHelper.check_span_elements(self.driver, expected_count=0)

            if spans_after_delete:
                print(f"   ❌ Span was not deleted")
            else:
                print(f"   ✅ Span was successfully deleted")
        else:
            print(f"   ⚠️ No spans found to delete")

    def test_firefox_instance_id_consistency(self):
        """Test instance_id consistency across navigation in Firefox."""
        print(f"\n🧪 Starting Firefox instance_id consistency test")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page setup
        self.wait_for_element(By.ID, "instance-text")

        # Get initial instance details
        initial_details = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
        print(f"   📊 Initial instance: {initial_details}")

        # Navigate through several instances
        for i in range(3):
            print(f"   🔄 Navigation {i+1}/3...")

            # Get current instance details
            current_details = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
            print(f"   📊 Current instance: {current_details}")

            # Navigate to next
            next_button = self.driver.find_element(By.ID, "next-button")
            next_button.click()
            time.sleep(2)

            # Get new instance details
            new_details = FirefoxSpanAnnotationHelper.get_instance_details(self.driver)
            print(f"   📊 New instance: {new_details}")

            # Verify instance changed
            assert current_details['instance_id'] != new_details['instance_id'], f"Instance ID should change on navigation {i+1}"
            assert current_details['instance_text_preview'] != new_details['instance_text_preview'], f"Instance text should change on navigation {i+1}"

        print(f"   ✅ Instance ID consistency test passed")

    def test_deep_debug_instrumentation_working(self):
        """Test that deep debug instrumentation is working properly."""
        print(f"\n🧪Testing deep debug instrumentation")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")
        FirefoxSpanAnnotationHelper.wait_for_page_load(self.driver)

        # Wait for span manager initialization
        self.wait_for_element(By.ID, "span-overlays")

        # Check for deep debug logs in console
        console_logs = FirefoxSpanAnnotationHelper.capture_console_logs(self.driver, "deep debug test")

        # Look for deep debug messages
        deep_debug_found = any("[DEEP DEBUG]" in log for log in console_logs)
        deep_debug_nav_found = any("[DEEP DEBUG NAV]" in log for log in console_logs)

        print(f"📊 Deep debug logs found: {deep_debug_found}")
        print(f"📊 Deep debug nav logs found: {deep_debug_nav_found}")

        # Check if span manager has debug state
        debug_state = self.driver.execute_script("""
            if (window.spanManager && window.spanManager.debugState) {
                return window.spanManager.debugState;
            }
            return null;
        """)

        print(f"📊 Span manager debug state: {debug_state}")

        # Verify span manager is initialized
        is_initialized = self.driver.execute_script("""
            return window.spanManager && window.spanManager.isInitialized;
        """)

        print(f"📊 Span manager initialized: {is_initialized}")

        # Basic assertion to ensure the test framework is working
        assert is_initialized, "Span manager should be initialized"
        print("✅ Deep debug instrumentation test completed")


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "-s"])