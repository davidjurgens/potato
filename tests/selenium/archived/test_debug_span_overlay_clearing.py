#!/usr/bin/env python3
"""
Debug test for span overlay clearing to help identify persistence issues.

This test creates spans and navigates between instances while logging
debug information to help identify where overlay persistence occurs.

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


class TestDebugSpanOverlayClearing(BaseSeleniumTest):
    """
    Debug test to help identify span overlay persistence issues.
    """

    def test_debug_overlay_clearing(self):
        """Test overlay clearing with detailed debug logging"""
        print("=== Debug Test: Span Overlay Clearing ===")

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")
        time.sleep(3)

        # Verify span manager is initialized
        span_manager_ready = self.execute_script_safe("""
            return window.spanManager && window.spanManager.isInitialized;
        """)
        self.assertTrue(span_manager_ready, "Span manager should be initialized")

        session_cookies = self.get_session_cookies()

        # Step 1: Create a span on instance 1
        print("1. Creating span on instance 1...")

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
        self.assertEqual(response.status_code, 200, "Failed to create span on instance 1")

        # Load annotations for instance 1
        self.execute_script_safe("""
            if (window.spanManager) {
                return window.spanManager.loadAnnotations('1');
            }
            return Promise.resolve();
        """)
        time.sleep(2)

        # Check overlays on instance 1
        span_overlays_1 = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"   Instance 1 has {len(span_overlays_1)} span overlays")
        self.assertEqual(len(span_overlays_1), 1, "Should have 1 span on instance 1")

        # Step 2: Navigate to instance 2 (should have no overlays)
        print("2. Navigating to instance 2...")

        next_button = self.driver.find_element(By.ID, "next-btn")
        next_button.click()
        time.sleep(3)

        # Check overlays on instance 2
        span_overlays_2 = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"   Instance 2 has {len(span_overlays_2)} span overlays")

        if len(span_overlays_2) > 0:
            print("   ❌ BUG DETECTED: Instance 2 has overlays when it shouldn't!")
            for i, overlay in enumerate(span_overlays_2):
                print(f"   Overlay {i}:", {
                    'className': overlay.get_attribute('class'),
                    'dataset': {
                        'annotationId': overlay.get_attribute('data-annotation-id'),
                        'start': overlay.get_attribute('data-start'),
                        'end': overlay.get_attribute('data-end'),
                        'label': overlay.get_attribute('data-label')
                    }
                })
        else:
            print("   ✅ Instance 2 correctly has no overlays")

        # Step 3: Navigate back to instance 1 (should have overlays restored)
        print("3. Navigating back to instance 1...")

        prev_button = self.driver.find_element(By.ID, "prev-btn")
        prev_button.click()
        time.sleep(3)

        # Check overlays on instance 1 again
        span_overlays_1_after = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        print(f"   Instance 1 after navigation back has {len(span_overlays_1_after)} span overlays")
        self.assertEqual(len(span_overlays_1_after), 1, "Should have 1 span on instance 1 after navigation back")

        print("✅ Debug test completed")


if __name__ == '__main__':
    unittest.main()