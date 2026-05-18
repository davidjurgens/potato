#!/usr/bin/env python3
"""
Selenium test for the annotator search-and-claim sidebar.

Verifies the panel only appears when search.annotator_claim is enabled,
that a query returns results, and that Claim moves an instance into the
annotator's queue (button reflects the claimed state).
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


class TestSearchClaimUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import (
            create_test_directory, create_test_data_file, create_test_config)
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(
            tests_dir, "output", f"search_ui_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(cls.test_dir, [
            {"id": "c1", "text": "common routine status update"},
            {"id": "c2", "text": "a distinctive rare anomaly candidate"},
            {"id": "c3", "text": "another common entry"},
            {"id": "c4", "text": "second distinctive rare example here"},
        ])
        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes=[{"name": "label", "description": "L",
                                 "annotation_type": "radio",
                                 "labels": ["a", "b"]}],
            data_files=[data_file], annotation_task_name="Search UI Test",
            require_password=False, max_annotations_per_user=1,
            additional_config={"search": {"annotator_claim": True}})
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
               f"searcher_{int(time.time()*1000)}")

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_search_then_claim(self):
        self.wait.until(EC.element_to_be_clickable(
            (By.ID, "search-panel-toggle"))).click()
        q = self.wait.until(EC.visibility_of_element_located(
            (By.ID, "search-q")))
        q.clear()
        q.send_keys("distinctive")
        self.driver.find_element(By.ID, "search-go").click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "search-results"), "distinctive"))
        claim_btn = self.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "#search-results .search-claim")))
        claim_btn.click()
        # button reflects claimed state
        self.wait.until(EC.text_to_be_present_in_element(
            (By.CSS_SELECTOR, "#search-results .search-claimed"), "queue"))


class TestSearchClaimDisabled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import (
            create_test_directory, create_test_data_file, create_test_config)
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(
            tests_dir, "output", f"search_ui_off_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(
            cls.test_dir, [{"id": "c1", "text": "hello"}])
        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes=[{"name": "label", "description": "L",
                                 "annotation_type": "radio",
                                 "labels": ["a", "b"]}],
            data_files=[data_file], annotation_task_name="Search UI Off",
            require_password=False)  # annotator_claim defaults off
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
        _login(self.driver, self.wait, self.server.base_url, "nosearch")

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_toggle_hidden_when_claim_disabled(self):
        time.sleep(1.5)  # allow the enable-probe to resolve
        toggle = self.driver.find_element(By.ID, "search-panel-toggle")
        self.assertFalse(
            toggle.is_displayed(),
            "Search toggle must stay hidden when annotator_claim is off")


if __name__ == "__main__":
    unittest.main()
