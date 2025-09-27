"""
Selenium tests for robust span annotation refactoring.

This module tests the new boundary-based span annotation system that replaces
the complex overlay approach with a simpler, more robust rendering method.
"""

import pytest
import time
import json
import os
import tempfile
import yaml
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.helpers.flask_test_setup import create_chrome_options, FlaskTestServer
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class TestRobustSpanAnnotationSelenium:
    """Test suite for robust span annotation system using Selenium."""

    def create_test_config(self, test_data):
        """Create a test configuration for robust span annotation testing."""
        config = {
            "debug": False,
            "max_annotations_per_user": 5,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Robust Span Annotation Test",
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": ["test_data.json"],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "annotation_type": "span",
                    "name": "emotion",
                    "description": "Highlight which phrases express different emotions in the text",
                    "labels": ["happy", "sad", "angry", "surprised", "neutral"],
                    "sequential_key_binding": True
                },
                {
                    "annotation_type": "radio",
                    "name": "overall_sentiment",
                    "description": "What is the overall sentiment of this text?",
                    "labels": ["positive", "neutral", "negative"]
                }
            ],
            "ui": {
                "spans": {
                    "span_colors": {
                        "emotion": {
                            "happy": "(255, 230, 230)",
                            "sad": "(230, 243, 255)",
                            "angry": "(255, 230, 204)",
                            "surprised": "(230, 255, 230)",
                            "neutral": "(240, 240, 240)"
                        }
                    }
                }
            },
            "site_file": "base_template_v2.html",
            "output_annotation_dir": "output",
            "task_dir": "task",
            "base_html_template": "default",
            "header_file": "default",
            "html_layout": "default",
            "site_dir": "templates",
            "alert_time_each_instance": 10000000
        }

        # Create temporary directory for test
        test_dir = tempfile.mkdtemp()

        # Create test data file in the test directory
        data_file = os.path.join(test_dir, "test_data.json")
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create output and task directories
        os.makedirs(os.path.join(test_dir, "output"), exist_ok=True)
        os.makedirs(os.path.join(test_dir, "task"), exist_ok=True)

        # Update config paths to use absolute paths
        config["output_annotation_dir"] = os.path.join(test_dir, "output")
        config["task_dir"] = os.path.join(test_dir, "task")
        config["site_dir"] = os.path.join(test_dir, "templates")
        config["data_files"] = [data_file]  # Use absolute path to the data file

        # Create config file
        config_path = os.path.join(test_dir, "test_config.yaml")
        with open(config_path, 'w') as f:
            yaml.dump(config, f)

        return config_path, test_dir

    def create_user(self, driver, base_url, username):
        """Register a new user."""
        driver.get(f"{base_url}/auth")

        # Switch to register tab
        register_tab = driver.find_element(By.ID, "register-tab")
        register_tab.click()

        # Fill registration form
        username_input = driver.find_element(By.ID, "register-email")
        password_input = driver.find_element(By.ID, "register-pass")

        username_input.clear()
        username_input.send_keys(username)
        password_input.clear()
        password_input.send_keys("testpass123")

        # Submit registration
        register_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Register')]")
        register_button.click()

        # Wait for redirect to annotation page
        WebDriverWait(driver, 10).until(
            lambda d: "/" in d.current_url and "auth" not in d.current_url
        )

    def test_robust_span_annotation_basic(self):
        """Test basic robust span annotation functionality."""
        test_data = [
            {
                "id": "1",
                "text": "I am so happy today! The weather is beautiful and everything is going well."
            },
            {
                "id": "2",
                "text": "This is a sad story about a lost puppy who couldn't find its way home."
            }
        ]

        config_path, test_dir = self.create_test_config(test_data)

        server = FlaskTestServer(lambda: create_app(), config_path, debug=False)
        server.start()
        server_url = server.base_url

        try:
            # Set up Chrome driver
            chrome_options = create_chrome_options(headless=True)
            driver = webdriver.Chrome(options=chrome_options)

            try:
                # Register a test user
                self.create_user(driver, server_url, "test_user")

                # Wait for the annotation page to load
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "instance_id"))
                )

                # Get the text content
                text_element = driver.find_element(By.CLASS_NAME, "text-content")
                text_content = text_element.text
                assert "happy" in text_content.lower(), "Text should contain 'happy'"

                # Select text for span annotation
                # Find the word "happy" in the text
                happy_text = driver.find_element(By.XPATH, "//*[contains(text(), 'happy')]")

                # Create a span annotation by selecting the text
                actions = ActionChains(driver)
                actions.move_to_element(happy_text)
                actions.click_and_hold()
                actions.move_by_offset(20, 0)  # Select a portion of the text
                actions.release()
                actions.perform()

                # Wait for the span annotation dialog or highlight to appear
                time.sleep(1)

                # Check if the text is highlighted (should have span-highlight class)
                highlighted_elements = driver.find_elements(By.CLASS_NAME, "span-highlight")
                assert len(highlighted_elements) > 0, "Text should be highlighted after selection"

                # Verify that the span annotation was created
                # Check the user state via admin endpoint
                user_state_response = server.get("/admin/user_state/test_user")
                assert user_state_response.status_code == 200, f"Failed to get user state: {user_state_response.status_code}"
                user_state = user_state_response.json()
                print('User state:', user_state)

                # Wait a moment for the backend check to complete
                time.sleep(2)

                # The span annotation should be visible in the DOM
                span_elements = driver.find_elements(By.CSS_SELECTOR, ".span-highlight")
                assert len(span_elements) > 0, "Span elements should be present in the DOM"

            finally:
                driver.quit()

        finally:
            server.stop()

    def test_robust_span_annotation_overlapping(self):
        """Test overlapping span annotations with the robust system."""
        test_data = [
            {
                "id": "1",
                "text": "I am so happy today! The weather is beautiful and everything is going well."
            }
        ]

        config_path, test_dir = self.create_test_config(test_data)

        server = FlaskTestServer(lambda: create_app(), config_path, debug=False)
        server.start()
        server_url = server.base_url

        try:
            # Set up Chrome driver
            chrome_options = create_chrome_options(headless=True)
            driver = webdriver.Chrome(options=chrome_options)

            try:
                # Register a test user
                self.create_user(driver, server_url, "test_user")

                # Wait for the annotation page to load
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "instance_id"))
                )

                # Get the text content
                text_element = driver.find_element(By.CLASS_NAME, "text-content")
                text_content = text_element.text

                # Create overlapping selections
                # First selection: "so happy"
                actions = ActionChains(driver)
                actions.move_to_element(text_element)
                actions.click_and_hold()
                actions.move_by_offset(50, 0)  # Select "so happy"
                actions.release()
                actions.perform()

                time.sleep(1)

                # Second selection: "happy today" (overlaps with first)
                actions = ActionChains(driver)
                actions.move_to_element(text_element)
                actions.click_and_hold()
                actions.move_by_offset(60, 0)  # Select "happy today"
                actions.release()
                actions.perform()

                time.sleep(1)

                # Check that both spans are visible
                span_elements = driver.find_elements(By.CSS_SELECTOR, ".span-highlight")
                assert len(span_elements) >= 2, "Should have at least 2 span elements for overlapping annotations"

                # Verify that the overlapping spans are properly rendered
                # The robust system should handle overlapping spans correctly
                for span in span_elements:
                    assert span.is_displayed(), "Span elements should be visible"

            finally:
                driver.quit()

        finally:
            server.stop()

    def test_robust_span_annotation_with_other_types(self):
        """Test that robust span annotations work alongside other annotation types."""
        test_data = [
            {
                "id": "1",
                "text": "I am so happy today! The weather is beautiful."
            }
        ]

        config_path, test_dir = self.create_test_config(test_data)

        server = FlaskTestServer(lambda: create_app(), config_path, debug=False)
        server.start()
        server_url = server.base_url

        try:
            # Set up Chrome driver
            chrome_options = create_chrome_options(headless=True)
            driver = webdriver.Chrome(options=chrome_options)

            try:
                # Register a test user
                self.create_user(driver, server_url, "test_user")

                # Wait for the annotation page to load
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "instance_id"))
                )

                # Create a span annotation first
                text_element = driver.find_element(By.CLASS_NAME, "text-content")
                actions = ActionChains(driver)
                actions.move_to_element(text_element)
                actions.click_and_hold()
                actions.move_by_offset(30, 0)
                actions.release()
                actions.perform()

                time.sleep(1)

                # Now create a radio button annotation
                radio_button = driver.find_element(By.CSS_SELECTOR, "input[type='radio'][value='positive']")
                radio_button.click()

                time.sleep(1)

                # Verify both annotations are present
                span_elements = driver.find_elements(By.CSS_SELECTOR, ".span-highlight")
                assert len(span_elements) > 0, "Span annotation should be present"

                # Check that radio button is selected
                selected_radio = driver.find_element(By.CSS_SELECTOR, "input[type='radio'][value='positive']:checked")
                assert selected_radio.is_selected(), "Radio button should be selected"

            finally:
                driver.quit()

        finally:
            server.stop()


def create_app():
    from potato.flask_server import create_app
    return create_app()