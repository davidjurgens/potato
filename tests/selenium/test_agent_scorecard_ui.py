"""Selenium UI tests for the agent_scorecard schema (M5)."""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions


class TestAgentScorecardUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file)
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory("agent_scorecard_ui")
        data = [{"id": "1", "task": "Plan + build",
                 "steps": [{"agent": "Planner", "content": "make a plan"},
                           {"agent": "Coder", "content": "write code"},
                           {"agent": "Reviewer", "content": "review"}]},
                {"id": "2", "task": "Research",
                 "steps": [{"agent": "Reader", "content": "read"},
                           {"agent": "Writer", "content": "summarize"}]}]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [{"annotation_type": "agent_scorecard", "name": "scorecard",
                    "description": "Score agents and team", "steps_key": "steps",
                    "agent_key": "agent", "scale": 5,
                    "milestones": ["plan made", "verified"]}]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_file=data_file,
            item_properties={"id_key": "id", "text_key": "task"})
        port = find_free_port(preferred_port=9024)
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
        d.find_element(By.ID, "login-email").send_keys(f"asc_{int(time.time()*1000)}")
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_agents_render(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".asc-card")))
        time.sleep(0.4)
        names = [e.text for e in d.find_elements(By.CSS_SELECTOR, ".asc-agent-name")]
        assert "Planner" in names and "Coder" in names and "Reviewer" in names

    def test_score_persists_after_navigate_away_and_back(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".asc-card")))
        time.sleep(0.4)
        # Score the first agent's first dimension a 4 (first .asc-sbtn[data-v="4"] in the first card).
        btn = d.find_element(By.CSS_SELECTOR, '.asc-card:first-child .asc-sbtn[data-v="4"]')
        d.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", btn)
        time.sleep(2.0)
        d.execute_script("document.getElementById('next-btn').click();"); time.sleep(1.5)
        d.execute_script("document.getElementById('prev-btn').click();"); time.sleep(1.5)
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".asc-card")))
        time.sleep(0.5)
        again = d.find_element(By.CSS_SELECTOR, '.asc-card:first-child .asc-sbtn[data-v="4"]')
        assert "selected" in (again.get_attribute("class") or ""), "score did not persist"


if __name__ == "__main__":
    unittest.main()
