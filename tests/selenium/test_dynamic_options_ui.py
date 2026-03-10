"""
Selenium tests for Issue #97: Varying number of options per instance.

Verifies that when dynamic_options is enabled, different instances
show different subsets of labels based on data field values.
"""

import json
import os
import time
import unittest

import yaml
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory


def create_dynamic_options_config(test_dir, port):
    """Create a config with dynamic_options enabled on a radio schema."""
    # Each item has a different subset of visible labels
    test_data = [
        {
            "id": "item_1",
            "text": "This item should show only positive and negative.",
            "visible_labels": ["positive", "negative"],
        },
        {
            "id": "item_2",
            "text": "This item should show all three labels.",
            "visible_labels": ["positive", "negative", "neutral"],
        },
        {
            "id": "item_3",
            "text": "This item should show only neutral.",
            "visible_labels": ["neutral"],
        },
    ]

    data_file = os.path.join(test_dir, "test_data.jsonl")
    with open(data_file, "w", encoding="utf-8") as f:
        for item in test_data:
            f.write(json.dumps(item) + "\n")

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": f"Dynamic Options Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "What is the sentiment?",
                "dynamic_options": True,
                "dynamic_options_field": "visible_labels",
            }
        ],
        "assignment_strategy": "fixed_order",
        "max_annotations_per_user": 3,
        "max_annotations_per_item": 3,
        "phases": {"order": ["annotation"], "annotation": {"type": "annotation"}},
        "site_file": "base_template.html",
        "site_dir": "default",
        "output_annotation_dir": output_dir,
        "task_dir": test_dir,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": f"test-secret-{port}",
        "persist_sessions": False,
        "alert_time_each_instance": 0,
        "user_config": {"allow_all_users": True, "users": []},
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config, f)
    return config_file


class TestDynamicOptionsUI(unittest.TestCase):
    """Tests that dynamic_options filters radio labels per instance."""

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", f"dynamic_options_ui_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_dynamic_options_config(cls.test_dir, cls.port)

        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"dynopt_user_{int(time.time() * 1000)}"

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(self.test_user)
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

    def _get_visible_radio_values(self):
        """Get the values of all visible radio buttons for the sentiment schema."""
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']"
        )
        return [r.get_attribute("value") for r in radios]

    def test_first_instance_shows_two_options(self):
        """First instance should only show 'positive' and 'negative'."""
        self._login()
        time.sleep(0.5)

        values = self._get_visible_radio_values()
        self.assertIn("positive", values, "Should show 'positive'")
        self.assertIn("negative", values, "Should show 'negative'")
        self.assertNotIn("neutral", values,
                          "Should NOT show 'neutral' for first instance")

    def test_second_instance_shows_three_options(self):
        """Second instance should show all three options."""
        self._login()
        time.sleep(0.5)

        # Select an option and navigate to next instance
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']"
        )
        if radios:
            radio_id = radios[0].get_attribute("id")
            label = self.driver.find_element(By.CSS_SELECTOR, f"label[for='{radio_id}']")
            label.click()
            time.sleep(0.5)

        next_btn = self.driver.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(1)

        values = self._get_visible_radio_values()
        self.assertEqual(len(values), 3,
                          "Second instance should show all 3 options")
        self.assertIn("positive", values)
        self.assertIn("negative", values)
        self.assertIn("neutral", values)

    def test_third_instance_shows_one_option(self):
        """Third instance should only show 'neutral'."""
        self._login()
        time.sleep(0.5)

        # Navigate through first two instances
        for _ in range(2):
            radios = self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']"
            )
            if radios:
                radio_id = radios[0].get_attribute("id")
                label = self.driver.find_element(By.CSS_SELECTOR, f"label[for='{radio_id}']")
                label.click()
                time.sleep(0.5)

            next_btn = self.driver.find_element(By.ID, "next-btn")
            next_btn.click()
            time.sleep(1)

        values = self._get_visible_radio_values()
        self.assertEqual(values, ["neutral"],
                          "Third instance should only show 'neutral'")

    def test_no_server_errors(self):
        """Navigation through instances with dynamic options should not cause errors."""
        self._login()
        time.sleep(0.5)

        page_source = self.driver.page_source
        self.assertNotIn("Internal Server Error", page_source)
        self.assertNotIn("Traceback", page_source)


if __name__ == "__main__":
    unittest.main()
