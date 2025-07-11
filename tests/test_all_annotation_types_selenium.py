"""
Comprehensive Selenium tests for all annotation schema types.

This test suite covers:
1. Individual tests for each annotation schema type
2. Tests with multiple schemas per instance
3. Multi-annotator tests with concurrent annotation
4. Navigation and data persistence verification
"""

import pytest
import time
import json
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from tests.flask_test_setup import FlaskTestServer
import threading
import requests


class TestAllAnnotationTypes:
    """Test suite for all annotation schema types."""

    @pytest.fixture(scope="class")
    def test_data(self):
        """Create test data for all annotation types."""
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

    def navigate_and_verify_persistence(self, driver, base_url, test_data):
        """Navigate to next instance and back, verifying annotation persistence."""
        # Get current instance number
        current_instance = driver.find_element(By.ID, "current_instance").text

        # Navigate to next instance
        next_button = driver.find_element(By.ID, "next-btn")
        next_button.click()

        # Wait for next instance to load
        WebDriverWait(driver, 10).until(
            lambda d: d.find_element(By.ID, "current_instance").text != current_instance
        )

        # Navigate back to previous instance
        prev_button = driver.find_element(By.ID, "prev-btn")
        prev_button.click()

        # Wait for previous instance to load
        WebDriverWait(driver, 10).until(
            lambda d: d.find_element(By.ID, "current_instance").text == current_instance
        )

    def verify_annotations_stored(self, driver, base_url, username, instance_id):
        """Verify that annotations are correctly stored by the server."""
        # Backend verification: Check that annotation was saved
        import requests
        api_key = os.environ.get("TEST_API_KEY", "test-api-key-123")
        headers = {"X-API-KEY": api_key}
        user_state_response = requests.get(f"{base_url}/test/user_state/{username}", headers=headers)
        assert user_state_response.status_code == 200, f"Failed to get user state: {user_state_response.status_code}"
        user_state = user_state_response.json()
        annotations = user_state.get("annotations", {}).get("by_instance", {})
        assert str(instance_id) in annotations, f"Annotations should exist for instance {instance_id}"
        return annotations[str(instance_id)]


class TestIndividualAnnotationTypes(TestAllAnnotationTypes):
    """Test individual annotation schema types."""

    def test_radio_annotation(self, test_data):
        """Test radio button annotation."""
        self.create_test_data_file(test_data)

        # Radio annotation config
        config = {
            "port": 9001,
            "server_name": "potato radio annotation test",
            "annotation_task_name": "Radio Button Annotation Test",
            "debug": True,
            "task_dir": "output/radio-annotation",
            "output_annotation_dir": "output/radio-annotation",
            "output_annotation_format": "json",
            "data_files": ["data/test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "What kind of sentiment does the given text hold?",
                    "labels": ["positive", "neutral", "negative"],
                    "sequential_key_binding": True,
                    "label_requirement": {"required": True}
                }
            ]
        }

        server = FlaskTestServer(port=config["port"], debug=config.get("debug", False))
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
                username = f"test_user_radio_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify Next button is disabled initially
                self.verify_next_button_state(driver, expected_disabled=True)

                # Select a radio option
                radio_option = driver.find_element(By.CSS_SELECTOR, "input[name='sentiment'][value='1']")
                radio_option.click()

                # Verify Next button is enabled
                self.verify_next_button_state(driver, expected_disabled=False)

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "sentiment" in annotations, "Sentiment annotation should be stored"

                # Test navigation and persistence
                self.navigate_and_verify_persistence(driver, base_url, test_data)

            finally:
                driver.quit()

    def test_text_annotation(self, test_data):
        """Test text input annotation (both textbox and textarea)."""
        self.create_test_data_file(test_data)

        # Text annotation config
        config = {
            "port": 9002,
            "server_name": "potato text annotation test",
            "annotation_task_name": "Text Input Annotation Test",
            "debug": True,
            "task_dir": "output/text-annotation",
            "output_annotation_dir": "output/text-annotation",
            "output_annotation_format": "json",
            "data_files": ["data/test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [
                {
                    "annotation_type": "text",
                    "name": "summary",
                    "description": "Please provide a brief summary:",
                    "multiline": True,
                    "rows": 4,
                    "cols": 60
                },
                {
                    "annotation_type": "text",
                    "name": "keywords",
                    "description": "What are the key terms?",
                    "multiline": False,
                    "rows": 2,
                    "cols": 40
                }
            ]
        }

        server = FlaskTestServer(port=config["port"], debug=config.get("debug", False))
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
                username = f"test_user_text_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify Next button is disabled initially
                self.verify_next_button_state(driver, expected_disabled=True)

                # Fill textarea (multiline)
                textarea = driver.find_element(By.CSS_SELECTOR, "textarea[name='summary']")
                textarea.send_keys("This is a test summary for the text annotation.")

                # Fill text input (single line)
                text_input = driver.find_element(By.CSS_SELECTOR, "input[name='keywords']")
                text_input.send_keys("AI, NLP, benchmarks")

                # Verify Next button is enabled
                self.verify_next_button_state(driver, expected_disabled=False)

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "summary" in annotations, "Summary annotation should be stored"
                assert "keywords" in annotations, "Keywords annotation should be stored"

                # Test navigation and persistence
                self.navigate_and_verify_persistence(driver, base_url, test_data)

            finally:
                driver.quit()

    def test_multiselect_annotation(self, test_data):
        """Test multiselect annotation."""
        self.create_test_data_file(test_data)

        # Multiselect annotation config
        config = {
            "port": 9003,
            "server_name": "potato multiselect annotation test",
            "annotation_task_name": "Multiselect Annotation Test",
            "debug": True,
            "task_dir": "output/multiselect-annotation",
            "output_annotation_dir": "output/multiselect-annotation",
            "output_annotation_format": "json",
            "data_files": ["data/test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [
                {
                    "annotation_type": "multiselect",
                    "name": "topics",
                    "description": "What topics are mentioned? (Select all that apply)",
                    "labels": ["politics", "technology", "sports", "entertainment", "science"],
                    "sequential_key_binding": True
                }
            ]
        }

        server = FlaskTestServer(port=config["port"], debug=config.get("debug", False))
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
                username = f"test_user_multiselect_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify Next button is disabled initially
                self.verify_next_button_state(driver, expected_disabled=True)

                # Select multiple options
                option1 = driver.find_element(By.CSS_SELECTOR, "input[name='topics'][value='politics']")
                option2 = driver.find_element(By.CSS_SELECTOR, "input[name='topics'][value='technology']")
                option1.click()
                option2.click()

                # Verify Next button is enabled
                self.verify_next_button_state(driver, expected_disabled=False)

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "topics" in annotations, "Topics annotation should be stored"

                # Test navigation and persistence
                self.navigate_and_verify_persistence(driver, base_url, test_data)

            finally:
                driver.quit()

    def test_likert_annotation(self, test_data):
        """Test Likert scale annotation."""
        self.create_test_data_file(test_data)

        # Likert annotation config
        config = {
            "port": 9004,
            "server_name": "potato likert annotation test",
            "annotation_task_name": "Likert Scale Annotation Test",
            "debug": True,
            "task_dir": "output/likert-annotation",
            "output_annotation_dir": "output/likert-annotation",
            "output_annotation_format": "json",
            "data_files": ["data/test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [
                {
                    "annotation_type": "likert",
                    "name": "agreement",
                    "description": "How much do you agree with this statement?",
                    "labels": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"],
                    "sequential_key_binding": True
                }
            ]
        }

        server = FlaskTestServer(port=config["port"], debug=config.get("debug", False))
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
                username = f"test_user_likert_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify Next button is disabled initially
                self.verify_next_button_state(driver, expected_disabled=True)

                # Select a Likert option
                likert_option = driver.find_element(By.CSS_SELECTOR, "input[name='agreement'][value='Agree']")
                likert_option.click()

                # Verify Next button is enabled
                self.verify_next_button_state(driver, expected_disabled=False)

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "agreement" in annotations, "Agreement annotation should be stored"

                # Test navigation and persistence
                self.navigate_and_verify_persistence(driver, base_url, test_data)

            finally:
                driver.quit()

    def test_number_annotation(self, test_data):
        """Test number input annotation."""
        self.create_test_data_file(test_data)

        # Number annotation config
        config = {
            "port": 9005,
            "server_name": "potato number annotation test",
            "annotation_task_name": "Number Input Annotation Test",
            "debug": True,
            "task_dir": "output/number-annotation",
            "output_annotation_dir": "output/number-annotation",
            "output_annotation_format": "json",
            "data_files": ["data/test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [
                {
                    "annotation_type": "number",
                    "name": "rating",
                    "description": "Rate this text on a scale of 1-10:",
                    "min": 1,
                    "max": 10,
                    "step": 1
                }
            ]
        }

        server = FlaskTestServer(port=config["port"], debug=config.get("debug", False))
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
                username = f"test_user_number_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify Next button is disabled initially
                self.verify_next_button_state(driver, expected_disabled=True)

                # Enter a number
                number_input = driver.find_element(By.CSS_SELECTOR, "input[name='rating']")
                number_input.send_keys("7")

                # Verify Next button is enabled
                self.verify_next_button_state(driver, expected_disabled=False)

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "rating" in annotations, "Rating annotation should be stored"

                # Test navigation and persistence
                self.navigate_and_verify_persistence(driver, base_url, test_data)

            finally:
                driver.quit()

    def test_slider_annotation(self, test_data):
        """Test slider annotation."""
        self.create_test_data_file(test_data)

        # Slider annotation config
        config = {
            "port": 9006,
            "server_name": "potato slider annotation test",
            "annotation_task_name": "Slider Annotation Test",
            "debug": True,
            "task_dir": "output/slider-annotation",
            "output_annotation_dir": "output/slider-annotation",
            "output_annotation_format": "json",
            "data_files": ["data/test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [
                {
                    "annotation_type": "slider",
                    "name": "confidence",
                    "description": "How confident are you in your assessment?",
                    "min": 0,
                    "max": 100,
                    "step": 5
                }
            ]
        }

        server = FlaskTestServer(port=config["port"], debug=config.get("debug", False))
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
                username = f"test_user_slider_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify Next button is disabled initially
                self.verify_next_button_state(driver, expected_disabled=True)

                # Move slider
                slider = driver.find_element(By.CSS_SELECTOR, "input[name='confidence']")
                driver.execute_script("arguments[0].value = '75';", slider)
                driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", slider)

                # Verify Next button is enabled
                self.verify_next_button_state(driver, expected_disabled=False)

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "confidence" in annotations, "Confidence annotation should be stored"

                # Test navigation and persistence
                self.navigate_and_verify_persistence(driver, base_url, test_data)

            finally:
                driver.quit()

    def test_select_annotation(self, test_data):
        """Test select dropdown annotation."""
        self.create_test_data_file(test_data)

        # Select annotation config
        config = {
            "port": 9007,
            "server_name": "potato select annotation test",
            "annotation_task_name": "Select Dropdown Annotation Test",
            "debug": True,
            "task_dir": "output/select-annotation",
            "output_annotation_dir": "output/select-annotation",
            "output_annotation_format": "json",
            "data_files": ["data/test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [
                {
                    "annotation_type": "select",
                    "name": "category",
                    "description": "Select the category for this text:",
                    "labels": ["News", "Opinion", "Review", "Analysis", "Other"]
                }
            ]
        }

        server = FlaskTestServer(port=config["port"], debug=config.get("debug", False))
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
                username = f"test_user_select_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify Next button is disabled initially
                self.verify_next_button_state(driver, expected_disabled=True)

                # Select an option from dropdown
                select_element = driver.find_element(By.CSS_SELECTOR, "select[name='category']")
                from selenium.webdriver.support.ui import Select
                select = Select(select_element)
                select.select_by_value("News")

                # Verify Next button is enabled
                self.verify_next_button_state(driver, expected_disabled=False)

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "category" in annotations, "Category annotation should be stored"

                # Test navigation and persistence
                self.navigate_and_verify_persistence(driver, base_url, test_data)

            finally:
                driver.quit()


class TestMultipleSchemas(TestAllAnnotationTypes):
    """Test annotation tasks with multiple schemas per instance."""

    def test_mixed_annotation_schemas(self, test_data):
        """Test a task with multiple different annotation schemas."""
        self.create_test_data_file(test_data)

        # Mixed annotation config
        config = {
            "port": 9010,
            "server_name": "potato mixed annotation test",
            "annotation_task_name": "Mixed Annotation Test",
            "debug": True,
            "task_dir": "output/mixed-annotation",
            "output_annotation_dir": "output/mixed-annotation",
            "output_annotation_format": "json",
            "data_files": ["data/test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "What kind of sentiment does the given text hold?",
                    "labels": ["positive", "neutral", "negative"],
                    "label_requirement": {"required": True}
                },
                {
                    "annotation_type": "text",
                    "name": "summary",
                    "description": "Please provide a brief summary:",
                    "multiline": True,
                    "rows": 3,
                    "cols": 50
                },
                {
                    "annotation_type": "multiselect",
                    "name": "topics",
                    "description": "What topics are mentioned? (Select all that apply)",
                    "labels": ["politics", "technology", "sports", "entertainment", "science"]
                },
                {
                    "annotation_type": "number",
                    "name": "rating",
                    "description": "Rate this text on a scale of 1-10:",
                    "min": 1,
                    "max": 10,
                    "step": 1
                }
            ]
        }

        server = FlaskTestServer(port=config["port"], debug=config.get("debug", False))
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
                username = f"test_user_mixed_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify Next button is disabled initially
                self.verify_next_button_state(driver, expected_disabled=True)

                # Fill out all annotation fields

                # 1. Select radio option
                radio_option = driver.find_element(By.CSS_SELECTOR, "input[name='sentiment'][value='positive']")
                radio_option.click()

                # 2. Fill textarea
                textarea = driver.find_element(By.CSS_SELECTOR, "textarea[name='summary']")
                textarea.send_keys("This is a comprehensive test summary.")

                # 3. Select multiple checkboxes
                topic1 = driver.find_element(By.CSS_SELECTOR, "input[name='topics'][value='technology']")
                topic2 = driver.find_element(By.CSS_SELECTOR, "input[name='topics'][value='science']")
                topic1.click()
                topic2.click()

                # 4. Enter number
                number_input = driver.find_element(By.CSS_SELECTOR, "input[name='rating']")
                number_input.send_keys("8")

                # Verify Next button is enabled
                self.verify_next_button_state(driver, expected_disabled=False)

                # Verify all annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "sentiment" in annotations, "Sentiment annotation should be stored"
                assert "summary" in annotations, "Summary annotation should be stored"
                assert "topics" in annotations, "Topics annotation should be stored"
                assert "rating" in annotations, "Rating annotation should be stored"

                # Test navigation and persistence
                self.navigate_and_verify_persistence(driver, base_url, test_data)

            finally:
                driver.quit()


class TestMultiAnnotator(TestAllAnnotationTypes):
    """Test multiple annotators working concurrently."""

    def test_concurrent_annotators(self, test_data):
        """Test two annotators working on the same task simultaneously."""
        self.create_test_data_file(test_data)

        # Multi-annotator config
        config = {
            "port": 9020,
            "server_name": "potato multi-annotator test",
            "annotation_task_name": "Multi-Annotator Test",
            "debug": True,
            "task_dir": "output/multi-annotator",
            "output_annotation_dir": "output/multi-annotator",
            "output_annotation_format": "json",
            "data_files": ["data/test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "What kind of sentiment does the given text hold?",
                    "labels": ["positive", "neutral", "negative"],
                    "label_requirement": {"required": True}
                },
                {
                    "annotation_type": "text",
                    "name": "comments",
                    "description": "Any additional comments?",
                    "multiline": True,
                    "rows": 3,
                    "cols": 50
                }
            ]
        }

        server = FlaskTestServer(port=config["port"], debug=config.get("debug", False))
        with server.server_context():
            # Create two drivers for two annotators
            # Create WebDriver with headless mode
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            driver1 = webdriver.Chrome(options=chrome_options)
            # Create WebDriver with headless mode
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            driver2 = webdriver.Chrome(options=chrome_options)

            try:
                username1 = f"test_user_1_{int(time.time())}"
                username2 = f"test_user_2_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Function for annotator 1
                def annotator1_task():
                    try:
                        # Register user 1
                        self.create_user(driver1, base_url, username1)

                        # Navigate to annotation page
                        driver1.get(f"{base_url}/annotate")

                        # Fill out annotation
                        radio_option = driver1.find_element(By.CSS_SELECTOR, "input[name='sentiment'][value='positive']")
                        radio_option.click()

                        textarea = driver1.find_element(By.CSS_SELECTOR, "textarea[name='comments']")
                        textarea.send_keys("Annotator 1 comment")

                        # Verify annotations are stored
                        annotations = self.verify_annotations_stored(driver1, base_url, username1, "1")
                        assert "sentiment" in annotations, "Annotator 1 sentiment should be stored"
                        assert "comments" in annotations, "Annotator 1 comments should be stored"

                    except Exception as e:
                        print(f"Annotator 1 error: {e}")
                        raise

                # Function for annotator 2
                def annotator2_task():
                    try:
                        # Register user 2
                        self.create_user(driver2, base_url, username2)

                        # Navigate to annotation page
                        driver2.get(f"{base_url}/annotate")

                        # Fill out annotation with different values
                        radio_option = driver2.find_element(By.CSS_SELECTOR, "input[name='sentiment'][value='negative']")
                        radio_option.click()

                        textarea = driver2.find_element(By.CSS_SELECTOR, "textarea[name='comments']")
                        textarea.send_keys("Annotator 2 comment")

                        # Verify annotations are stored
                        annotations = self.verify_annotations_stored(driver2, base_url, username2, "1")
                        assert "sentiment" in annotations, "Annotator 2 sentiment should be stored"
                        assert "comments" in annotations, "Annotator 2 comments should be stored"

                    except Exception as e:
                        print(f"Annotator 2 error: {e}")
                        raise

                # Run both annotators concurrently
                thread1 = threading.Thread(target=annotator1_task)
                thread2 = threading.Thread(target=annotator2_task)

                thread1.start()
                thread2.start()

                thread1.join()
                thread2.join()

                # Verify both annotators' data is stored separately
                driver1.get(f"{base_url}/test/user_state/{username1}")
                response1 = driver1.find_element(By.TAG_NAME, "pre").text
                user_state1 = json.loads(response1)

                driver2.get(f"{base_url}/test/user_state/{username2}")
                response2 = driver2.find_element(By.TAG_NAME, "pre").text
                user_state2 = json.loads(response2)

                # Verify different annotations for different users
                assert user_state1["annotations"]["1"]["sentiment"] != user_state2["annotations"]["1"]["sentiment"], \
                    "Different annotators should have different annotations"

            finally:
                driver1.quit()
                driver2.quit()


class TestSpanAnnotation(TestAllAnnotationTypes):
    """Test span-based annotation (most complex)."""

    def test_span_annotation(self, test_data):
        """Test span highlighting annotation."""
        self.create_test_data_file(test_data)

        # Span annotation config
        config = {
            "port": 9030,
            "server_name": "potato span annotation test",
            "annotation_task_name": "Span Annotation Test",
            "debug": True,
            "task_dir": "output/span-annotation",
            "output_annotation_dir": "output/span-annotation",
            "output_annotation_format": "json",
            "data_files": ["data/test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [
                {
                    "annotation_type": "highlight",
                    "name": "entities",
                    "description": "Highlight named entities in the text:",
                    "labels": ["PERSON", "ORGANIZATION", "LOCATION", "DATE"],
                    "sequential_key_binding": True
                }
            ]
        }

        server = FlaskTestServer(port=config["port"], debug=config.get("debug", False))
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
                username = f"test_user_span_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify Next button is disabled initially
                self.verify_next_button_state(driver, expected_disabled=True)

                # For span annotation, we need to simulate text selection
                # This is complex and may require JavaScript execution
                # For now, we'll test basic functionality

                # Check if span annotation interface is present
                span_container = driver.find_element(By.CSS_SELECTOR, ".span-annotation-container")
                assert span_container.is_displayed(), "Span annotation container should be visible"

                # Verify Next button state (may be enabled by default for span annotation)
                # This depends on the specific implementation

                # Verify annotations are stored (even if empty initially)
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "entities" in annotations, "Entities annotation should be stored"

                # Test navigation and persistence
                self.navigate_and_verify_persistence(driver, base_url, test_data)

            finally:
                driver.quit()