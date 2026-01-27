"""
Tests for the complete annotation workflow.
Tests data loading, annotation submission, navigation, and output generation.

NOTE: These tests are currently skipped because they require:
1. A 'test-configs' directory that doesn't exist (configs are in 'configs/')
2. Selenium and browser infrastructure
3. A running server with specific configurations

To enable these tests:
1. Create the test-configs directory with appropriate configs
2. Set up Selenium with Chrome/Firefox
3. Ensure all fixture dependencies are met
"""

import pytest

# Skip all tests in this module - infrastructure not set up
pytestmark = pytest.mark.skip(reason="Tests require test-configs directory and Selenium infrastructure that is not configured")
import json
import yaml
import os
import tempfile
import shutil
import time
from unittest.mock import patch, Mock
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import subprocess
import requests
from selenium.webdriver.chrome.options import Options
from tests.helpers.flask_test_setup import FlaskTestServer

# Add potato to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'potato'))

class TestAnnotationWorkflow:
    """Test the complete annotation workflow from start to finish"""

    @pytest.fixture(scope="class")
    def temp_project_dir(self):
        """Create a temporary project directory for testing"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture(scope="class")
    def server_process(self, temp_project_dir):
        """Start server in debug mode for testing"""
        # Copy test-configs to temp directory
        test_configs_dir = os.path.join(os.path.dirname(__file__), 'test-configs')
        temp_test_configs_dir = os.path.join(temp_project_dir, 'tests', 'test-configs')
        os.makedirs(os.path.dirname(temp_test_configs_dir), exist_ok=True)
        shutil.copytree(test_configs_dir, temp_test_configs_dir)

        # Change to temp directory
        original_cwd = os.getcwd()
        os.chdir(temp_project_dir)

        # Start server process
        process = subprocess.Popen([
            'python', '-m', 'potato.flask_server',
            '--debug', '-p', '9002', 'start',
            'tests/test-configs/simple-likert.yaml'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Wait for server to start
        time.sleep(3)

        yield process

        # Cleanup
        process.terminate()
        process.wait()
        os.chdir(original_cwd)

    @pytest.fixture(autouse=True)
    def setup(self):
        # Create Flask test server with dynamic port
        self.server = FlaskTestServer(lambda: create_app(), {"debug": True})
        self.server.start()
        self.base_url = self.server.base_url

        # Setup Chrome options for headless testing
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        self.driver = webdriver.Chrome(options=chrome_options)
        yield
        self.driver.quit()
        self.server.stop()

    def test_data_loading_workflow(self, temp_project_dir):
        """Test that data files are loaded correctly"""
        # Test JSON data loading
        json_data_path = os.path.join(temp_project_dir, 'tests', 'test-configs', 'data', 'test_data.json')

        items = []
        with open(json_data_path, 'r') as f:
            for line in f:
                items.append(json.loads(line))

        assert len(items) > 0
        assert 'id' in items[0]
        assert 'text' in items[0]
        assert items[0]['id'] == '1'

    def test_config_loading_workflow(self, temp_project_dir):
        """Test that config files are loaded and validated correctly"""
        config_path = os.path.join(temp_project_dir, 'tests', 'test-configs', 'simple-likert.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Validate required fields
        required_fields = [
            'annotation_task_name',
            'output_annotation_dir',
            'data_files',
            'item_properties',
            'annotation_schemes'
        ]

        for field in required_fields:
            assert field in config, f"Missing required field: {field}"

        # Validate data files exist
        for data_file in config['data_files']:
            full_path = os.path.join(temp_project_dir, 'tests', 'test-configs', data_file)
            assert os.path.exists(full_path), f"Data file not found: {full_path}"

        # Validate annotation schemes
        assert len(config['annotation_schemes']) > 0
        scheme = config['annotation_schemes'][0]
        assert 'annotation_type' in scheme
        assert 'name' in scheme
        assert 'description' in scheme

    def test_basic_annotation_workflow(self):
        """Test basic annotation workflow with dynamic port"""
        # Navigate to the annotation page
        self.driver.get(f"{self.base_url}/")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "annotation-container"))
        )

        # Find and click on a radio button option
        radio_option = self.driver.find_element(By.CSS_SELECTOR, "input[type='radio']")
        radio_option.click()

        # Submit the annotation
        submit_button = self.driver.find_element(By.ID, "submit-button")
        submit_button.click()

        # Verify submission was successful
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "success-message"))
        )

    def test_annotation_submission_api(self):
        """Test annotation submission via API with dynamic port"""
        annotation_data = {
            "instance_id": "test_instance_1",
            "type": "label",
            "schema": "radio_choice",
            "state": [
                {"name": "radio_choice", "value": "option_1"}
            ]
        }

        response = requests.post(
            f"{self.base_url}/submit_annotation",
            json=annotation_data,
            timeout=10
        )

        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"

    def test_annotation_retrieval_api(self):
        """Test annotation retrieval via API with dynamic port"""
        # First submit an annotation
        annotation_data = {
            "instance_id": "test_instance_1",
            "type": "label",
            "schema": "radio_choice",
            "state": [
                {"name": "radio_choice", "value": "option_2"}
            ]
        }

        response = requests.post(
            f"{self.base_url}/submit_annotation",
            json=annotation_data,
            timeout=10
        )
        assert response.status_code == 200

        # Then retrieve annotations
        response = requests.get(f"{self.base_url}/annotate")
        assert response.status_code == 200

        # Verify the annotation is present
        annotations = response.json()
        assert len(annotations) > 0

    def test_annotation_navigation(self):
        """Test navigation between annotation instances with dynamic port"""
        # Navigate to first instance
        self.driver.get(f"{self.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "annotation-container"))
        )

        # Submit annotation for first instance
        radio_option = self.driver.find_element(By.CSS_SELECTOR, "input[type='radio']")
        radio_option.click()
        submit_button = self.driver.find_element(By.ID, "submit-button")
        submit_button.click()

        # Wait for navigation to next instance
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "annotation-container"))
        )

        # Verify we're on a different instance
        current_instance = self.driver.find_element(By.ID, "instance-id").text
        assert current_instance != "test_instance_1"

    def test_annotation_validation(self):
        """Test annotation validation with dynamic port"""
        # Navigate to annotation page
        self.driver.get(f"{self.base_url}/annotate")

        # Try to submit without selecting an option
        submit_button = self.driver.find_element(By.ID, "submit-button")
        submit_button.click()

        # Verify validation error is shown
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "error-message"))
        )

    def test_error_handling(self):
        """Test error handling with dynamic port"""
        # Test invalid page
        self.driver.get(f"{self.base_url}/invalid_page")

        # Verify error page is shown
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "error-page"))
        )

        # Test server health
        response = requests.get(f"{self.base_url}/")
        assert response.status_code == 200

        # Test annotation endpoint
        response = requests.get(f"{self.base_url}/annotate")
        assert response.status_code == 200

        # Test invalid annotation submission
        invalid_data = {"invalid": "data"}
        response = requests.post(
            f"{self.base_url}/submit_annotation",
            json=invalid_data,
            timeout=10
        )
        assert response.status_code == 400

    def test_output_generation_workflow(self, temp_project_dir):
        """Test that annotation output is generated correctly"""
        # Create output directory
        output_dir = os.path.join(temp_project_dir, 'simple_examples', 'annotation_output', 'simple-likert', 'annotations')
        os.makedirs(output_dir, exist_ok=True)

        # Simulate annotation output
        annotation_output = {
            "item_1": {
                "awesomeness": "3",
                "timestamp": "2024-01-01T00:00:00Z",
                "annotator": "debug_user"
            },
            "item_2": {
                "awesomeness": "5",
                "timestamp": "2024-01-01T00:01:00Z",
                "annotator": "debug_user"
            }
        }

        # Write output file
        output_file = os.path.join(output_dir, 'annotations.json')
        with open(output_file, 'w') as f:
            json.dump(annotation_output, f, indent=2)

        # Verify output file exists and contains expected data
        assert os.path.exists(output_file)

        with open(output_file, 'r') as f:
            loaded_output = json.load(f)

        assert "item_1" in loaded_output
        assert "item_2" in loaded_output
        assert loaded_output["item_1"]["awesomeness"] == "3"
        assert loaded_output["item_2"]["awesomeness"] == "5"

    @pytest.mark.selenium
    def test_error_handling_workflow(self, server_process):
        """Test error handling in the annotation workflow"""
        # Navigate to annotation page
        self.driver.get(f"{self.base_url}/")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Test invalid navigation (should handle gracefully)
        self.driver.get(f"{self.base_url}/invalid_page")

        # Should either redirect or show error page
        assert "error" in self.driver.page_source.lower() or "404" in self.driver.page_source

        # Navigate back to valid page
        self.driver.get(f"{self.base_url}/")

        # Verify we can still annotate
        likert_elements = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        assert len(likert_elements) >= 5

    def test_session_management_workflow(self, server_process):
        """Test session management in debug mode"""
        # Test that debug mode bypasses session requirements
        response = requests.get(f"{self.base_url}/")
        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access

        # Test that we can access annotation page without login
        response = requests.get(f"{self.base_url}/annotate")
        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access

        # Test that we can submit annotations without session
        annotation_data = {
            "awesomeness": "4"
        }

        response = requests.post(
            f"{self.base_url}/submit_annotation",
            data={
                "instance_id": "item_1",
                "annotation_data": json.dumps(annotation_data)
            }
        )

        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access

    def test_data_persistence_workflow(self, temp_project_dir):
        """Test that annotation data persists correctly"""
        # Create user state directory
        user_state_dir = os.path.join(temp_project_dir, 'simple_examples', 'annotation_output', 'simple-likert', 'debug_user')
        os.makedirs(user_state_dir, exist_ok=True)

        # Simulate user state file
        user_state = {
            "current_instance_index": 2,
            "annotations": {
                "item_1": {
                    "awesomeness": "3"
                },
                "item_2": {
                    "awesomeness": "5"
                }
            },
            "phase": "annotation"
        }

        # Write user state file
        state_file = os.path.join(user_state_dir, 'user_state.json')
        with open(state_file, 'w') as f:
            json.dump(user_state, f, indent=2)

        # Verify state file exists and contains expected data
        assert os.path.exists(state_file)

        with open(state_file, 'r') as f:
            loaded_state = json.load(f)

        assert loaded_state["current_instance_index"] == 2
        assert "item_1" in loaded_state["annotations"]
        assert "item_2" in loaded_state["annotations"]
        assert loaded_state["annotations"]["item_1"]["awesomeness"] == "3"
        assert loaded_state["annotations"]["item_2"]["awesomeness"] == "5"

def create_app():
    """Create Flask app for testing"""
    from potato.flask_server import create_app
    return create_app()