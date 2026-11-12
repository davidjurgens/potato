"""
Taking over a model's spans, links, chains and events in the browser.

Two ways the prediction outlived the annotator's answer:

- Editing one scheme stored that scheme alone. From then on the annotator
  had a stored link, so ``/api/links`` offered no prelabels for any scheme,
  and the other schemes' untouched predictions vanished. Now the first edit
  stores every prelabel on the item first.
- Deleting every predicted span left nothing stored, and "nothing stored"
  is when prelabels are offered, so Back brought the whole prediction back.
  Now moving on from a page that showed prelabels takes them over, and an
  item the annotator emptied stays empty. A predicted link to a deleted span
  is dropped with it rather than stored pointing at nothing.
"""

import json
import os
import time
import unittest

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)
from tests.selenium.test_link_prelabel_ui import SCHEMES

TEXT = "alice works at acme because she says her boss is kind ."
ALICE, WORKS, ACME = ({"start": 0, "end": 5, "label": "PER"},
                      {"start": 6, "end": 11, "label": "TRIG"},
                      {"start": 15, "end": 19, "label": "ORG"})
SHE, HER = {"start": 28, "end": 31, "label": "PER"}, {"start": 37, "end": 40, "label": "PER"}
ITEM = {"id": "d1", "text": TEXT, "predictions": {
    "rels": {"spans": [ALICE, ACME],
             "links": [{"type": "WORKS_AT", "spans": [0, 1], "directed": True}]},
    "coref": {"spans": [ALICE, SHE, HER],
              "clusters": [{"type": "ENTITY", "spans": [0, 1, 2]}]},
    "events": {"spans": [ALICE, ACME, WORKS], "events": [
        {"type": "JOB", "trigger": 2, "arguments": [{"role": "worker", "span": 0}]}]}}}


class TestPrelabelTakeoverUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("prelabel_takeover_ui")
        port = find_free_port(preferred_port=9897)
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

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        cleanup_test_directory(cls.test_dir)

    def setUp(self):
        options = ChromeOptions()
        for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                     "--disable-gpu", "--window-size=1400,2000"):
            options.add_argument(flag)
        self.driver = webdriver.Chrome(options=options)
        self.driver.implicitly_wait(2)
        self.addCleanup(self.driver.quit)

    def _login(self, user):
        self.user = user
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        self.driver.find_element(By.NAME, "email").send_keys(user)
        try:
            self.driver.find_element(By.NAME, "pass").send_keys("pw")
        except Exception:
            pass
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "rels_link_list")))

    def _state(self):
        path = next((os.path.join(root, "user_state.json")
                     for root, _, files in os.walk(self.test_dir)
                     if "user_state.json" in files
                     and os.path.basename(root) == self.user), None)
        if not path:
            return {}
        with open(path) as fh:
            return json.load(fh)

    def _stored(self):
        state = self._state()
        return {"spans": (state.get("instance_id_to_span_to_value") or {}).get("d1", []),
                "links": (state.get("instance_id_to_link_to_value") or {}).get("d1", {}),
                "events": (state.get("instance_id_to_event_to_value") or {}).get("d1", {})}

    def _shown(self):
        return self.driver.execute_script("""
            const text = id => (document.getElementById(id) || {}).innerText || '';
            const manager = (document.querySelector('.coref-container') || {})._coreferenceManager;
            return {relations: text('rels_link_list'),
                    chains: manager ? manager.chains.map(c => c.spanIds.length) : null,
                    events: (document.querySelector('[id$=event_list]') || {}).innerText || '',
                    spans: document.querySelectorAll('.span-overlay-pure').length};""")

    def _wait_for(self, check, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = check()
            if value:
                return value
            time.sleep(0.25)
        return check()

    def _wait_for_prediction(self):
        shown = self._wait_for(lambda: (lambda s: s if "WORKS_AT" in s["relations"]
                                        and "JOB" in s["events"] and s["chains"]
                                        and s["spans"] == 5 else None)(self._shown()))
        self.assertIsNotNone(shown, self._shown())
        return shown

    def test_editing_one_scheme_keeps_the_other_schemes_prelabels(self):
        self._login("takeover_edit")
        self.assertEqual(self._wait_for_prediction()["chains"], [3])

        # Select "she" and remove it from the chain: a coreference edit only.
        she = self.driver.find_element(
            By.CSS_SELECTOR, '.span-overlay-pure[data-start="28"] .span-highlight-segment')
        she.click()
        WebDriverWait(self.driver, 5).until(
            lambda d: d.find_element(By.ID, "coref_remove_mention").is_enabled())
        self.driver.find_element(By.ID, "coref_remove_mention").click()

        stored = self._wait_for(lambda: (lambda s: s if s["events"] and len(s["links"]) == 2
                                         else None)(self._stored()))
        self.assertTrue(stored, self._stored())
        links = {l["schema"]: l for l in stored["links"].values()}
        self.assertEqual(sorted(links), ["coref", "rels"])
        self.assertEqual(len(links["coref"]["span_ids"]), 2)
        span_ids = {entry[0]["id"] for entry in stored["spans"]}
        self.assertEqual(len(span_ids), 5)
        for link in links.values():
            self.assertTrue(set(link["span_ids"]) <= span_ids, link)

        self.driver.refresh()
        after = self._wait_for(lambda: (lambda s: s if "WORKS_AT" in s["relations"]
                                        and "JOB" in s["events"] and s["chains"]
                                        else None)(self._shown()))
        self.assertIsNotNone(after, self._shown())
        self.assertEqual(after["chains"], [2])

    def test_deleting_every_span_stays_deleted(self):
        self._login("takeover_delete")
        self._wait_for_prediction()
        for _ in range(15):
            count = self._shown()["spans"]
            if not count:
                break
            # Overlays are redrawn as spans change, so a found button can go
            # stale or miss; find it afresh until the count drops.
            try:
                button = self.driver.find_element(By.CSS_SELECTOR, ".span-delete-btn")
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'})", button)
                button.click()
            except StaleElementReferenceException:
                pass
            self._wait_for(lambda: self._shown()["spans"] < count, timeout=2)
        self.assertEqual(self._shown()["spans"], 0)

        self.driver.find_element(By.ID, "next-btn").click()
        WebDriverWait(self.driver, 10).until(lambda d: "nothing predicted" in d.page_source)
        time.sleep(1)
        stored = self._stored()
        self.assertEqual((stored["spans"], stored["links"], stored["events"]), ([], {}, {}),
                         "a predicted link or event was stored after its spans were deleted")
        self.assertIn("d1", self._state().get("prelabels_resolved_ids", []))

        self.driver.find_element(By.ID, "prev-btn").click()
        WebDriverWait(self.driver, 10).until(lambda d: "acme" in d.page_source)
        time.sleep(3)  # long enough for /api/spans, /api/links and /api/events
        back = self._shown()
        self.assertEqual(back["spans"], 0, back)
        self.assertNotIn("WORKS_AT", back["relations"])
        self.assertNotIn("JOB", back["events"])
        self.assertEqual(back["chains"], [])

        self.driver.refresh()
        WebDriverWait(self.driver, 10).until(lambda d: "acme" in d.page_source)
        time.sleep(3)
        self.assertEqual(self._shown()["spans"], 0)


if __name__ == "__main__":
    unittest.main()
