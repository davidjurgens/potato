"""
Selenium tests for MTurk integration: url_direct login, preview mode, and completion flow.

Prevents regression of issue #113 (url_direct login skipped phases).
No actual MTurk API calls are made — only the server-side rendering is tested.
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


def create_mturk_config(test_dir, port, include_consent=False):
    """Create a config with url_direct login using workerId for MTurk."""
    test_data = [
        {"id": "item_1", "text": "First item to annotate."},
        {"id": "item_2", "text": "Second item to annotate."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    phases = {"order": ["annotation"], "annotation": {"type": "annotation"}}

    if include_consent:
        surveys_dir = os.path.join(test_dir, "surveys")
        os.makedirs(surveys_dir, exist_ok=True)
        consent_survey = [
            {
                "id": "1",
                "name": "consent_agree",
                "description": "Do you consent to participate?",
                "annotation_type": "radio",
                "labels": ["Yes", "No"],
            }
        ]
        consent_file = os.path.join(surveys_dir, "consent.json")
        with open(consent_file, "w", encoding="utf-8") as f:
            json.dump(consent_survey, f)
        phases = {
            "order": ["consent", "annotation"],
            "consent": {"type": "consent", "file": "surveys/consent.json"},
            "annotation": {"type": "annotation"},
        }

    config = {
        "annotation_task_name": f"MTurk Test {port}",
        "login": {
            "type": "url_direct",
            "url_argument": "workerId",
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
        "completion_code": "MTURK_TEST_CODE",
        "task_description": "This is a test MTurk annotation task.",
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


class TestMTurkIntegrationUI(unittest.TestCase):
    """
    MTurk integration tests: preview mode, auto-login, phase workflow,
    completion with submit form and completion code.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"mturk_ui_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_mturk_config(cls.test_dir, cls.port)

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
        self.test_user = f"mturk_w_{int(time.time() * 1000)}"

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

    def test_mturk_preview_mode(self):
        """
        When assignmentId=ASSIGNMENT_ID_NOT_AVAILABLE, MTurk preview page renders.
        """
        self.driver.get(
            f"{self.server.base_url}/"
            f"?workerId={self.test_user}"
            f"&assignmentId=ASSIGNMENT_ID_NOT_AVAILABLE"
            f"&hitId=hit1"
        )
        time.sleep(2)

        page_source = self.driver.page_source
        self.assertIn(
            "Accept the HIT to Begin",
            page_source,
            "MTurk preview page should show 'Accept the HIT to Begin'",
        )

    def test_mturk_worker_auto_login(self):
        """
        Providing workerId, assignmentId, hitId auto-logs the worker in
        and shows the annotation interface.
        """
        self.driver.get(
            f"{self.server.base_url}/"
            f"?workerId={self.test_user}"
            f"&assignmentId=a1"
            f"&hitId=h1"
            f"&turkSubmitTo=https://workersandbox.mturk.com"
        )
        time.sleep(3)

        # Should see annotation interface, not login page
        page_source = self.driver.page_source.lower()
        has_annotation = (
            "task_layout" in page_source
            or "annotation" in page_source
            or "sentiment" in page_source
        )
        has_login = "login-email" in page_source and "submit" in page_source
        self.assertTrue(
            has_annotation and not has_login,
            "Worker should be auto-logged in and see annotation interface",
        )

    def test_mturk_completion_code_displayed(self):
        """
        After completing all annotations, the done page shows the completion code.
        """
        self.driver.get(
            f"{self.server.base_url}/"
            f"?workerId={self.test_user}"
            f"&assignmentId=a_done"
            f"&hitId=h_done"
            f"&turkSubmitTo=https://workersandbox.mturk.com"
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

        # Navigate to home to reach done page
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)

        page_source = self.driver.page_source
        self.assertIn(
            "MTURK_TEST_CODE",
            page_source,
            "Completion code should be displayed on done page",
        )

    def test_mturk_completion_shows_submit_form(self):
        """
        After completing annotations, the done page has the MTurk submit form
        with assignmentId hidden input.
        """
        worker_id = f"mturk_submit_{int(time.time() * 1000)}"
        self.driver.get(
            f"{self.server.base_url}/"
            f"?workerId={worker_id}"
            f"&assignmentId=assign_123"
            f"&hitId=h_submit"
            f"&turkSubmitTo=https://workersandbox.mturk.com"
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

        # Check for MTurk form elements
        has_mturk_form = "mturk-form" in page_source
        has_assignment_id = "assignmentId" in page_source
        has_submit_btn = "Submit HIT" in page_source

        self.assertTrue(
            has_mturk_form or has_assignment_id or has_submit_btn,
            "Done page should have MTurk submit form with assignmentId",
        )

    def test_mturk_missing_workerid_shows_error(self):
        """
        Visiting without workerId parameter should show an error.
        """
        self.driver.get(
            f"{self.server.base_url}/"
            f"?assignmentId=test_assign"
            f"&hitId=h_err"
        )
        time.sleep(2)

        page_source = self.driver.page_source.lower()
        # Should show error or login page (not auto-login without workerId)
        has_error = "error" in page_source or "missing" in page_source
        has_login = "login-email" in page_source
        self.assertTrue(
            has_error or has_login,
            "Missing workerId should show error or fall back to login page",
        )


class TestMTurkWithPhasesUI(unittest.TestCase):
    """
    Issue #113: MTurk workers must go through phases (consent, etc.)
    instead of being skipped directly to annotation.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"mturk_phases_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_mturk_config(
            cls.test_dir, cls.port, include_consent=True
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

    def test_mturk_worker_proceeds_through_phases(self):
        """
        Issue #113: MTurk worker with consent phase should see consent first,
        NOT be skipped directly to annotation.
        """
        worker_id = f"mturk_phase_{int(time.time() * 1000)}"
        self.driver.get(
            f"{self.server.base_url}/"
            f"?workerId={worker_id}"
            f"&assignmentId=a_phase"
            f"&hitId=h_phase"
            f"&turkSubmitTo=https://workersandbox.mturk.com"
        )
        time.sleep(3)

        page_source = self.driver.page_source.lower()

        # Should see consent page content, NOT annotation interface directly
        has_consent = (
            "consent" in page_source
            or "agree" in page_source
            or "participate" in page_source
        )
        # Should NOT be on annotation page already
        has_annotation_only = (
            "task_layout" in page_source
            and "consent" not in page_source
        )

        self.assertTrue(
            has_consent and not has_annotation_only,
            "MTurk worker should see consent page first, not skip to annotation "
            "(issue #113: url_direct login skipped phases)",
        )


if __name__ == "__main__":
    unittest.main()
