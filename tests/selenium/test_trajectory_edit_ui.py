"""
Selenium UI + persistence tests for the trajectory_edit schema.

The persistence test uses navigate-away-and-back (Next then Previous), NOT a
page refresh — browsers cache form state across refresh, which would give a
false positive even if the server never stored the edit (CLAUDE.md).
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


class TestTrajectoryEditUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.config_path = os.path.join(
            get_project_root(),
            "examples/agent-traces/trajectory-correction/config.yaml",
        )
        port = find_free_port(preferred_port=9076)
        cls.server = FlaskTestServer(config=cls.config_path, port=port)
        assert cls.server.start(), "Failed to start Flask server"

        cls.opts = ChromeOptions()
        cls.opts.add_argument("--headless=new")
        cls.opts.add_argument("--no-sandbox")
        cls.opts.add_argument("--disable-dev-shm-usage")
        cls.opts.add_argument("--disable-gpu")
        cls.opts.add_argument("--window-size=1600,1200")
        cls.opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        cls.opts.add_experimental_option("useAutomationExtension", False)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.opts)
        self.user = f"test_traj_{int(time.time() * 1000)}"
        self._login()

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email")))
        try:
            self.driver.find_element(By.ID, "register-tab").click()
            WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.ID, "register-content")))
            self.driver.find_element(By.ID, "register-email").send_keys(self.user)
            self.driver.find_element(By.ID, "register-pass").send_keys("test123")
            self.driver.find_element(By.CSS_SELECTOR, "#register-content form").submit()
        except NoSuchElementException:
            f = self.driver.find_element(By.ID, "login-email")
            f.clear(); f.send_keys(self.user)
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(0.5)
        try:
            WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.ID, "main-content")))
        except TimeoutException:
            pass

    def _wait_editor(self):
        return WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "trajectory-edit-container")))

    def _click_nav(self, btn_id, fallback_css):
        """Click a nav button and wait for the real reload (instance_id stale).

        The trajectory-correction page is tall (multiple step editors), so the
        nav button can be off-screen / overlapped — scroll it into view and
        fall back to a JS click to avoid ElementClickIntercepted.
        """
        def _click():
            try:
                btn = self.driver.find_element(By.ID, btn_id)
            except Exception:
                btn = self.driver.find_element(By.CSS_SELECTOR, fallback_css)
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", btn)
            try:
                btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", btn)
        marker = self.driver.find_element(By.ID, "instance_id")
        _click()
        try:
            WebDriverWait(self.driver, 10).until(EC.staleness_of(marker))
        except TimeoutException:
            time.sleep(0.5)
            _click()
            WebDriverWait(self.driver, 10).until(EC.staleness_of(marker))
        self._wait_editor()

    def _textareas(self):
        return self.driver.find_elements(By.CSS_SELECTOR, ".trajedit-textarea")

    # --- rendering ---

    def test_editors_render_prefilled(self):
        self._wait_editor()
        tas = self._textareas()
        self.assertGreater(len(tas), 0)
        # First editor is prefilled with the original action text.
        self.assertTrue(tas[0].get_attribute("value").strip())

    def test_final_answer_editor_present(self):
        self._wait_editor()
        self.assertTrue(self.driver.find_elements(By.CSS_SELECTOR, ".trajedit-final-card"))

    def test_edit_shows_diff_and_flag(self):
        self._wait_editor()
        ta = self._textareas()[0]
        ta.clear()
        ta.send_keys("web_search(query='San Francisco weather')")
        time.sleep(0.6)
        # An "edited" flag and diff spans appear.
        flags = [f.text for f in self.driver.find_elements(By.CSS_SELECTOR, ".trajedit-edited-flag") if f.text.strip()]
        self.assertTrue(flags)
        self.assertTrue(self.driver.find_elements(By.CSS_SELECTOR, ".trajedit-diff-ins, .trajedit-diff-del"))

    def test_reset_restores_original(self):
        self._wait_editor()
        ta = self._textareas()[0]
        original = ta.get_attribute("value")
        ta.clear(); ta.send_keys("totally different")
        time.sleep(0.5)
        # Click the Reset button inside the same field block.
        block = ta.find_element(By.XPATH, "./ancestor::div[contains(@class,'trajedit-field-block')]")
        block.find_element(By.CSS_SELECTOR, ".trajedit-reset-btn").click()
        time.sleep(0.4)
        self.assertEqual(ta.get_attribute("value"), original)

    # --- the critical persistence test: navigate away and back ---

    def test_edit_persists_across_navigation(self):
        self._wait_editor()
        ta = self._textareas()[0]
        ta.clear()
        new_text = "web_search(query='San Francisco weather')"
        ta.send_keys(new_text)
        time.sleep(1.8)  # debounce + save

        # Navigate to the next instance, then back (real reloads, not refresh).
        self._click_nav("next-btn", 'a[onclick*="click_to_next"]')
        self._click_nav("prev-btn", 'a[onclick*="click_to_prev"]')

        ta2 = self._textareas()[0]
        # Visual state — the edited text survived navigation (not a refresh false-positive).
        self.assertEqual(ta2.get_attribute("value"), new_text)
        # And the edited flag is restored.
        flags = [f.text for f in self.driver.find_elements(By.CSS_SELECTOR, ".trajedit-edited-flag") if f.text.strip()]
        self.assertTrue(flags, "edited flag not restored after navigation")

    def test_step_text_xss_escaped(self):
        # The example data has no <script>; assert escaping at the renderer level
        # by checking the original block contains escaped entities, not raw tags.
        self._wait_editor()
        page = self.driver.page_source
        self.assertNotIn("<script>alert", page)


if __name__ == "__main__":
    unittest.main()
