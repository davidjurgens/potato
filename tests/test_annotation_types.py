"""
Tests for different annotation types using the simple examples configs.
Tests both backend functionality and frontend rendering for each annotation type.
"""

import pytest
import json
import os
import tempfile
import shutil
from unittest.mock import patch, Mock
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import threading
import subprocess
import requests

# Add potato to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'potato'))

class TestAnnotationTypes:
    """Test different annotation types with their respective configs"""

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
            '--debug', '-p', '9001', 'start',
            'simple_examples/configs/simple-likert.yaml'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Wait for server to start
        time.sleep(3)

        yield process

        # Cleanup
        process.terminate()
        process.wait()
        os.chdir(original_cwd)

    def test_likert_annotation_backend(self, temp_project_dir):
        """Test likert annotation backend functionality"""
        config_path = os.path.join(temp_project_dir, 'simple_examples', 'configs', 'simple-likert.yaml')

        # Test config loading
        with open(config_path, 'r') as f:
            config = json.load(f)

        assert config['annotation_task_name'] == 'Simple Likert Scale Example'
        assert config['annotation_schemes'][0]['annotation_type'] == 'likert'
        assert config['annotation_schemes'][0]['size'] == 5

        # Test data loading
        data_path = os.path.join(temp_project_dir, 'simple_examples', 'data', 'toy-example.json')
        assert os.path.exists(data_path)

        # Test output directory creation
        output_dir = os.path.join(temp_project_dir, 'simple_examples', config['output_annotation_dir'])
        os.makedirs(output_dir, exist_ok=True)
        assert os.path.exists(output_dir)

    def test_checkbox_annotation_backend(self, temp_project_dir):
        """Test checkbox (multiselect) annotation backend functionality"""
        config_path = os.path.join(temp_project_dir, 'simple_examples', 'configs', 'simple-check-box.yaml')

        with open(config_path, 'r') as f:
            config = json.load(f)

        assert config['annotation_task_name'] == 'Simple Check Box Example'
        assert config['annotation_schemes'][0]['annotation_type'] == 'multiselect'
        assert 'blue' in config['annotation_schemes'][0]['labels']
        assert 'maize' in config['annotation_schemes'][0]['labels']

    def test_slider_annotation_backend(self, temp_project_dir):
        """Test slider annotation backend functionality"""
        config_path = os.path.join(temp_project_dir, 'simple_examples', 'configs', 'simple-slider.yaml')

        with open(config_path, 'r') as f:
            config = json.load(f)

        assert config['annotation_task_name'] == 'Simple Slider Example'
        assert config['annotation_schemes'][0]['annotation_type'] == 'slider'
        assert config['annotation_schemes'][0]['min_value'] == 0
        assert config['annotation_schemes'][0]['max_value'] == 100
        assert config['annotation_schemes'][0]['starting_value'] == 50

    def test_span_annotation_backend(self, temp_project_dir):
        """Test span annotation backend functionality"""
        config_path = os.path.join(temp_project_dir, 'simple_examples', 'configs', 'simple-span-labeling.yaml')

        with open(config_path, 'r') as f:
            config = json.load(f)

        assert config['annotation_task_name'] == 'Simple Highlighting Example'
        assert config['annotation_schemes'][0]['annotation_type'] == 'highlight'
        assert 'certain' in config['annotation_schemes'][0]['labels']
        assert 'uncertain' in config['annotation_schemes'][0]['labels']

    @pytest.mark.selenium
    def test_likert_annotation_frontend(self, server_process):
        """Test likert annotation frontend with Selenium"""
        driver = webdriver.Chrome(options=Options().add_argument("--headless"))
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
            assert "Not Awesome" in driver.page_source
            assert "Compeletely Awesome" in driver.page_source

            # Test selecting a scale point
            likert_elements[2].click()  # Select middle option
            assert likert_elements[2].is_selected()

        finally:
            driver.quit()

    @pytest.mark.selenium
    def test_checkbox_annotation_frontend(self, server_process):
        """Test checkbox annotation frontend with Selenium"""
        # Start server with checkbox config
        config_path = 'simple_examples/configs/simple-check-box.yaml'

        driver = webdriver.Chrome(options=Options().add_argument("--headless"))
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
        driver = webdriver.Chrome(options=Options().add_argument("--headless"))
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
        driver = webdriver.Chrome(options=Options().add_argument("--headless"))
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
        json_data_path = os.path.join(temp_project_dir, 'simple_examples', 'data', 'toy-example.json')
        with open(json_data_path, 'r') as f:
            first_line = f.readline()
            item = json.loads(first_line)

        assert 'id' in item
        assert 'text' in item
        assert item['id'] == 'item_1'

        # Test CSV format
        csv_data_path = os.path.join(temp_project_dir, 'simple_examples', 'data', 'toy-example.csv')
        assert os.path.exists(csv_data_path)

        # Test TSV format
        tsv_data_path = os.path.join(temp_project_dir, 'simple_examples', 'data', 'toy-example.tsv')
        assert os.path.exists(tsv_data_path)

    def test_config_validation(self, temp_project_dir):
        """Test that config files are valid and contain required fields"""
        config_files = [
            'simple_examples/configs/simple-likert.yaml',
            'simple_examples/configs/simple-check-box.yaml',
            'simple_examples/configs/simple-slider.yaml',
            'simple_examples/configs/simple-span-labeling.yaml'
        ]

        for config_file in config_files:
            config_path = os.path.join(temp_project_dir, config_file)
            with open(config_path, 'r') as f:
                config = json.load(f)

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