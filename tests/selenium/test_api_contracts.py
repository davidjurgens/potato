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

        # Get the current instance ID from user state
        user_state_script = f"""
            return fetch('{base_url}/admin/user_state/{username}', {{credentials: 'same-origin'}})
                .then(r => r.json())
                .then(data => data.current_instance.id)
                .catch(e => 'ERROR: ' + e.message);
        """
        instance_id = self.execute_script_safe(user_state_script)
        self.assertFalse(isinstance(instance_id, str) and instance_id.startswith("ERROR:"), f"Failed to get instance ID: {instance_id}")

        # Fetch spans for this instance
        spans_script = f"""
            return fetch('{base_url}/api/spans/{instance_id}', {{credentials: 'same-origin'}})
                .then(r => r.json())
                .then(data => JSON.stringify(data))
                .catch(e => 'ERROR: ' + e.message);
        """
        spans_json = self.execute_script_safe(spans_script)
        self.assertFalse(isinstance(spans_json, str) and spans_json.startswith("ERROR:"), f"Failed to fetch spans: {spans_json}")
        spans = json.loads(spans_json)

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