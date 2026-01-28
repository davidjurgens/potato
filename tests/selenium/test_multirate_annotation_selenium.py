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
from tests.helpers.flask_test_setup import FlaskTestServer
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
            "user_config": {
                "allow_all_users": True
            },
            "data_files": [data_file],  # Use absolute path to the data file
            "item_properties": config.get('item_properties', {"text_key": "text", "id_key": "id"}),
            "annotation_schemes": config.get('annotation_schemes', []),
            "site_file": "base_template.html",
            "output_annotation_dir": os.path.join(config_dir, "output"),
            "task_dir": config_dir,  # Set task_dir to config_dir so data files are found
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
        # Use FlaskTestServer's .get() method for admin endpoints
        from tests.helpers.flask_test_setup import FlaskTestServer
        # Assume self.server is available or pass it as an argument if needed
        # If not, fallback to requests.get with API key
        try:
            user_state_response = self.server.get(f"/admin/user_state/{username}")
        except AttributeError:
            import requests
            user_state_response = requests.get(f"{base_url}/admin/user_state/{username}", headers={'X-API-Key': 'admin_api_key'})
        assert user_state_response.status_code == 200, f"Failed to get user state: {user_state_response.status_code}"
        user_state = user_state_response.json()
        annotations = user_state.get("annotations", {}).get("by_instance", {})
        assert len(annotations) > 0, "No annotations found in backend verification"

        # Check if annotations exist for the instance
        assert "annotations" in user_state, "User state should contain annotations"
        assert str(instance_id) in user_state["annotations"]["by_instance"], f"Annotations should exist for instance {instance_id}"

        # The backend returns annotation keys in format "schema:label" (e.g., "quality_ratings:readability")
        # So we need to check if any key starts with the schema name
        instance_annotations = user_state["annotations"]["by_instance"][str(instance_id)]
        print(f"   Instance {instance_id} annotations: {instance_annotations}")

        return instance_annotations

    @pytest.mark.skip(reason="Covered by test_all_annotation_types_selenium.py::test_multirate_annotation and unit tests")
    def test_multirate_annotation(self, test_data):
        """Test multirate annotation with multiple rating scales.

        Critical test: Verify that each row in multirate has independent radio groups,
        so selecting a rating for one option doesn't deselect ratings for other options.
        """
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
                    "options": ["readability", "clarity", "accuracy"],
                    "labels": ["Very Poor", "Poor", "Average", "Good", "Excellent"],
                    "label_requirement": {"required": True}
                }
            ]
        }

        # Create config file
        config_file = self.create_test_config_file(config, config_dir)

        server = FlaskTestServer(port=config['port'], debug=False, config_file=config_file)
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
                base_url = f"http://localhost:{config['port']}"

                # Navigate to annotation page with user param
                driver.get(f"{base_url}/?PROLIFIC_PID=test_user")

                # Wait for annotation interface to load
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "form.multirate, input[type='radio']"))
                )
                time.sleep(0.5)  # Allow any JS to finish

                # Find radio inputs for each option (row)
                # Each option should have its own radio group with a unique name
                readability_radios = driver.find_elements(By.CSS_SELECTOR, "input[name*='readability']")
                clarity_radios = driver.find_elements(By.CSS_SELECTOR, "input[name*='clarity']")
                accuracy_radios = driver.find_elements(By.CSS_SELECTOR, "input[name*='accuracy']")

                print(f"Found {len(readability_radios)} readability radios")
                print(f"Found {len(clarity_radios)} clarity radios")
                print(f"Found {len(accuracy_radios)} accuracy radios")

                # Each option should have 5 radio buttons (one for each label)
                assert len(readability_radios) == 5, f"Readability should have 5 radio buttons, got {len(readability_radios)}"
                assert len(clarity_radios) == 5, f"Clarity should have 5 radio buttons, got {len(clarity_radios)}"
                assert len(accuracy_radios) == 5, f"Accuracy should have 5 radio buttons, got {len(accuracy_radios)}"

                # Select different ratings for each option
                readability_radios[3].click()  # "Good" (4th option, 0-indexed)
                time.sleep(0.2)
                clarity_radios[4].click()      # "Excellent" (5th option)
                time.sleep(0.2)
                accuracy_radios[2].click()     # "Average" (3rd option)
                time.sleep(0.2)

                # CRITICAL: Verify all three selections are still active
                # This is the key test - if radio groups weren't unique, only one would be selected
                assert readability_radios[3].is_selected(), "Readability 'Good' should still be selected after selecting other options"
                assert clarity_radios[4].is_selected(), "Clarity 'Excellent' should still be selected after selecting other options"
                assert accuracy_radios[2].is_selected(), "Accuracy 'Average' should still be selected after selecting other options"

                print("SUCCESS: All three multirate selections are independent!")

            finally:
                driver.quit()

    @pytest.mark.skip(reason="Covered by test_all_annotation_types_selenium.py::test_multirate_annotation and unit tests")
    def test_multirate_with_required_fields(self, test_data):
        """Test multirate annotation verifies each row has independent selections."""
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
                    "options": ["relevance", "completeness"],
                    "labels": ["Not at all", "Very Low", "Low", "Neutral", "High", "Very High", "Extremely"],
                    "label_requirement": {
                        "required": True
                    }
                }
            ]
        }

        # Create config file
        config_file = self.create_test_config_file(config, config_dir)

        server = FlaskTestServer(port=config['port'], debug=False, config_file=config_file)
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
                base_url = f"http://localhost:{config['port']}"

                # Navigate to annotation page with user param
                driver.get(f"{base_url}/?PROLIFIC_PID=test_user")

                # Wait for annotation interface to load
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "form.multirate, input[type='radio']"))
                )
                time.sleep(0.5)  # Allow any JS to finish

                # Find radio inputs for each option (row)
                relevance_radios = driver.find_elements(By.CSS_SELECTOR, "input[name*='relevance']")
                completeness_radios = driver.find_elements(By.CSS_SELECTOR, "input[name*='completeness']")

                print(f"Found {len(relevance_radios)} relevance radios")
                print(f"Found {len(completeness_radios)} completeness radios")

                # Each option should have 7 radio buttons (one for each label)
                assert len(relevance_radios) == 7, f"Relevance should have 7 radio buttons, got {len(relevance_radios)}"
                assert len(completeness_radios) == 7, f"Completeness should have 7 radio buttons, got {len(completeness_radios)}"

                # Select different ratings for each option
                relevance_radios[5].click()     # "Very High" (6th option, 0-indexed)
                time.sleep(0.2)
                completeness_radios[4].click()  # "High" (5th option)
                time.sleep(0.2)

                # CRITICAL: Verify both selections are still active
                assert relevance_radios[5].is_selected(), "Relevance 'Very High' should still be selected"
                assert completeness_radios[4].is_selected(), "Completeness 'High' should still be selected"

                print("SUCCESS: Both multirate selections are independent!")

            finally:
                driver.quit()