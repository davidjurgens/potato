#!/usr/bin/env python3
"""
Base class for Solo Mode Selenium tests.

Provides common setup for Solo Mode testing including:
- Server configuration with Solo Mode enabled
- Ollama LLM endpoint for testing (skips if not available)
- Common navigation and interaction utilities
"""

import os
import time
import unittest
import requests
from unittest.mock import patch, MagicMock
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


# Ollama configuration
OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'llama3.2:1b')


def is_ollama_available():
    """Check if Ollama is running and has the required model."""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=2)
        if response.status_code != 200:
            return False, "Ollama not responding"

        models = response.json().get('models', [])
        model_names = [m.get('name', '') for m in models]

        # Check if our model (or a variant) is available
        if not any(OLLAMA_MODEL in name or name in OLLAMA_MODEL for name in model_names):
            return False, f"Model {OLLAMA_MODEL} not found. Available: {model_names[:5]}"

        return True, "Ollama available"
    except requests.exceptions.ConnectionError:
        return False, "Ollama not running"
    except Exception as e:
        return False, f"Ollama check failed: {e}"


OLLAMA_AVAILABLE, OLLAMA_SKIP_REASON = is_ollama_available()


@unittest.skipUnless(OLLAMA_AVAILABLE, OLLAMA_SKIP_REASON)
class BaseSoloModeSeleniumTest(unittest.TestCase):
    """
    Base class for Solo Mode Selenium tests.

    Provides:
    - Flask server with Solo Mode enabled
    - Chrome/Firefox WebDriver setup
    - User authentication helpers
    - Solo Mode navigation utilities

    Requires Ollama to be running. Set environment variables:
    - OLLAMA_HOST: Ollama server URL (default: http://localhost:11434)
    - OLLAMA_MODEL: Model to use (default: llama3.2:1b)
    """

    @classmethod
    def setUpClass(cls):
        """Set up Flask server with Solo Mode configuration."""
        import json
        import yaml

        # Create test directory
        tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        cls.test_dir = os.path.join(tests_dir, "output", "selenium_solo_mode")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create data directory and test data
        data_dir = os.path.join(cls.test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create test data file
        test_data = [
            {"id": "test_001", "text": "This product is amazing! I love it."},
            {"id": "test_002", "text": "Terrible experience. Would not recommend."},
            {"id": "test_003", "text": "The package arrived on time."},
            {"id": "test_004", "text": "Best purchase ever! So happy."},
            {"id": "test_005", "text": "Waste of money. Broke immediately."},
        ]
        data_file = os.path.join(data_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(test_data, f)

        # Create Solo Mode config
        config = {
            'task_dir': '.',
            'verbose': True,
            'annotation_task_name': 'solo_selenium_test',
            'output_annotation_dir': 'annotations',

            # Enable Solo Mode
            'solo_mode': {
                'enabled': True,
                'labeling_models': [
                    {
                        'endpoint_type': 'ollama',
                        'model': OLLAMA_MODEL,
                        'endpoint_url': OLLAMA_HOST,
                        'max_tokens': 256,
                        'temperature': 0.1,
                    }
                ],
                'revision_models': [
                    {
                        'endpoint_type': 'ollama',
                        'model': OLLAMA_MODEL,
                        'endpoint_url': OLLAMA_HOST,
                    }
                ],
                'uncertainty': {
                    'strategy': 'direct_confidence',
                },
                'thresholds': {
                    'end_human_annotation_agreement': 0.90,
                    'minimum_validation_sample': 5,
                    'confidence_low': 0.5,
                    'periodic_review_interval': 10,
                },
                'instance_selection': {
                    'low_confidence_weight': 0.4,
                    'diversity_weight': 0.3,
                    'random_weight': 0.2,
                    'disagreement_weight': 0.1,
                },
                'batches': {
                    'llm_labeling_batch': 5,
                    'max_parallel_labels': 10,
                },
                'state_dir': 'solo_state',
            },

            # Data configuration
            'data_files': ['data/test_data.json'],

            'item_properties': {
                'id_key': 'id',
                'text_key': 'text',
            },

            # Annotation scheme
            'annotation_schemes': [
                {
                    'name': 'sentiment',
                    'annotation_type': 'radio',
                    'description': 'Classify the sentiment',
                    'labels': [
                        {'name': 'positive', 'key_value': '1'},
                        {'name': 'negative', 'key_value': '2'},
                        {'name': 'neutral', 'key_value': '3'},
                    ]
                }
            ],

            # User configuration
            'user_config': {
                'allow_no_password': True,
            },

            # Output
            'output': {
                'annotation_output_format': 'json',
                'annotation_output_dir': 'annotations',
            },
        }

        config_file = os.path.join(cls.test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        cls.config_file = config_file

        # Start server
        port = find_free_port(preferred_port=9100)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server for Solo Mode tests"

        # Wait for server to be ready
        cls.server._wait_for_server_ready(timeout=15)

        # Set up Chrome options for headless testing
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")

        cls.chrome_options = chrome_options

    @classmethod
    def tearDownClass(cls):
        """Clean up Flask server and test files."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()

        # Clean up test directory
        if hasattr(cls, 'test_dir'):
            import shutil
            try:
                shutil.rmtree(cls.test_dir)
            except Exception:
                pass

    def setUp(self):
        """Set up WebDriver for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)

        # Generate unique test user
        timestamp = int(time.time())
        self.test_user = f"solo_test_user_{timestamp}"

    def tearDown(self):
        """Clean up WebDriver after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def login_user(self):
        """Login a test user via the web interface."""
        self.driver.get(f"{self.server.base_url}/")

        # Wait for login form
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-content"))
        )

        # Fill in username (simple mode without password)
        try:
            username_field = self.driver.find_element(By.ID, "login-email")
            username_field.clear()
            username_field.send_keys(self.test_user)

            # Submit form
            login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
            login_form.submit()

            time.sleep(0.5)
        except NoSuchElementException:
            pass

    def navigate_to_solo_setup(self):
        """Navigate to Solo Mode setup page."""
        self.driver.get(f"{self.server.base_url}/solo/setup")
        time.sleep(0.5)

    def navigate_to_solo_prompt(self):
        """Navigate to Solo Mode prompt editor."""
        self.driver.get(f"{self.server.base_url}/solo/prompt")
        time.sleep(0.5)

    def navigate_to_solo_annotate(self):
        """Navigate to Solo Mode annotation page."""
        self.driver.get(f"{self.server.base_url}/solo/annotate")
        time.sleep(0.5)

    def navigate_to_solo_status(self):
        """Navigate to Solo Mode status page."""
        self.driver.get(f"{self.server.base_url}/solo/status")
        time.sleep(0.5)

    def wait_for_element(self, by, value, timeout=10):
        """Wait for an element to be present."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def wait_for_element_visible(self, by, value, timeout=10):
        """Wait for an element to be visible."""
        return WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((by, value))
        )

    def wait_for_element_clickable(self, by, value, timeout=10):
        """Wait for an element to be clickable."""
        return WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )

    def click_element(self, by, value):
        """Wait for and click an element."""
        element = self.wait_for_element_clickable(by, value)
        element.click()
        return element

    def fill_text(self, by, value, text):
        """Wait for element and fill with text."""
        element = self.wait_for_element(by, value)
        element.clear()
        element.send_keys(text)
        return element

    def press_key(self, key):
        """Press a keyboard key."""
        actions = ActionChains(self.driver)
        actions.send_keys(key)
        actions.perform()

    def get_page_source(self):
        """Get the current page source."""
        return self.driver.page_source

    def assert_element_present(self, by, value, message=None):
        """Assert that an element is present on the page."""
        try:
            self.driver.find_element(by, value)
        except NoSuchElementException:
            if message:
                self.fail(message)
            else:
                self.fail(f"Element not found: {by}={value}")

    def assert_element_not_present(self, by, value, message=None):
        """Assert that an element is not present on the page."""
        try:
            self.driver.find_element(by, value)
            if message:
                self.fail(message)
            else:
                self.fail(f"Element should not be present: {by}={value}")
        except NoSuchElementException:
            pass  # Expected

    def assert_text_in_page(self, text, message=None):
        """Assert that text is present in the page source."""
        if text not in self.driver.page_source:
            if message:
                self.fail(message)
            else:
                self.fail(f"Text not found in page: {text}")

    def get_current_url(self):
        """Get the current URL."""
        return self.driver.current_url
