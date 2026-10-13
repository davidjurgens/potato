"""Readable span highlights, keyboard per-turn ratings, and an unboxed trace.

UI audit, 2026-10-08. Each of these passed every existing test while broken:

* A span highlight was painted over its text at alpha 0.8, leaving the
  labelled words at about 2:1 contrast.
* Per-turn ratings were bare spans, so they could not be reached by keyboard.
* Every display field was capped at 500px, cutting an agent trace off
  mid-sentence with no way to see the rest except scrolling a nested pane.

Persistence uses navigate-away-and-back (Next, then Previous) and checks the
visual state, per CLAUDE.md: a refresh can restore cached form state and pass
when the server stored nothing.
"""

import json
import os
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)
from tests.selenium.test_base import BaseSeleniumTest


CONTRAST_JS = """
const seg = arguments[0];
const parse = c => { const m = c.match(/[\\d.]+/g).map(Number); return m.length === 3 ? [...m, 1] : m; };
const lin = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
const L = c => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
const over = (t, b) => [0, 1, 2].map(i => t[3] * t[i] + (1 - t[3]) * b[i]);
const fill = parse(getComputedStyle(seg).backgroundColor);
let e = document.getElementById('instance-text'), bg = [255, 255, 255];
while (e) { const c = parse(getComputedStyle(e).backgroundColor); if (c[3] > 0.9) { bg = c; break; } e = e.parentElement; }
const fg = parse(getComputedStyle(document.getElementById('instance-text')).color);
const b = over(fill, bg), t = over(fill, fg);
return (Math.max(L(b), L(t)) + 0.05) / (Math.min(L(b), L(t)) + 0.05);
"""


class TestSpanHighlightReadability(BaseSeleniumTest):
    """Uses BaseSeleniumTest's span config."""

    def _make_span(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "instance-text")))
        time.sleep(1.5)
        label = self.driver.find_element(
            By.CSS_SELECTOR, ".annotation-form.span input[type=checkbox]")
        self.driver.execute_script("arguments[0].click();", label)
        # A real drag across the first word.
        box = self.driver.execute_script("""
            const root = document.getElementById('instance-text');
            const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
            let n;
            while ((n = w.nextNode())) {
              const m = n.textContent.match(/[A-Za-z]{3,}/);
              if (!m || n.parentElement.closest('#span-overlays')) continue;
              const r = document.createRange();
              r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
              const b = r.getBoundingClientRect();
              return [b.left, b.top + b.height / 2, b.width];
            }
            return null;""")
        self.assertIsNotNone(box, "no word to select")
        x0, y, width = box
        actions = ActionBuilder(self.driver)
        actions.pointer_action.move_to_location(int(x0) + 1, int(y))
        actions.pointer_action.pointer_down()
        actions.pointer_action.move_to_location(int(x0 + width) - 1, int(y))
        actions.pointer_action.pointer_up()
        actions.perform()
        selector = (By.CSS_SELECTOR, ".span-overlay-pure .span-highlight-segment")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located(selector))
        # The overlay is redrawn once the server confirms the span; take the
        # settled element, not the first one drawn.
        time.sleep(1.5)
        return self.driver.find_element(*selector)

    def test_highlighted_text_stays_readable(self):
        segment = self._make_span()
        ratio = self.driver.execute_script(CONTRAST_JS, segment)
        self.assertGreaterEqual(ratio, 7, f"covered text at {ratio:.2f}:1")

    def test_delete_control_uses_destructive_token(self):
        self._make_span()
        btn = self.driver.find_element(By.CSS_SELECTOR, ".span-controls .span-delete-btn")
        colour = btn.value_of_css_property("background-color")
        destructive = self.driver.execute_script(
            "const p=document.createElement('div'); p.style.color='var(--destructive-text)';"
            "document.body.appendChild(p); const c=getComputedStyle(p).color; p.remove(); return c;")
        self.assertEqual(colour.replace("rgba", "rgb").replace(", 1)", ")"), destructive)
        self.assertTrue(btn.get_attribute("aria-label").startswith("Remove "))


def _dialogue(n_pairs):
    turns = []
    for i in range(n_pairs):
        turns.append({"speaker": "Agent (Thought)",
                      "text": f"Step {i}: I should look at the next result carefully before acting."})
        turns.append({"speaker": "Agent (Action)", "text": f"click(result={i})"})
    return turns


class TestPerTurnRatingKeyboard(BaseSeleniumTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()          # chrome options; its span server is replaced
        cls.server.stop_server()
        cls.dialogue_dir = create_test_directory("display_a11y_dialogue")
        data = [{"id": f"t{i}", "text": f"trace {i}", "conversation": _dialogue(20)}
                for i in range(1, 4)]
        data_file = create_test_data_file(cls.dialogue_dir, data)
        config_file = create_test_config(
            cls.dialogue_dir,
            [{"annotation_type": "radio", "name": "task_success",
              "description": "Did it work?", "labels": ["yes_it_did", "no_it_did_not"]}],
            data_files=[data_file],
            additional_config={
                "instance_display": {
                    "fields": [{
                        "key": "conversation", "type": "dialogue", "label": "Trace",
                        "display_options": {
                            "per_turn_ratings": {
                                "speakers": ["Agent (Action)"],
                                "schema_name": "action_correctness",
                                "scheme": {"type": "likert", "size": 3,
                                           "labels": ["Wrong", "Right"]},
                            }
                        },
                    }]
                }
            },
        )
        port = find_free_port(preferred_port=9318)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cleanup_test_directory(cls.dialogue_dir)

    def _load(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".ptr-value")))
        time.sleep(1)

    def _instance(self):
        # Read through JS: navigation reloads the page, and a held element
        # goes stale between find and read.
        return self.driver.execute_script(
            "const e = document.getElementById('instance_id'); return e && e.value;")

    def _group_state(self, index=0):
        return self.driver.execute_script("""
            const g = document.querySelectorAll('.ptr-values')[arguments[0]];
            return [...g.querySelectorAll('.ptr-value')].map(v => ({
              checked: v.getAttribute('aria-checked'), tab: v.tabIndex,
              filled: v.classList.contains('ptr-selected')}));""", index)

    def test_keyboard_sets_rating_without_leaving_the_item(self):
        self._load()
        instance = self.driver.find_element(By.ID, "instance_id").get_attribute("value")
        first = self.driver.find_elements(By.CSS_SELECTOR, ".ptr-value")[0]
        self.assertEqual(first.get_attribute("role"), "radio")
        # Tab until the first rating group has focus.
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.click()
        for _ in range(40):
            ActionChains(self.driver).send_keys(Keys.TAB).perform()
            if self.driver.execute_script(
                    "return document.activeElement === document.querySelector('.ptr-value')"):
                break
        else:
            self.fail("Tab never reached a per-turn rating")
        ActionChains(self.driver).send_keys(Keys.ARROW_RIGHT).send_keys(Keys.ARROW_RIGHT).perform()
        time.sleep(0.3)
        # Arrows choose a value; they must not navigate to another item.
        self.assertEqual(
            self.driver.find_element(By.ID, "instance_id").get_attribute("value"), instance)
        self.assertEqual(
            [s["checked"] for s in self._group_state()], ["false", "false", "true"])
        self.assertEqual([s["tab"] for s in self._group_state()], [-1, -1, 0])

        # Persistence: navigate away and back, then check the VISUAL state.
        time.sleep(1.6)
        nxt = self.driver.find_element(By.ID, "next-btn")
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", nxt)
        time.sleep(0.3)
        nxt.click()
        WebDriverWait(self.driver, 10).until(
            lambda d: self._instance() not in (None, instance))
        # Next reloads the page; wait for the new document to settle.
        time.sleep(2)
        prev = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, "prev-btn")))
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", prev)
        time.sleep(0.3)
        prev.click()
        WebDriverWait(self.driver, 10).until(
            lambda d: self._instance() == instance)
        time.sleep(1)
        state = self._group_state()
        self.assertEqual([s["filled"] for s in state], [True, True, True])
        self.assertEqual([s["checked"] for s in state], ["false", "false", "true"])

        stored = self.driver.execute_script(
            "return fetch('/get_annotations?instance_id=' + arguments[0]).then(r => r.text());",
            instance)
        self.assertIn("action_correctness", stored)

    def test_space_toggles_the_focused_value(self):
        self._load()
        target = self.driver.find_elements(By.CSS_SELECTOR, ".ptr-values")[1] \
            .find_elements(By.CSS_SELECTOR, ".ptr-value")[1]
        self.driver.execute_script("arguments[0].focus();", target)
        ActionChains(self.driver).send_keys(Keys.SPACE).perform()
        self.assertEqual([s["checked"] for s in self._group_state(1)], ["false", "true", "false"])
        ActionChains(self.driver).send_keys(Keys.SPACE).perform()
        self.assertEqual([s["checked"] for s in self._group_state(1)], ["false", "false", "false"])

    def test_long_trace_gets_show_all(self):
        self._load()
        pane = self.driver.find_element(By.CSS_SELECTOR, ".display-field-resizable")
        button = self.driver.find_element(By.CSS_SELECTOR, ".display-field-expand")
        self.assertTrue(button.is_displayed(), "a 40-turn trace should overflow 80vh")
        before = pane.size["height"]
        button.click()
        time.sleep(0.3)
        self.assertEqual(button.get_attribute("aria-expanded"), "true")
        after = pane.size["height"]
        scroll_height = self.driver.execute_script("return arguments[0].scrollHeight", pane)
        self.assertGreater(after, before)
        self.assertLessEqual(scroll_height - after, 4, "expanded pane still scrolls")
