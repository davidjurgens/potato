"""
Selenium navigate-away-and-back persistence test for a custom-hidden-input B1
schema (process_reward).

This is the client-side complement to the API round-trip checks in QA: it
catches the IIFE-overwrite regression class (a page-load IIFE clobbering
server-restored values) that a curl/API round-trip cannot, because it executes
the real page JavaScript and asserts VISUAL state after Next -> Previous.

process_reward is the representative case: error_span / trajectory_eval /
code_review share the identical single-hidden-JSON-input shape whose init IIFE
restores from input.value (the correct pattern).
"""

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

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PRM_CONFIG = os.path.join(_REPO, "examples/agent-traces/coding-agent-prm/config.yaml")


class TestProcessRewardPersistenceUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = find_free_port()
        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=PRM_CONFIG)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        cls.chrome_options = ChromeOptions()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-gpu", "--window-size=1920,1080"):
            cls.chrome_options.add_argument(arg)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.user = f"prm_user_{int(time.time() * 1000)}"

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        d = self.driver
        d.get(f"{self.server.base_url}/")
        WebDriverWait(d, 10).until(
            EC.presence_of_element_located((By.ID, "login-email")))
        d.find_element(By.ID, "login-email").send_keys(self.user)
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content")))

    def _card_class(self, step_idx):
        return self.driver.find_element(
            By.CSS_SELECTOR, f'.prm-step-card[data-step-index="{step_idx}"]'
        ).get_attribute("class")

    def test_process_reward_marks_persist_across_navigation(self):
        d = self.driver
        self._login()

        # Wait for the inline PRM controls to be injected into the coding trace.
        WebDriverWait(d, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".prm-btn-incorrect")))
        incorrect_btn = d.find_elements(By.CSS_SELECTOR, ".prm-btn-incorrect")[0]
        step_idx = incorrect_btn.get_attribute("data-step")

        # Mark the step incorrect through the real widget button.
        d.execute_script("arguments[0].click();", incorrect_btn)
        time.sleep(1.5)  # save debounce

        # Hidden input now carries a reward, and the card shows the incorrect state.
        val = d.execute_script(
            "return document.querySelector('.process-reward-data-input').value;")
        self.assertTrue(val and '"reward"' in val,
                        f"hidden input should hold rewards, got {val!r}")
        self.assertIn("prm-incorrect", self._card_class(step_idx),
                      "card should visually show the incorrect mark")

        # Navigate away (Next) and back (Previous) — a real round-trip that
        # destroys and rebuilds the annotation DOM and re-runs the page IIFE.
        d.execute_script("document.getElementById('next-btn').click();")
        WebDriverWait(d, 10).until(
            EC.presence_of_element_located((By.ID, "prev-btn")))
        time.sleep(1.0)
        d.execute_script("document.getElementById('prev-btn').click();")
        WebDriverWait(d, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, f'.prm-step-card[data-step-index="{step_idx}"]')))
        time.sleep(1.5)  # let the PRM IIFE rebuild from the restored value

        # IIFE round-trip: the visual mark must be RESTORED, not clobbered.
        self.assertIn("prm-incorrect", self._card_class(step_idx),
                      "step mark must survive Next->Previous (IIFE must restore "
                      "from the server-populated hidden input, not overwrite it)")
        restored_val = d.execute_script(
            "return document.querySelector('.process-reward-data-input').value;")
        self.assertTrue(restored_val and '"reward"' in restored_val,
                        f"hidden input should be repopulated, got {restored_val!r}")


if __name__ == "__main__":
    unittest.main()
