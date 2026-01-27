#!/usr/bin/env python3
"""
Example Selenium test demonstrating secure patterns.

This test shows how to use the test utilities to create secure test configurations
for Selenium tests that comply with path security requirements.
"""

import time
from selenium.webdriver.common.by import By
from tests.selenium.test_base import BaseSeleniumTest
from tests.helpers.test_utils import (
    create_test_directory,
    create_span_annotation_config,
    create_comprehensive_annotation_config,
    TestConfigManager
)


class TestSecureSeleniumPatterns(BaseSeleniumTest):
    """
    Example Selenium test class demonstrating secure test patterns.

    Authentication: Handled automatically by BaseSeleniumTest
    """

    def test_page_loads_correctly(self):
        """Simple test to verify the page loads and basic elements are present."""
        # Navigate to annotation page (user is already authenticated)
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for the instance text to be present
        self.wait_for_element(By.ID, "instance-text")

        # Check that the text content is loaded
        text_content = self.driver.find_element(By.ID, "text-content")
        original_text = text_content.text
        print(f"Page loaded successfully. Text content: '{original_text}'")

        # Verify the text contains expected content
        self.assertIn("thrilled", original_text, "Expected text not found on page")

        # Check that span labels are present
        positive_label = self.wait_for_element(By.ID, "emotion_spans_positive")
        negative_label = self.wait_for_element(By.ID, "emotion_spans_negative")
        neutral_label = self.wait_for_element(By.ID, "emotion_spans_neutral")

        print(f"✅ All span labels found: {positive_label.text}, {negative_label.text}, {neutral_label.text}")

        # Verify labels are clickable
        self.assertTrue(positive_label.is_enabled(), "Positive label should be enabled")
        self.assertTrue(negative_label.is_enabled(), "Negative label should be enabled")
        self.assertTrue(neutral_label.is_enabled(), "Neutral label should be enabled")

    def test_span_annotation_secure_pattern(self):
        """Example of span annotation test using secure patterns."""
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

        # Get the text content
        text_content = self.driver.find_element(By.ID, "text-content")
        original_text = text_content.text
        print(f"Original text: '{original_text}'")

        # Select a specific text span
        target_text = "thrilled"
        start_pos = original_text.find(target_text)
        end_pos = start_pos + len(target_text)

        print(f"Target text: '{target_text}' (positions {start_pos}-{end_pos})")

        # Create a range and select the text
        self.execute_script_safe(f"""
            const textContent = document.getElementById('text-content');
            const range = document.createRange();
            const textNode = textContent.firstChild;
            range.setStart(textNode, {start_pos});
            range.setEnd(textNode, {end_pos});

            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """)

        # Wait a moment for selection to be processed
        time.sleep(0.1)

        # Click on the "positive" label to create the span annotation
        positive_label = self.wait_for_element(By.ID, "emotion_spans_positive")
        positive_label.click()

        # Wait for the span overlay to appear
        time.sleep(0.1)

        # Check that the span overlay exists and contains the correct text
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertGreater(len(span_overlays), 0, "No span overlays found")

        # Get the text content of the overlay
        overlay_text = span_overlays[0].text.strip()
        print(f"Overlay text: '{overlay_text}'")

        # Verify the overlay text matches the selected text
        self.assertEqual(overlay_text, target_text,
                       f"Overlay text '{overlay_text}' does not match selected text '{target_text}'")

        print(f"✅ Overlay text matches selection: '{overlay_text}'")

    def test_span_overlay_persistence_after_navigation(self):
        """Test that span overlays maintain correct positioning after navigation."""
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

        # Get the text content
        text_content = self.driver.find_element(By.ID, "text-content")
        original_text = text_content.text
        print(f"Original text: '{original_text}'")

        # Select a specific text span
        target_text = "thrilled"
        start_pos = original_text.find(target_text)
        end_pos = start_pos + len(target_text)

        print(f"Target text: '{target_text}' (positions {start_pos}-{end_pos})")

        # Create a range and select the text
        self.execute_script_safe(f"""
            const textContent = document.getElementById('text-content');
            const range = document.createRange();
            const textNode = textContent.firstChild;
            range.setStart(textNode, {start_pos});
            range.setEnd(textNode, {end_pos});

            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """)

        # Wait a moment for selection to be processed
        time.sleep(0.1)

        # Click on the "positive" label to create the span annotation
        positive_label = self.wait_for_element(By.ID, "emotion_spans_positive")
        positive_label.click()

        # Wait for the span overlay to appear
        time.sleep(0.1)

        # Get the initial overlay position
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertGreater(len(span_overlays), 0, "No span overlays found")

        initial_overlay = span_overlays[0]
        initial_text = initial_overlay.text.strip()
        initial_rect = initial_overlay.rect

        print(f"Initial overlay text: '{initial_text}'")
        print(f"Initial overlay position: {initial_rect}")

        # Navigate to the next instance
        next_button = self.wait_for_element(By.ID, "next-button")
        next_button.click()

        # Wait for navigation to complete
        time.sleep(0.1)

        # Navigate back to the first instance
        prev_button = self.wait_for_element(By.ID, "prev-button")
        prev_button.click()

        # Wait for navigation to complete
        time.sleep(0.1)

        # Check that the span overlay still exists and has the correct text
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertGreater(len(span_overlays), 0, "No span overlays found after navigation")

        final_overlay = span_overlays[0]
        final_text = final_overlay.text.strip()
        final_rect = final_overlay.rect

        print(f"Final overlay text: '{final_text}'")
        print(f"Final overlay position: {final_rect}")

        # Verify the overlay text is still correct
        self.assertEqual(final_text, target_text,
                       f"Overlay text changed after navigation: '{final_text}' != '{target_text}'")

        # Verify the overlay position is reasonable (should be similar to initial position)
        # Allow some tolerance for minor rendering differences
        position_tolerance = 10  # pixels
        self.assertLess(abs(final_rect['top'] - initial_rect['top']), position_tolerance,
                        f"Overlay top position changed too much: {final_rect['top']} vs {initial_rect['top']}")
        self.assertLess(abs(final_rect['left'] - initial_rect['left']), position_tolerance,
                        f"Overlay left position changed too much: {final_rect['left']} vs {initial_rect['left']}")

        print(f"✅ Overlay text persisted correctly: '{final_text}'")
        print(f"✅ Overlay position maintained after navigation")

    def test_multiple_span_overlays_positioning(self):
        """Test that multiple span overlays are positioned correctly."""
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

        # Get the text content
        text_content = self.driver.find_element(By.ID, "text-content")
        original_text = text_content.text
        print(f"Original text: '{original_text}'")

        # Create multiple span annotations
        span_data = [
            {"text": "thrilled", "label": "emotion_spans_positive"},
            {"text": "technology", "label": "emotion_spans_positive"},
            {"text": "revolutionize", "label": "emotion_spans_positive"}
        ]

        created_overlays = []

        for span_info in span_data:
            target_text = span_info["text"]
            start_pos = original_text.find(target_text)
            end_pos = start_pos + len(target_text)

            print(f"Creating span for: '{target_text}' (positions {start_pos}-{end_pos})")

            # Create a range and select the text
            self.execute_script_safe(f"""
                const textContent = document.getElementById('text-content');
                const range = document.createRange();
                const textNode = textContent.firstChild;
                range.setStart(textNode, {start_pos});
                range.setEnd(textNode, {end_pos});

                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            """)

            # Wait a moment for selection to be processed
            time.sleep(0.1)

            # Click on the label to create the span annotation
            label = self.wait_for_element(By.ID, span_info["label"])
            label.click()

            # Wait for the span overlay to appear
            time.sleep(0.1)

            # Store overlay info
            span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
            if span_overlays:
                latest_overlay = span_overlays[-1]  # Get the most recent overlay
                created_overlays.append({
                    "text": target_text,
                    "overlay_text": latest_overlay.text.strip(),
                    "rect": latest_overlay.rect
                })

        # Verify all overlays were created with correct text
        self.assertEqual(len(created_overlays), len(span_data),
                       f"Expected {len(span_data)} overlays, got {len(created_overlays)}")

        for i, overlay_info in enumerate(created_overlays):
            self.assertEqual(overlay_info["overlay_text"], overlay_info["text"],
                           f"Overlay {i} text mismatch: '{overlay_info['overlay_text']}' != '{overlay_info['text']}'")
            print(f"✅ Overlay {i} text correct: '{overlay_info['overlay_text']}'")

        # Verify overlays are positioned within text content area
        text_rect = text_content.rect
        for i, overlay_info in enumerate(created_overlays):
            rect = overlay_info["rect"]
            self.assertGreaterEqual(rect['top'], text_rect['top'],
                                  f"Overlay {i} positioned above text content")
            self.assertLessEqual(rect['bottom'], text_rect['bottom'],
                                f"Overlay {i} positioned below text content")
            print(f"✅ Overlay {i} positioned correctly within text area")

        print(f"✅ All {len(created_overlays)} overlays positioned correctly")


class TestCustomSeleniumConfig(BaseSeleniumTest):
    """
    Example of creating custom Selenium test configurations securely.

    This demonstrates how to create custom test configurations for Selenium tests
    while maintaining path security requirements.
    """

    @classmethod
    def setUpClass(cls):
        """Set up custom test configuration for this test class."""
        # Create a custom test configuration
        test_dir = create_test_directory("custom_selenium_test")

        # Create custom test data
        test_data = [
            {"id": "custom_1", "text": "This is a custom test item for Selenium testing."},
            {"id": "custom_2", "text": "Another custom test item with different content."}
        ]

        # Create custom annotation schemes
        annotation_schemes = [
            {
                "name": "custom_span",
                "annotation_type": "span",
                "labels": ["highlight", "important"],
                "description": "Mark important text spans",
                "color_scheme": {
                    "highlight": "#ffeb3b",
                    "important": "#ff5722"
                }
            },
            {
                "name": "custom_radio",
                "annotation_type": "radio",
                "labels": ["yes", "no", "maybe"],
                "description": "Choose an option"
            }
        ]

        # Create config using test utilities
        from tests.helpers.test_utils import create_test_data_file, create_test_config

        data_file = create_test_data_file(test_dir, test_data, "custom_data.jsonl")
        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Custom Selenium Test",
            require_password=False,
            debug=False
        )

        # Store for cleanup
        cls.test_dir = test_dir

        # Create and start server with custom config
        from tests.helpers.flask_test_setup import FlaskTestServer
        cls.server = FlaskTestServer(debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"

        # Set up browser options (same as BaseSeleniumTest)
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        chrome_options = ChromeOptions()
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

        cls.chrome_options = chrome_options

    @classmethod
    def tearDownClass(cls):
        """Clean up custom test configuration."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        """Set up for each test: create WebDriver and authenticate user."""
        # Create WebDriver
        from selenium import webdriver
        self.driver = webdriver.Chrome(options=self.chrome_options)

        # Register and login user
        self.register_user()
        self.login_user()

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def register_user(self):
        """Register a test user."""
        self.driver.get(f"{self.server.base_url}/register")

        # Generate unique username
        import time
        username = f"test_user_{int(time.time())}"
        self.test_user = username

        # Fill registration form
        email_field = self.driver.find_element(By.NAME, "email")
        password_field = self.driver.find_element(By.NAME, "pass")

        email_field.send_keys(username)
        password_field.send_keys("test_password")

        # Submit registration
        register_button = self.driver.find_element(By.ID, "register-button")
        register_button.click()

        # Wait for registration to complete
        time.sleep(0.05)

    def login_user(self):
        """Login the test user."""
        self.driver.get(f"{self.server.base_url}/auth")

        # Fill login form
        email_field = self.driver.find_element(By.NAME, "email")
        password_field = self.driver.find_element(By.NAME, "pass")

        email_field.send_keys(self.test_user)
        password_field.send_keys("test_password")

        # Submit login
        login_button = self.driver.find_element(By.ID, "login-button")
        login_button.click()

        # Wait for login to complete
        time.sleep(0.05)

    def test_custom_span_annotation(self):
        """Test custom span annotation functionality."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        wait = WebDriverWait(self.driver, 10)
        wait.until(EC.presence_of_element_located((By.ID, "instance-text")))

        # Wait for span manager to be initialized
        self.driver.execute_script("""
            return new Promise((resolve) => {
                const check = () => {
                    if (window.spanManager && window.spanManager.isInitialized) resolve(true);
                    else setTimeout(check, 100);
                }; check();
            });
        """)

        # Get the text content
        text_content = self.driver.find_element(By.ID, "text-content")
        original_text = text_content.text
        print(f"Custom test text: '{original_text}'")

        # Select a text span
        target_text = "custom test item"
        start_pos = original_text.find(target_text)
        end_pos = start_pos + len(target_text)

        # Create a range and select the text
        self.driver.execute_script(f"""
            const textContent = document.getElementById('text-content');
            const range = document.createRange();
            const textNode = textContent.firstChild;
            range.setStart(textNode, {start_pos});
            range.setEnd(textNode, {end_pos});

            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """)

        # Wait for selection
        time.sleep(0.1)

        # Click on the "highlight" label
        highlight_label = wait.until(EC.element_to_be_clickable((By.ID, "custom_span_highlight")))
        highlight_label.click()

        # Wait for overlay to appear
        time.sleep(0.1)

        # Verify overlay was created
        span_overlays = self.driver.find_elements(By.CLASS_NAME, "span-overlay")
        self.assertGreater(len(span_overlays), 0, "No span overlays found")

        overlay_text = span_overlays[0].text.strip()
        self.assertEqual(overlay_text, target_text,
                       f"Overlay text '{overlay_text}' does not match selected text '{target_text}'")

        print(f"✅ Custom span annotation working: '{overlay_text}'")