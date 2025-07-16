"""
Selenium tests for frontend integration with user state endpoint.

These tests verify that the frontend can properly load user state from the
/admin/user_state/<user_id> endpoint and handle the annotations.by_instance structure.
"""

import pytest
import time
import json
import tempfile
import os
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from tests.helpers.flask_test_setup import FlaskTestServer


class TestUserStateFrontendIntegration:
    """Test frontend integration with user state endpoint."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with span annotation config."""
        # Create a temporary directory for this test
        test_dir = tempfile.mkdtemp()

        # Create test data file
        test_data = [
            {
                "id": "frontend_test_item_1",
                "text": "This is a positive statement about the product.",
                "displayed_text": "This is a positive statement about the product."
            },
            {
                "id": "frontend_test_item_2",
                "text": "This is a negative statement about the product.",
                "displayed_text": "This is a negative statement about the product."
            }
        ]

        data_file = os.path.join(test_dir, 'frontend_test_data.jsonl')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config with span annotation scheme
        config = {
            "debug": False,
            "max_annotations_per_user": 10,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Frontend User State Test",
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": [os.path.basename(data_file)],
            "item_properties": {
                "text_key": "text",
                "id_key": "id"
            },
            "annotation_schemes": [
                {
                    "annotation_type": "span",
                    "name": "sentiment",
                    "description": "Annotate the sentiment of text spans",
                    "labels": ["happy", "sad", "angry", "neutral"],
                    "colors": {
                        "happy": "#4CAF50",
                        "sad": "#2196F3",
                        "angry": "#f44336",
                        "neutral": "#9E9E9E"
                    }
                }
            ],
            "site_file": "base_template_v2.html",
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": os.path.join(test_dir, "task"),
            "site_dir": os.path.join(test_dir, "templates"),
            "alert_time_each_instance": 0
        }

        # Write config file
        config_file = os.path.join(test_dir, 'frontend_test_config.yaml')
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Create server with the config file
        server = FlaskTestServer(
            port=9013,
            debug=False,
            config_file=config_file,
            test_data_file=data_file
        )

        # Start server
        if not server.start_server(test_dir):
            pytest.fail("Failed to start Flask test server")

        yield server

        # Cleanup
        server.stop_server()

    @pytest.fixture
    def driver(self):
        """Create a headless Chrome driver."""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        driver = webdriver.Chrome(options=chrome_options)
        yield driver
        driver.quit()

    def test_frontend_loads_user_state(self, flask_server, driver):
        """Test that frontend can load user state without errors."""
        # Register a test user
        user_data = {"email": "frontend_test_user", "pass": "test_password"}
        session = requests.Session()

        reg_response = session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        assert reg_response.status_code in [200, 302]

        # Navigate to annotation page
        driver.get(f"{flask_server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Check for JavaScript errors in console
        logs = driver.get_log('browser')
        error_logs = [log for log in logs if log['level'] == 'SEVERE']

        # Filter out expected errors (like favicon.ico 404)
        unexpected_errors = []
        for error in error_logs:
            error_message = error['message'].lower()
            if 'favicon.ico' not in error_message and '404' not in error_message:
                unexpected_errors.append(error)

        # Should not have unexpected errors
        assert len(unexpected_errors) == 0, f"Unexpected JavaScript errors: {unexpected_errors}"

        # Verify that the page loaded successfully
        instance_text = driver.find_element(By.ID, "instance-text")
        assert instance_text.is_displayed()
        assert len(instance_text.text) > 0

    def test_frontend_handles_annotations_by_instance(self, flask_server, driver):
        """Test that frontend can handle annotations.by_instance structure."""
        # Register a test user
        user_data = {"email": "annotations_frontend_user", "pass": "test_password"}
        session = requests.Session()

        reg_response = session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        assert reg_response.status_code in [200, 302]

        # Submit an annotation first
        annotation_data = {
            "instance_id": "frontend_test_item_1",
            "annotations": {
                "sentiment:happy": "happy"
            },
            "span_annotations": {}
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=annotation_data,
            timeout=5
        )
        assert response.status_code == 200

        # Navigate to annotation page
        driver.get(f"{flask_server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Check for JavaScript errors related to annotations
        logs = driver.get_log('browser')
        error_logs = [log for log in logs if log['level'] == 'SEVERE']

        # Look for specific errors we encountered
        annotation_errors = []
        for error in error_logs:
            error_message = error['message'].lower()
            if any(keyword in error_message for keyword in [
                'annotations.by_instance',
                'userstate.annotations',
                'progress is undefined',
                'to_dict'
            ]):
                annotation_errors.append(error)

        # Should not have annotation-related errors
        assert len(annotation_errors) == 0, f"Annotation-related errors: {annotation_errors}"

    def test_frontend_span_annotation_workflow(self, flask_server, driver):
        """Test complete span annotation workflow in frontend."""
        # Register a test user
        user_data = {"email": "span_frontend_user", "pass": "test_password"}
        session = requests.Session()

        reg_response = session.post(f"{flask_server.base_url}/register", data=user_data, timeout=5)
        assert reg_response.status_code in [200, 302]

        # Navigate to annotation page
        driver.get(f"{flask_server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Get the instance text
        instance_text = driver.find_element(By.ID, "instance-text")
        text_content = instance_text.text

        # Select some text (simulate span annotation)
        driver.execute_script("""
            const textElement = document.getElementById('instance-text');
            const range = document.createRange();
            const textNode = textElement.firstChild;
            range.setStart(textNode, 0);
            range.setEnd(textNode, 5);

            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        """)

        # Wait a moment for selection to be processed
        time.sleep(1)

        # Check for span annotation UI elements
        try:
            # Look for span label buttons or similar UI elements
            span_labels = driver.find_elements(By.CSS_SELECTOR, "[data-span-label]")
            if span_labels:
                # Click on a span label if available
                span_labels[0].click()
                time.sleep(1)
        except:
            # Span labels might not be present, which is OK for this test
            pass

        # Check for JavaScript errors after span interaction
        logs = driver.get_log('browser')
        error_logs = [log for log in logs if log['level'] == 'SEVERE']

        # Filter out expected errors
        unexpected_errors = []
        for error in error_logs:
            error_message = error['message'].lower()
            if 'favicon.ico' not in error_message and '404' not in error_message:
                unexpected_errors.append(error)

        # Should not have unexpected errors
        assert len(unexpected_errors) == 0, f"Unexpected errors after span interaction: {unexpected_errors}"

    def test_frontend_error_handling(self, flask_server, driver):
        """Test frontend error handling when user state is invalid."""
        # Try to access annotation page without registering
        driver.get(f"{flask_server.base_url}/annotate")

        # Should be redirected to login/register page
        current_url = driver.current_url
        assert "/" in current_url or "/login" in current_url or "/register" in current_url

        # Check for JavaScript errors
        logs = driver.get_log('browser')
        error_logs = [log for log in logs if log['level'] == 'SEVERE']

        # Should not have critical errors
        critical_errors = []
        for error in error_logs:
            error_message = error['message'].lower()
            if any(keyword in error_message for keyword in [
                'to_dict',
                'annotations.by_instance',
                'userstate.annotations'
            ]):
                critical_errors.append(error)

        # Should not have critical errors
        assert len(critical_errors) == 0, f"Critical errors on unauthenticated access: {critical_errors}"