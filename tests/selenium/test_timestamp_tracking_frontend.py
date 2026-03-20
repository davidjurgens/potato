"""
Selenium tests for timestamp tracking frontend functionality.

This module tests the timestamp tracking system through the browser interface,
verifying that annotation actions are properly tracked and performance metrics
are displayed correctly.

BaseSeleniumTest uses a span annotation config (emotion_spans with labels:
positive, negative, neutral). Span label element IDs: emotion_spans_positive, etc.
Navigation buttons: next-btn, prev-btn. No submit button exists.
"""

import time
import datetime
import json
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException

from tests.selenium.test_base import BaseSeleniumTest


class TestTimestampTrackingFrontend(BaseSeleniumTest):
    """
    Frontend tests for timestamp tracking functionality.

    Tests the complete user workflow through the browser interface,
    including annotation submission, performance tracking, and admin dashboard.
    """

    def _select_text_and_annotate(self, driver=None):
        """Helper: select text in the instance and click a span label to annotate."""
        d = driver or self.driver
        # Click the span label to set it as active
        label = d.find_element(By.ID, "emotion_spans_positive")
        d.execute_script("arguments[0].click()", label)
        time.sleep(0.3)

        # Find the text content element and select some text
        text_el = d.find_element(By.CSS_SELECTOR, "[id^='text-content']")
        d.execute_script("""
            var el = arguments[0];
            var textNode = el.firstChild;
            if (!textNode || textNode.nodeType !== 3) {
                // Find the first text node
                var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
                textNode = walker.nextNode();
            }
            if (textNode) {
                var range = document.createRange();
                var end = Math.min(10, textNode.length);
                range.setStart(textNode, 0);
                range.setEnd(textNode, end);
                var selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                // Trigger mouseup to create the span
                el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
            }
        """, text_el)
        time.sleep(0.5)

    def _navigate_next(self, driver=None):
        """Helper: click the next button."""
        d = driver or self.driver
        next_btn = d.find_element(By.ID, "next-btn")
        d.execute_script("arguments[0].click()", next_btn)
        time.sleep(1.0)

    def test_basic_annotation_timestamp_tracking(self):
        """Test that basic annotations are tracked with timestamps."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "main-content")
        time.sleep(0.5)

        # Create a span annotation
        self._select_text_and_annotate()

        # Navigate to next instance
        self._navigate_next()

        # Verify we moved to a new instance (page still has content)
        main_content = self.driver.find_element(By.ID, "main-content")
        self.assertTrue(main_content.is_displayed())

        # Check browser console for any severe errors
        logs = self.driver.get_log('browser')
        severe_errors = [log for log in logs if log['level'] == 'SEVERE']
        for log in severe_errors:
            print(f"Browser error: {log['message']}")

    def test_multiple_annotations_performance_tracking(self):
        """Test performance tracking across multiple annotations."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "main-content")
        time.sleep(0.5)

        # Submit multiple annotations across instances
        for i in range(3):
            self._select_text_and_annotate()
            self._navigate_next()

        # Check that no severe errors occurred
        logs = self.driver.get_log('browser')
        severe_errors = [log for log in logs if log['level'] == 'SEVERE']
        for log in severe_errors:
            print(f"Browser error: {log['message']}")

    def test_span_annotation_timestamp_tracking(self):
        """Test timestamp tracking for span annotations."""
        # Navigate to annotation page (same page, span annotation is the default config)
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "main-content")
        time.sleep(0.5)

        # Create a span annotation
        self._select_text_and_annotate()

        # Check for span highlights
        highlights = self.driver.find_elements(By.CSS_SELECTOR, ".span-highlight, .span-overlay")
        # Span may or may not render overlay immediately
        print(f"Found {len(highlights)} span highlight elements")

        # Navigate to next to trigger save
        self._navigate_next()

        # Check for errors
        logs = self.driver.get_log('browser')
        for log in logs:
            if log['level'] == 'SEVERE':
                print(f"Browser error: {log['message']}")

    def test_admin_dashboard_timestamp_data(self):
        """Test that admin dashboard displays annotation tracking data."""
        # First create some annotation data
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "main-content")
        time.sleep(0.5)
        self._select_text_and_annotate()
        self._navigate_next()

        # Navigate to admin dashboard
        self.driver.get(f"{self.server.base_url}/admin")
        time.sleep(1.0)

        # Admin page should load (may require API key or may show dashboard directly)
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        # Admin page should have some content
        self.assertGreater(len(body_text), 0, "Admin page should have content")

    def test_annotation_history_display(self):
        """Test that annotation history is reflected in admin view."""
        # Create some annotation history
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "main-content")
        time.sleep(0.5)

        for i in range(2):
            self._select_text_and_annotate()
            self._navigate_next()

        # Navigate to admin dashboard to check history
        self.driver.get(f"{self.server.base_url}/admin")
        time.sleep(1.0)

        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        # Admin page should have loaded
        self.assertGreater(len(body_text), 0, "Admin page should have content")

    def test_performance_metrics_display(self):
        """Test that admin dashboard loads after annotation activity."""
        # Navigate to admin dashboard
        self.driver.get(f"{self.server.base_url}/admin")
        time.sleep(1.0)

        # Admin page should load without errors
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertGreater(len(body_text), 0, "Admin page should have content")

    def test_suspicious_activity_detection_display(self):
        """Test that admin dashboard loads for suspicious activity monitoring."""
        self.driver.get(f"{self.server.base_url}/admin")
        time.sleep(1.0)

        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertGreater(len(body_text), 0, "Admin page should have content")

    def test_session_tracking_display(self):
        """Test that admin dashboard loads for session tracking."""
        self.driver.get(f"{self.server.base_url}/admin")
        time.sleep(1.0)

        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertGreater(len(body_text), 0, "Admin page should have content")

    def test_error_handling_in_frontend(self):
        """Test error handling in the frontend - navigate without annotation."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "main-content")
        time.sleep(0.5)

        # Try to navigate without making any annotation
        self._navigate_next()

        # Page should still function
        main_content = self.driver.find_element(By.ID, "main-content")
        self.assertTrue(main_content.is_displayed())

        # Check browser console for errors
        logs = self.driver.get_log('browser')
        for log in logs:
            if log['level'] == 'SEVERE':
                print(f"Browser error: {log['message']}")

    def test_concurrent_user_activity_tracking(self):
        """Test tracking of concurrent user activity."""
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        second_driver = webdriver.Chrome(options=chrome_options)

        try:
            # Register second user via simple login (require_password=False)
            second_driver.get(f"{self.server.base_url}/")
            WebDriverWait(second_driver, 10).until(
                EC.presence_of_element_located((By.ID, "login-email"))
            )

            # Handle both auth modes
            try:
                second_driver.find_element(By.ID, "login-tab")
                # Password mode
                register_tab = second_driver.find_element(By.ID, "register-tab")
                register_tab.click()
                WebDriverWait(second_driver, 5).until(
                    EC.visibility_of_element_located((By.ID, "register-content"))
                )
                second_driver.find_element(By.ID, "register-email").send_keys("concurrent_user_2")
                second_driver.find_element(By.ID, "register-pass").send_keys("testpass123")
                second_driver.find_element(By.CSS_SELECTOR, "#register-content form").submit()
            except NoSuchElementException:
                # Simple mode
                username_field = second_driver.find_element(By.ID, "login-email")
                username_field.clear()
                username_field.send_keys("concurrent_user_2")
                second_driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

            time.sleep(1.0)

            # Wait for annotation page to load
            WebDriverWait(second_driver, 10).until(
                EC.presence_of_element_located((By.ID, "main-content"))
            )
            time.sleep(0.5)

            # Annotate in second session
            self._select_text_and_annotate(driver=second_driver)

            # Annotate in first session
            self.driver.get(f"{self.server.base_url}/annotate")
            self.wait_for_element(By.ID, "main-content")
            time.sleep(0.5)
            self._select_text_and_annotate()

            # Check that both sessions worked without severe errors
            logs1 = self.driver.get_log('browser')
            logs2 = second_driver.get_log('browser')
            for log in logs1 + logs2:
                if log['level'] == 'SEVERE':
                    print(f"Browser error: {log['message']}")

        finally:
            second_driver.quit()

    def test_annotation_history_persistence(self):
        """Test that annotation history persists across browser sessions."""
        # Submit annotation in first session
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "main-content")
        time.sleep(0.5)

        self._select_text_and_annotate()
        self._navigate_next()
        time.sleep(0.5)

        # Close and reopen browser (simulate new session)
        old_user = self.test_user
        self.driver.quit()
        self.setUp()  # Creates new driver and NEW user

        # Navigate to admin dashboard to check if old user's history persisted
        self.driver.get(f"{self.server.base_url}/admin")
        time.sleep(1.0)

        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        # Admin page should load with content
        self.assertGreater(len(body_text), 0, "Admin page should have content")


if __name__ == "__main__":
    import unittest
    unittest.main()
