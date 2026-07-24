"""Selenium UI test for multi-document event annotation persistence.

The critical check (per CLAUDE.md): make an annotation, navigate AWAY (Next) and
BACK (Previous) — NOT a page refresh — and confirm it survived. Because event data
lives in the server-side registry (not the DOM/updateinstance pipeline), returning
to a document must re-fetch and re-render the event with its slot value intact.
This guards against the IIFE-overwrite class of persistence bugs.
"""

import os
import time

import pytest

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_config, create_test_data_file, create_test_directory

pytest.importorskip("selenium")
from selenium import webdriver  # noqa: E402
from selenium.webdriver.chrome.options import Options  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402
from selenium.webdriver.support import expected_conditions as EC  # noqa: E402


SLOTS = [
    {"name": "event_type", "description": "kind", "type": "text"},
    {"name": "where", "description": "location", "type": "text"},
]


def _make_driver():
    opts = Options()
    for a in ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
              "--window-size=1400,900"]:
        opts.add_argument(a)
    try:
        return webdriver.Chrome(options=opts)
    except Exception as e:  # pragma: no cover - CI without chromedriver
        pytest.skip(f"Chrome webdriver unavailable: {e}")


class TestMultiDocumentEventUI:
    @classmethod
    def setup_class(cls):
        cls.test_dir = create_test_directory("mde_ui")
        data = [{"id": "1", "text": "Flooding submerged the city of Ayutthaya."},
                {"id": "2", "text": "An earthquake struck the coast of Japan."}]
        data_file = create_test_data_file(cls.test_dir, data)
        config_file = create_test_config(
            cls.test_dir,
            [{
                "annotation_type": "multi_document_event",
                "name": "events",
                "description": "Cross-document events",
                "slots": SLOTS,
                "allow_annotator_create": True,
            }],
            data_files=[data_file],
            require_password=False,
            additional_config={
                "event_template": {
                    "enabled": True, "name": "disaster_event",
                    "allow_annotator_create": True, "slots": SLOTS,
                },
                "instance_display": {
                    "fields": [{"key": "text", "type": "text", "span_target": True}]
                },
            },
        )
        cls.server = FlaskTestServer(port=9062, debug=False, config_file=config_file)
        assert cls.server.start(), "Failed to start server"

    @classmethod
    def teardown_class(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def _login(self, driver):
        driver.get(f"{self.server.base_url}/")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "login-email")))
        driver.find_element(By.ID, "login-email").send_keys("mde_tester")
        # simple login form (require_password=False) submits with the username
        driver.find_element(By.ID, "login-email").submit()
        WebDriverWait(driver, 10).until(EC.url_contains("/annotate"))

    def test_event_persists_across_navigation(self):
        driver = _make_driver()
        try:
            self._login(driver)
            wait = WebDriverWait(driver, 12)

            # Wait for the MDE form + create the event.
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mde-container")))
            create_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, '.mde-container [data-role="create-event"]'))
            )
            create_btn.click()

            # Fill the event_type slot (editor renders after create).
            slot_input = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '.mde-slot-input[data-slot="event_type"]')
                )
            )
            slot_input.send_keys("flood")
            slot_input.send_keys("\t")  # blur -> change -> save
            time.sleep(1.0)

            # Navigate AWAY (Next) then BACK (Previous) — not a refresh.
            wait.until(EC.element_to_be_clickable((By.ID, "next-btn"))).click()
            time.sleep(1.0)
            wait.until(EC.element_to_be_clickable((By.ID, "prev-btn"))).click()
            time.sleep(1.4)

            # The event must reappear with its slot value restored.
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mde-event-row")))
            # Open the event and read the slot input value.
            driver.find_element(By.CSS_SELECTOR, '.mde-event-open').click()
            restored = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '.mde-slot-input[data-slot="event_type"]')
                )
            )
            assert restored.get_attribute("value") == "flood", (
                "Slot value did not persist across navigate-away-and-back"
            )

            # And it is stored server-side.
            import requests
            cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
            r = requests.get(f"{self.server.base_url}/corpus/api/events?doc_id=1", cookies=cookies)
            assert r.status_code == 200
            events = r.json()["events"]
            assert any(e["slot_values"].get("event_type") == "flood" for e in events)
        finally:
            driver.quit()
