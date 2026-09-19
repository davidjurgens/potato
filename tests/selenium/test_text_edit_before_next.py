#!/usr/bin/env python3
"""
A text edit made just before Next is the one the server keeps.

Text and number inputs reach the page's answer state through a 1 s debounce.
A save inside that second sent what the box held before the edit: the DOM sync
copies a non-empty value across but skips an empty one, so clearing a box and
pressing Next at once kept the old text on the server. With a pause it saved.

Checked on the server (`/get_annotations`) and on screen after
navigate-away-and-back, not after a refresh.
"""

import os
import time
import unittest
from pathlib import Path

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class TestTextEditBeforeNext(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import create_test_config, create_test_data_file

        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(tests_dir, "output", f"text_before_next_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(cls.test_dir, [
            {"id": f"item_{i + 1}", "text": f"Text edit item {i + 1}."}
            for i in range(4)
        ])
        config_file = create_test_config(
            cls.test_dir,
            [{"name": "feeling", "annotation_type": "text",
              "labels": ["why"], "description": "Why?"}],
            data_files=[data_file],
            annotation_task_name="Text Edit Before Next",
            require_password=False,
        )
        cls.server = FlaskTestServer(port=find_free_port(preferred_port=9033),
                                     debug=False, config_file=config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        cls.chrome_options = ChromeOptions()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-gpu", "--window-size=1400,1000"):
            cls.chrome_options.add_argument(arg)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop_server()
        from tests.helpers.test_utils import cleanup_test_directory
        cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "login-email")))
        self.driver.find_element(By.ID, "login-email").send_keys(f"text_next_{int(time.time() * 1000)}")
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        self._wait_ready()

    def tearDown(self):
        self.driver.quit()

    def _wait_ready(self):
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content")))
        WebDriverWait(self.driver, 15).until(
            EC.invisibility_of_element_located((By.ID, "loading-state")))

    def _instance_id(self):
        return self.driver.find_element(By.ID, "instance_id").get_attribute("value")

    def _box(self):
        return self.driver.find_element(
            By.CSS_SELECTOR, "input[type='text'][schema='feeling'], textarea[schema='feeling']")

    def _go(self, button_id):
        before = self._instance_id()
        origin = self.driver.execute_script("return performance.timeOrigin")
        self.driver.find_element(By.ID, button_id).click()
        WebDriverWait(self.driver, 15).until(
            lambda d: d.execute_script("return performance.timeOrigin") != origin)
        self._wait_ready()
        self.assertNotEqual(self._instance_id(), before)

    def _stored(self, instance_id):
        cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
        r = requests.get(f"{self.server.base_url}/get_annotations",
                         params={"instance_id": instance_id}, cookies=cookies, timeout=5)
        return r.json().get("label_annotations", {}).get("feeling")

    def _answer_and_come_back(self):
        """Type an answer, let it save, and return to this item via Next/Prev."""
        first = self._instance_id()
        self._box().send_keys("abc")
        time.sleep(1.5)  # debounce + autosave
        self.assertTrue(self._stored(first), "precondition: the first answer was saved")
        self._go("next-btn")
        self._go("prev-btn")
        self.assertEqual(self._box().get_attribute("value"), "abc")
        return first

    def test_clearing_a_box_and_pressing_next_at_once_is_saved(self):
        first = self._answer_and_come_back()
        box = self._box()
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(Keys.COMMAND, "a")
        box.send_keys(Keys.BACKSPACE)
        self.assertEqual(box.get_attribute("value"), "")
        self._go("next-btn")          # no pause
        self.assertFalse(self._stored(first), "the cleared answer should not survive")
        self._go("prev-btn")
        self.assertEqual(self._box().get_attribute("value"), "")

    def test_replacing_text_and_pressing_next_at_once_is_saved(self):
        first = self._answer_and_come_back()
        box = self._box()
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(Keys.COMMAND, "a")
        box.send_keys("xyz")
        self._go("next-btn")          # no pause
        self._go("prev-btn")
        self.assertEqual(self._box().get_attribute("value"), "xyz")
        self.assertTrue(self._stored(first))


if __name__ == "__main__":
    unittest.main()
