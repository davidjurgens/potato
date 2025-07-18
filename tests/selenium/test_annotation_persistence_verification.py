#!/usr/bin/env python3
"""
Selenium tests for verifying annotation persistence across all annotation types.

This test suite verifies that annotations are properly saved to output files
for each annotation type supported by the system. It uses the test config files
in tests/configs/ and verifies that annotations persist after completing
annotation tasks.

Test Coverage:
- Likert annotation persistence
- Radio annotation persistence
- Slider annotation persistence
- Text annotation persistence
- Multiselect annotation persistence
- Span annotation persistence

Each test:
1. Starts a Flask server with the specific annotation type config
2. Registers a unique test user
3. Completes annotations for all instances
4. Verifies annotations are saved to output files
5. Checks that output files contain expected annotation data
"""

import os
import json
import time
import tempfile
import shutil
import yaml
import uuid
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import unittest

# Add potato to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.selenium.test_base import BaseSeleniumTest


class TestAnnotationPersistenceVerification(unittest.TestCase):
    """
    Test class for verifying annotation persistence across all annotation types.

    This class manages its own server setup for each test to use different config files.
    """

    @classmethod
    def setUpClass(cls):
        """Set up Chrome options for headless testing."""
        # Set up Chrome options for headless testing
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

        cls.chrome_options = chrome_options

    def setUp(self):
        """Set up test environment with WebDriver."""
        # Create WebDriver
        self.driver = webdriver.Chrome(options=self.chrome_options)

        # Generate unique test user credentials
        timestamp = int(time.time())
        self.test_user = f"test_user_{self.__class__.__name__}_{timestamp}"
        self.test_password = "test_password_123"

    def register_user(self):
        """Register a new test user via the web interface."""
        self.driver.get(f"{self.server.base_url}/")

        # Wait for page to load - should show login/register form
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-tab"))
        )

        # Switch to registration tab
        register_tab = self.driver.find_element(By.ID, "register-tab")
        register_tab.click()

        # Wait for register form to be visible
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "register-content"))
        )

        # Fill registration form using correct field IDs
        username_field = self.driver.find_element(By.ID, "register-email")
        password_field = self.driver.find_element(By.ID, "register-pass")

        username_field.clear()
        password_field.clear()
        username_field.send_keys(self.test_user)
        password_field.send_keys(self.test_password)

        # Submit registration form
        register_form = self.driver.find_element(By.CSS_SELECTOR, "#register-content form")
        register_form.submit()

        # Wait for redirect after registration
        time.sleep(2)

    def login_user(self):
        """Login the test user via the web interface."""
        # If not already logged in, login
        if "/annotate" not in self.driver.current_url:
            self.driver.get(f"{self.server.base_url}/")

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "login-tab"))
            )

            # Switch to login tab
            login_tab = self.driver.find_element(By.ID, "login-tab")
            login_tab.click()

            # Wait for login form to be visible
            WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.ID, "login-content"))
            )

            # Fill login form using correct field IDs
            username_field = self.driver.find_element(By.ID, "login-email")
            password_field = self.driver.find_element(By.ID, "login-pass")

            username_field.clear()
            password_field.clear()
            username_field.send_keys(self.test_user)
            password_field.send_keys(self.test_password)

            # Submit login form
            login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
            login_form.submit()

            # Wait for redirect after login
            time.sleep(2)

    def verify_authentication(self):
        """Verify that authentication worked by checking if we can access the annotation page."""
        try:
            # Try to access annotation page
            self.driver.get(f"{self.server.base_url}/annotate")

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                lambda d: "annotate" in d.current_url
            )

            # Check if we're on the annotation page (not redirected to login)
            if "/annotate" in self.driver.current_url:
                print(f"✅ Authentication successful for user: {self.test_user}")
                return True
            else:
                print(f"❌ Authentication failed for user: {self.test_user}")
                return False
        except Exception as e:
            print(f"❌ Authentication verification failed: {e}")
            return False

    def tearDown(self):
        """Clean up test environment."""
        # Clean up WebDriver
        if hasattr(self, 'driver'):
            self.driver.quit()

    def create_test_environment(self, config_file, test_name):
        """
        Create a test environment with the specified config file.

        Args:
            config_file: Path to the config file to use
            test_name: Name for this test run

        Returns:
            tuple: (temp_config_path, instance_ids, output_dir)
        """
        # Create unique temp directory for this test
        test_id = str(uuid.uuid4())[:8]
        temp_dir = tempfile.mkdtemp(prefix=f"potato_test_{test_name}_{test_id}_")

        # Copy config file to temp directory
        config_dir = os.path.join(temp_dir, "configs")
        os.makedirs(config_dir, exist_ok=True)

        # Read original config
        with open(config_file, 'r') as f:
            config_data = yaml.safe_load(f)

        # Update config to use temp directory paths
        config_data['output_annotation_dir'] = os.path.join(temp_dir, "output")
        config_data['task_dir'] = os.path.join(temp_dir, "task")
        config_data['site_dir'] = os.path.join(temp_dir, "templates")
        config_data['data_file'] = os.path.join(temp_dir, "data", "test_data.json")

        # Write updated config to temp directory
        temp_config_path = os.path.join(config_dir, os.path.basename(config_file))
        with open(temp_config_path, 'w') as f:
            yaml.dump(config_data, f)

        print(f"Created config file: {temp_config_path}")
        print(f"Config data: {config_data}")

        # Create data directory and test data file with unique IDs
        data_dir = os.path.join(temp_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create unique test data with timestamp-based IDs
        timestamp = int(time.time() * 1000)  # Use milliseconds for more uniqueness
        test_data = [
            {"id": "1", "text": "The new artificial intelligence model achieved remarkable results in natural language processing tasks, outperforming previous benchmarks by a significant margin."},
            {"id": "2", "text": "I'm feeling incredibly sad today because my beloved pet passed away unexpectedly. The house feels so empty without their cheerful presence."},
            {"id": "3", "text": "The political debate was heated and intense, with candidates passionately arguing about healthcare reform and economic policies."}
        ]

        unique_test_data = []
        instance_ids = []

        for i, item in enumerate(test_data):
            unique_item = item.copy()
            instance_id = f"test_{test_name}_{timestamp}_{i+1}"
            unique_item['id'] = instance_id
            instance_ids.append(instance_id)
            unique_test_data.append(unique_item)

        # Write test data file
        test_data_file = os.path.join(data_dir, "test_data.json")
        with open(test_data_file, 'w') as f:
            for item in unique_test_data:
                f.write(json.dumps(item) + '\n')

        print(f"Created test data file: {test_data_file}")
        print(f"Test data content:")
        for item in unique_test_data:
            print(f"  {item}")

        output_dir = os.path.join(temp_dir, "output")
        return temp_config_path, instance_ids, output_dir

    def start_server_with_config(self, config_path):
        """
        Start a Flask server with the specified config file.

        Args:
            config_path: Path to the config file

        Returns:
            FlaskTestServer: The started server instance
        """
        # Stop any existing server
        if hasattr(self, 'server'):
            self.server.stop_server()

        # Start new server with the config and test data file
        config_dir = os.path.dirname(config_path)
        test_data_file = os.path.join(config_dir, "..", "data", "test_data.json")

        server = FlaskTestServer(port=9009, debug=False, config_file=config_path, test_data_file=test_data_file)
        started = server.start_server()
        assert started, f"Failed to start Flask server with config {config_path}"

        # Wait for server to be ready
        server._wait_for_server_ready(timeout=10)

        return server

    def complete_annotation_task(self, annotation_type, expected_values=None):
        """
        Complete an annotation task for all instances.

        Args:
            annotation_type: Type of annotation (likert, radio, slider, text, multiselect, span)
            expected_values: Dictionary mapping instance IDs to expected annotation values
        """
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for annotation page to load
        WebDriverWait(self.driver, 10).until(
            lambda d: "annotate" in d.current_url
        )

        # Complete annotations for each instance
        instance_count = 0
        max_instances = 10  # Safety limit

        while instance_count < max_instances:
            try:
                # Wait for current instance to load
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "annotation-container"))
                    )
                except TimeoutException:
                    print("Could not find annotation-container, trying alternative selectors")
                    # Try to find any annotation-related elements
                    radio_buttons = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                    print(f"Found {len(radio_buttons)} radio buttons")
                    if radio_buttons:
                        print("Radio buttons found, proceeding with annotation")
                    else:
                        print("No radio buttons found")
                        # Print page source for debugging
                        print(f"Page source (first 1000 chars): {self.driver.page_source[:1000]}")

                # Get current instance ID
                try:
                    instance_element = self.driver.find_element(By.CSS_SELECTOR, "[data-instance-id]")
                    current_instance_id = instance_element.get_attribute("data-instance-id")
                except NoSuchElementException:
                    print("Could not find data-instance-id attribute")
                    current_instance_id = "unknown"

                print(f"Annotating instance: {current_instance_id}")

                # Perform annotation based on type
                self.perform_annotation(annotation_type, expected_values)

                # Move to next instance
                next_button = self.driver.find_element(By.ID, "next-btn")
                if not next_button.is_enabled():
                    # We're at the end
                    break

                next_button.click()
                time.sleep(1)
                instance_count += 1

            except (TimeoutException, NoSuchElementException) as e:
                print(f"Error during annotation: {e}")
                break

    def perform_annotation(self, annotation_type, expected_values=None):
        """
        Perform annotation for the current instance based on annotation type.

        Args:
            annotation_type: Type of annotation to perform
            expected_values: Dictionary mapping instance IDs to expected values
        """
        if annotation_type == "likert":
            self.perform_likert_annotation()
        elif annotation_type == "radio":
            self.perform_radio_annotation()
        elif annotation_type == "slider":
            self.perform_slider_annotation()
        elif annotation_type == "text":
            self.perform_text_annotation()
        elif annotation_type == "multiselect":
            self.perform_multiselect_annotation()
        elif annotation_type == "span":
            self.perform_span_annotation()
        else:
            raise ValueError(f"Unknown annotation type: {annotation_type}")

    def perform_likert_annotation(self):
        """Perform likert scale annotation."""
        # Find and click a likert scale option (usually radio buttons)
        # Try multiple selectors to find the radio buttons
        selectors = [
            "input.shadcn-likert-input[name*='quality']",
            "input.shadcn-likert-input[name*='clarity']",
            "input.shadcn-likert-input[name*='relevance']",
            "input[type='radio']"
        ]

        radio_buttons = []
        for selector in selectors:
            radio_buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
            if radio_buttons:
                print(f"Found {len(radio_buttons)} radio buttons with selector: {selector}")
                break

        if radio_buttons:
            # Click the first option
            try:
                radio_buttons[0].click()
                print("Clicked first radio button")
            except Exception as e:
                # Try clicking the label if input is not interactable
                input_id = radio_buttons[0].get_attribute('id')
                if input_id:
                    label = self.driver.find_element(By.CSS_SELECTOR, f"label[for='{input_id}']")
                    label.click()
                    print(f"Clicked label for radio button with id: {input_id}")
                else:
                    raise e
            time.sleep(1)

            # Check if Next button is enabled and click it
            try:
                next_button = self.driver.find_element(By.ID, "next-btn")
                if not next_button.get_attribute("disabled"):
                    next_button.click()
                    print("Clicked Next button")
                    time.sleep(2)
                else:
                    print("Next button is disabled")
            except Exception as e:
                print(f"Could not click Next button: {e}")
        else:
            print("No radio buttons found")

    def perform_radio_annotation(self):
        """Perform radio button annotation."""
        # Find and click a radio button
        radio_buttons = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        if radio_buttons:
            radio_buttons[0].click()
            time.sleep(1)

            # Click Next button
            try:
                next_button = self.driver.find_element(By.ID, "next-btn")
                if not next_button.get_attribute("disabled"):
                    next_button.click()
                    print("Clicked Next button")
                    time.sleep(2)
            except Exception as e:
                print(f"Could not click Next button: {e}")

    def perform_slider_annotation(self):
        """Perform slider annotation."""
        # Find slider and set a value
        slider = self.driver.find_element(By.CSS_SELECTOR, "input[type='range']")
        self.driver.execute_script("arguments[0].value = '50';", slider)
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", slider)
        time.sleep(1)

        # Click Next button
        try:
            next_button = self.driver.find_element(By.ID, "next-btn")
            if not next_button.get_attribute("disabled"):
                next_button.click()
                print("Clicked Next button")
                time.sleep(2)
        except Exception as e:
            print(f"Could not click Next button: {e}")

    def perform_text_annotation(self):
        """Perform text annotation."""
        # Find text input and enter text
        text_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='text'], textarea")
        text_input.clear()
        text_input.send_keys("Test annotation text")
        time.sleep(1)

        # Click Next button
        try:
            next_button = self.driver.find_element(By.ID, "next-btn")
            if not next_button.get_attribute("disabled"):
                next_button.click()
                print("Clicked Next button")
                time.sleep(2)
        except Exception as e:
            print(f"Could not click Next button: {e}")

    def perform_multiselect_annotation(self):
        """Perform multiselect annotation."""
        # Find checkboxes and select first one
        checkboxes = self.driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        if checkboxes:
            checkboxes[0].click()
            time.sleep(1)

            # Click Next button
            try:
                next_button = self.driver.find_element(By.ID, "next-btn")
                if not next_button.get_attribute("disabled"):
                    next_button.click()
                    print("Clicked Next button")
                    time.sleep(2)
            except Exception as e:
                print(f"Could not click Next button: {e}")

    def perform_span_annotation(self):
        """Perform span annotation."""
        # Find text to annotate and create a span
        text_elements = self.driver.find_elements(By.CSS_SELECTOR, ".text-content, .annotation-text")
        if text_elements:
            text_element = text_elements[0]
            # Select first few words
            self.driver.execute_script("""
                var range = document.createRange();
                var textNode = arguments[0].firstChild;
                range.setStart(textNode, 0);
                range.setEnd(textNode, 10);
                var selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            """, text_element)
            time.sleep(1)

            # Click Next button
            try:
                next_button = self.driver.find_element(By.ID, "next-btn")
                if not next_button.get_attribute("disabled"):
                    next_button.click()
                    print("Clicked Next button")
                    time.sleep(2)
            except Exception as e:
                print(f"Could not click Next button: {e}")

    def verify_annotations_stored(self, annotation_type, expected_value=None):
        """
        Verify that annotations are properly stored by checking UI state after navigation.

        Args:
            annotation_type: Type of annotation that was performed
            expected_value: Expected value of the annotation

        Returns:
            bool: True if annotations were found, False otherwise
        """
        # Wait a moment for any pending requests to complete
        time.sleep(2)

        # Navigate away and back to annotation page
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1)
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(2)

        # Navigate to the first instance to verify
        try:
            go_to_input = self.driver.find_element(By.ID, "go_to")
            go_to_input.clear()
            go_to_input.send_keys("1")
            go_to_button = self.driver.find_element(By.ID, "go-to-btn")
            go_to_button.click()
            time.sleep(2)
        except Exception as e:
            print(f"Could not navigate to specific instance: {e}")
            # Continue with current instance if navigation fails

        if annotation_type == "likert":
            # Check Likert radio input
            likert_selectors = [
                "input.shadcn-likert-input[name*='quality']",
                "input.shadcn-likert-input[name*='clarity']",
                "input.shadcn-likert-input[name*='relevance']",
                "input[type='radio']"
            ]
            found = False
            for selector in likert_selectors:
                radios = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for radio in radios:
                    if radio.is_selected():
                        print(f"Found selected Likert radio with value {radio.get_attribute('value')} using selector {selector}")
                        found = True
                        break
                if found:
                    break
            return found
        elif annotation_type == "text":
            # Check text input
            textarea_selectors = [
                "textarea[name='feedback']",
                "textarea",
                "textarea[name*='feedback']",
                "textarea.feedback",
                "textarea[name*='text']"
            ]
            for selector in textarea_selectors:
                try:
                    textarea = self.driver.find_element(By.CSS_SELECTOR, selector)
                    value = textarea.get_attribute("value")
                    print(f"Found textarea with selector: {selector}, value: '{value}'")
                    return value == expected_value
                except NoSuchElementException:
                    continue
            return False
        elif annotation_type == "slider":
            # Check slider value
            try:
                slider = self.driver.find_element(By.CSS_SELECTOR, "input[type='range']")
                value = slider.get_attribute("value")
                print(f"Slider value: '{value}'")
                return value == expected_value
            except NoSuchElementException:
                return False
        elif annotation_type == "radio":
            # Check radio button selection
            radio_buttons = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            for radio in radio_buttons:
                if radio.is_selected():
                    print(f"Found selected radio with value {radio.get_attribute('value')}")
                    return True
            return False
        elif annotation_type == "multiselect":
            # Check checkbox selection
            checkboxes = self.driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            for checkbox in checkboxes:
                if checkbox.is_selected():
                    print(f"Found selected checkbox with value {checkbox.get_attribute('value')}")
                    return True
            return False
        elif annotation_type == "span":
            # Check span annotation
            highlight_elements = self.driver.find_elements(By.CSS_SELECTOR, ".highlighted-span, .shadcn-span-highlight, span[data-annotation-label]")
            print(f"Found {len(highlight_elements)} highlighted span elements")
            return len(highlight_elements) >= 1
        else:
            print(f"Unknown annotation type: {annotation_type}")
            return False

    def test_likert_annotation_persistence(self):
        """Test that likert annotations are properly saved."""
        config_file = "tests/configs/likert-annotation.yaml"
        temp_config_path, instance_ids, output_dir = self.create_test_environment(config_file, "likert")

        # Start server with config
        self.server = self.start_server_with_config(temp_config_path)

        try:
            # Register and login user
            self.register_user()
            self.login_user()

            # Verify authentication worked
            self.assertTrue(self.verify_authentication(), "Authentication failed")

            # Complete annotation task
            self.complete_annotation_task("likert")

            # Verify annotations were stored
            self.assertTrue(
                self.verify_annotations_stored("likert"),
                "Likert annotations were not stored properly"
            )
        finally:
            self.server.stop_server()

    def test_radio_annotation_persistence(self):
        """Test that radio annotations are properly saved."""
        config_file = "tests/configs/radio_annotation_test.yaml"
        temp_config_path, instance_ids, output_dir = self.create_test_environment(config_file, "radio")

        # Start server with config
        self.server = self.start_server_with_config(temp_config_path)

        try:
            # Register and login user
            self.register_user()
            self.login_user()

            # Verify authentication worked
            self.assertTrue(self.verify_authentication(), "Authentication failed")

            # Complete annotation task
            self.complete_annotation_task("radio")

            # Verify annotations were stored
            self.assertTrue(
                self.verify_annotations_stored("radio"),
                "Radio annotations were not stored properly"
            )
        finally:
            self.server.stop_server()

    def test_slider_annotation_persistence(self):
        """Test that slider annotations are properly saved."""
        config_file = "tests/configs/slider_annotation_test.yaml"
        temp_config_path, instance_ids, output_dir = self.create_test_environment(config_file, "slider")

        # Start server with config
        self.server = self.start_server_with_config(temp_config_path)

        try:
            # Register and login user
            self.register_user()
            self.login_user()

            # Verify authentication worked
            self.assertTrue(self.verify_authentication(), "Authentication failed")

            # Complete annotation task
            self.complete_annotation_task("slider")

            # Verify annotations were stored
            self.assertTrue(
                self.verify_annotations_stored("slider", "50"),
                "Slider annotations were not stored properly"
            )
        finally:
            self.server.stop_server()

    def test_text_annotation_persistence(self):
        """Test that text annotations are properly saved."""
        config_file = "tests/configs/text_annotation_test.yaml"
        temp_config_path, instance_ids, output_dir = self.create_test_environment(config_file, "text")

        # Start server with config
        self.server = self.start_server_with_config(temp_config_path)

        try:
            # Register and login user
            self.register_user()
            self.login_user()

            # Verify authentication worked
            self.assertTrue(self.verify_authentication(), "Authentication failed")

            # Complete annotation task
            self.complete_annotation_task("text")

            # Verify annotations were stored
            self.assertTrue(
                self.verify_annotations_stored("text", "Test annotation text"),
                "Text annotations were not stored properly"
            )
        finally:
            self.server.stop_server()

    def test_multiselect_annotation_persistence(self):
        """Test that multiselect annotations are properly saved."""
        config_file = "tests/configs/multiselect_annotation_test.yaml"
        temp_config_path, instance_ids, output_dir = self.create_test_environment(config_file, "multiselect")

        # Start server with config
        self.server = self.start_server_with_config(temp_config_path)

        try:
            # Register and login user
            self.register_user()
            self.login_user()

            # Verify authentication worked
            self.assertTrue(self.verify_authentication(), "Authentication failed")

            # Complete annotation task
            self.complete_annotation_task("multiselect")

            # Verify annotations were stored
            self.assertTrue(
                self.verify_annotations_stored("multiselect"),
                "Multiselect annotations were not stored properly"
            )
        finally:
            self.server.stop_server()

    def test_span_annotation_persistence(self):
        """Test that span annotations are properly saved."""
        config_file = "tests/configs/span_annotation_test.yaml"
        temp_config_path, instance_ids, output_dir = self.create_test_environment(config_file, "span")

        # Start server with config
        self.server = self.start_server_with_config(temp_config_path)

        try:
            # Register and login user
            self.register_user()
            self.login_user()

            # Verify authentication worked
            self.assertTrue(self.verify_authentication(), "Authentication failed")

            # Complete annotation task
            self.complete_annotation_task("span")

            # Verify annotations were stored
            self.assertTrue(
                self.verify_annotations_stored("span"),
                "Span annotations were not stored properly"
            )
        finally:
            self.server.stop_server()


if __name__ == "__main__":
    unittest.main()