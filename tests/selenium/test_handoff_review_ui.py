"""Selenium UI tests for the handoff_review schema (M2)."""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions


class TestHandoffReviewUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file)
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory("handoff_review_ui")
        data = [{"id": "1", "task": "Plan + build",
                 "steps": [{"agent": "Planner", "content": "make a plan"},
                           {"agent": "Coder", "content": "write code"},
                           {"agent": "Reviewer", "content": "review"}]},
                {"id": "2", "task": "Research",
                 "steps": [{"agent": "Reader", "content": "read"},
                           {"agent": "Writer", "content": "summarize"}]}]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [{"annotation_type": "handoff_review", "name": "handoffs",
                    "description": "Review handoffs", "steps_key": "steps",
                    "agent_key": "agent", "quality_scale": 5}]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_file=data_file,
            item_properties={"id_key": "id", "text_key": "task"})
        port = find_free_port(preferred_port=9025)
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
        d.find_element(By.ID, "login-email").send_keys(f"hr_{int(time.time()*1000)}")
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_handoffs_render(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".hr-card")))
        time.sleep(0.4)
        # 3 agents -> 2 handoffs (Planner->Coder, Coder->Reviewer).
        cards = d.find_elements(By.CSS_SELECTOR, ".hr-card")
        assert len(cards) == 2
        froms = [e.text for e in d.find_elements(By.CSS_SELECTOR, ".hr-from")]
        assert "Planner" in froms and "Coder" in froms

    def test_flag_persists_after_navigate_away_and_back(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".hr-card")))
        time.sleep(0.4)
        d.find_element(By.CSS_SELECTOR, '.hr-card[data-idx="0"] .hr-flag[data-f="info_loss"]').click()
        time.sleep(2.0)
        d.find_element(By.ID, "next-btn").click(); time.sleep(1.5)
        d.find_element(By.ID, "prev-btn").click(); time.sleep(1.5)
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".hr-card")))
        time.sleep(0.5)
        btn = d.find_element(By.CSS_SELECTOR, '.hr-card[data-idx="0"] .hr-flag[data-f="info_loss"]')
        assert "selected" in (btn.get_attribute("class") or ""), "flag did not persist"


if __name__ == "__main__":
    unittest.main()
