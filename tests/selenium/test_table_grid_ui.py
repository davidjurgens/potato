"""Selenium UI tests for the table_grid schema (M16)."""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

_IMG = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' "
        "width='150' height='90'><rect width='150' height='90' fill='%23eee'/></svg>")


class TestTableGridUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.test_utils import (
            create_test_directory, create_test_config, create_test_data_file)
        from tests.helpers.port_manager import find_free_port

        cls.test_dir = create_test_directory("table_grid_ui")
        data = [{"id": "1", "task": "Sales table", "rows": 3, "cols": 3, "image": _IMG},
                {"id": "2", "task": "Small table", "rows": 2, "cols": 2, "image": _IMG}]
        data_file = create_test_data_file(cls.test_dir, data)
        schemes = [{"annotation_type": "table_grid", "name": "structure",
                    "description": "Mark structure", "image_key": "image",
                    "rows_key": "rows", "cols_key": "cols"}]
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_file=data_file,
            item_properties={"id_key": "id", "text_key": "task"})
        port = find_free_port(preferred_port=9034)
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
        d.find_element(By.ID, "login-email").send_keys(f"tbg_{int(time.time()*1000)}")
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))
        time.sleep(0.5)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_grid_renders_from_data_dims(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".tbg-cell")))
        time.sleep(0.4)
        assert len(d.find_elements(By.CSS_SELECTOR, ".tbg-cell")) == 9   # 3x3

    def test_cell_role_persists_after_navigate_away_and_back(self):
        d = self.driver
        d.get(f"{self.server.base_url}/annotate")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".tbg-cell")))
        time.sleep(0.4)
        # Click cell (0,0) once -> col_header (roles[1]).
        cell = d.find_element(By.CSS_SELECTOR, '.tbg-cell[data-r="0"][data-c="0"]')
        d.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", cell)
        time.sleep(2.0)
        d.execute_script("document.getElementById('next-btn').click();"); time.sleep(1.5)
        d.execute_script("document.getElementById('prev-btn').click();"); time.sleep(1.5)
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".tbg-cell")))
        time.sleep(0.5)
        again = d.find_element(By.CSS_SELECTOR, '.tbg-cell[data-r="0"][data-c="0"]')
        assert "role-col_header" in (again.get_attribute("class") or ""), "cell role did not persist"


if __name__ == "__main__":
    unittest.main()
