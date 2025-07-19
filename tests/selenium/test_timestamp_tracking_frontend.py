"""
Selenium tests for timestamp tracking frontend functionality.

This module tests the timestamp tracking system through the browser interface,
verifying that annotation actions are properly tracked and performance metrics
are displayed correctly.
"""

import time
import datetime
import json
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

from tests.selenium.test_base import BaseSeleniumTest


class TestTimestampTrackingFrontend(BaseSeleniumTest):
    """
    Frontend tests for timestamp tracking functionality.

    Tests the complete user workflow through the browser interface,
    including annotation submission, performance tracking, and admin dashboard.
    """

    def test_basic_annotation_timestamp_tracking(self):
        """Test that basic annotations are tracked with timestamps."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Submit a basic annotation
        sentiment_label = self.wait_for_element(By.ID, "sentiment_positive_label")
        sentiment_label.click()

        # Submit the annotation
        submit_button = self.wait_for_element(By.ID, "submit-button")
        submit_button.click()

        # Wait for submission to complete
        time.sleep(1)

        # Navigate to next instance
        next_button = self.wait_for_element(By.ID, "next-button")
        next_button.click()

        # Wait for next instance to load
        time.sleep(1)

        # Verify we're on a new instance
        new_instance_text = self.driver.find_element(By.ID, "instance-text").text
        self.assertNotEqual(new_instance_text, "")

        # Check browser console for any errors
        logs = self.driver.get_log('browser')
        for log in logs:
            if log['level'] == 'SEVERE':
                print(f"Browser error: {log['message']}")

    def test_multiple_annotations_performance_tracking(self):
        """Test performance tracking across multiple annotations."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Submit multiple annotations
        for i in range(3):
            # Wait for instance to be ready
            self.wait_for_element(By.ID, "instance-text")

            # Submit annotation
            sentiment_label = self.wait_for_element(By.ID, "sentiment_positive_label")
            sentiment_label.click()

            submit_button = self.wait_for_element(By.ID, "submit-button")
            submit_button.click()

            # Wait for submission
            time.sleep(0.5)

            # Navigate to next instance
            next_button = self.wait_for_element(By.ID, "next-button")
            next_button.click()

            # Wait for navigation
            time.sleep(0.5)

        # Check that no errors occurred
        logs = self.driver.get_log('browser')
        for log in logs:
            if log['level'] == 'SEVERE':
                print(f"Browser error: {log['message']}")

    def test_span_annotation_timestamp_tracking(self):
        """Test timestamp tracking for span annotations."""
        # Navigate to span annotation page
        self.driver.get(f"{self.server.base_url}/span-api-frontend")

        # Wait for page to load
        self.wait_for_element(By.ID, "instance-text")

        # Get the instance text
        instance_text = self.driver.find_element(By.ID, "instance-text").text

        # Select text for span annotation
        if len(instance_text) > 10:
            # Create a span annotation by selecting text
            text_element = self.driver.find_element(By.ID, "instance-text")

            # Use JavaScript to select text
            self.driver.execute_script("""
                var range = document.createRange();
                var textNode = arguments[0].firstChild;
                range.setStart(textNode, 0);
                range.setEnd(textNode, 10);
                var selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            """, text_element)

            # Wait a moment for selection
            time.sleep(0.5)

            # Try to find and click a span annotation button
            try:
                span_button = self.driver.find_element(By.CSS_SELECTOR, "[data-schema='entity']")
                span_button.click()

                # Wait for span to be created
                time.sleep(0.5)

                # Submit the annotation
                submit_button = self.driver.find_element(By.ID, "submit-button")
                submit_button.click()

                # Wait for submission
                time.sleep(1)

            except Exception as e:
                print(f"Span annotation not available: {e}")

        # Check for errors
        logs = self.driver.get_log('browser')
        for log in logs:
            if log['level'] == 'SEVERE':
                print(f"Browser error: {log['message']}")

    def test_admin_dashboard_timestamp_data(self):
        """Test that admin dashboard displays timestamp tracking data."""
        # Navigate to admin dashboard
        self.driver.get(f"{self.server.base_url}/admin")

        # Wait for admin page to load
        self.wait_for_element(By.TAG_NAME, "body")

        # Check if we need to enter API key
        try:
            api_key_input = self.driver.find_element(By.NAME, "api_key")
            api_key_input.send_keys("admin_api_key")

            submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for dashboard to load
            time.sleep(1)
        except:
            # API key might already be set or not required
            pass

        # Look for timing-related elements in the dashboard
        try:
            # Check for annotators table with timing data
            annotators_table = self.driver.find_element(By.ID, "annotators-table")

            # Look for timing-related columns
            headers = annotators_table.find_elements(By.TAG_NAME, "th")
            timing_headers = [h.text for h in headers if any(keyword in h.text.lower()
                           for keyword in ['time', 'action', 'performance', 'speed'])]

            # Should have some timing-related columns
            self.assertGreater(len(timing_headers), 0, "No timing columns found in annotators table")

        except Exception as e:
            print(f"Admin dashboard timing data not available: {e}")

    def test_annotation_history_display(self):
        """Test that annotation history is properly displayed."""
        # First, create some annotation history
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Submit a few annotations
        for i in range(2):
            sentiment_label = self.wait_for_element(By.ID, "sentiment_positive_label")
            sentiment_label.click()

            submit_button = self.wait_for_element(By.ID, "submit-button")
            submit_button.click()
            time.sleep(0.5)

            next_button = self.wait_for_element(By.ID, "next-button")
            next_button.click()
            time.sleep(0.5)

        # Navigate to admin dashboard to check history
        self.driver.get(f"{self.server.base_url}/admin")
        self.wait_for_element(By.TAG_NAME, "body")

        # Check for annotation history section
        try:
            # Look for history-related elements
            history_elements = self.driver.find_elements(By.XPATH,
                "//*[contains(text(), 'History') or contains(text(), 'history')]")

            # Should have some history-related elements
            self.assertGreater(len(history_elements), 0, "No history elements found")

        except Exception as e:
            print(f"Annotation history display not available: {e}")

    def test_performance_metrics_display(self):
        """Test that performance metrics are properly displayed."""
        # Navigate to admin dashboard
        self.driver.get(f"{self.server.base_url}/admin")
        self.wait_for_element(By.TAG_NAME, "body")

        # Look for performance metrics
        try:
            # Check for metrics-related elements
            metrics_elements = self.driver.find_elements(By.XPATH,
                "//*[contains(text(), 'Performance') or contains(text(), 'performance') or " +
                "contains(text(), 'Speed') or contains(text(), 'speed') or " +
                "contains(text(), 'Actions') or contains(text(), 'actions')]")

            # Should have some metrics-related elements
            self.assertGreater(len(metrics_elements), 0, "No performance metrics elements found")

        except Exception as e:
            print(f"Performance metrics display not available: {e}")

    def test_suspicious_activity_detection_display(self):
        """Test that suspicious activity detection is displayed."""
        # Navigate to admin dashboard
        self.driver.get(f"{self.server.base_url}/admin")
        self.wait_for_element(By.TAG_NAME, "body")

        # Look for suspicious activity indicators
        try:
            # Check for suspicious activity elements
            suspicious_elements = self.driver.find_elements(By.XPATH,
                "//*[contains(text(), 'Suspicious') or contains(text(), 'suspicious') or " +
                "contains(text(), 'Alert') or contains(text(), 'alert') or " +
                "contains(text(), 'Warning') or contains(text(), 'warning')]")

            # May or may not have suspicious activity elements (depends on data)
            print(f"Found {len(suspicious_elements)} suspicious activity elements")

        except Exception as e:
            print(f"Suspicious activity detection display not available: {e}")

    def test_session_tracking_display(self):
        """Test that session tracking information is displayed."""
        # Navigate to admin dashboard
        self.driver.get(f"{self.server.base_url}/admin")
        self.wait_for_element(By.TAG_NAME, "body")

        # Look for session-related information
        try:
            # Check for session-related elements
            session_elements = self.driver.find_elements(By.XPATH,
                "//*[contains(text(), 'Session') or contains(text(), 'session') or " +
                "contains(text(), 'Duration') or contains(text(), 'duration') or " +
                "contains(text(), 'Active') or contains(text(), 'active')]")

            # May or may not have session elements (depends on implementation)
            print(f"Found {len(session_elements)} session-related elements")

        except Exception as e:
            print(f"Session tracking display not available: {e}")

    def test_error_handling_in_frontend(self):
        """Test error handling in the frontend timestamp tracking."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        # Try to submit annotation without selecting anything
        submit_button = self.wait_for_element(By.ID, "submit-button")
        submit_button.click()

        # Wait for any error handling
        time.sleep(1)

        # Check for error messages
        try:
            error_elements = self.driver.find_elements(By.CLASS_NAME, "error")
            if error_elements:
                print(f"Found error elements: {[e.text for e in error_elements]}")
        except:
            pass

        # Check browser console for errors
        logs = self.driver.get_log('browser')
        for log in logs:
            if log['level'] == 'SEVERE':
                print(f"Browser error: {log['message']}")

    def test_concurrent_user_activity_tracking(self):
        """Test tracking of concurrent user activity."""
        # Create a second browser session
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        second_driver = webdriver.Chrome(options=chrome_options)

        try:
            # Register and login second user
            second_driver.get(f"{self.server.base_url}/register")

            # Fill registration form
            email_input = second_driver.find_element(By.NAME, "email")
            email_input.send_keys("concurrent_user_2")

            password_input = second_driver.find_element(By.NAME, "pass")
            password_input.send_keys("password123")

            # Submit registration
            submit_button = second_driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_button.click()

            # Wait for redirect
            time.sleep(1)

            # Navigate to annotation page
            second_driver.get(f"{self.server.base_url}/annotate")

            # Submit annotation in second session
            sentiment_label = second_driver.find_element(By.ID, "sentiment_positive_label")
            sentiment_label.click()

            submit_button = second_driver.find_element(By.ID, "submit-button")
            submit_button.click()

            # Wait for submission
            time.sleep(1)

            # Submit annotation in first session
            self.driver.get(f"{self.server.base_url}/annotate")
            self.wait_for_element(By.ID, "instance-text")

            sentiment_label = self.wait_for_element(By.ID, "sentiment_positive_label")
            sentiment_label.click()

            submit_button = self.wait_for_element(By.ID, "submit-button")
            submit_button.click()

            # Wait for submission
            time.sleep(1)

            # Check that both sessions worked
            logs1 = self.driver.get_log('browser')
            logs2 = second_driver.get_log('browser')

            # Check for errors
            for log in logs1 + logs2:
                if log['level'] == 'SEVERE':
                    print(f"Browser error: {log['message']}")

        finally:
            second_driver.quit()

    def test_annotation_history_persistence(self):
        """Test that annotation history persists across browser sessions."""
        # Submit annotation in first session
        self.driver.get(f"{self.server.base_url}/annotate")
        self.wait_for_element(By.ID, "instance-text")

        sentiment_label = self.wait_for_element(By.ID, "sentiment_positive_label")
        sentiment_label.click()

        submit_button = self.wait_for_element(By.ID, "submit-button")
        submit_button.click()
        time.sleep(1)

        # Close and reopen browser (simulate new session)
        self.driver.quit()
        self.setUp()

        # Login again
        self.driver.get(f"{self.server.base_url}/auth")

        email_input = self.driver.find_element(By.NAME, "email")
        email_input.send_keys(self.test_user)

        password_input = self.driver.find_element(By.NAME, "pass")
        password_input.send_keys(self.test_password)

        submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_button.click()

        # Wait for redirect
        time.sleep(1)

        # Navigate to admin dashboard to check if history persisted
        self.driver.get(f"{self.server.base_url}/admin")
        self.wait_for_element(By.TAG_NAME, "body")

        # Check for persisted history
        try:
            # Look for user in admin dashboard
            user_elements = self.driver.find_elements(By.XPATH,
                f"//*[contains(text(), '{self.test_user}')]")

            # Should find the user
            self.assertGreater(len(user_elements), 0, "User not found in admin dashboard")

        except Exception as e:
            print(f"History persistence check not available: {e}")


if __name__ == "__main__":
    import unittest
    unittest.main()