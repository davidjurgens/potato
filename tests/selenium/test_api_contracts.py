import json
import unittest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.selenium.test_base import BaseSeleniumTest

class TestApiSpansContract(BaseSeleniumTest):
    def test_api_spans_contract(self):
        """Test the /api/spans/<instance_id> endpoint contract."""
        base_url = self.server.base_url
        # User is already registered and logged in by BaseSeleniumTest
        username = self.test_user

        # Navigate to annotation page to establish session
        self.driver.get(f"{base_url}/annotate")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "instance-text")))

        # Get the current instance ID from user state using server's get method
        response = self.server.get(f"/admin/user_state/{username}")
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