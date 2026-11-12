"""
A text_edit line left as it was is saved as accepted when the annotator
presses Next.

The record was written only by typing, so Next on a line that was already
correct saved nothing: the progress counter stayed put and the export could not
tell a line someone checked from one nobody opened. Checked on the server
(`/get_annotations`) and after navigating away and back.
"""

import json
import time
import unittest

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)


class TestTextEditAcceptUnchanged(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("text_edit_accept_unchanged")
        data_file = create_test_data_file(cls.test_dir, [
            {"id": f"line_{n}", "text": f"Line {n}", "htr_text": f"the quick brown fox {n}"}
            for n in range(3)])
        config_file = create_test_config(
            cls.test_dir,
            [{"annotation_type": "text_edit", "name": "transcription",
              "description": "Correct the line", "source_field": "htr_text",
              "show_edit_distance": True}],
            data_files=[data_file], require_password=False,
            user_config={"allow_all_users": True, "users": []})
        cls.server = FlaskTestServer(port=find_free_port(preferred_port=9895),
                                     debug=False, config_file=config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)
        options = ChromeOptions()
        for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                     "--disable-gpu", "--window-size=1400,1000"):
            options.add_argument(flag)
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)
        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("checker")
        cls.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            cls.driver.quit()
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def _instance(self):
        return self.driver.execute_script("return document.getElementById('instance_id').value")

    def _stored(self, iid):
        session = requests.Session()
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])
        r = session.get(f"{self.server.base_url}/get_annotations", params={"instance_id": iid})
        values = (r.json().get("label_values") or {}).get("transcription") or {}
        return next(iter(values.values()), None)

    def test_next_on_an_unchanged_line_saves_it_as_accepted(self):
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".text-edit-textarea")))
        time.sleep(1)
        first = self._instance()
        self.assertEqual(self.driver.find_element(By.CSS_SELECTOR, ".text-edit-textarea")
                         .get_attribute("value"), "the quick brown fox 0")
        self.driver.find_element(By.ID, "next-btn").click()
        time.sleep(2)
        self.assertNotEqual(self._instance(), first)
        record = json.loads(self._stored(first))
        self.assertEqual(record["edited_text"], "the quick brown fox 0")
        self.assertEqual(record["edit_distance_chars"], 0)
        # The line not reached yet has no record.
        self.assertIsNone(self._stored("line_2"))
        self.driver.find_element(By.ID, "prev-btn").click()
        time.sleep(2)
        self.assertEqual(self._instance(), first)
        self.assertEqual(self.driver.find_element(By.CSS_SELECTOR, ".text-edit-textarea")
                         .get_attribute("value"), "the quick brown fox 0")


if __name__ == "__main__":
    unittest.main()
