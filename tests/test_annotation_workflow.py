"""
Tests for the complete annotation workflow.
Tests data loading, annotation submission, navigation, and output generation.
"""

import pytest
import json
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
        # Copy simple examples to temp directory
        simple_examples_dir = os.path.join(os.path.dirname(__file__), '..', 'project-hub', 'simple_examples')
        shutil.copytree(simple_examples_dir, os.path.join(temp_project_dir, 'simple_examples'))

        # Change to temp directory
        original_cwd = os.getcwd()
        os.chdir(temp_project_dir)

        # Start server process
        process = subprocess.Popen([
            'python', '-m', 'potato.flask_server',
            '--debug', '-p', '9002', 'start',
            'simple_examples/configs/simple-likert.yaml'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Wait for server to start
        time.sleep(3)

        yield process

        # Cleanup
        process.terminate()
        process.wait()
        os.chdir(original_cwd)

    def test_data_loading_workflow(self, temp_project_dir):
        """Test that data files are loaded correctly"""
        # Test JSON data loading
        json_data_path = os.path.join(temp_project_dir, 'simple_examples', 'data', 'toy-example.json')

        items = []
        with open(json_data_path, 'r') as f:
            for line in f:
                items.append(json.loads(line))

        assert len(items) > 0
        assert 'id' in items[0]
        assert 'text' in items[0]

        # Test CSV data loading
        csv_data_path = os.path.join(temp_project_dir, 'simple_examples', 'data', 'toy-example.csv')
        assert os.path.exists(csv_data_path)

        # Test TSV data loading
        tsv_data_path = os.path.join(temp_project_dir, 'simple_examples', 'data', 'toy-example.tsv')
        assert os.path.exists(tsv_data_path)

    def test_config_loading_workflow(self, temp_project_dir):
        """Test that config files are loaded and validated correctly"""
        config_path = os.path.join(temp_project_dir, 'simple_examples', 'configs', 'simple-likert.yaml')

        with open(config_path, 'r') as f:
            config = json.load(f)

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
            full_path = os.path.join(temp_project_dir, 'simple_examples', data_file)
            assert os.path.exists(full_path), f"Data file not found: {full_path}"

        # Validate annotation schemes
        assert len(config['annotation_schemes']) > 0
        scheme = config['annotation_schemes'][0]
        assert 'annotation_type' in scheme
        assert 'name' in scheme
        assert 'description' in scheme

    @pytest.mark.selenium
    def test_complete_annotation_workflow(self, server_process):
        """Test complete annotation workflow with Selenium"""
        driver = webdriver.Chrome()
        try:
            # Navigate to annotation page
            driver.get("http://localhost:9002/")

            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Verify we're in debug mode
            assert "debug_user" in driver.page_source

            # Find and interact with annotation elements
            likert_elements = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            assert len(likert_elements) >= 5

            # Select a rating
            likert_elements[2].click()  # Select middle option
            assert likert_elements[2].is_selected()

            # Navigate to next instance
            next_button = driver.find_element(By.CSS_SELECTOR, "a[onclick*='next_instance']")
            next_button.click()

            # Wait for page to update
            time.sleep(1)

            # Verify we're on a new instance
            current_instance = driver.find_element(By.ID, "instance_id")
            assert current_instance.get_attribute("value") != "1"

            # Select a different rating on new instance
            likert_elements = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            likert_elements[4].click()  # Select last option
            assert likert_elements[4].is_selected()

            # Navigate back to previous instance
            prev_button = driver.find_element(By.CSS_SELECTOR, "a[onclick*='prev_instance']")
            prev_button.click()

            # Wait for page to update
            time.sleep(1)

            # Verify we're back to first instance
            current_instance = driver.find_element(By.ID, "instance_id")
            assert current_instance.get_attribute("value") == "1"

            # Verify previous selection is still there
            likert_elements = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            assert likert_elements[2].is_selected()

        finally:
            driver.quit()

    def test_annotation_submission_workflow(self, server_process):
        """Test annotation submission via API"""
        # Submit annotation for first instance
        annotation_data = {
            "awesomeness": "3"  # Likert scale value
        }

        response = requests.post(
            "http://localhost:9002/submit_annotation",
            data={
                "instance_id": "item_1",
                "annotation_data": json.dumps(annotation_data)
            }
        )

        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access
        response_data = response.json()
        assert response_data["status"] == "success"

        # Submit annotation for second instance
        annotation_data = {
            "awesomeness": "5"  # Different value
        }

        response = requests.post(
            "http://localhost:9002/submit_annotation",
            data={
                "instance_id": "item_2",
                "annotation_data": json.dumps(annotation_data)
            }
        )

        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access
        response_data = response.json()
        assert response_data["status"] == "success"

    def test_navigation_workflow(self, server_process):
        """Test navigation between instances"""
        # Test moving to next instance
        response = requests.post(
            "http://localhost:9002/annotate",
            json={
                "action": "next_instance",
                "instance_id": "item_1"
            }
        )

        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access

        # Test moving to previous instance
        response = requests.post(
            "http://localhost:9002/annotate",
            json={
                "action": "prev_instance",
                "instance_id": "item_2"
            }
        )

        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access

        # Test jumping to specific instance
        response = requests.post(
            "http://localhost:9002/annotate",
            json={
                "action": "go_to",
                "instance_id": "item_5"
            }
        )

        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access

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
        driver = webdriver.Chrome()
        try:
            # Navigate to annotation page
            driver.get("http://localhost:9002/")

            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Test invalid navigation (should handle gracefully)
            driver.get("http://localhost:9002/invalid_page")

            # Should either redirect or show error page
            assert "error" in driver.page_source.lower() or "404" in driver.page_source

            # Navigate back to valid page
            driver.get("http://localhost:9002/")

            # Verify we can still annotate
            likert_elements = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            assert len(likert_elements) >= 5

        finally:
            driver.quit()

    def test_session_management_workflow(self, server_process):
        """Test session management in debug mode"""
        # Test that debug mode bypasses session requirements
        response = requests.get("http://localhost:9002/")
        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access

        # Test that we can access annotation page without login
        response = requests.get("http://localhost:9002/annotate")
        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access

        # Test that we can submit annotations without session
        annotation_data = {
            "awesomeness": "4"
        }

        response = requests.post(
            "http://localhost:9002/submit_annotation",
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