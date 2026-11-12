"""
A model's relations, chains and events in the browser.

hf-relation's prediction becomes span prelabels plus links, chains and
events between them. In the page they must be drawn and listed, stay off the
server until the annotator moves on, be stored with ids that still join them
when they do, and come back after navigating away and back. The relation
list must show its own scheme's links only: the route returns every link on
the item, and the list used to show the coreference chain beside them.
"""

import json
import os
import time
import unittest

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
from tests.server.test_link_pre_annotation import ITEM

SCHEMES = [
    {"annotation_type": "span", "name": "ents", "description": "Entities",
     "labels": ["PER", "ORG", "TRIG"]},
    {"annotation_type": "span_link", "name": "rels", "description": "Relations",
     "span_schema": "ents",
     "link_types": [{"name": "WORKS_AT", "directed": True, "color": "#dc2626"}]},
    {"annotation_type": "coreference", "name": "coref", "description": "Chains",
     "span_schema": "ents"},
    {"annotation_type": "event_annotation", "name": "events", "description": "Events",
     "span_schema": "ents",
     "event_types": [{"type": "JOB", "trigger_labels": ["TRIG"],
                      "arguments": [{"role": "worker", "entity_types": ["PER"]}]}]},
]


class TestLinkPrelabelUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("link_prelabel_ui")
        port = find_free_port(preferred_port=9898)
        data_file = create_test_data_file(cls.test_dir, [
            ITEM, {"id": "d2", "text": "nothing predicted here ."}])
        cls.config_file = create_test_config(
            cls.test_dir, SCHEMES, data_files=[data_file], port=port,
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
                     "--disable-gpu", "--window-size=1400,2000"):
            options.add_argument(flag)
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)
        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("link_reader")
        try:
            cls.driver.find_element(By.NAME, "pass").send_keys("pw")
        except Exception:
            pass
        cls.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(cls.driver, 10).until(
            EC.presence_of_element_located((By.ID, "rels_link_list")))

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            cls.driver.quit()
        if hasattr(cls, "server"):
            cls.server.stop_server()
        cleanup_test_directory(cls.test_dir)

    def _stored(self):
        path = os.path.join(self.test_dir, "annotation_output", "link_reader",
                            "user_state.json")
        if not os.path.exists(path):
            path = next((os.path.join(root, "user_state.json")
                         for root, _, files in os.walk(self.test_dir)
                         if "user_state.json" in files and "link_reader" in root), None)
        if not path:
            return {}
        with open(path) as fh:
            state = json.load(fh)
        return {"spans": (state.get("instance_id_to_span_to_value") or {}).get("d1", []),
                "links": (state.get("instance_id_to_link_to_value") or {}).get("d1", {}),
                "events": (state.get("instance_id_to_event_to_value") or {}).get("d1", {})}

    def _shown(self):
        return self.driver.execute_script("""
            const text = id => (document.getElementById(id) || {}).innerText || '';
            return {relations: text('rels_link_list'),
                    chains: (document.querySelector('.coref-container') || {}).innerText || '',
                    events: (document.querySelector('[id$=event_list]') || {}).innerText || ''};""")

    def _wait_for(self, check, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = check()
            if value:
                return value
            time.sleep(0.25)
        return check()

    def test_predictions_are_shown_kept_on_next_and_restored(self):
        shown = self._wait_for(lambda: (lambda s: s if "WORKS_AT" in s["relations"]
                                        and "JOB" in s["events"] else None)(self._shown()))
        self.assertIsNotNone(shown, self._shown())
        self.assertIn("alice", shown["relations"])
        self.assertNotIn("ENTITY", shown["relations"], "the chain is listed as a relation")
        self.assertIn("ENTITY", shown["chains"])
        self.assertIn("works", shown["events"])          # the trigger text
        time.sleep(2)
        stored = self._stored()
        self.assertFalse(stored and (stored["links"] or stored["events"]),
                         "prelabels were stored before the annotator moved on")

        self.driver.find_element(By.ID, "next-btn").click()
        WebDriverWait(self.driver, 10).until(
            lambda d: "nothing predicted" in d.page_source)
        stored = self._wait_for(lambda: (lambda s: s if s.get("events") else None)(self._stored()))
        span_ids = {entry[0]["id"] for entry in stored["spans"]}
        links = list(stored["links"].values())
        self.assertEqual(sorted(l["schema"] for l in links), ["coref", "rels"])
        for link in links:
            self.assertTrue(set(link["span_ids"]) <= span_ids, link)
        (event,) = stored["events"].values()
        self.assertIn(event["trigger_span_id"], span_ids)

        self.driver.find_element(By.ID, "prev-btn").click()
        WebDriverWait(self.driver, 10).until(lambda d: "acme" in d.page_source)
        back = self._wait_for(lambda: (lambda s: s if "WORKS_AT" in s["relations"]
                                       and "JOB" in s["events"] else None)(self._shown()))
        self.assertIsNotNone(back, self._shown())
        self.assertIn("ENTITY", back["chains"])
