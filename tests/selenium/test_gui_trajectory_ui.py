"""Selenium UI tests for the gui_trajectory schema (M11)."""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

_PNG = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' "
        "width='200' height='120'><rect width='200' height='120' fill='%23eee'/></svg>")


class TestGuiTrajectoryUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file)
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory("gui_trajectory_ui")
        data = [{"id": "1", "task": "Open settings",
                 "steps": [{"action": "click settings", "x": 0.2, "y": 0.8, "screenshot": _PNG},
                           {"action": "toggle dark mode", "x": 0.7, "y": 0.3, "screenshot": _PNG}]},
                {"id": "2", "task": "Search files",
                 "steps": [{"action": "click search", "x": 0.5, "y": 0.1, "screenshot": _PNG}]}]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [{"annotation_type": "gui_trajectory", "name": "gui_review",
                    "description": "Judge each GUI step", "steps_key": "steps"}]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_file=data_file,
            item_properties={"id_key": "id", "text_key": "task"})
        port = find_free_port(preferred_port=9027)
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
        d.find_element(By.ID, "login-email").send_keys(f"gt_{int(time.time()*1000)}")
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_steps_render_with_screenshots_and_markers(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gt-card")))
        time.sleep(0.4)
        assert len(d.find_elements(By.CSS_SELECTOR, ".gt-card")) == 2
        assert len(d.find_elements(By.CSS_SELECTOR, ".gt-shot")) == 2
        assert len(d.find_elements(By.CSS_SELECTOR, ".gt-marker")) == 2

    def test_verdict_persists_after_navigate_away_and_back(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gt-card")))
        time.sleep(0.4)
        btn = d.find_element(By.CSS_SELECTOR, '.gt-card[data-idx="1"] .gt-vbtn[data-v="wrong_element"]')
        d.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", btn)
        time.sleep(2.0)
        d.execute_script("document.getElementById('next-btn').click();"); time.sleep(1.5)
        d.execute_script("document.getElementById('prev-btn').click();"); time.sleep(1.5)
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gt-card")))
        time.sleep(0.5)
        again = d.find_element(By.CSS_SELECTOR, '.gt-card[data-idx="1"] .gt-vbtn[data-v="wrong_element"]')
        assert "selected" in (again.get_attribute("class") or ""), "verdict did not persist"


if __name__ == "__main__":
    unittest.main()
