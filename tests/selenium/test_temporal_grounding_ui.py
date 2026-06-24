"""Selenium UI tests for the temporal_grounding schema (M10)."""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions


class TestTemporalGroundingUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file)
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory("temporal_grounding_ui")
        data = [{"id": "1", "task": "Localize events",
                 "events": [{"prompt": "egg crack", "predicted": {"start": 3.0, "end": 6.0}},
                            {"prompt": "pour", "predicted": {"start": 11.0, "end": 14.0}}]},
                {"id": "2", "task": "Other",
                 "events": [{"prompt": "shot", "predicted": {"start": 1.0, "end": 2.0}}]}]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [{"annotation_type": "temporal_grounding", "name": "grounding",
                    "description": "Mark intervals", "events_key": "events", "duration": 20}]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_file=data_file,
            item_properties={"id_key": "id", "text_key": "task"})
        port = find_free_port(preferred_port=9032)
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
        d.find_element(By.ID, "login-email").send_keys(f"tg_{int(time.time()*1000)}")
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_events_render_with_prediction(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".tg-card")))
        time.sleep(0.4)
        assert len(d.find_elements(By.CSS_SELECTOR, ".tg-card")) == 2
        # predicted bars present for both events.
        assert len(d.find_elements(By.CSS_SELECTOR, ".tg-bar-pred")) == 2

    def test_iou_computes_and_interval_persists(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".tg-card")))
        time.sleep(0.4)
        # Set gold = predicted (3-6) on event 0 -> IoU should be 1.00.
        start = d.find_element(By.CSS_SELECTOR, '.tg-start[data-idx="0"]')
        end = d.find_element(By.CSS_SELECTOR, '.tg-end[data-idx="0"]')
        d.execute_script("arguments[0].scrollIntoView({block:'center'});", start)
        start.send_keys("3"); end.send_keys("6")
        d.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", start)
        d.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", end)
        time.sleep(2.0)
        iou_txt = d.find_element(By.CSS_SELECTOR, '.tg-iou[data-idx="0"]').text
        assert "1.00" in iou_txt, f"expected perfect IoU, got {iou_txt!r}"
        # Navigate away and back; gold interval should persist.
        d.execute_script("document.getElementById('next-btn').click();"); time.sleep(1.5)
        d.execute_script("document.getElementById('prev-btn').click();"); time.sleep(1.5)
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".tg-card")))
        time.sleep(0.5)
        again = d.find_element(By.CSS_SELECTOR, '.tg-start[data-idx="0"]')
        assert (again.get_attribute("value") or "") in ("3", "3.0"), "gold start did not persist"


if __name__ == "__main__":
    unittest.main()
