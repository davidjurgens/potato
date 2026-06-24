"""Selenium UI tests for the multimodal_reasoning schema (M15)."""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

_IMG = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' "
        "width='120' height='80'><rect width='120' height='80' fill='%23ddd'/></svg>")


class TestMultimodalReasoningUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file)
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory("multimodal_reasoning_ui")
        data = [{"id": "1", "task": "Chart QA",
                 "steps": [{"type": "text", "text": "look at the chart"},
                           {"type": "image", "image": _IMG, "caption": "a chart"},
                           {"type": "tool", "tool": "count", "args": {"x": 1}},
                           {"type": "action", "action": "Answer: Q3"}]},
                {"id": "2", "task": "Count",
                 "steps": [{"type": "text", "text": "I see five people"}]}]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [{"annotation_type": "multimodal_reasoning", "name": "reasoning_review",
                    "description": "Rate each step", "steps_key": "steps", "type_key": "type"}]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_file=data_file,
            item_properties={"id_key": "id", "text_key": "task"})
        port = find_free_port(preferred_port=9029)
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
        d.find_element(By.ID, "login-email").send_keys(f"mmr_{int(time.time()*1000)}")
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_typed_blocks_render(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mmr-card")))
        time.sleep(0.4)
        assert len(d.find_elements(By.CSS_SELECTOR, ".mmr-card")) == 4
        assert len(d.find_elements(By.CSS_SELECTOR, ".mmr-img")) == 1
        assert len(d.find_elements(By.CSS_SELECTOR, ".mmr-tool-name")) == 1

    def test_verdict_persists_after_navigate_away_and_back(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mmr-card")))
        time.sleep(0.4)
        btn = d.find_element(By.CSS_SELECTOR, '.mmr-card[data-idx="1"] .mmr-vbtn[data-v="visual_hallucination"]')
        d.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", btn)
        time.sleep(2.0)
        d.execute_script("document.getElementById('next-btn').click();"); time.sleep(1.5)
        d.execute_script("document.getElementById('prev-btn').click();"); time.sleep(1.5)
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mmr-card")))
        time.sleep(0.5)
        again = d.find_element(By.CSS_SELECTOR, '.mmr-card[data-idx="1"] .mmr-vbtn[data-v="visual_hallucination"]')
        assert "selected" in (again.get_attribute("class") or ""), "verdict did not persist"


if __name__ == "__main__":
    unittest.main()
