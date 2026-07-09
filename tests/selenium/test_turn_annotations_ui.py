"""Selenium UI tests for the turn-level annotation framework.

Covers rendering of per-turn proxy widgets, interaction, and — critically —
persistence via navigate-away-and-back (NOT page refresh; browsers cache form
state across refresh, per CLAUDE.md). Also includes the regression test for
the legacy per_turn_ratings restore bug (visual state was lost on nav-back
because initPerTurnRatings never seeded from the server-restored hidden
input).
"""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

TRACE = [
    {"speaker": "User", "text": "What is 2+2?"},
    {"speaker": "Assistant", "text": "Let me compute that."},
    {"speaker": "Agent (Action)", "text": "calculator(expression=\"2+2\")"},
    {"speaker": "Assistant", "text": "The answer is 4."},
]


def _chrome_options():
    options = ChromeOptions()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu", "--window-size=1920,1080"):
        options.add_argument(a)
    return options


class _TurnAnnoBase(unittest.TestCase):
    """Shared server setup helpers."""

    CONFIG_SCHEMES = None
    DISPLAY_FIELDS = None
    TEST_DIR_NAME = None
    PREFERRED_PORT = 9024

    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file)
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory(cls.TEST_DIR_NAME)
        data = [
            {"id": "1", "task": "evaluate trace one", "conversation": TRACE},
            {"id": "2", "task": "evaluate trace two", "conversation": TRACE},
        ]
        data_file = create_test_data_file(cls.test_dir, data)
        cls.config_file = create_test_config(
            cls.test_dir, cls.CONFIG_SCHEMES, data_files=[data_file],
            item_properties={"id_key": "id", "text_key": "task"},
            additional_config={
                "instance_display": {"fields": cls.DISPLAY_FIELDS},
            })
        port = find_free_port(preferred_port=cls.PREFERRED_PORT)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "server failed to start"
        cls.server._wait_for_server_ready(timeout=10)
        cls.chrome_options = _chrome_options()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            from tests.helpers.test_utils import cleanup_test_directory
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        d = self.driver
        d.get(f"{self.server.base_url}/")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.ID, "login-email")))
        d.find_element(By.ID, "login-email").send_keys(f"ta_{int(time.time() * 1000)}")
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()


class TestTurnAnnotationUI(_TurnAnnoBase):
    TEST_DIR_NAME = "turn_anno_ui"
    PREFERRED_PORT = 9024
    CONFIG_SCHEMES = [
        {"annotation_type": "multiselect", "name": "turn_errors",
         "description": "Errors in this turn",
         "labels": ["hallucination", "contradiction"],
         "turn_level": True,
         "turn_binding": {"field": "conversation", "speakers": ["Assistant"]}},
        {"annotation_type": "likert", "name": "action_quality",
         "description": "Action quality", "size": 5,
         "min_label": "Poor", "max_label": "Great",
         "turn_level": True,
         "turn_binding": {"field": "conversation", "step_types": ["action"]}},
    ]
    DISPLAY_FIELDS = [
        {"key": "conversation", "type": "dialogue", "label": "Trace"},
    ]

    def _open(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".turn-anno-slot")))
        time.sleep(0.4)
        return d

    def test_slots_render_on_matching_turns_only(self):
        d = self._open()
        slots = d.find_elements(By.CSS_SELECTOR, ".turn-anno-slot")
        # 2 Assistant turns (multiselect) + 1 action turn (likert)
        assert len(slots) == 3, f"expected 3 slots, got {len(slots)}"
        speakers = {s.get_attribute("data-speaker") for s in slots}
        assert speakers == {"Assistant", "Agent (Action)"}

    def test_chip_click_updates_hidden_input(self):
        d = self._open()
        chip = d.find_element(
            By.CSS_SELECTOR,
            '.turn-anno-slot[data-turn-id="t1"] .ta-chip[data-value="hallucination"]')
        chip.click()
        time.sleep(0.3)
        assert "ta-selected" in (chip.get_attribute("class") or "")
        hidden = d.find_element(By.CSS_SELECTOR, 'input.turn-anno-hidden[name="turn_errors"]')
        value = hidden.get_attribute("value") or ""
        assert "hallucination" in value and '"t1"' in value, value
        assert hidden.get_attribute("data-modified") == "true"

    def test_chip_persists_after_navigate_away_and_back(self):
        d = self._open()
        chip = d.find_element(
            By.CSS_SELECTOR,
            '.turn-anno-slot[data-turn-id="t3"] .ta-chip[data-value="contradiction"]')
        chip.click()
        time.sleep(2.0)  # debounced save
        d.find_element(By.ID, "next-btn").click()
        time.sleep(1.5)
        d.find_element(By.ID, "prev-btn").click()
        time.sleep(1.5)
        WebDriverWait(d, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".turn-anno-slot")))
        time.sleep(0.5)
        chip2 = d.find_element(
            By.CSS_SELECTOR,
            '.turn-anno-slot[data-turn-id="t3"] .ta-chip[data-value="contradiction"]')
        assert "ta-selected" in (chip2.get_attribute("class") or ""), \
            "turn annotation visual state did not survive navigate-away-and-back"

    def test_likert_fill_up_to_and_persistence(self):
        d = self._open()
        chip = d.find_element(
            By.CSS_SELECTOR,
            '.turn-anno-slot[data-turn-id="t2"] .ta-likert[data-value="4"]')
        chip.click()
        time.sleep(0.3)
        selected = d.find_elements(
            By.CSS_SELECTOR, '.turn-anno-slot[data-turn-id="t2"] .ta-likert.ta-selected')
        assert len(selected) == 4, "likert should fill up to the picked value"
        time.sleep(2.0)
        d.find_element(By.ID, "next-btn").click()
        time.sleep(1.5)
        d.find_element(By.ID, "prev-btn").click()
        time.sleep(1.5)
        WebDriverWait(d, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".turn-anno-slot")))
        time.sleep(0.5)
        selected2 = d.find_elements(
            By.CSS_SELECTOR, '.turn-anno-slot[data-turn-id="t2"] .ta-likert.ta-selected')
        assert len(selected2) == 4, "likert state did not survive nav-away-and-back"

    def test_toggle_off_clears_turn(self):
        d = self._open()
        sel = ('.turn-anno-slot[data-turn-id="t1"] .ta-chip[data-value="hallucination"]')
        chip = d.find_element(By.CSS_SELECTOR, sel)
        chip.click()
        time.sleep(0.3)
        chip.click()
        time.sleep(0.3)
        assert "ta-selected" not in (chip.get_attribute("class") or "")
        hidden = d.find_element(By.CSS_SELECTOR, 'input.turn-anno-hidden[name="turn_errors"]')
        assert "hallucination" not in (hidden.get_attribute("value") or "")

    def test_no_annotation_inputs_inside_slots(self):
        """R3: proxies must be invisible to the global persistence pipeline."""
        d = self._open()
        leaked = d.find_elements(
            By.CSS_SELECTOR, ".turn-anno-slot .annotation-input, "
                             ".turn-anno-slot .annotation-data-input")
        assert leaked == [], "slot widgets must not carry annotation input classes"


class TestPerTurnRatingsRestoreRegression(_TurnAnnoBase):
    """Regression: legacy per_turn_ratings visual state must survive
    navigate-away-and-back (initPerTurnRatings now seeds from the
    server-restored hidden input)."""

    TEST_DIR_NAME = "ptr_restore_ui"
    PREFERRED_PORT = 9026
    CONFIG_SCHEMES = [
        {"annotation_type": "radio", "name": "task_success",
         "description": "success", "labels": ["yes", "no"]},
    ]
    DISPLAY_FIELDS = [
        {"key": "conversation", "type": "dialogue", "label": "Trace",
         "display_options": {
             "per_turn_ratings": {
                 "speakers": ["Assistant"],
                 "schemes": [{"schema_name": "helpfulness",
                              "scheme": {"type": "likert", "size": 5,
                                         "labels": ["Poor", "Great"]}}],
             }}},
    ]

    def test_rating_persists_after_navigate_away_and_back(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".ptr-value")))
        time.sleep(0.4)
        target = d.find_element(
            By.CSS_SELECTOR, '.per-turn-rating[data-turn="1"] .ptr-value[data-value="4"]')
        target.click()
        time.sleep(2.0)
        d.find_element(By.ID, "next-btn").click()
        time.sleep(1.5)
        d.find_element(By.ID, "prev-btn").click()
        time.sleep(1.5)
        WebDriverWait(d, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".ptr-value")))
        time.sleep(0.5)
        selected = d.find_elements(
            By.CSS_SELECTOR, '.per-turn-rating[data-turn="1"] .ptr-value.ptr-selected')
        assert len(selected) == 4, \
            "per_turn_ratings visual state did not survive navigate-away-and-back"


if __name__ == "__main__":
    unittest.main()
