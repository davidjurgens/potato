"""Selenium UI tests for the threaded `dialogue` display.

Three things need a real browser to check honestly:

1. **Indentation** — depth is derived from `reply_to` in Python, but the indent
   itself is a CSS custom property, so only a browser knows whether it landed.
2. **The span-offset invariant** — the threading chrome is drawn as
   pseudo-element `content`. A unit test can assert the markup carries the right
   attributes; only a browser can confirm that content really stays out of
   `textContent`, which is what span offsets are measured against.
3. **Per-turn persistence** — verified by navigating away and back rather than
   refreshing, because browsers restore form state across a refresh and would
   make a broken save look like a working one.
"""

import json
import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

#: A branching thread: m2 and m4 both reply to m1, m3 replies to m2.
THREAD = [
    {"id": "m1", "speaker": "ana", "text": "Anyone tried the new API?",
     "timestamp": 1000},
    {"id": "m2", "speaker": "ben", "text": "Yes, works fine.",
     "reply_to": "m1", "timestamp": 4600, "meta": {"score": 0.25}},
    {"id": "m3", "speaker": "cy", "text": "Not for me, it times out.",
     "reply_to": "m2", "timestamp": 8200, "meta": {"score": 0.5}},
    {"id": "m4", "speaker": "dee", "text": "Same here, on the v2 endpoint.",
     "reply_to": "m1", "timestamp": 11800, "meta": {"score": 0.75}},
]


class TestThreadedDialogueUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file)
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory("threaded_dialogue_ui")
        data = [
            {"id": "t1", "title": "API deprecation", "thread": THREAD},
            {"id": "t2", "title": "Flaky test", "thread": [
                {"id": "n1", "speaker": "eve", "text": "The auth test is flaky."},
                {"id": "n2", "speaker": "fay", "text": "Shared fixture.",
                 "reply_to": "n1"},
            ]},
        ]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [
            {"annotation_type": "radio", "name": "outcome",
             "description": "Outcome", "labels": ["consensus", "unresolved"]},
            {"annotation_type": "multiselect", "name": "comment_flags",
             "description": "Flags", "labels": ["helpful", "off_topic"],
             "turn_level": True, "turn_binding": {"field": "thread"}},
            {"annotation_type": "span", "name": "evidence",
             "description": "Evidence", "labels": ["claim", "counter"]},
        ]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_file=data_file,
            item_properties={"id_key": "id", "text_key": "title"},
        )
        # The display config is not expressible through create_test_config, so
        # patch the instance_display block in directly.
        import yaml
        with open(cls.config_file) as f:
            config = yaml.safe_load(f)
        config["instance_display"] = {
            "fields": [
                {"key": "title", "type": "text", "label": "Topic"},
                {"key": "thread", "type": "dialogue", "label": "Discussion",
                 "span_target": True,
                 "display_options": {
                     "show_turn_numbers": True,
                     "indent_replies": True,
                     "show_reply_lines": True,
                     "show_timestamps": True,
                     "timestamp_format": "relative",
                     "turn_meta_fields": ["score"],
                 }},
            ]
        }
        with open(cls.config_file, "w") as f:
            yaml.safe_dump(config, f)

        port = find_free_port(preferred_port=9031)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "server failed to start"
        cls.server._wait_for_server_ready(timeout=15)

        cls.chrome_options = ChromeOptions()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-gpu", "--window-size=1920,1080"):
            cls.chrome_options.add_argument(arg)

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
        d.find_element(By.ID, "login-email").send_keys(f"thr_{int(time.time()*1000)}")
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".dialogue-turn"))
        )
        time.sleep(0.4)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    # -- rendering ---------------------------------------------------------- #

    def test_depth_is_derived_from_reply_to(self):
        depths = self.driver.execute_script(
            "return [...document.querySelectorAll('.dialogue-turn')]"
            ".map(t => t.getAttribute('data-depth'));"
        )
        self.assertEqual(depths, ["0", "1", "2", "1"])

    def test_indentation_increases_with_depth(self):
        margins = self.driver.execute_script(
            "return [...document.querySelectorAll('.dialogue-turn')]"
            ".map(t => parseFloat(getComputedStyle(t).marginLeft));"
        )
        self.assertEqual(margins[0], 0)
        self.assertGreater(margins[1], margins[0])
        self.assertGreater(margins[2], margins[1])
        self.assertEqual(margins[1], margins[3], "siblings share an indent")

    def test_timestamps_and_meta_chips_render_as_pseudo_content(self):
        content = self.driver.execute_script(
            "const t = document.querySelectorAll('.dialogue-turn')[1];"
            "return getComputedStyle(t.querySelector('.dialogue-text'), '::before').content;"
        )
        self.assertIn("+1h", content)
        self.assertIn("score", content)

    # -- the invariant ------------------------------------------------------ #

    def test_chrome_never_enters_the_span_offset_basis(self):
        """The reason the chrome is pseudo-content and not elements."""
        result = self.driver.execute_script(
            "const s = window.spanManager.fieldStrategies['thread'];"
            "const canon = s.getCanonicalText();"
            "return {canon: canon,"
            " raw: document.querySelector('.dialogue-display-content').textContent};"
        )
        for leaked in ("+1h", "score:", "depth 1"):
            self.assertNotIn(leaked, result["canon"])
        # The turn text itself is present.
        self.assertIn("Not for me, it times out.", result["canon"])

    def test_turn_widget_text_is_excluded_from_offsets(self):
        result = self.driver.execute_script(
            "const s = window.spanManager.fieldStrategies['thread'];"
            "return {canon: s.getCanonicalText(),"
            " raw: document.querySelector('.dialogue-display-content').textContent};"
        )
        # The widget labels are in the DOM...
        self.assertIn("off_topic", result["raw"])
        # ...but not in what offsets are measured against.
        self.assertNotIn("off_topic", result["canon"])

    def test_client_offsets_match_the_server_reconstruction(self):
        """The end-to-end guard: a span selected in the browser slices correctly."""
        from potato.server_utils.displays.base import reconstruct_dialogue_dom_text

        canon = self.driver.execute_script(
            "return window.spanManager.fieldStrategies['thread'].getCanonicalText();"
        )
        server = reconstruct_dialogue_dom_text(THREAD, show_turn_numbers=True)
        self.assertEqual(canon, server)

        phrase = "it times out"
        start = canon.index(phrase)
        self.assertEqual(server[start:start + len(phrase)], phrase)

    # -- per-turn annotation ------------------------------------------------ #

    def test_turn_widgets_are_keyed_by_the_turns_own_id(self):
        ids = self.driver.execute_script(
            "return [...document.querySelectorAll('.turn-anno-slot')]"
            ".map(s => s.getAttribute('data-turn-id'));"
        )
        self.assertEqual(ids, ["m1", "m2", "m3", "m4"])

    def _navigate(self, button_id):
        """Click a nav button and wait for the next instance to render.

        Scrolled into view first: at this viewport the annotation form can sit
        over the nav bar, and a click landing on the overlay is a quirk of the
        test window size rather than anything this test is about.
        """
        d = self.driver
        button = d.find_element(By.ID, button_id)
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
        time.sleep(0.2)
        try:
            button.click()
        except Exception:
            d.execute_script("arguments[0].click();", button)
        WebDriverWait(d, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".dialogue-turn"))
        )
        time.sleep(1.0)

    def test_per_turn_annotation_persists_across_navigation(self):
        """Navigate away and back — never refresh, which restores form state."""
        d = self.driver

        d.execute_script(
            "[...document.querySelectorAll('button.ta-chip')]"
            ".find(c => c.getAttribute('data-turn-id') === 'm3'"
            "        && c.getAttribute('data-value') === 'off_topic').click();"
        )
        time.sleep(2.0)   # save debounce

        self._navigate("next-btn")
        self._navigate("prev-btn")

        # Visual state, not just the hidden input's value.
        selected = d.execute_script(
            "return [...document.querySelectorAll('button.ta-chip.ta-selected')]"
            ".map(c => [c.getAttribute('data-turn-id'), c.getAttribute('data-value')]);"
        )
        self.assertIn(["m3", "off_topic"], selected)

        stored = d.execute_script(
            "const a = document.querySelector("
            "  'input.annotation-data-input[name=\"comment_flags\"]');"
            "return a ? a.value : null;"
        )
        self.assertIsNotNone(stored)
        self.assertIn("m3", json.loads(stored)["turns"])


if __name__ == "__main__":
    unittest.main()
