"""
Tests for different annotation types using the simple examples configs.
Tests both backend functionality and frontend rendering for each annotation type.

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
from unittest.mock import patch, Mock
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import threading
import subprocess
import requests
from selenium.webdriver.chrome.options import Options
from tests.helpers.flask_test_setup import FlaskTestServer

# Add potato to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'potato'))

class TestAnnotationTypes:
    """Test different annotation types with their respective configs"""

    @pytest.fixture(scope="class")
    def temp_project_dir(self):
        """Create a temporary project directory for testing"""
        temp_dir = tempfile.mkdtemp()

        # Copy test-configs to temp directory
        test_configs_dir = os.path.join(os.path.dirname(__file__), 'test-configs')
        temp_test_configs_dir = os.path.join(temp_dir, 'tests', 'test-configs')
        os.makedirs(os.path.dirname(temp_test_configs_dir), exist_ok=True)
        shutil.copytree(test_configs_dir, temp_test_configs_dir, dirs_exist_ok=True)

        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture(scope="class")
    def server_process(self, temp_project_dir):
        """Start server in debug mode for testing"""
        # Copy test-configs to temp directory
        test_configs_dir = os.path.join(os.path.dirname(__file__), 'test-configs')
        temp_test_configs_dir = os.path.join(temp_project_dir, 'tests', 'test-configs')
        os.makedirs(os.path.dirname(temp_test_configs_dir), exist_ok=True)
        shutil.copytree(test_configs_dir, temp_test_configs_dir, dirs_exist_ok=True)

        # Change to temp directory
        original_cwd = os.getcwd()
        os.chdir(temp_project_dir)

        # Start server process
        process = subprocess.Popen([
            'python', '-m', 'potato.flask_server',
            '--debug', '-p', '9001', 'start',
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

    def test_likert_annotation(self):
        """Test Likert scale annotation with dynamic port"""
        # Navigate to annotation page
        self.driver.get(f"{self.base_url}/")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='radio']"))
        )

        # Find Likert scale options
        likert_options = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        assert len(likert_options) >= 5

        # Select a rating
        likert_options[2].click()  # Select middle option
        assert likert_options[2].is_selected()

        # Submit annotation
        submit_button = self.driver.find_element(By.ID, "submit-button")
        submit_button.click()

        # Verify submission
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "success-message"))
        )

    def test_slider_annotation(self):
        """Test slider annotation with dynamic port"""
        # Navigate to annotation page
        self.driver.get(f"{self.base_url}/")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='range']"))
        )

        # Find slider element
        slider = self.driver.find_element(By.CSS_SELECTOR, "input[type='range']")

        # Set slider value
        self.driver.execute_script("arguments[0].value = '75';", slider)

        # Submit annotation
        submit_button = self.driver.find_element(By.ID, "submit-button")
        submit_button.click()

        # Verify submission
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "success-message"))
        )

    def test_text_annotation(self):
        """Test text annotation with dynamic port"""
        # Navigate to annotation page
        self.driver.get(f"{self.base_url}/")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "textarea"))
        )

        # Find text area
        text_area = self.driver.find_element(By.CSS_SELECTOR, "textarea")

        # Enter text
        text_area.send_keys("This is a test annotation")

        # Submit annotation
        submit_button = self.driver.find_element(By.ID, "submit-button")
        submit_button.click()

        # Verify submission
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "success-message"))
        )

    def test_annotation_submission_api(self):
        """Test annotation submission via API with dynamic port"""
        # Test Likert annotation submission
        annotation_data = {
            "instance_id": "test_instance_1",
            "type": "label",
            "schema": "likert_scale",
            "state": [
                {"name": "likert_rating", "value": "3"}
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

    def test_annotation_retrieval(self):
        """Test annotation retrieval with dynamic port"""
        # Navigate to annotation page
        self.driver.get(f"{self.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "annotation-container"))
        )

        # Verify annotation interface is present
        assert self.driver.find_element(By.ID, "annotation-container").is_displayed()

    def test_annotation_navigation(self):
        """Test navigation between annotation instances with dynamic port"""
        # Navigate to annotation page
        self.driver.get(f"{self.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "annotation-container"))
        )

        # Submit annotation for current instance
        submit_button = self.driver.find_element(By.ID, "submit-button")
        submit_button.click()

        # Wait for navigation to next instance
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "annotation-container"))
        )

        # Verify we're on a new instance
        current_instance = self.driver.find_element(By.ID, "instance-id").text
        assert current_instance != "test_instance_1"

    def test_likert_annotation_backend(self, temp_project_dir):
        """Test likert annotation backend functionality"""
        config_path = os.path.join(temp_project_dir, 'tests', 'test-configs', 'simple-likert.yaml')

        # Test config loading
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert config['annotation_task_name'] == 'Simple Likert Scale Test'
        assert config['annotation_schemes'][0]['annotation_type'] == 'likert'
        assert config['annotation_schemes'][0]['size'] == 5

        # Test data loading
        data_path = os.path.join(temp_project_dir, 'tests', 'test-configs', 'data', 'test_data.json')
        assert os.path.exists(data_path)

        # Test output directory creation
        output_dir = os.path.join(temp_project_dir, 'tests', 'test-configs', config['output_annotation_dir'])
        os.makedirs(output_dir, exist_ok=True)
        assert os.path.exists(output_dir)

    def test_checkbox_annotation_backend(self, temp_project_dir):
        """Test checkbox (multiselect) annotation backend functionality"""
        config_path = os.path.join(temp_project_dir, 'tests', 'test-configs', 'simple-check-box.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert config['annotation_task_name'] == 'Simple Check Box Test'
        assert config['annotation_schemes'][0]['annotation_type'] == 'multiselect'
        assert 'blue' in config['annotation_schemes'][0]['labels']
        assert 'maize' in config['annotation_schemes'][0]['labels']

    def test_slider_annotation_backend(self, temp_project_dir):
        """Test slider annotation backend functionality"""
        config_path = os.path.join(temp_project_dir, 'tests', 'test-configs', 'simple-slider.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert config['annotation_task_name'] == 'Simple Slider Test'
        assert config['annotation_schemes'][0]['annotation_type'] == 'slider'
        assert config['annotation_schemes'][0]['min_value'] == 0
        assert config['annotation_schemes'][0]['max_value'] == 100
        assert config['annotation_schemes'][0]['starting_value'] == 50

    def test_span_annotation_backend(self, temp_project_dir):
        """Test span annotation backend functionality"""
        config_path = os.path.join(temp_project_dir, 'tests', 'test-configs', 'simple-span-labeling.yaml')

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        assert config['annotation_task_name'] == 'Simple Span Labeling Test'
        assert config['annotation_schemes'][0]['annotation_type'] == 'span'
        assert 'certain' in config['annotation_schemes'][0]['labels']
        assert 'uncertain' in config['annotation_schemes'][0]['labels']

    @pytest.mark.selenium
    def test_likert_annotation_frontend(self, server_process):
        """Test likert annotation frontend with Selenium"""
        driver = webdriver.Chrome()
        try:
            driver.get("http://localhost:9001/")

            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Check that we're in debug mode
            assert "debug_user" in driver.page_source

            # Check for likert scale elements
            likert_elements = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            assert len(likert_elements) >= 5  # Should have 5 scale points

            # Check for scale labels
            assert "Very Negative" in driver.page_source
            assert "Very Positive" in driver.page_source

            # Test selecting a scale point
            likert_elements[2].click()  # Select middle option
            assert likert_elements[2].is_selected()

        finally:
            driver.quit()

    @pytest.mark.selenium
    def test_checkbox_annotation_frontend(self, server_process):
        """Test checkbox annotation frontend with Selenium"""
        # Start server with checkbox config
        config_path = 'tests/test-configs/simple-check-box.yaml'

        driver = webdriver.Chrome()
        try:
            driver.get("http://localhost:9001/")

            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Check for checkbox elements
            checkbox_elements = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            assert len(checkbox_elements) >= 4  # Should have 4 color options

            # Check for color labels
            assert "blue" in driver.page_source
            assert "maize" in driver.page_source
            assert "green" in driver.page_source
            assert "white" in driver.page_source

            # Test selecting checkboxes
            checkbox_elements[0].click()  # Select first checkbox
            assert checkbox_elements[0].is_selected()

            checkbox_elements[1].click()  # Select second checkbox
            assert checkbox_elements[1].is_selected()

        finally:
            driver.quit()

    @pytest.mark.selenium
    def test_slider_annotation_frontend(self, server_process):
        """Test slider annotation frontend with Selenium"""
        driver = webdriver.Chrome()
        try:
            driver.get("http://localhost:9001/")

            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Check for slider element
            slider_elements = driver.find_elements(By.CSS_SELECTOR, "input[type='range']")
            assert len(slider_elements) >= 1

            # Check slider attributes
            slider = slider_elements[0]
            assert slider.get_attribute("min") == "0"
            assert slider.get_attribute("max") == "100"
            assert slider.get_attribute("value") == "50"  # Starting value

            # Test moving slider
            driver.execute_script("arguments[0].value = '75'; arguments[0].dispatchEvent(new Event('input'));", slider)
            assert slider.get_attribute("value") == "75"

        finally:
            driver.quit()

    @pytest.mark.selenium
    def test_span_annotation_frontend(self, server_process):
        """Test span annotation frontend with Selenium"""
        driver = webdriver.Chrome()
        try:
            driver.get("http://localhost:9001/")

            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Check for span annotation elements
            assert "Highlight which phrases" in driver.page_source
            assert "certain" in driver.page_source
            assert "uncertain" in driver.page_source

            # Check for text content to annotate
            text_elements = driver.find_elements(By.CSS_SELECTOR, ".instance")
            assert len(text_elements) > 0

            # Check for annotation controls
            radio_elements = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            assert len(radio_elements) >= 2  # Should have at least 2 label options

        finally:
            driver.quit()

    def test_annotation_submission_api(self, server_process):
        """Test annotation submission via API"""
        # Test submitting annotation data
        annotation_data = {
            "awesomeness": "3"  # Likert scale value
        }

        response = requests.post(
            "http://localhost:9001/submit_annotation",
            data={
                "instance_id": "item_1",
                "annotation_data": json.dumps(annotation_data)
            }
        )

        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access
        response_data = response.json()
        assert response_data["status"] == "success"

    def test_navigation_api(self, server_process):
        """Test navigation between instances"""
        # Test moving to next instance
        response = requests.post(
            "http://localhost:9001/annotate",
            json={
                "action": "next_instance",
                "instance_id": "item_1"
            }
        )

        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access

        # Test moving to previous instance
        response = requests.post(
            "http://localhost:9001/annotate",
            json={
                "action": "prev_instance",
                "instance_id": "item_2"
            }
        )

        assert response.status_code in [200, 302]  # 302 is redirect to login, 200 is direct access

    def test_instance_data_loading(self, temp_project_dir):
        """Test that instance data loads correctly for different formats"""
        # Test JSON format
        json_data_path = os.path.join(temp_project_dir, 'tests', 'test-configs', 'data', 'test_data.json')
        with open(json_data_path, 'r') as f:
            first_line = f.readline()
            item = json.loads(first_line)

        assert 'id' in item
        assert 'text' in item
        assert item['id'] == 'item_1'

    def test_config_validation(self, temp_project_dir):
        """Test that config files are valid and contain required fields"""
        config_files = [
            'tests/test-configs/simple-likert.yaml',
            'tests/test-configs/simple-check-box.yaml',
            'tests/test-configs/simple-slider.yaml',
            'tests/test-configs/simple-span-labeling.yaml'
        ]

        for config_file in config_files:
            config_path = os.path.join(temp_project_dir, config_file)
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)

            # Check required fields
            assert 'annotation_task_name' in config
            assert 'output_annotation_dir' in config
            assert 'data_files' in config
            assert 'item_properties' in config
            assert 'annotation_schemes' in config

            # Check item properties
            assert 'id_key' in config['item_properties']
            assert 'text_key' in config['item_properties']

            # Check annotation schemes
            assert len(config['annotation_schemes']) > 0
            scheme = config['annotation_schemes'][0]
            assert 'annotation_type' in scheme
            assert 'name' in scheme
            assert 'description' in scheme

def create_app():
    """Create Flask app for testing"""
    from potato.flask_server import create_app
    return create_app()