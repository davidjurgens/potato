"""
Selenium tests for multirate annotation.

Multirate annotation allows users to rate multiple items on the same scale.
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
from selenium.webdriver.chrome.options import Options
from tests.flask_test_setup import FlaskTestServer
import requests


class TestMultirateAnnotation:
    """Test suite for multirate annotation."""

    @pytest.fixture(scope="class")
    def test_data(self):
        """Create test data for multirate annotation."""
        return [
            {
                "id": "1",
                "text": "The new artificial intelligence model achieved remarkable results in natural language processing tasks, outperforming previous benchmarks by a significant margin."
            },
            {
                "id": "2",
                "text": "I'm feeling incredibly sad today because my beloved pet passed away unexpectedly. The house feels so empty without their cheerful presence."
            },
            {
                "id": "3",
                "text": "The political debate was heated and intense, with candidates passionately arguing about healthcare reform and economic policies."
            }
        ]

    def create_test_data_file(self, test_data, filename="data/test_data.json"):
        """Create test data file."""
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

    def create_test_config_file(self, config, config_dir):
        """Create a test config file."""
        os.makedirs(config_dir, exist_ok=True)

        # Create test data file
        data_file = os.path.join(config_dir, "test_data.json")
        with open(data_file, 'w') as f:
            for item in config.get('test_data', []):
                f.write(json.dumps(item) + '\n')

        # Create phase files
        phase_dir = os.path.join(config_dir, 'configs', 'test-phases')
        os.makedirs(phase_dir, exist_ok=True)

        # Create consent phase file
        consent_data = [
            {
                "name": "consent_check",
                "type": "radio",
                "annotation_type": "radio",
                "labels": ["I agree", "I do not agree"],
                "description": "Do you agree to participate in this study?"
            }
        ]
        consent_path = os.path.join(phase_dir, 'consent.json')
        with open(consent_path, 'w') as f:
            json.dump(consent_data, f, indent=2)

        # Create instructions phase file
        instructions_data = [
            {
                "name": "instructions_check",
                "type": "radio",
                "annotation_type": "radio",
                "labels": ["I understand", "I need more explanation"],
                "description": "Do you understand the instructions?"
            }
        ]
        instructions_path = os.path.join(phase_dir, 'instructions.json')
        with open(instructions_path, 'w') as f:
            json.dump(instructions_data, f, indent=2)

        # Create the main config file
        test_config = {
            "debug": config.get('debug', True),
            "max_annotations_per_user": 5,
            "max_annotations_per_item": -1,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": config.get('annotation_task_name', 'Test Annotation Task'),
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": ["test_data.json"],
            "item_properties": config.get('item_properties', {"text_key": "text", "id_key": "id"}),
            "annotation_schemes": config.get('annotation_schemes', []),
            "phases": {
                "order": ["consent", "instructions"],
                "consent": {
                    "type": "consent",
                    "file": "configs/test-phases/consent.json"
                },
                "instructions": {
                    "type": "instructions",
                    "file": "configs/test-phases/instructions.json"
                }
            },
            "site_file": "base_template.html",
            "output_annotation_dir": os.path.join(config_dir, "output"),
            "task_dir": os.path.join(config_dir, "task"),
            "base_html_template": "default",
            "header_file": "default",
            "html_layout": "default",
            "site_dir": os.path.join(config_dir, "templates"),
            "alert_time_each_instance": 0
        }

        # Ensure output and task directories exist
        os.makedirs(test_config["output_annotation_dir"], exist_ok=True)
        os.makedirs(test_config["task_dir"], exist_ok=True)

        config_path = os.path.join(config_dir, 'test_config.yaml')
        with open(config_path, 'w') as f:
            yaml.dump(test_config, f)

        return config_path

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

    def verify_next_button_state(self, driver, expected_disabled=True):
        """Verify the Next button state."""
        next_button = driver.find_element(By.ID, "next-btn")
        is_disabled = next_button.get_attribute("disabled") is not None
        assert is_disabled == expected_disabled, f"Next button should be {'disabled' if expected_disabled else 'enabled'}"

    def verify_annotations_stored(self, driver, base_url, username, instance_id):
        """Verify that annotations are correctly stored by the server."""
        # Backend verification: Check that annotation was saved
        api_key = os.environ.get("TEST_API_KEY", "test-api-key-123")
        headers = {"X-API-KEY": api_key}
        user_state_response = requests.get(f"{base_url}/test/user_state/{username}", headers=headers)
        assert user_state_response.status_code == 200, f"Failed to get user state: {user_state_response.status_code}"
        user_state = user_state_response.json()
        annotations = user_state.get("annotations", {}).get("by_instance", {})
        assert len(annotations) > 0, "No annotations found in backend verification"

        # Check if annotations exist for the instance
        assert "annotations" in user_state, "User state should contain annotations"
        assert str(instance_id) in user_state["annotations"], f"Annotations should exist for instance {instance_id}"

        return user_state["annotations"][str(instance_id)]

    def test_multirate_annotation(self, test_data):
        """Test multirate annotation with multiple rating scales."""
        # Create temporary config directory
        config_dir = tempfile.mkdtemp()

        # Multirate annotation config
        config = {
            "port": 9008,
            "server_name": "potato multirate annotation test",
            "annotation_task_name": "Multirate Annotation Test",
            "debug": True,
            "test_data": test_data,
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "annotation_type": "multirate",
                    "name": "quality_ratings",
                    "description": "Rate the following aspects of this text:",
                    "labels": [
                        {
                            "name": "readability",
                            "description": "How easy is this text to read?"
                        },
                        {
                            "name": "clarity",
                            "description": "How clear is the message?"
                        },
                        {
                            "name": "accuracy",
                            "description": "How accurate is the information?"
                        }
                    ],
                    "rating_scale": {
                        "min": 1,
                        "max": 5,
                        "labels": ["Very Poor", "Poor", "Average", "Good", "Excellent"]
                    }
                }
            ]
        }

        # Create config file
        config_file = self.create_test_config_file(config, config_dir)

        server = FlaskTestServer(port=config['port'], debug=config['debug'], config_file=config_file)
        with server.server_context():
            # Create WebDriver with headless mode
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            driver = webdriver.Chrome(options=chrome_options)
            try:
                username = f"test_user_multirate_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify Next button is disabled initially
                self.verify_next_button_state(driver, expected_disabled=True)

                # Rate each aspect
                # Find all rating inputs for the multirate scheme
                rating_inputs = driver.find_elements(By.CSS_SELECTOR, "input[name*='quality_ratings']")

                # Rate readability (first rating)
                if len(rating_inputs) >= 1:
                    rating_inputs[0].send_keys("4")  # Good

                # Rate clarity (second rating)
                if len(rating_inputs) >= 2:
                    rating_inputs[1].send_keys("5")  # Excellent

                # Rate accuracy (third rating)
                if len(rating_inputs) >= 3:
                    rating_inputs[2].send_keys("3")  # Average

                # Verify Next button is enabled
                self.verify_next_button_state(driver, expected_disabled=False)

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "quality_ratings" in annotations, "Quality ratings annotation should be stored"

                # Verify all three ratings are present
                quality_ratings = annotations["quality_ratings"]
                assert "readability" in quality_ratings, "Readability rating should be stored"
                assert "clarity" in quality_ratings, "Clarity rating should be stored"
                assert "accuracy" in quality_ratings, "Accuracy rating should be stored"

                # Verify rating values
                assert quality_ratings["readability"] == "4", "Readability should be rated 4"
                assert quality_ratings["clarity"] == "5", "Clarity should be rated 5"
                assert quality_ratings["accuracy"] == "3", "Accuracy should be rated 3"

            finally:
                driver.quit()

    def test_multirate_with_required_fields(self, test_data):
        """Test multirate annotation with required fields."""
        # Create temporary config directory
        config_dir = tempfile.mkdtemp()

        # Multirate annotation config with required fields
        config = {
            "port": 9009,
            "server_name": "potato multirate required test",
            "annotation_task_name": "Multirate Required Test",
            "debug": True,
            "test_data": test_data,
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "annotation_type": "multirate",
                    "name": "evaluation",
                    "description": "Evaluate this text on the following criteria:",
                    "labels": [
                        {
                            "name": "relevance",
                            "description": "How relevant is this text to the topic?"
                        },
                        {
                            "name": "completeness",
                            "description": "How complete is the information provided?"
                        }
                    ],
                    "rating_scale": {
                        "min": 1,
                        "max": 7,
                        "labels": ["Not at all", "Very Low", "Low", "Neutral", "High", "Very High", "Extremely"]
                    },
                    "label_requirement": {
                        "required": True
                    }
                }
            ]
        }

        # Create config file
        config_file = self.create_test_config_file(config, config_dir)

        server = FlaskTestServer(port=config['port'], debug=config['debug'], config_file=config_file)
        with server.server_context():
            # Create WebDriver with headless mode
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            driver = webdriver.Chrome(options=chrome_options)
            try:
                username = f"test_user_multirate_required_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify Next button is disabled initially (all fields required)
                self.verify_next_button_state(driver, expected_disabled=True)

                # Fill only one rating - Next button should still be disabled
                rating_inputs = driver.find_elements(By.CSS_SELECTOR, "input[name*='evaluation']")
                if len(rating_inputs) >= 1:
                    rating_inputs[0].send_keys("6")  # Very High

                # Verify Next button is still disabled (second field required)
                self.verify_next_button_state(driver, expected_disabled=True)

                # Fill the second rating
                if len(rating_inputs) >= 2:
                    rating_inputs[1].send_keys("5")  # High

                # Verify Next button is now enabled
                self.verify_next_button_state(driver, expected_disabled=False)

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "evaluation" in annotations, "Evaluation annotation should be stored"

                # Verify both ratings are present
                evaluation = annotations["evaluation"]
                assert "relevance" in evaluation, "Relevance rating should be stored"
                assert "completeness" in evaluation, "Completeness rating should be stored"

            finally:
                driver.quit()