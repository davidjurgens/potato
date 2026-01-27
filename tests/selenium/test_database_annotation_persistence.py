"""
Selenium tests for annotation persistence.

This module tests that annotations persist correctly across page reloads
and navigation using file-based storage.
"""

import pytest
import os
import time
import shutil

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_config, create_test_data_file


class TestAnnotationPersistence:
    """Test that annotations persist correctly with file-based storage."""

    @classmethod
    def setup_class(cls):
        """Set up the test environment using pytest style."""
        # Create test data
        test_data = [
            {"id": "item1", "text": "This is a positive text about technology."},
            {"id": "item2", "text": "This is a negative text about politics."},
            {"id": "item3", "text": "This is a neutral text about sports."},
            {"id": "item4", "text": "This is another positive text about science."},
            {"id": "item5", "text": "This is another negative text about economics."}
        ]

        # Create test directory
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", f"persistence_test_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create test data file
        data_file = create_test_data_file(cls.test_dir, test_data)

        # Create configuration with multiple annotation types
        annotation_schemes = [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "What is the sentiment?"
            },
            {
                "name": "topics",
                "annotation_type": "multiselect",
                "labels": ["politics", "technology", "sports", "science", "economics"],
                "description": "What topics are mentioned?"
            },
            {
                "name": "quality",
                "annotation_type": "likert",
                "min_label": "Very Poor",
                "max_label": "Excellent",
                "size": 5,
                "description": "Rate the quality"
            },
            {
                "name": "summary",
                "annotation_type": "text",
                "description": "Provide a summary"
            },
            {
                "name": "confidence",
                "annotation_type": "slider",
                "min_value": 0,
                "max_value": 10,
                "starting_value": 5,
                "step": 1,
                "min_label": "Low",
                "max_label": "High",
                "description": "How confident are you?"
            }
        ]

        config_file = create_test_config(
            cls.test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Persistence Test",
            require_password=False
        )

        # Start server
        cls.port = find_free_port()
        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options
        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def teardown_class(cls):
        """Clean up test environment."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir') and os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setup_method(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.base_url = self.server.base_url

    def teardown_method(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def login_user(self, username):
        """Login a user (for require_password=False config)."""
        self.driver.get(self.base_url)
        # For require_password=False, the email field is login-email
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        email_field = self.driver.find_element(By.ID, "login-email")
        email_field.clear()
        email_field.send_keys(username)
        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "#login-content button[type='submit']")
        submit_btn.click()
        time.sleep(0.3)

    def test_radio_button_annotation_persistence(self):
        """Test that radio button annotations persist after page reload."""
        self.login_user("test_user_radio")

        # Navigate to annotation page
        self.driver.get(f"{self.base_url}/annotate")
        time.sleep(0.2)

        # Make radio button annotation
        radio_button = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='radio'][value='positive']"))
        )
        radio_button.click()

        # Submit annotation (moves to next item)
        submit_button = self.driver.find_element(By.ID, "next-btn")
        submit_button.click()
        time.sleep(0.3)

        # Navigate back to first item
        prev_button = self.driver.find_element(By.ID, "prev-btn")
        prev_button.click()
        time.sleep(0.5)

        # Verify annotation persisted
        radio_button = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='radio'][value='positive']"))
        )
        assert radio_button.is_selected(), "Radio button annotation should persist"

    def test_multiselect_annotation_persistence(self):
        """Test that multiselect annotations persist after page reload."""
        self.login_user("test_user_multiselect")

        self.driver.get(f"{self.base_url}/annotate")
        time.sleep(0.2)

        # Select multiple topics
        tech_checkbox = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='checkbox'][value='technology']"))
        )
        tech_checkbox.click()
        science_checkbox = self.driver.find_element(By.CSS_SELECTOR, "input[type='checkbox'][value='science']")
        science_checkbox.click()

        # Submit
        submit_button = self.driver.find_element(By.ID, "next-btn")
        submit_button.click()
        time.sleep(0.3)

        # Navigate back
        prev_button = self.driver.find_element(By.ID, "prev-btn")
        prev_button.click()
        time.sleep(0.5)

        # Verify
        tech_checkbox = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='checkbox'][value='technology']"))
        )
        science_checkbox = self.driver.find_element(By.CSS_SELECTOR, "input[type='checkbox'][value='science']")
        assert tech_checkbox.is_selected(), "Technology checkbox should persist"
        assert science_checkbox.is_selected(), "Science checkbox should persist"

    def test_text_annotation_persistence(self):
        """Test that text annotations persist."""
        self.login_user("test_user_text")

        self.driver.get(f"{self.base_url}/annotate")
        time.sleep(0.2)

        # Enter text annotation
        text_area = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[schema='summary']"))
        )
        text_area.clear()
        text_area.send_keys("This is a test summary annotation.")
        time.sleep(0.15)  # Allow time for text to be captured

        # Submit
        submit_button = self.driver.find_element(By.ID, "next-btn")
        submit_button.click()
        time.sleep(0.3)

        # Navigate back
        prev_button = self.driver.find_element(By.ID, "prev-btn")
        prev_button.click()
        time.sleep(0.5)

        # Verify
        text_area = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[schema='summary']"))
        )
        assert text_area.get_attribute("value") == "This is a test summary annotation.", \
            "Text annotation should persist"

    def test_navigation_persistence(self):
        """Test that annotations persist when navigating between instances."""
        self.login_user("test_user_nav")

        self.driver.get(f"{self.base_url}/annotate")
        time.sleep(0.2)

        # Annotate first instance
        radio_button = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='radio'][value='positive']"))
        )
        radio_button.click()

        # Submit and go to next
        submit_button = self.driver.find_element(By.ID, "next-btn")
        submit_button.click()
        time.sleep(0.3)

        # Navigate back
        prev_button = self.driver.find_element(By.ID, "prev-btn")
        prev_button.click()
        time.sleep(0.5)

        # Verify annotation persisted
        radio_button = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='radio'][value='positive']"))
        )
        assert radio_button.is_selected(), "Annotation should persist after navigation"

    def test_multiple_annotation_types_persistence(self):
        """Test that multiple annotation types persist together."""
        self.login_user("test_user_multiple")

        self.driver.get(f"{self.base_url}/annotate")
        time.sleep(0.2)

        # Radio
        radio_button = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='radio'][value='negative']"))
        )
        radio_button.click()

        # Multiselect
        checkbox = self.driver.find_element(By.CSS_SELECTOR, "input[type='checkbox'][value='politics']")
        checkbox.click()

        # Text
        text_area = self.driver.find_element(By.CSS_SELECTOR, "input[schema='summary']")
        text_area.clear()
        text_area.send_keys("Multiple annotation test")
        time.sleep(0.15)  # Allow time for text to be captured

        # Submit (moves to next item)
        submit_button = self.driver.find_element(By.ID, "next-btn")
        submit_button.click()
        time.sleep(0.3)

        # Navigate back to first item
        prev_button = self.driver.find_element(By.ID, "prev-btn")
        prev_button.click()
        time.sleep(0.5)

        radio_button = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='radio'][value='negative']"))
        )
        assert radio_button.is_selected(), "Radio should persist"

        checkbox = self.driver.find_element(By.CSS_SELECTOR, "input[type='checkbox'][value='politics']")
        assert checkbox.is_selected(), "Checkbox should persist"

        text_area = self.driver.find_element(By.CSS_SELECTOR, "input[schema='summary']")
        assert text_area.get_attribute("value") == "Multiple annotation test", "Text should persist"
