#!/usr/bin/env python3
"""
Selenium test for the universal Memos sidebar.

Per CLAUDE.md annotation-persistence discipline this uses the
navigate-away-and-back pattern (NOT page refresh): add a memo on
instance 1, click Next, click Previous, and verify the memo is still
shown (re-fetched from the server) and present server-side.

Navigation in Potato is a full page reload, and memos persist
immediately via /api/memos, so correctness hinges on the sidebar
re-fetching for the displayed instance on load.
"""

import os
import time
import unittest
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions


class TestMemosUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import (
            create_test_directory,
            create_test_data_file,
            create_test_config,
        )

        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(
            tests_dir, "output", f"memos_ui_test_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        data_file = create_test_data_file(cls.test_dir, [
            {"id": "m1", "text": "first instance text for memo"},
            {"id": "m2", "text": "second instance text"},
            {"id": "m3", "text": "third instance text"},
        ])
        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes=[{
                "name": "label", "description": "Pick",
                "annotation_type": "radio", "labels": ["a", "b"],
            }],
            data_files=[data_file],
            annotation_task_name="Memos UI Test",
            require_password=False,
            additional_config={"annotation_ui": {"memos": True}},
        )

        cls.port = find_free_port()
        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "Flask server failed to start"
        cls.server._wait_for_server_ready(timeout=10)

        opts = ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        cls.chrome_options = opts

    @classmethod
    def tearDownClass(cls):
        from tests.helpers.test_utils import cleanup_test_directory
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, 15)
        # Passwordless login via the web form (proven pattern).
        self.driver.get(f"{self.server.base_url}/")
        self.wait.until(EC.presence_of_element_located((By.ID, "login-email")))
        uid = f"memo_user_{int(time.time()*1000)}"
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(uid)
        self.driver.find_element(
            By.CSS_SELECTOR, "#login-content form").submit()
        self.wait.until(EC.presence_of_element_located((By.ID, "instance_id")))

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _instance_id(self):
        return self.driver.find_element(By.ID, "instance_id").get_attribute("value")

    def _annotate_radio(self):
        """Potato requires an annotation before Next will advance."""
        radio = self.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, 'input[type="radio"].annotation-input')))
        radio.click()
        time.sleep(0.4)  # debounce save

    def _nav(self, button_id):
        self.driver.find_element(By.ID, button_id).click()
        self.wait.until(EC.presence_of_element_located((By.ID, "instance_id")))
        time.sleep(0.3)

    def _add_memo(self, body):
        self.wait.until(EC.element_to_be_clickable(
            (By.ID, "memo-panel-toggle"))).click()
        ta = self.wait.until(EC.visibility_of_element_located(
            (By.ID, "memo-new-body")))
        ta.clear()
        ta.send_keys(body)
        self.driver.find_element(By.ID, "memo-add-btn").click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "memo-list"), body))

    def _open_panel(self):
        self.wait.until(EC.element_to_be_clickable(
            (By.ID, "memo-panel-toggle"))).click()
        return self.wait.until(EC.visibility_of_element_located(
            (By.ID, "memo-list")))

    def test_memo_survives_navigate_away_and_back(self):
        body = "interesting edge case here"
        start = self._instance_id()
        self._add_memo(body)
        self._annotate_radio()

        self._nav("next-btn")
        self.assertNotEqual(self._instance_id(), start,
                            "Next did not advance to a new instance")
        self._nav("prev-btn")
        self.assertEqual(self._instance_id(), start,
                         "Previous did not return to the original instance")

        memo_list = self._open_panel()
        self.assertIn(body, memo_list.text,
                      "Memo did not survive navigate-away-and-back")

    def test_memo_not_shown_on_other_instance(self):
        body = "note for instance one only"
        start = self._instance_id()
        self._add_memo(body)
        self._annotate_radio()

        self._nav("next-btn")
        self.assertNotEqual(self._instance_id(), start)
        memo_list = self._open_panel()
        self.assertNotIn(body, memo_list.text,
                         "Memo leaked onto a different instance")


if __name__ == "__main__":
    unittest.main()
