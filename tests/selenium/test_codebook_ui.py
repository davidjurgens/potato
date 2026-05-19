#!/usr/bin/env python3
"""
Selenium test for the universal Codebook tray.

Verifies the tray only appears when a codebook is enabled, that seeded
codes render, that the on-the-fly composer is shown in `open` mode, and
that adding a code reflects in the tray without a reload.
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


def _chrome():
    o = ChromeOptions()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu", "--window-size=1600,1000"):
        o.add_argument(a)
    return o


def _login(driver, wait, base_url, uid):
    driver.get(f"{base_url}/")
    wait.until(EC.presence_of_element_located((By.ID, "login-email")))
    f = driver.find_element(By.ID, "login-email")
    f.clear()
    f.send_keys(uid)
    driver.find_element(By.CSS_SELECTOR, "#login-content form").submit()
    wait.until(EC.presence_of_element_located((By.ID, "instance_id")))


_CB_SCHEME = [{
    "name": "code", "description": "Codebook scheme",
    "annotation_type": "radio", "codebook": True,
    "labels": ["seed-a", "seed-b"],
}]


class TestCodebookTrayOpenMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import (
            create_test_data_file, create_test_config)
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(
            tests_dir, "output", f"cb_ui_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(
            cls.test_dir, [{"id": "c1", "text": "an instance"}])
        cls.config_file = create_test_config(
            cls.test_dir, _CB_SCHEME, data_files=[data_file],
            annotation_task_name="Codebook UI Test",
            require_password=False,
            additional_config={"codebook_mode": "open"})
        cls.port = find_free_port()
        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "server did not start"
        cls.server._wait_for_server_ready(timeout=10)
        cls.chrome_options = _chrome()

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
        _login(self.driver, self.wait, self.server.base_url,
               f"coder_{int(time.time()*1000)}")

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_tray_lists_seeded_codes_and_adds_one(self):
        self.wait.until(EC.element_to_be_clickable(
            (By.ID, "cb-panel-toggle"))).click()
        tree = self.wait.until(EC.visibility_of_element_located(
            (By.ID, "cb-tree")))
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "cb-tree"), "seed-a"))
        self.assertIn("seed-b", tree.text)
        # open mode -> composer visible
        composer = self.driver.find_element(By.ID, "cb-composer")
        self.assertTrue(composer.is_displayed())
        # add on the fly
        name = self.driver.find_element(By.ID, "cb-new-name")
        name.clear()
        name.send_keys("runtime-code")
        self.driver.find_element(By.ID, "cb-add-btn").click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "cb-tree"), "runtime-code"))

    def test_duplicate_shows_inline_error(self):
        self.wait.until(EC.element_to_be_clickable(
            (By.ID, "cb-panel-toggle"))).click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "cb-tree"), "seed-a"))
        name = self.driver.find_element(By.ID, "cb-new-name")
        name.clear()
        name.send_keys("seed-a")
        self.driver.find_element(By.ID, "cb-add-btn").click()
        err = self.wait.until(EC.visibility_of_element_located(
            (By.ID, "cb-error")))
        self.assertIn("already exists", err.text.lower())


class TestCodebookTrayDisabled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import (
            create_test_data_file, create_test_config)
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(
            tests_dir, "output", f"cb_ui_off_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(
            cls.test_dir, [{"id": "c1", "text": "x"}])
        cls.config_file = create_test_config(
            cls.test_dir,
            [{"name": "l", "description": "d",
              "annotation_type": "radio", "labels": ["a", "b"]}],
            data_files=[data_file], annotation_task_name="Codebook Off",
            require_password=False)  # no codebook scheme/config
        cls.port = find_free_port()
        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "server did not start"
        cls.server._wait_for_server_ready(timeout=10)
        cls.chrome_options = _chrome()

    @classmethod
    def tearDownClass(cls):
        from tests.helpers.test_utils import cleanup_test_directory
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.wait = WebDriverWait(self.driver, 15)
        _login(self.driver, self.wait, self.server.base_url, "nocb")

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_toggle_hidden_when_codebook_disabled(self):
        time.sleep(1.5)  # allow the enable-probe to resolve
        toggle = self.driver.find_element(By.ID, "cb-panel-toggle")
        self.assertFalse(
            toggle.is_displayed(),
            "Codebook toggle must stay hidden when no codebook is enabled")


if __name__ == "__main__":
    unittest.main()
