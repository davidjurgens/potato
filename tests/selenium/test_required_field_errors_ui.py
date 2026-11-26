"""
Selenium tests for Issue #101: Required question error messages.

Verifies that when required annotation fields are not filled and the
annotator tries to go forward (Next stays clickable since d8b59365, errors
are deferred until the first forward attempt):
1. Navigation is blocked
2. A visible error message appears listing unfilled questions
3. Unfilled annotation forms get a red highlight
4. Error clears when all required fields are filled
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
from tests.helpers.test_utils import cleanup_test_directory, create_test_data_file


import pytest


pytestmark = pytest.mark.core

def create_required_fields_config(test_dir, port):
    """Create a config with two required annotation schemes."""
    test_data = [
        {"id": f"item_{i}", "text": f"Test sentence number {i} for annotation."}
        for i in range(1, 6)
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": f"Required Fields Test {port}",
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
                "label_requirement": {"required": True},
            },
            {
                "name": "topic",
                "annotation_type": "radio",
                "labels": ["sports", "politics", "tech"],
                "description": "What is the topic?",
                "label_requirement": {"required": True},
            },
        ],
        "assignment_strategy": "fixed_order",
        "max_annotations_per_user": 5,
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


class TestRequiredFieldErrorsUI(unittest.TestCase):
    """Tests for required field validation error messages in the UI."""

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", f"required_fields_ui_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_required_fields_config(cls.test_dir, cls.port)

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
        self.test_user = f"reqfield_user_{int(time.time() * 1000)}"

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

    def _attempt_next(self):
        """Click Next with required fields empty and wait for the errors to show."""
        # navigateToNext() ignores clicks while the instance is still loading
        WebDriverWait(self.driver, 10).until(
            lambda d: d.execute_script(
                "return typeof isLoading !== 'undefined' && !isLoading;")
        )
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, "next-btn"))
        ).click()
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "required-fields-error"))
        )

    def test_next_blocked_when_required_fields_empty(self):
        """Clicking Next with required fields empty should not navigate."""
        self._login()
        instance_id = self.driver.find_element(By.ID, "instance_id").get_attribute("value")

        self._attempt_next()

        self.assertEqual(
            self.driver.find_element(By.ID, "instance_id").get_attribute("value"),
            instance_id,
            "Next should not navigate while required fields are empty")

    def test_error_message_appears_when_required_fields_empty(self):
        """An error message div should be visible listing unfilled required questions."""
        self._login()
        self._attempt_next()

        error_text = self.driver.find_element(By.ID, "required-fields-error").text
        # Should mention the question descriptions
        self.assertIn("sentiment", error_text.lower(),
                      "Error should mention the unfilled sentiment question")

    def test_unfilled_forms_have_red_highlight(self):
        """Unfilled required annotation forms should have the 'required-unfilled' CSS class."""
        self._login()
        self._attempt_next()

        unfilled_forms = self.driver.find_elements(By.CSS_SELECTOR, ".annotation-form.required-unfilled")
        self.assertEqual(len(unfilled_forms), 2,
                         "Both required annotation forms should have required-unfilled class")

    def test_filling_one_field_still_shows_error_for_other(self):
        """Filling one required field should remove its highlight but keep the other's."""
        self._login()
        self._attempt_next()

        # Click a radio button in the sentiment scheme
        radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']")
        self.assertGreater(len(radios), 0, "Sentiment radio buttons should exist")

        radio_id = radios[0].get_attribute("id")
        label = self.driver.find_element(By.CSS_SELECTOR, f"label[for='{radio_id}']")
        label.click()

        # Sentiment form should no longer have required-unfilled
        sentiment_form = self.driver.find_element(By.CSS_SELECTOR, "form[data-schema-name='sentiment']")
        WebDriverWait(self.driver, 10).until(
            lambda d: "required-unfilled" not in (sentiment_form.get_attribute("class") or ""),
            "Filled sentiment form should not have required-unfilled class")

        # Topic form should still have required-unfilled
        topic_form = self.driver.find_element(By.CSS_SELECTOR, "form[data-schema-name='topic']")
        self.assertIn("required-unfilled", topic_form.get_attribute("class") or "",
                       "Unfilled topic form should still have required-unfilled class")

        # The error should still be listed for the unfilled topic question
        self.assertTrue(self.driver.find_element(By.ID, "required-fields-error").is_displayed(),
                        "Error should remain visible with one unfilled required field")

    def test_filling_all_fields_enables_next_and_clears_error(self):
        """Filling all required fields should enable Next and hide the error message."""
        self._login()
        time.sleep(0.5)

        # Fill sentiment
        radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']")
        radio_id = radios[0].get_attribute("id")
        self.driver.find_element(By.CSS_SELECTOR, f"label[for='{radio_id}']").click()
        time.sleep(0.3)

        # Fill topic
        radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio'][schema='topic']")
        radio_id = radios[0].get_attribute("id")
        self.driver.find_element(By.CSS_SELECTOR, f"label[for='{radio_id}']").click()
        time.sleep(0.5)

        # Next button should be enabled
        next_btn = self.driver.find_element(By.ID, "next-btn")
        self.assertFalse(next_btn.get_attribute("disabled"),
                         "Next button should be enabled when all required fields are filled")

        # No forms should have required-unfilled
        unfilled_forms = self.driver.find_elements(By.CSS_SELECTOR, ".annotation-form.required-unfilled")
        self.assertEqual(len(unfilled_forms), 0,
                         "No forms should have required-unfilled class when all fields are filled")

        # Error message should be hidden
        error_div = self.driver.find_elements(By.ID, "required-fields-error")
        if error_div:
            self.assertFalse(error_div[0].is_displayed(),
                             "Error message should be hidden when all required fields are filled")


if __name__ == "__main__":
    unittest.main()
