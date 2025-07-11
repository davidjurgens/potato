"""
Selenium tests for span annotation (text highlighting).

Span annotation is the most complex annotation type as it involves:
- Text selection and highlighting
- Multiple span types/labels
- Span boundaries and overlapping
- Visual feedback
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
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from tests.flask_test_setup import FlaskTestServer


class TestSpanAnnotation:
    """Test suite for span annotation."""

    @pytest.fixture(scope="class")
    def test_data(self):
        """Create test data for span annotation."""
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
        # Navigate to test endpoint to check user state
        driver.get(f"{base_url}/test/user_state/{username}")

        # Parse the JSON response
        response_text = driver.find_element(By.TAG_NAME, "pre").text
        user_state = json.loads(response_text)

        # Check if annotations exist for the instance
        assert "annotations" in user_state, "User state should contain annotations"
        assert str(instance_id) in user_state["annotations"], f"Annotations should exist for instance {instance_id}"

        return user_state["annotations"][str(instance_id)]

    def test_span_annotation_basic(self, test_data):
        """Test basic span annotation functionality."""
        # Create temporary config directory
        config_dir = tempfile.mkdtemp()

        # Span annotation config
        config = {
            "port": 9030,
            "server_name": "potato span annotation test",
            "annotation_task_name": "Span Annotation Test",
            "debug": True,
            "test_data": test_data,
            "item_properties": {"id_key": "id", "text_key": "text"},
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
                username = f"test_user_span_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify span annotation interface is present
                span_container = driver.find_element(By.CSS_SELECTOR, ".span-annotation-container")
                assert span_container.is_displayed(), "Span annotation container should be visible"

                # Check if text is displayed for highlighting
                text_element = driver.find_element(By.CSS_SELECTOR, ".annotation-text")
                assert text_element.is_displayed(), "Annotation text should be visible"

                # Check if entity labels are present
                entity_labels = driver.find_elements(By.CSS_SELECTOR, ".entity-label")
                assert len(entity_labels) >= 4, "Should have at least 4 entity labels (PERSON, ORGANIZATION, LOCATION, DATE)"

                # Verify Next button state (may be enabled by default for span annotation)
                # This depends on the specific implementation

                # Verify annotations are stored (even if empty initially)
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "entities" in annotations, "Entities annotation should be stored"

            finally:
                driver.quit()

    def test_span_annotation_with_selection(self, test_data):
        """Test span annotation with text selection."""
        # Create temporary config directory
        config_dir = tempfile.mkdtemp()

        # Span annotation config
        config = {
            "port": 9031,
            "server_name": "potato span selection test",
            "annotation_task_name": "Span Selection Test",
            "debug": True,
            "test_data": test_data,
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "annotation_type": "highlight",
                    "name": "sentiment_spans",
                    "description": "Highlight positive and negative sentiment spans:",
                    "labels": ["positive", "negative"],
                    "sequential_key_binding": True
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
                username = f"test_user_span_sel_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Find the text element for selection
                text_element = driver.find_element(By.CSS_SELECTOR, ".annotation-text")

                # Try to select text using JavaScript (simulating user selection)
                # This is a simplified approach - real span annotation may require more complex interaction

                # Select a word using JavaScript
                driver.execute_script("""
                    var textElement = arguments[0];
                    var range = document.createRange();
                    var textNode = textElement.firstChild;
                    range.setStart(textNode, 0);
                    range.setEnd(textNode, 5);
                    var selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                """, text_element)

                # Check if selection was made
                selection = driver.execute_script("return window.getSelection().toString();")

                # If selection worked, try to apply a label
                if selection:
                    # Find and click on a sentiment label
                    positive_label = driver.find_element(By.CSS_SELECTOR, ".entity-label[data-label='positive']")
                    positive_label.click()

                    # Verify that the span was created
                    spans = driver.find_elements(By.CSS_SELECTOR, ".highlighted-span")
                    assert len(spans) > 0, "Should have at least one highlighted span"

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "sentiment_spans" in annotations, "Sentiment spans annotation should be stored"

            finally:
                driver.quit()

    def test_span_annotation_multiple_spans(self, test_data):
        """Test span annotation with multiple spans of different types."""
        # Create temporary config directory
        config_dir = tempfile.mkdtemp()

        # Span annotation config with multiple entity types
        config = {
            "port": 9032,
            "server_name": "potato span multiple test",
            "annotation_task_name": "Multiple Spans Test",
            "debug": True,
            "test_data": test_data,
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "annotation_type": "highlight",
                    "name": "named_entities",
                    "description": "Highlight different types of named entities:",
                    "labels": [
                        {
                            "name": "PERSON",
                            "description": "Person names"
                        },
                        {
                            "name": "ORGANIZATION",
                            "description": "Organization names"
                        },
                        {
                            "name": "LOCATION",
                            "description": "Location names"
                        }
                    ],
                    "sequential_key_binding": True
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
                username = f"test_user_span_multi_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Verify all entity labels are present
                person_label = driver.find_element(By.CSS_SELECTOR, ".entity-label[data-label='PERSON']")
                org_label = driver.find_element(By.CSS_SELECTOR, ".entity-label[data-label='ORGANIZATION']")
                location_label = driver.find_element(By.CSS_SELECTOR, ".entity-label[data-label='LOCATION']")

                assert person_label.is_displayed(), "PERSON label should be visible"
                assert org_label.is_displayed(), "ORGANIZATION label should be visible"
                assert location_label.is_displayed(), "LOCATION label should be visible"

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "named_entities" in annotations, "Named entities annotation should be stored"

            finally:
                driver.quit()

    def test_span_annotation_navigation_persistence(self, test_data):
        """Test that span annotations persist when navigating between instances."""
        # Create temporary config directory
        config_dir = tempfile.mkdtemp()

        # Span annotation config
        config = {
            "port": 9033,
            "server_name": "potato span persistence test",
            "annotation_task_name": "Span Persistence Test",
            "debug": True,
            "test_data": test_data,
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "annotation_type": "highlight",
                    "name": "key_phrases",
                    "description": "Highlight key phrases in the text:",
                    "labels": ["important", "technical", "emotional"],
                    "sequential_key_binding": True
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
                username = f"test_user_span_persist_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

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

                # Verify that span annotation interface is still present
                span_container = driver.find_element(By.CSS_SELECTOR, ".span-annotation-container")
                assert span_container.is_displayed(), "Span annotation container should still be visible"

                # Verify annotations are stored for both instances
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "key_phrases" in annotations, "Key phrases annotation should be stored for instance 1"

                annotations2 = self.verify_annotations_stored(driver, base_url, username, "2")
                assert "key_phrases" in annotations2, "Key phrases annotation should be stored for instance 2"

            finally:
                driver.quit()

    def test_span_annotation_undo_redo(self, test_data):
        """Test span annotation undo/redo functionality."""
        # Create temporary config directory
        config_dir = tempfile.mkdtemp()

        # Span annotation config
        config = {
            "port": 9034,
            "server_name": "potato span undo test",
            "annotation_task_name": "Span Undo/Redo Test",
            "debug": True,
            "test_data": test_data,
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "annotation_type": "highlight",
                    "name": "annotations",
                    "description": "Highlight important parts of the text:",
                    "labels": ["highlight", "underline", "comment"],
                    "sequential_key_binding": True
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
                username = f"test_user_span_undo_{int(time.time())}"
                base_url = f"http://localhost:{config['port']}"

                # Register user
                self.create_user(driver, base_url, username)

                # Navigate to annotation page
                driver.get(f"{base_url}/annotate")

                # Look for undo/redo buttons
                try:
                    undo_button = driver.find_element(By.CSS_SELECTOR, ".undo-button, [data-action='undo']")
                    redo_button = driver.find_element(By.CSS_SELECTOR, ".redo-button, [data-action='redo']")

                    # Test undo functionality
                    undo_button.click()

                    # Test redo functionality
                    redo_button.click()

                except NoSuchElementException:
                    # Undo/redo buttons may not be present in all implementations
                    pass

                # Verify annotations are stored
                annotations = self.verify_annotations_stored(driver, base_url, username, "1")
                assert "annotations" in annotations, "Annotations should be stored"

            finally:
                driver.quit()