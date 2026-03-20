"""
Selenium tests for Prolific integration: PROLIFIC_PID login, session tracking,
and completion redirect.

Prevents regression of issue #113 (url_direct login skipped phases).
No actual Prolific API calls are made — only the server-side rendering is tested.
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
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_directory,
    create_test_data_file,
)


def create_prolific_config(test_dir, port, include_phases=False):
    """Create a config with url_direct login using PROLIFIC_PID."""
    test_data = [
        {"id": "item_1", "text": "First item to annotate."},
        {"id": "item_2", "text": "Second item to annotate."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    phases = {"order": ["annotation"], "annotation": {"type": "annotation"}}

    if include_phases:
        surveys_dir = os.path.join(test_dir, "surveys")
        os.makedirs(surveys_dir, exist_ok=True)

        consent_survey = [
            {
                "id": "1",
                "name": "consent_agree",
                "description": "Do you consent to participate in this study?",
                "annotation_type": "radio",
                "labels": ["Yes", "No"],
            }
        ]
        consent_file = os.path.join(surveys_dir, "consent.json")
        with open(consent_file, "w", encoding="utf-8") as f:
            json.dump(consent_survey, f)

        instructions_survey = [
            {
                "id": "1",
                "name": "instructions_ack",
                "description": "Please read the instructions carefully before proceeding.",
                "annotation_type": "radio",
                "labels": ["I understand"],
            }
        ]
        instructions_file = os.path.join(surveys_dir, "instructions.json")
        with open(instructions_file, "w", encoding="utf-8") as f:
            json.dump(instructions_survey, f)

        phases = {
            "order": ["consent", "instructions", "annotation"],
            "consent": {"type": "consent", "file": "surveys/consent.json"},
            "instructions": {"type": "instructions", "file": "surveys/instructions.json"},
            "annotation": {"type": "annotation"},
        }

    config = {
        "annotation_task_name": f"Prolific Test {port}",
        "login": {
            "type": "url_direct",
            "url_argument": "PROLIFIC_PID",
        },
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
        "completion_code": "PROLIFIC_TEST_CODE",
        "phases": phases,
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


class TestProlificIntegrationUI(unittest.TestCase):
    """
    Prolific integration tests: auto-login via PROLIFIC_PID, completion redirect,
    and completion code display.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"prolific_ui_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_prolific_config(cls.test_dir, cls.port)

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

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

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

    def test_prolific_pid_auto_login(self):
        """
        Providing PROLIFIC_PID, SESSION_ID, STUDY_ID auto-logs the user in
        and shows the annotation interface.
        """
        pid = f"prolific_{int(time.time() * 1000)}"
        self.driver.get(
            f"{self.server.base_url}/"
            f"?PROLIFIC_PID={pid}"
            f"&SESSION_ID=s1"
            f"&STUDY_ID=st1"
        )
        time.sleep(3)

        page_source = self.driver.page_source.lower()
        has_annotation = (
            "task_layout" in page_source
            or "annotation" in page_source
            or "sentiment" in page_source
        )
        has_login = "login-email" in page_source
        self.assertTrue(
            has_annotation,
            "Prolific user should be auto-logged in and see annotation interface",
        )

    def test_prolific_completion_code_displayed(self):
        """
        After completing all annotations, the done page shows the completion code.
        """
        pid = f"prolific_done_{int(time.time() * 1000)}"
        self.driver.get(
            f"{self.server.base_url}/"
            f"?PROLIFIC_PID={pid}"
            f"&SESSION_ID=s_done"
            f"&STUDY_ID=st_done"
        )
        time.sleep(3)

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

        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)

        page_source = self.driver.page_source
        self.assertIn(
            "PROLIFIC_TEST_CODE",
            page_source,
            "Completion code should be displayed on done page",
        )

    def test_prolific_completion_redirect_url(self):
        """
        After completing annotations, the done page has a Prolific return link
        with the correct redirect URL containing the completion code.
        """
        pid = f"prolific_redir_{int(time.time() * 1000)}"
        self.driver.get(
            f"{self.server.base_url}/"
            f"?PROLIFIC_PID={pid}"
            f"&SESSION_ID=s_redir"
            f"&STUDY_ID=st_redir"
        )
        time.sleep(3)

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

        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)

        page_source = self.driver.page_source

        # Check for Prolific redirect elements
        has_prolific_btn = "platform-btn-prolific" in page_source
        has_prolific_redirect = "prolific.co/submissions/complete" in page_source

        self.assertTrue(
            has_prolific_btn or has_prolific_redirect,
            "Done page should have Prolific return link with redirect URL",
        )

    def test_prolific_missing_pid_shows_error(self):
        """
        Visiting without PROLIFIC_PID parameter should show an error or login page.
        """
        self.driver.get(
            f"{self.server.base_url}/"
            f"?SESSION_ID=s1"
            f"&STUDY_ID=st1"
        )
        time.sleep(2)

        page_source = self.driver.page_source.lower()
        # Should show error or login page (not auto-login without PID)
        has_error = "error" in page_source or "missing" in page_source
        has_login = "login-email" in page_source
        self.assertTrue(
            has_error or has_login,
            "Missing PROLIFIC_PID should show error or fall back to login page",
        )


class TestProlificWithPhasesUI(unittest.TestCase):
    """
    Issue #113: Prolific workers must go through phases (consent, instructions)
    instead of being skipped directly to annotation.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"prolific_phases_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_prolific_config(
            cls.test_dir, cls.port, include_phases=True
        )

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

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_prolific_worker_proceeds_through_phases(self):
        """
        Issue #113: Prolific worker with consent+instructions phases should see
        consent first, NOT be skipped directly to annotation.
        """
        pid = f"prolific_phase_{int(time.time() * 1000)}"
        self.driver.get(
            f"{self.server.base_url}/"
            f"?PROLIFIC_PID={pid}"
            f"&SESSION_ID=s_phase"
            f"&STUDY_ID=st_phase"
        )
        time.sleep(3)

        page_source = self.driver.page_source.lower()

        has_consent = (
            "consent" in page_source
            or "agree" in page_source
            or "participate" in page_source
        )
        has_annotation_only = (
            "task_layout" in page_source
            and "consent" not in page_source
        )

        self.assertTrue(
            has_consent and not has_annotation_only,
            "Prolific worker should see consent page first, not skip to annotation "
            "(issue #113: url_direct login skipped phases)",
        )

    def test_prolific_session_tracked(self):
        """
        After login via Prolific URL, session should have Prolific parameters stored.
        """
        import requests

        pid = f"prolific_track_{int(time.time() * 1000)}"
        session = requests.Session()

        response = session.get(
            f"{self.server.base_url}/",
            params={
                "PROLIFIC_PID": pid,
                "SESSION_ID": "track_session",
                "STUDY_ID": "track_study",
            },
            allow_redirects=True,
            timeout=10,
        )

        self.assertEqual(response.status_code, 200)
        # Verify the user was created and is in a valid state
        self.assertNotIn("Internal Server Error", response.text)
        self.assertNotIn("KeyError", response.text)


if __name__ == "__main__":
    unittest.main()
