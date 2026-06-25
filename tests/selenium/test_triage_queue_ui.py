"""
Selenium UI tests for the signal-based triage queue.

Covers BOTH surfaces:
- the inline triage banner on the annotation page (why this item was prioritized),
- the admin triage-queue report page (ranked table).

No LLM / external service — the quality signals live in the static data file.
Runs with debug=True so the admin key check is bypassed for the report assertion.
"""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
)

import pytest

pytestmark = pytest.mark.core


class TestTriageQueueUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("triage_queue_ui")
        data = [
            {"id": "ok1", "text": "A clean trace that succeeded.", "status": "ok", "score": 0.9},
            {"id": "bad1", "text": "A trace where the agent errored.", "status": "error"},
        ]
        data_file = create_test_data_file(cls.test_dir, data, filename="triage.jsonl")
        schemes = [{"annotation_type": "radio", "name": "trace_quality",
                    "description": "Rate this trace",
                    "labels": ["good", "needs_fix", "broken"]}]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[data_file],
            additional_config={
                "item_properties": {"id_key": "id", "text_key": "text"},
                "assignment_strategy": "priority",
                "max_annotations_per_item": -1,
                "triage": {
                    "enabled": True,
                    "rules": [
                        {"name": "Agent errored", "badge": "Agent errored",
                         "priority": 100, "when": {"field": "status", "equals": "error"}},
                    ],
                },
            },
        )

        port = find_free_port(preferred_port=9081)
        cls.server = FlaskTestServer(port=port, debug=True, config_file=cls.config_file)
        assert cls.server.start(), "server failed to start"

        cls.opts = ChromeOptions()
        for a in ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-gpu", "--window-size=1500,1100"]:
            cls.opts.add_argument(a)
        cls.opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.opts)
        self.user = f"tq_ui_{int(time.time() * 1000)}"
        self._login()

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email")))
        try:
            self.driver.find_element(By.ID, "register-tab").click()
            WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.ID, "register-content")))
            self.driver.find_element(By.ID, "register-email").send_keys(self.user)
            self.driver.find_element(By.ID, "register-pass").send_keys("test123")
            self.driver.find_element(By.CSS_SELECTOR, "#register-content form").submit()
        except NoSuchElementException:
            f = self.driver.find_element(By.ID, "login-email")
            f.clear(); f.send_keys(self.user)
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(0.5)
        try:
            WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.ID, "main-content")))
        except TimeoutException:
            pass

    # --- inline surface ---

    def test_triage_badge_renders_with_reason(self):
        # PRIORITY strategy serves the errored trace (priority 100) first, and
        # the banner explains why.
        block = WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "triage-flag")))
        self.assertIn("Prioritized", block.text)
        reason = self.driver.find_element(By.CSS_SELECTOR, ".triage-flag-reason")
        self.assertEqual(reason.text, "Agent errored")

    # --- admin report surface ---

    def test_admin_queue_renders_ranked_table(self):
        # debug=True bypasses the admin key check.
        self.driver.get(f"{self.server.base_url}/admin/triage-queue?format=html")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1")))
        body = self.driver.page_source
        self.assertIn("Triage Queue", body)
        self.assertIn("Agent errored", body)
        # The errored item should be the first data row (highest priority).
        first_row_id = self.driver.find_element(
            By.CSS_SELECTOR, "table.tq-table tbody tr th.tq-rowhead").text
        self.assertEqual(first_row_id, "bad1")


if __name__ == "__main__":
    unittest.main()
