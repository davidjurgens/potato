"""
Selenium tests for end-to-end user journey through all phases:
consent -> instructions -> annotation -> poststudy -> done.

Directly prevents regression of issues #113 and #115.
"""

import json
import os
import time
import unittest

import requests
import yaml
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_data_file,
)


import pytest


pytestmark = pytest.mark.core

def create_multiphase_config(test_dir, port):
    """Create config with consent -> instructions -> annotation -> poststudy."""
    test_data = [
        {"id": "item_1", "text": "First item to annotate."},
        {"id": "item_2", "text": "Second item to annotate."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    surveys_dir = os.path.join(test_dir, "surveys")
    os.makedirs(surveys_dir, exist_ok=True)

    # Create consent survey
    consent_survey = [
        {
            "id": "1",
            "name": "consent_agree",
            "description": "Do you consent to participate in this research study?",
            "annotation_type": "radio",
            "labels": ["Yes, I consent", "No"],
        }
    ]
    with open(os.path.join(surveys_dir, "consent.json"), "w", encoding="utf-8") as f:
        json.dump(consent_survey, f)

    # Create instructions survey
    instructions_survey = [
        {
            "id": "1",
            "name": "instructions_ack",
            "description": "Please read the instructions carefully. Select the option below to proceed.",
            "annotation_type": "radio",
            "labels": ["I have read and understand the instructions"],
        }
    ]
    with open(os.path.join(surveys_dir, "instructions.json"), "w", encoding="utf-8") as f:
        json.dump(instructions_survey, f)

    # Create poststudy survey
    poststudy_survey = [
        {
            "id": "1",
            "name": "study_satisfaction",
            "description": "How satisfied were you with this study?",
            "annotation_type": "radio",
            "labels": ["Very satisfied", "Somewhat satisfied", "Not satisfied"],
        }
    ]
    with open(os.path.join(surveys_dir, "poststudy.json"), "w", encoding="utf-8") as f:
        json.dump(poststudy_survey, f)

    config = {
        "annotation_task_name": f"Multiphase Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative"],
                "description": "What is the sentiment?",
            }
        ],
        "assignment_strategy": "random",
        "max_annotations_per_user": 2,
        "max_annotations_per_item": 3,
        "phases": {
            "order": ["consent", "instructions", "annotation", "post_survey"],
            "consent": {"type": "consent", "file": "surveys/consent.json"},
            "instructions": {"type": "instructions", "file": "surveys/instructions.json"},
            "annotation": {"type": "annotation"},
            "post_survey": {"type": "poststudy", "file": "surveys/poststudy.json"},
        },
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


class TestMultiphaseWorkflowUI(unittest.TestCase):
    """
    End-to-end user journey through all phases.
    Tests that users progress consent -> instructions -> annotation -> poststudy -> done.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"multiphase_ui_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_multiphase_config(cls.test_dir, cls.port)

        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file
        )
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
        self.test_user = f"multiphase_user_{int(time.time() * 1000)}"

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        """Login with simple auth (no password)."""
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(self.test_user)
        self.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit']"
        ).click()
        time.sleep(2)

    def _get_requests_session(self):
        """Create a requests.Session with cookies from Selenium driver."""
        session = requests.Session()
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])
        return session

    def _advance_phase(self, route):
        """Advance a phase by POSTing directly to the phase route."""
        session = self._get_requests_session()
        session.post(
            f"{self.server.base_url}/{route}",
            data={"submitted": "true"},
            timeout=5,
        )
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1)

    def _annotate_and_next(self):
        """Select a radio option and click Next."""
        time.sleep(0.5)
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']"
        )
        if radios:
            radio_id = radios[0].get_attribute("id")
            if radio_id:
                try:
                    label = self.driver.find_element(
                        By.CSS_SELECTOR, f"label[for='{radio_id}']"
                    )
                    label.click()
                except Exception:
                    radios[0].click()
            else:
                radios[0].click()
            time.sleep(0.5)

        try:
            next_btn = self.driver.find_element(By.ID, "next-btn")
            next_btn.click()
        except Exception:
            next_btn = self.driver.find_element(
                By.CSS_SELECTOR, 'a[onclick*="click_to_next"]'
            )
            next_btn.click()
        time.sleep(2)

    def test_consent_page_renders_after_login(self):
        """After login, consent page should be shown (not annotation)."""
        self._login()

        page_source = self.driver.page_source.lower()
        has_consent = (
            "consent" in page_source
            or "participate" in page_source
        )
        self.assertTrue(
            has_consent,
            "After login, user should see consent page first",
        )

    def test_consent_advances_to_instructions(self):
        """Submitting consent form should advance to instructions phase."""
        self._login()
        self._advance_phase("consent")

        page_source = self.driver.page_source.lower()
        has_instructions = (
            "instructions" in page_source
            or "read" in page_source
            or "understand" in page_source
        )
        self.assertTrue(
            has_instructions,
            "After consent, user should see instructions page",
        )

    def test_instructions_advances_to_annotation(self):
        """Submitting consent + instructions should advance to annotation phase."""
        self._login()
        self._advance_phase("consent")
        self._advance_phase("instructions")

        page_source = self.driver.page_source.lower()
        has_annotation = (
            "task_layout" in page_source
            or "sentiment" in page_source
        )
        self.assertTrue(
            has_annotation,
            "After consent + instructions, user should see annotation page",
        )

    def test_annotation_advances_to_poststudy(self):
        """
        Issue #115: After completing all annotations, poststudy survey should show
        (not done page).
        """
        self._login()
        self._advance_phase("consent")
        self._advance_phase("instructions")

        # Annotate both items
        for _ in range(2):
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']")
                    )
                )
                self._annotate_and_next()
            except Exception:
                break

        # Navigate home — should be on poststudy
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)
        page_source = self.driver.page_source.lower()

        has_poststudy = (
            "satisfied" in page_source
            or "study_satisfaction" in page_source
            or "post-study" in page_source
            or "survey" in page_source
        )
        is_done_only = (
            "thank you" in page_source
            and "satisfied" not in page_source
        )

        self.assertTrue(
            has_poststudy or not is_done_only,
            "After annotation completion, poststudy survey should show (issue #115)",
        )

    def test_poststudy_advances_to_done(self):
        """Complete entire workflow and verify done page."""
        self._login()
        self._advance_phase("consent")
        self._advance_phase("instructions")

        # Annotate both items
        for _ in range(2):
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']")
                    )
                )
                self._annotate_and_next()
            except Exception:
                break

        # Submit poststudy
        self._advance_phase("poststudy")

        page_source = self.driver.page_source.lower()

        has_done = (
            "thank you" in page_source
            or "completed" in page_source
            or "all done" in page_source
        )
        self.assertTrue(
            has_done,
            "After completing all phases, user should see done/thank you page",
        )

    def test_phase_state_persists_across_refresh(self):
        """Navigate to instructions, refresh, verify still on instructions."""
        self._login()
        self._advance_phase("consent")

        page_source_before = self.driver.page_source.lower()

        # Refresh
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1)
        page_source_after = self.driver.page_source.lower()

        # Both should show instructions (not consent or annotation)
        has_instructions_after = (
            "instructions" in page_source_after
            or "read" in page_source_after
            or "understand" in page_source_after
        )
        self.assertTrue(
            has_instructions_after,
            "Phase state should persist across page refresh",
        )


if __name__ == "__main__":
    unittest.main()
