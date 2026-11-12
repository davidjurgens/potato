"""Selenium test for hotkey review mode (review_mode auto-advance).

With review_mode.enabled + auto_advance, completing the only schema on the
page (via click or keybinding) must auto-navigate to the next instance.
"""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions


class TestReviewModeAutoAdvance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file)
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory("review_mode_ui")
        data = [
            {"id": "r1", "text": "response one"},
            {"id": "r2", "text": "response two"},
            {"id": "r3", "text": "response three"},
        ]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [{
            "annotation_type": "radio", "name": "verdict",
            "description": "verdict", "labels": ["good", "bad"],
            "sequential_key_binding": True,
        }]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[data_file],
            item_properties={"id_key": "id", "text_key": "text"},
            additional_config={
                "review_mode": {"enabled": True, "auto_advance": True,
                                "advance_on": "complete", "delay_ms": 200},
            })
        port = find_free_port(preferred_port=9028)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "server failed to start"
        cls.server._wait_for_server_ready(timeout=10)
        cls.chrome_options = ChromeOptions()
        for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-gpu", "--window-size=1920,1080"):
            cls.chrome_options.add_argument(a)

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
        d.find_element(By.ID, "login-email").send_keys(f"rm_{int(time.time() * 1000)}")
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _current_instance_id(self):
        el = self.driver.find_element(By.ID, "instance_id")
        return el.get_attribute("value")

    def test_completing_schema_auto_advances(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="radio"]')))
        time.sleep(0.4)
        first_id = self._current_instance_id()

        # Answer the only schema — review mode should navigate automatically
        # (delay_ms=200 + save round-trip + reload).
        d.find_element(By.CSS_SELECTOR, 'input[type="radio"][value="good"]').click()
        deadline = time.time() + 8
        advanced = False
        while time.time() < deadline:
            time.sleep(0.5)
            try:
                if self._current_instance_id() != first_id:
                    advanced = True
                    break
            except Exception:
                pass  # mid-navigation reload
        assert advanced, "review mode did not auto-advance after completion"

    def test_no_advance_while_incomplete(self):
        """Loading a fresh instance without annotating must not navigate."""
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="radio"]')))
        time.sleep(0.4)
        first_id = self._current_instance_id()
        time.sleep(2.0)
        assert self._current_instance_id() == first_id, \
            "review mode advanced without any annotation"


if __name__ == "__main__":
    unittest.main()
