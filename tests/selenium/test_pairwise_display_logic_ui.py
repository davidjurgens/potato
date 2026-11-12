"""
display_logic on a page with a pairwise scheme, in a browser.

The pairwise layout moved every annotation form into its grid wrapper,
including forms inside a .display-logic-container. The container was left
empty and the gated question was always visible, whatever was answered.
"""

import time
import unittest

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)


class TestPairwiseDisplayLogicUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("pairwise_display_logic_ui")
        schemes = [
            {"annotation_type": "pairwise", "name": "pref", "description": "Which is better?",
             "items_key": "responses"},
            {"annotation_type": "radio", "name": "why_a", "description": "Why is A better?",
             "labels": ["clearer", "more accurate"],
             "display_logic": {"show_when": [
                 {"schema": "pref", "operator": "equals", "value": "A"}]}},
        ]
        port = find_free_port(preferred_port=9899)
        data_file = create_test_data_file(cls.test_dir, [
            {"id": f"p{i}", "text": "Which reply is better?",
             "responses": [f"one {i}", f"two {i}"]} for i in range(2)])
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[data_file], port=port,
            user_config={"allow_all_users": True, "users": []})
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        options = ChromeOptions()
        for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                     "--disable-gpu", "--window-size=1400,1200"):
            options.add_argument(flag)
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)
        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("gated")
        try:
            cls.driver.find_element(By.NAME, "pass").send_keys("pw")
        except Exception:
            pass
        cls.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            cls.driver.quit()
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def _gated_height(self):
        # The gate collapses its container; the form inside keeps its size.
        return self.driver.execute_script("""
            const f = document.getElementById('why_a');
            const g = f.closest('.display-logic-container');
            const h = f.getBoundingClientRect().height;
            return g ? Math.min(h, g.getBoundingClientRect().height) : h;""")

    def _tile(self, value):
        self.driver.find_element(
            By.CSS_SELECTOR, f"#pref .pairwise-tile[data-value='{value}']").click()
        time.sleep(0.8)

    def test_the_gated_question_follows_the_pairwise_answer(self):
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#pref .pairwise-tile")))
        time.sleep(1)
        self.assertEqual(self._gated_height(), 0, "shown before anything was answered")
        self._tile("A")
        self.assertGreater(self._gated_height(), 0, "hidden although A was chosen")
        self._tile("B")
        self.assertEqual(self._gated_height(), 0, "still shown after B was chosen")


if __name__ == "__main__":
    unittest.main()
