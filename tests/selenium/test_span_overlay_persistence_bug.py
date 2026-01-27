#!/usr/bin/env python3
"""
Selenium test to reproduce and verify the span overlay persistence bug.

This test verifies that span overlays are properly cleared when navigating
between instances, and don't persist from one instance to the next.

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


class TestSpanOverlayPersistenceBug(BaseSeleniumTest):
    """
    Test suite for span overlay persistence bug.

    This class tests that span overlays are properly cleared during navigation
    and don't persist from one instance to the next.

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_span_overlay_persistence_during_navigation(self):
        """Test that span overlays are cleared when navigating between instances"""
        print("=== Testing Span Overlay Persistence Bug ===")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Wait for span manager to be ready
        time.sleep(0.1)
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        self.assertTrue(span_manager_ready, "Span manager should be initialized")

        # Get session cookies for API requests
        session_cookies = self.get_session_cookies()

        # Step 1: Create a span on the first instance
        print("1. Creating span on first instance...")

        # Create span via API for first instance
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
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200, "Failed to create span on first instance")

        # Force span manager to reload annotations
        self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.loadAnnotations('1');
            }
            return Promise.resolve();
        """)
        time.sleep(0.05)

        # Verify span overlay is present on first instance
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"   Found {len(span_overlays)} span overlays on first instance")
        self.assertEqual(len(span_overlays), 1, "Should have 1 span overlay on first instance")

        # Get the text content of the first instance for later comparison
        first_instance_text = self.driver.find_element(By.ID, "instance-text").text
        print(f"   First instance text: {first_instance_text[:50]}...")

        # Step 2: Navigate to next instance
        print("2. Navigating to next instance...")

        # Find and click the next button
        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()
        time.sleep(0.1)  # Wait for navigation to complete

        # Verify we're on a different instance
        second_instance_text = self.driver.find_element(By.ID, "instance-text").text
        print(f"   Second instance text: {second_instance_text[:50]}...")
        self.assertNotEqual(first_instance_text, second_instance_text,
                           "Navigation failed - same text displayed")

        # Step 3: Check that span overlays are cleared on second instance
        print("3. Checking that span overlays are cleared on second instance...")

        # Wait for any potential async operations to complete
        time.sleep(0.05)

        # Check for span overlays on second instance
        span_overlays_second = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"   Found {len(span_overlays_second)} span overlays on second instance")

        # This is the bug: overlays from first instance are persisting
        if len(span_overlays_second) > 0:
            print("   ❌ BUG DETECTED: Span overlays are persisting from first instance!")
            print("   Expected: 0 overlays, Found:", len(span_overlays_second))

            # Debug: Print details of persisting overlays
            for i, overlay in enumerate(span_overlays_second):
                start = overlay.get_attribute("data-start")
                end = overlay.get_attribute("data-end")
                label = overlay.get_attribute("data-label")
                print(f"   Overlay {i}: start={start}, end={end}, label={label}")

            # This should fail the test
            self.assertEqual(len(span_overlays_second), 0,
                           "Span overlays should be cleared when navigating to new instance")
        else:
            print("   ✅ No span overlays found on second instance (correct behavior)")

        # Step 4: Navigate back to first instance and verify overlays are restored
        print("4. Navigating back to first instance...")

        prev_button = self.driver.find_element(By.ID, "prev-btn")
        prev_button.click()
        time.sleep(0.1)

        # Verify we're back to the first instance
        restored_text = self.driver.find_element(By.ID, "instance-text").text
        self.assertEqual(restored_text, first_instance_text,
                        "Navigation back failed - different text displayed")

        # Verify span overlays are restored on first instance
        span_overlays_restored = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"   Found {len(span_overlays_restored)} span overlays after navigation back")
        self.assertEqual(len(span_overlays_restored), 1,
                        "Span overlays should be restored when navigating back to first instance")

        print("✅ Span overlay persistence test completed")

    def test_span_overlay_clear_on_instance_load(self):
        """Test that span overlays are cleared when loading a new instance"""
        print("=== Testing Span Overlay Clear on Instance Load ===")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(0.1)

        # Get session cookies
        session_cookies = self.get_session_cookies()

        # Create span on first instance
        span_request = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'emotion_spans',
            'state': [
                {
                    'name': 'negative',
                    'title': 'Negative sentiment',
                    'start': 5,
                    'end': 20,
                    'value': 'absolutely thrilled'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_request,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Load annotations
        self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.loadAnnotations('1');
            }
            return Promise.resolve();
        """)
        time.sleep(0.05)

        # Verify span is present
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(span_overlays), 1, "Should have 1 span overlay")

        # Test direct navigation to instance 2
        print("Testing direct navigation to instance 2...")
        self.driver.get(f"{self.server.base_url}/annotate?instance_id=2")
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(0.1)

        # Check that overlays are cleared
        span_overlays_after_nav = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"Found {len(span_overlays_after_nav)} span overlays after direct navigation")

        if len(span_overlays_after_nav) > 0:
            print("❌ BUG DETECTED: Span overlays persisting after direct navigation!")
            self.assertEqual(len(span_overlays_after_nav), 0,
                           "Span overlays should be cleared after direct navigation")
        else:
            print("✅ Span overlays properly cleared after direct navigation")

        print("✅ Span overlay clear test completed")

    def test_multiple_instances_with_spans(self):
        """Test navigation between multiple instances with different spans"""
        print("=== Testing Multiple Instances with Spans ===")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(0.1)

        session_cookies = self.get_session_cookies()

        # Create span on instance 1
        span_request_1 = {
            'instance_id': '1',
            'type': 'span',
            'schema': 'emotion_spans',
            'state': [
                {
                    'name': 'positive',
                    'title': 'Positive sentiment',
                    'start': 0,
                    'end': 10,
                    'value': 'I am'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_request_1,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Load annotations for instance 1
        self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.loadAnnotations('1');
            }
            return Promise.resolve();
        """)
        time.sleep(0.05)

        # Verify span on instance 1
        span_overlays_1 = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(span_overlays_1), 1, "Should have 1 span on instance 1")

        # Navigate to instance 2
        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()
        time.sleep(0.1)

        # Verify no spans on instance 2
        span_overlays_2 = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        if len(span_overlays_2) > 0:
            print("❌ BUG: Instance 2 has spans when it shouldn't!")
            self.assertEqual(len(span_overlays_2), 0, "Instance 2 should have no spans")
        else:
            print("✅ Instance 2 correctly has no spans")

        # Create different span on instance 2
        span_request_2 = {
            'instance_id': '2',
            'type': 'span',
            'schema': 'emotion_spans',
            'state': [
                {
                    'name': 'negative',
                    'title': 'Negative sentiment',
                    'start': 5,
                    'end': 15,
                    'value': 'different'
                }
            ]
        }

        response = requests.post(
            f"{self.server.base_url}/updateinstance",
            json=span_request_2,
            cookies=session_cookies
        )
        self.assertEqual(response.status_code, 200)

        # Load annotations for instance 2
        self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.loadAnnotations('2');
            }
            return Promise.resolve();
        """)
        time.sleep(0.05)

        # Verify span on instance 2
        span_overlays_2_after = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(span_overlays_2_after), 1, "Should have 1 span on instance 2")

        # Navigate back to instance 1
        prev_button = self.driver.find_element(By.ID, "prev-btn")
        prev_button.click()
        time.sleep(0.1)

        # Verify correct span on instance 1 (should be positive, not negative)
        span_overlays_1_after = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertEqual(len(span_overlays_1_after), 1, "Should have 1 span on instance 1")

        # Check the label of the span
        if span_overlays_1_after:
            label = span_overlays_1_after[0].get_attribute("data-label")
            if label != "positive":
                print(f"❌ BUG: Instance 1 span has wrong label: {label} (expected: positive)")
                self.assertEqual(label, "positive", "Instance 1 should have positive span")
            else:
                print("✅ Instance 1 correctly has positive span")

        print("✅ Multiple instances test completed")


if __name__ == '__main__':
    unittest.main()