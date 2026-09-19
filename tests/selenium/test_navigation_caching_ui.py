#!/usr/bin/env python3
"""
Next/Previous in a real browser: cached assets, a plain navigation, and the
answer still there on the way back.

Between instances the page shows "Loading annotation interface" until the next
page is usable. It used to revalidate every script and stylesheet on each page
(one round trip apiece), render the next page twice on the server, and reload
rather than navigate. These tests watch the browser side of the fix:

- after Next, no /static asset (fonts and @imported stylesheets included)
  comes from the network;
- the new page is a navigation, not a reload;
- the answer given before Next is visibly restored after Previous
  (navigate-away-and-back, not refresh -- browsers restore form state on
  refresh, which makes refresh-based persistence tests pass on their own).
"""

import os
import time
import unittest
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class TestNavigationCaching(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import create_test_config, create_test_data_file

        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(tests_dir, "output", f"nav_caching_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(cls.test_dir, [
            {"id": f"item_{i + 1}", "text": f"Navigation caching item {i + 1}."}
            for i in range(4)
        ])
        config_file = create_test_config(
            cls.test_dir,
            [{"name": "sentiment", "annotation_type": "radio",
              "labels": ["positive", "negative", "neutral"],
              "description": "Select the sentiment"}],
            data_files=[data_file],
            annotation_task_name="Navigation Caching Test",
            require_password=False,
        )
        cls.server = FlaskTestServer(port=find_free_port(preferred_port=9031),
                                     debug=False, config_file=config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        cls.chrome_options = ChromeOptions()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-gpu", "--window-size=1400,1000"):
            cls.chrome_options.add_argument(arg)
        cls.chrome_options.set_capability("goog:loggingPrefs", {"browser": "ALL"})

    @classmethod
    def tearDownClass(cls):
        cls.server.stop_server()
        from tests.helpers.test_utils import cleanup_test_directory
        cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "login-email")))
        self.driver.find_element(By.ID, "login-email").send_keys(f"nav_cache_{int(time.time() * 1000)}")
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        self._wait_ready()

    def tearDown(self):
        self.driver.quit()

    # -- helpers ---------------------------------------------------------

    def _wait_ready(self):
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content")))
        WebDriverWait(self.driver, 15).until(
            EC.invisibility_of_element_located((By.ID, "loading-state")))

    def _instance_id(self):
        return self.driver.find_element(By.ID, "instance_id").get_attribute("value")

    def _click_radio(self, label):
        radio = self.driver.find_element(
            By.CSS_SELECTOR, f"input[type='radio'][schema='sentiment'][label_name='{label}']")
        self.driver.find_element(By.CSS_SELECTOR, f"label[for='{radio.get_attribute('id')}']").click()

    def _checked(self):
        for radio in self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']"):
            if radio.is_selected():
                return radio.get_attribute("label_name")
        return None

    def _go(self, button_id):
        before = self._instance_id()
        origin = self.driver.execute_script("return performance.timeOrigin")
        self.driver.find_element(By.ID, button_id).click()
        WebDriverWait(self.driver, 15).until(
            lambda d: d.execute_script("return performance.timeOrigin") != origin)
        self._wait_ready()
        self.assertNotEqual(self._instance_id(), before)

    def _static_fetches(self):
        """(path, bytes over the network) for this document's /static requests.

        Resource Timing is scoped to the current document, so nothing from the
        previous page can leak in. A cache hit transfers 0 bytes; a 304
        revalidation transfers its headers.
        """
        return self.driver.execute_script("""
            return performance.getEntriesByType('resource')
                .filter(e => e.name.includes('/static/'))
                .map(e => [e.name.split('/static/')[1], e.transferSize]);
        """)

    # -- tests -----------------------------------------------------------

    def test_next_serves_every_static_asset_from_cache(self):
        first_load = self._static_fetches()
        self.assertTrue(
            any(size > 0 for _, size in first_load),
            "the first page load should have fetched assets; the check below "
            "would otherwise pass without measuring anything")

        self._click_radio("positive")
        time.sleep(1.5)  # autosave debounce
        self._go("next-btn")

        after = self._static_fetches()
        self.assertGreater(len(after), 5)
        from_network = [(path, size) for path, size in after if size > 0]
        self.assertEqual(from_network, [],
                         "every /static asset, including fonts and @imported "
                         "stylesheets, should come from the browser cache")
        self.assertTrue(self.driver.execute_script("return !!window.spanManager"))

    def test_next_is_a_navigation_not_a_reload(self):
        self._click_radio("negative")
        time.sleep(1.5)
        self._go("next-btn")
        nav_type = self.driver.execute_script(
            "return performance.getEntriesByType('navigation')[0].type")
        self.assertEqual(nav_type, "navigate")

    def test_answer_survives_next_and_previous(self):
        self._click_radio("neutral")
        time.sleep(1.5)
        self._go("next-btn")
        self.assertIsNone(self._checked(), "the next item should start unanswered")
        self._go("prev-btn")
        self.assertEqual(self._checked(), "neutral")

    def test_next_from_an_instance_id_url_moves_on(self):
        # A GET /annotate?instance_id=X moves the annotator to X. Next loads
        # the current URL after its POST, so keeping the parameter sent the
        # annotator straight back to the item they had just left.
        first = self._instance_id()
        self.driver.get(f"{self.server.base_url}/annotate?instance_id={first}")
        self._wait_ready()
        self.assertEqual(self._instance_id(), first)
        self._click_radio("positive")
        time.sleep(1.5)
        self._go("next-btn")   # asserts the item changed
        self.assertNotIn("instance_id", self.driver.current_url)

    def test_no_console_errors_across_navigation(self):
        self._click_radio("positive")
        time.sleep(1.5)
        self._go("next-btn")
        self._go("prev-btn")
        errors = [e["message"] for e in self.driver.get_log("browser")
                  if e["level"] == "SEVERE" and "favicon" not in e["message"]]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
