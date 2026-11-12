"""
Selenium UI tests for the eval_trace three-pane display.

Drives the continuous-eval example end-to-end and verifies:
- the three panes (reasoning | function calls | final answer) render
- panes are laid out side-by-side (not stacked) at desktop width
- clicking a reasoning card highlights the linked card(s) across panes
- the per-component eval schemes render alongside the panes

Uses examples/agent-traces/continuous-eval/config.yaml.
"""

import os
import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port

import pytest

pytestmark = pytest.mark.core


def get_project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


class TestEvalTraceUI(unittest.TestCase):
    """Selenium tests for the eval_trace display type."""

    @classmethod
    def setUpClass(cls):
        project_root = get_project_root()
        cls.config_path = os.path.join(
            project_root, "examples/agent-traces/continuous-eval/config.yaml"
        )

        port = find_free_port(preferred_port=9072)
        cls.server = FlaskTestServer(config=cls.config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start Flask server"

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        cls.chrome_options.add_experimental_option("useAutomationExtension", False)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"test_eval_{int(time.time() * 1000)}"
        self._login()

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        try:
            register_tab = self.driver.find_element(By.ID, "register-tab")
            register_tab.click()
            WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.ID, "register-content"))
            )
            self.driver.find_element(By.ID, "register-email").send_keys(self.test_user)
            self.driver.find_element(By.ID, "register-pass").send_keys("test123")
            self.driver.find_element(By.CSS_SELECTOR, "#register-content form").submit()
        except NoSuchElementException:
            field = self.driver.find_element(By.ID, "login-email")
            field.clear()
            field.send_keys(self.test_user)
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        time.sleep(0.5)
        try:
            WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.ID, "main-content"))
            )
        except TimeoutException:
            pass

    def _wait_display(self):
        return WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".eval-trace-display"))
        )

    # --- rendering ---

    def test_three_panes_render(self):
        self._wait_display()
        panes = self.driver.find_elements(By.CSS_SELECTOR, ".eval-pane")
        self.assertEqual(len(panes), 3)

    def test_pane_headers(self):
        self._wait_display()
        headers = [
            h.text.strip().lower()
            for h in self.driver.find_elements(By.CSS_SELECTOR, ".eval-pane-header")
        ]
        self.assertIn("reasoning", headers)
        self.assertIn("function calls", headers)
        self.assertIn("final answer", headers)

    def test_panes_side_by_side(self):
        """Panes must be laid out horizontally (same top, increasing left)."""
        self._wait_display()
        panes = self.driver.find_elements(By.CSS_SELECTOR, ".eval-pane")
        rects = [p.rect for p in panes]
        tops = [round(r["y"]) for r in rects]
        lefts = [round(r["x"]) for r in rects]
        # tops roughly equal
        self.assertLess(max(tops) - min(tops), 20, f"panes not aligned: {tops}")
        # lefts strictly increasing
        self.assertTrue(lefts[0] < lefts[1] < lefts[2], f"panes not side-by-side: {lefts}")

    def test_reasoning_and_calls_content(self):
        self._wait_display()
        reasoning = self.driver.find_element(By.CSS_SELECTOR, ".eval-pane-reasoning")
        calls = self.driver.find_element(By.CSS_SELECTOR, ".eval-pane-calls")
        self.assertTrue(reasoning.find_elements(By.CSS_SELECTOR, ".eval-card"))
        # tool badge present in the calls pane
        self.assertTrue(calls.find_elements(By.CSS_SELECTOR, ".eval-tool-badge"))

    def test_final_answer_content(self):
        self._wait_display()
        answer = self.driver.find_element(By.CSS_SELECTOR, ".eval-pane-answer")
        self.assertTrue(answer.text.strip())

    # --- cross-pane linking ---

    def test_click_links_across_panes(self):
        self._wait_display()
        # pick a reasoning card that has a step index also present in calls
        cards = self.driver.find_elements(
            By.CSS_SELECTOR, ".eval-pane-reasoning .eval-card[data-step-index]"
        )
        self.assertTrue(cards, "no linkable reasoning cards found")
        target = cards[0]
        idx = target.get_attribute("data-step-index")
        target.click()
        time.sleep(0.4)
        linked = self.driver.find_elements(By.CSS_SELECTOR, ".eval-card.eval-linked")
        self.assertGreaterEqual(len(linked), 1)
        # all highlighted cards share the clicked index
        for c in linked:
            self.assertEqual(c.get_attribute("data-step-index"), idx)

    def test_click_outside_clears_link(self):
        self._wait_display()
        cards = self.driver.find_elements(
            By.CSS_SELECTOR, ".eval-pane-reasoning .eval-card[data-step-index]"
        )
        self.assertTrue(cards)
        cards[0].click()
        time.sleep(0.3)
        self.assertTrue(self.driver.find_elements(By.CSS_SELECTOR, ".eval-card.eval-linked"))
        # click an empty area of the display
        self.driver.find_element(By.CSS_SELECTOR, ".eval-pane-answer .eval-pane-header").click()
        time.sleep(0.3)
        self.assertFalse(self.driver.find_elements(By.CSS_SELECTOR, ".eval-card.eval-linked"))

    # --- eval schemes alongside the panes ---

    def test_eval_schemes_present(self):
        self._wait_display()
        page = self.driver.page_source
        for scheme in ["reasoning_quality", "tool_use_correctness", "answer_helpfulness", "failure_mode", "notes"]:
            self.assertIn(scheme, page, f"missing eval scheme: {scheme}")


if __name__ == "__main__":
    unittest.main()
