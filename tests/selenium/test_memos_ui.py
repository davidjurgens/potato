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
        uid = self.uid = f"memo_user_{int(time.time()*1000)}"
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
        # Navigation is a full page reload, so waiting for #instance_id to be
        # *present* proves nothing -- the pre-navigation element satisfies it
        # immediately, and the following read returns the old instance id.
        # Wait for the old node to go stale first.
        old = self.driver.find_element(By.ID, "instance_id")
        self.driver.find_element(By.ID, button_id).click()
        self.wait.until(EC.staleness_of(old))
        self.wait.until(EC.presence_of_element_located((By.ID, "instance_id")))

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

    # --- composer visibility -------------------------------------------

    def _server_memos(self):
        """{body: visibility} for this instance, read from the server."""
        return self.driver.execute_async_script(
            "var done = arguments[arguments.length - 1];"
            "fetch('/api/memos?instance_id=' + encodeURIComponent(arguments[0]),"
            " {credentials: 'same-origin'}).then(r => r.json())"
            ".then(d => { var out = {}; (d.memos || []).forEach(m => out[m.body] = m.visibility);"
            " done(out); }, () => done(null));",
            self._instance_id())

    def _visibility_select(self):
        from selenium.webdriver.support.ui import Select
        return Select(self.driver.find_element(By.ID, "memo-new-visibility"))

    def _edit_memo(self, body, new_body):
        """Click Edit on the memo whose text is ``body`` and save ``new_body``."""
        item = self.wait.until(EC.presence_of_element_located((
            By.XPATH, f"//*[@id='memo-list']//*[contains(text(), '{body}')]"
                      f"/ancestor::*[.//button[@data-act='edit']][1]")))
        item.find_element(By.CSS_SELECTOR, "button[data-act='edit']").click()
        ta = self.driver.find_element(By.ID, "memo-new-body")
        self.assertEqual(ta.get_attribute("value"), body)
        ta.clear()
        ta.send_keys(new_body)
        self.driver.find_element(By.ID, "memo-add-btn").click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "memo-list"), new_body))

    def test_editing_a_shared_memo_does_not_leave_the_composer_shared(self):
        """startEdit copies the memo's visibility into the select. The
        composer has to return to the project default afterwards, or every
        later note silently goes out shared."""
        self._open_panel()
        self.assertEqual(
            self._visibility_select().first_selected_option.get_attribute("value"),
            "private")
        ta = self.driver.find_element(By.ID, "memo-new-body")
        ta.send_keys("shared on purpose")
        self._visibility_select().select_by_value("shared")
        self.driver.find_element(By.ID, "memo-add-btn").click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "memo-list"), "shared on purpose"))

        self._edit_memo("shared on purpose", "shared on purpose, edited")
        self.assertEqual(
            self._visibility_select().first_selected_option.get_attribute("value"),
            "private",
            "after saving an edit to a shared memo the composer stayed Shared")

        self.driver.find_element(By.ID, "memo-new-body").send_keys("next note")
        self.driver.find_element(By.ID, "memo-add-btn").click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "memo-list"), "next note"))
        stored = self._server_memos()
        self.assertEqual(stored.get("shared on purpose, edited"), "shared")
        self.assertEqual(stored.get("next note"), "private")


class TestMemosDefaultVisibilityUI(TestMemosUI):
    """`annotation_ui.visibility: shared` makes the composer start Shared.

    Inherits the login/navigation helpers; the parent's tests are not
    re-run here (see ``__test__`` handling below)."""

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
            tests_dir, "output", f"memos_visibility_ui_test_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(cls.test_dir, [
            {"id": "v1", "text": "first instance text"},
            {"id": "v2", "text": "second instance text"},
        ])
        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes=[{
                "name": "label", "description": "Pick",
                "annotation_type": "radio", "labels": ["a", "b"],
            }],
            data_files=[data_file],
            annotation_task_name="Memos Visibility UI Test",
            require_password=False,
            additional_config={"annotation_ui": {"memos": True,
                                                 "visibility": "shared"}},
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

    # The parent's tests assume the private default; skip them here.
    test_memo_survives_navigate_away_and_back = None
    test_memo_not_shown_on_other_instance = None
    test_editing_a_shared_memo_does_not_leave_the_composer_shared = None

    def test_the_composer_starts_on_the_configured_default(self):
        self._open_panel()
        self.assertEqual(
            self._visibility_select().first_selected_option.get_attribute("value"),
            "shared")
        self.driver.find_element(By.ID, "memo-new-body").send_keys("default note")
        self.driver.find_element(By.ID, "memo-add-btn").click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "memo-list"), "default note"))
        self.assertEqual(self._server_memos().get("default note"), "shared",
                         "the note was not posted with the project default")

    def test_editing_a_private_memo_returns_the_composer_to_shared(self):
        self._open_panel()
        self.driver.find_element(By.ID, "memo-new-body").send_keys("just mine")
        self._visibility_select().select_by_value("private")
        self.driver.find_element(By.ID, "memo-add-btn").click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "memo-list"), "just mine"))
        # After a plain add the composer is back on the default too.
        self.assertEqual(
            self._visibility_select().first_selected_option.get_attribute("value"),
            "shared")

        self._edit_memo("just mine", "just mine, edited")
        self.assertEqual(
            self._visibility_select().first_selected_option.get_attribute("value"),
            "shared")
        self.assertEqual(self._server_memos().get("just mine, edited"), "private")


if __name__ == "__main__":
    unittest.main()
