"""Selenium UI tests for the MAST failure-taxonomy preset (D2).

Covers the annotation-facing behavior added by D2: the `taxonomy_preset: mast`
auto-population, the accessible ⓘ tooltip markers, that clicking a marker does NOT
toggle its checkbox, and that a selected mode persists across navigate-away/back.
"""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions


class TestFailureTaxonomyUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file,
        )
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory("failure_taxonomy_ui")
        data = [{"id": "1", "text": "Trace A: planner ignored the task spec."},
                {"id": "2", "text": "Trace B: agents looped without verifying."}]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [{
            "annotation_type": "hierarchical_multiselect",
            "name": "failure_modes",
            "description": "Tag MAST failure modes",
            "taxonomy_preset": "mast",
            "show_search": True,
        }]
        cls.config_file = create_test_config(cls.test_dir, schemes, data_file=data_file)

        port = find_free_port(preferred_port=9021)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

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
        self.test_user = f"mast_user_{int(time.time() * 1000)}"
        self._login()

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        d = self.driver
        d.get(f"{self.server.base_url}/")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.ID, "login-email")))
        d.find_element(By.ID, "login-email").send_keys(self.test_user)
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        time.sleep(0.5)

    def _expand_all(self):
        for t in self.driver.find_elements(By.CSS_SELECTOR, ".hier-toggle"):
            try:
                t.click()
            except Exception:
                pass
        time.sleep(0.3)

    def test_preset_renders_categories_and_modes(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".hier-checkbox")))
        body = self.driver.page_source
        self.assertIn("Inter-Agent Misalignment", body)
        self.assertIn("1.1 Disobey task specification", body)
        self.assertIn("3.1 Premature termination", body)

    def test_info_markers_present_and_accessible(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".hier-checkbox")))
        markers = self.driver.find_elements(By.CSS_SELECTOR, ".hier-info")
        self.assertEqual(len(markers), 14)  # one per MAST mode
        m = markers[0]
        self.assertEqual(m.get_attribute("role"), "img")
        self.assertEqual(m.get_attribute("tabindex"), "0")
        self.assertTrue(m.get_attribute("aria-label"))

    def test_clicking_info_marker_does_not_toggle_checkbox(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".hier-checkbox")))
        self._expand_all()
        # Find a leaf node with both a checkbox and an info marker.
        leaf = self.driver.find_element(By.CSS_SELECTOR, ".hier-node .hier-info")
        node = leaf.find_element(By.XPATH, "./ancestor::div[contains(@class,'hier-node')][1]")
        cb = node.find_element(By.CSS_SELECTOR, ".hier-checkbox")
        before = cb.is_selected()
        self.driver.execute_script("arguments[0].click();", leaf)
        time.sleep(0.2)
        self.assertEqual(cb.is_selected(), before, "Clicking ⓘ must not toggle the checkbox")

    def test_select_mode_persists_after_navigate_away_and_back(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".hier-checkbox")))
        self._expand_all()
        target = "1.1 Disobey task specification"
        cb = d.find_element(By.CSS_SELECTOR, f".hier-checkbox[value='{target}']")
        self.driver.execute_script("arguments[0].click();", cb)
        time.sleep(2.0)  # debounced save

        # navigate away and back
        d.find_element(By.ID, "next-btn").click(); time.sleep(1.5)
        d.find_element(By.ID, "prev-btn").click(); time.sleep(1.5)
        self._expand_all()
        cb2 = d.find_element(By.CSS_SELECTOR, f".hier-checkbox[value='{target}']")
        self.assertTrue(cb2.is_selected(), "Selected MAST mode should persist after nav away/back")


if __name__ == "__main__":
    unittest.main()
