#!/usr/bin/env python3
"""
Cloze blanks save, and come back on screen after navigate-away-and-back.

Typed into with real key events, checked on the server (`/get_annotations`),
then Next and Previous (not a refresh, which keeps form state on its own) and
the blanks are read again. Also: the answer key is not in the page source.
"""

import os
import time
import unittest
from pathlib import Path

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class TestClozeUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import create_test_config, create_test_data_file

        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(tests_dir, "output", f"cloze_ui_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(cls.test_dir, [
            {"id": f"item_{i + 1}", "text": f"Passage {i + 1}."} for i in range(3)])
        config_file = create_test_config(
            cls.test_dir,
            [{"name": "fill", "annotation_type": "cloze", "description": "Fill in the blanks",
              "text": "The [[zebrafinch]] sang to the [[moonrise|dawn]].",
              "label_requirement": {"required": True}}],
            data_files=[data_file],
            annotation_task_name="Cloze UI",
            require_password=False,
        )
        cls.server = FlaskTestServer(port=find_free_port(preferred_port=9061),
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
        self.username = f"cloze_{int(time.time() * 1000)}"
        self.driver.find_element(By.ID, "login-email").send_keys(self.username)
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        self._wait_ready()

    def tearDown(self):
        self.driver.quit()

    def _wait_ready(self):
        WebDriverWait(self.driver, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        WebDriverWait(self.driver, 15).until(EC.invisibility_of_element_located((By.ID, "loading-state")))

    def _instance_id(self):
        return self.driver.find_element(By.ID, "instance_id").get_attribute("value")

    def _blanks(self):
        return self.driver.find_elements(By.CSS_SELECTOR, "input.cloze-blank[schema='fill']")

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
        return r.json().get("label_annotations", {}).get("fill")

    def test_answer_key_not_in_page(self):
        source = self.driver.page_source.lower()
        self.assertNotIn("zebrafinch", source)
        self.assertNotIn("moonrise", source)
        self.assertEqual(len(self._blanks()), 2)

    def test_required_blanks_block_next(self):
        first = self._instance_id()
        self._blanks()[0].send_keys("only one")
        self.driver.find_element(By.ID, "next-btn").click()
        time.sleep(0.8)
        self.assertEqual(self._instance_id(), first)

    def test_blanks_persist_across_navigation(self):
        first = self._instance_id()
        a, b = self._blanks()
        a.send_keys("zebrafinch")
        b.send_keys("dawn")
        time.sleep(1.6)  # debounce + autosave
        self.assertEqual(sorted(self._stored(first) or []), ["blank_1", "blank_2"])
        from potato.user_state_management import get_user_state_manager
        us = get_user_state_manager().get_user_state(self.username)
        values = {label.get_name(): value
                  for label, value in us.instance_id_to_label_to_value.get(first, {}).items()
                  if label.get_schema() == "fill"}
        self.assertEqual(values, {"blank_1": "zebrafinch", "blank_2": "dawn"})
        self._go("next-btn")
        self.assertEqual([x.get_attribute("value") for x in self._blanks()], ["", ""])
        self._go("prev-btn")
        self.assertEqual(self._instance_id(), first)
        self.assertEqual([x.get_attribute("value") for x in self._blanks()],
                         ["zebrafinch", "dawn"])


if __name__ == "__main__":
    unittest.main()
