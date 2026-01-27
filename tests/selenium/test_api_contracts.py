import json
import os
import unittest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_span_annotation_config
from tests.helpers.port_manager import find_free_port


class TestApiSpansContract(unittest.TestCase):
    """Test API contract for spans endpoint."""

    # Admin API key for testing admin endpoints
    ADMIN_API_KEY = "test-admin-api-key"

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server with admin API key."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", "api_contracts_test")
        os.makedirs(test_dir, exist_ok=True)

        # Create span annotation config with admin API key
        config_file, data_file = create_span_annotation_config(
            test_dir,
            annotation_task_name="API Contracts Test",
            require_password=False,
            admin_api_key=cls.ADMIN_API_KEY
        )

        cls.test_dir = test_dir
        port = find_free_port(preferred_port=9494)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options for headless testing
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_options

    @classmethod
    def tearDownClass(cls):
        """Stop the Flask server."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()

    def setUp(self):
        """Set up the WebDriver and register a user."""
        from selenium import webdriver
        import time
        self.driver = webdriver.Chrome(options=self.chrome_options)
        timestamp = int(time.time())
        self.test_user = f"test_user_{self.__class__.__name__}_{timestamp}"

        # Register the test user
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        username_input = self.driver.find_element(By.ID, "login-email")
        username_input.send_keys(self.test_user)
        submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()
        time.sleep(0.05)

    def tearDown(self):
        """Clean up the WebDriver."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def get_session_cookies(self):
        """Get session cookies from the browser."""
        cookies = self.driver.get_cookies()
        return {cookie['name']: cookie['value'] for cookie in cookies}

    def test_api_spans_contract(self):
        """Test the /api/spans/<instance_id> endpoint contract."""
        base_url = self.server.base_url
        username = self.test_user

        # Navigate to annotation page to establish session
        self.driver.get(f"{base_url}/annotate")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "instance-text")))

        # Get the current instance ID from user state using admin API key
        import requests
        response = requests.get(
            f"{base_url}/admin/user_state/{username}",
            headers={"X-API-Key": self.ADMIN_API_KEY}
        )
        if response.status_code != 200:
            self.fail(f"Failed to get user state: HTTP {response.status_code} - {response.text}")

        user_state = response.json()
        instance_id = user_state.get("current_instance", {}).get("id")
        if not instance_id:
            self.fail("No current instance found in user state")

        # Get session cookies from browser
        session_cookies = self.get_session_cookies()

        # Fetch spans for this instance using requests with session cookies
        import requests
        response = requests.get(f"{base_url}/api/spans/{instance_id}", cookies=session_cookies)
        if response.status_code != 200:
            self.fail(f"Failed to fetch spans: HTTP {response.status_code} - {response.text}")

        spans = response.json()

        # Assert spans contract
        self.assertIsInstance(spans, dict, "Spans should be a dictionary")
        self.assertIn("spans", spans, "Spans response should have 'spans' key")
        self.assertIsInstance(spans["spans"], list, "Spans should be a list")
        # Each span should be a dict with required keys (if any spans exist)
        if spans["spans"]:
            for span in spans["spans"]:
                self.assertIsInstance(span, dict)
                self.assertIn("start", span)
                self.assertIn("end", span)
                self.assertIn("label", span)
                self.assertIn("span_text", span)
        print(f"Spans contract test passed. Spans: {spans}")

if __name__ == "__main__":
    unittest.main()