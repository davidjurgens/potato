"""Selenium UI tests for the failure_attribution schema (M1)."""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions


class TestFailureAttributionUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file)
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory("failure_attribution_ui")
        data = [{"id": "1", "task": "Book a flight",
                 "steps": [{"agent": "Planner", "content": "Plan the booking."},
                           {"agent": "Researcher", "content": "Found 3 options."},
                           {"agent": "Booking", "content": "Booked the wrong one."}]},
                {"id": "2", "task": "Summarize a paper",
                 "steps": [{"agent": "Reader", "content": "Read it."},
                           {"agent": "Writer", "content": "Wrote summary."}]}]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [{"annotation_type": "failure_attribution", "name": "attribution",
                    "description": "Which agent failed?", "steps_key": "steps", "agent_key": "agent"}]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_file=data_file,
            item_properties={"id_key": "id", "text_key": "task"})
        port = find_free_port(preferred_port=9022)
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
        self.user = f"fa_user_{int(time.time()*1000)}"
        d = self.driver
        d.get(f"{self.server.base_url}/")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.ID, "login-email")))
        d.find_element(By.ID, "login-email").send_keys(self.user)
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_agents_populate_from_trace(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".fa-agent")))
        time.sleep(0.5)
        agents = [o.text for o in d.find_elements(By.CSS_SELECTOR, ".fa-agent option")]
        assert "Planner" in agents and "Researcher" in agents and "Booking" in agents

    def test_attribution_persists_after_navigate_away_and_back(self):
        from selenium.webdriver.support.ui import Select
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".fa-agent")))
        time.sleep(0.5)
        Select(d.find_element(By.CSS_SELECTOR, ".fa-agent")).select_by_visible_text("Booking")
        Select(d.find_element(By.CSS_SELECTOR, ".fa-step")).select_by_index(3)  # step 3
        reason = d.find_element(By.CSS_SELECTOR, ".fa-reason")
        reason.send_keys("Booking agent booked the wrong flight.")
        time.sleep(2.0)  # debounced save

        d.find_element(By.ID, "next-btn").click(); time.sleep(1.5)
        d.find_element(By.ID, "prev-btn").click(); time.sleep(1.5)
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".fa-agent")))
        time.sleep(0.5)
        assert d.find_element(By.CSS_SELECTOR, ".fa-agent").get_attribute("value") == "Booking"
        assert "wrong flight" in d.find_element(By.CSS_SELECTOR, ".fa-reason").get_attribute("value")


if __name__ == "__main__":
    unittest.main()
