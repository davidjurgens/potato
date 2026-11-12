"""
A model's slider prelabel is shown, not saved, until the annotator acts.

populateInputValues() sets a restored slider and dispatches ``input`` so
displays redraw. The slider's save listener took that event for a person
moving it: a prelabel on a slider, soft label or pairwise scale was saved as
the annotator's answer on page load, the item counted as done before anyone
touched it, and the model's answer could go back into training as a human
label. Radio prelabels never did this, because nothing dispatches an event
for them.

Pressing Next keeps the prefilled values, as it does for a radio prelabel,
and they are there again after navigating away and back. A number prelabel
was stored under the slider's label and never reached its box.
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


class TestSliderPrelabelNotSavedOnLoad(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("slider_prelabel_on_load")
        schemes = [
            {"annotation_type": "slider", "name": "sl", "description": "How much?",
             "min_value": 0, "max_value": 10, "starting_value": 5},
            {"annotation_type": "soft_label", "name": "soft", "description": "How sure?",
             "labels": ["pos", "neg"], "total": 100},
            {"annotation_type": "number", "name": "num", "description": "How many?",
             "min_value": 0, "max_value": 10},
        ]
        port = find_free_port(preferred_port=9897)
        data_file = create_test_data_file(cls.test_dir, [
            {"id": "x1", "text": "first item",
             "predictions": {"sl": {"label": "7", "confidence": 0.8},
                             "soft": {"pos": 0.7, "neg": 0.3},
                             "num": {"label": "4", "confidence": 0.6}}},
            {"id": "x2", "text": "second item"}])
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[data_file], port=port,
            item_properties={"id_key": "id", "text_key": "text"},
            user_config={"allow_all_users": True, "users": []},
            additional_config={"pre_annotation": {"enabled": True,
                                                  "field": "predictions",
                                                  "allow_modification": True}})
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        options = ChromeOptions()
        for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                     "--disable-gpu", "--window-size=1400,1200"):
            options.add_argument(flag)
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)
        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("slider_reader")
        try:
            cls.driver.find_element(By.NAME, "pass").send_keys("pw")
        except Exception:
            pass
        cls.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(cls.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[schema='sl']")))

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            cls.driver.quit()
        if hasattr(cls, "server"):
            cls.server.stop_server()
        cleanup_test_directory(cls.test_dir)

    def _saved(self, instance_id):
        session = requests.Session()
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])
        response = session.get(f"{self.server.base_url}/get_annotations",
                               params={"instance_id": instance_id})
        self.assertTrue(response.ok, response.text)
        body = response.json()
        self.assertIn("label_values", body)
        return body["label_values"]

    def _values(self):
        return self.driver.execute_script("""
            const v = s => document.querySelector(s) && document.querySelector(s).value;
            return {sl: v("input[schema='sl']"),
                    pos: v("input[schema='soft'][label_name='pos']"),
                    neg: v("input[schema='soft'][label_name='neg']"),
                    num: v("input[schema='num']")};""")

    def test_prelabel_is_shown_but_not_saved_until_next(self):
        self.assertEqual(self._values(), {"sl": "7", "pos": "70", "neg": "30", "num": "4"})
        time.sleep(2.5)                      # past every debounce
        saved = self._saved("x1")
        self.assertEqual(saved, {}, "a prelabel was saved before the annotator "
                                    "acted: %s" % json.dumps(saved))

        self.driver.find_element(By.ID, "next-btn").click()
        WebDriverWait(self.driver, 10).until(
            lambda d: "second item" in d.page_source)
        self.assertEqual(self._saved("x1"), {"sl": {"slider": "7"},
                                             "soft": {"pos": "70", "neg": "30"},
                                             "num": {"number": "4"}})
        self.driver.find_element(By.ID, "prev-btn").click()
        WebDriverWait(self.driver, 10).until(
            lambda d: "first item" in d.page_source)
        time.sleep(1)
        # Accepted with Next, like a radio prelabel, and restored on return.
        self.assertEqual(self._values(), {"sl": "7", "pos": "70", "neg": "30", "num": "4"})
