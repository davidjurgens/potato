"""Selenium UI tests for the voice_interaction schema (M9)."""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions


class TestVoiceInteractionUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file)
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory("voice_interaction_ui")
        # Instance 1 has one overlap (user 6.0-7.4 vs agent 3.0-6.5 -> 6.0-6.5).
        data = [{"id": "1", "task": "Reservation",
                 "turns": [{"speaker": "user", "start": 0.0, "end": 2.8, "text": "table for four"},
                           {"speaker": "agent", "start": 3.0, "end": 6.5, "text": "patio or inside?"},
                           {"speaker": "user", "start": 6.0, "end": 7.4, "text": "patio"}]},
                {"id": "2", "task": "Support",
                 "turns": [{"speaker": "user", "start": 0.0, "end": 3.5, "text": "internet drops"},
                           {"speaker": "agent", "start": 3.7, "end": 9.0, "text": "restart router"}]}]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [{"annotation_type": "voice_interaction", "name": "turn_taking",
                    "description": "Classify overlaps", "turns_key": "turns",
                    "speaker_key": "speaker", "rating_scale": 5}]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_file=data_file,
            item_properties={"id_key": "id", "text_key": "task"})
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
        d.find_element(By.ID, "login-email").send_keys(f"vi_{int(time.time()*1000)}")
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_timeline_and_overlap_render(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".vi-timeline")))
        time.sleep(0.4)
        assert len(d.find_elements(By.CSS_SELECTOR, ".vi-turn")) == 3
        # One overlap card + one overlap band on the timeline.
        assert len(d.find_elements(By.CSS_SELECTOR, ".vi-ocard")) == 1
        assert len(d.find_elements(By.CSS_SELECTOR, ".vi-overlap-band")) == 1

    def test_overlap_label_persists_after_navigate_away_and_back(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".vi-ocard")))
        time.sleep(0.4)
        btn = d.find_element(By.CSS_SELECTOR, '.vi-ocard[data-idx="0"] .vi-lbtn[data-l="backchannel"]')
        d.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", btn)
        time.sleep(2.0)
        d.execute_script("document.getElementById('next-btn').click();"); time.sleep(1.5)
        d.execute_script("document.getElementById('prev-btn').click();"); time.sleep(1.5)
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".vi-ocard")))
        time.sleep(0.5)
        again = d.find_element(By.CSS_SELECTOR, '.vi-ocard[data-idx="0"] .vi-lbtn[data-l="backchannel"]')
        assert "selected" in (again.get_attribute("class") or ""), "overlap label did not persist"


if __name__ == "__main__":
    unittest.main()
