"""
Selenium tests for Issue #103: Multilingual UI headers.

Verifies that the ui_language config option correctly translates
UI elements like buttons, badges, and labels.
"""

import json
import os
import time
import unittest

import yaml
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory, create_test_data_file


def create_german_ui_config(test_dir, port):
    """Create a config with German UI language settings."""
    test_data = [
        {"id": f"item_{i}", "text": f"Testtext Nummer {i} zum Annotieren."}
        for i in range(1, 4)
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": f"German UI Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positiv", "negativ", "neutral"],
                "description": "Was ist die Stimmung?",
            }
        ],
        "ui_language": {
            "next_button": "Weiter",
            "previous_button": "Zur\u00fcck",
            "labeled_badge": "Beschriftet",
            "not_labeled_badge": "Nicht beschriftet",
            "progress_label": "Fortschritt",
            "go_button": "Los",
            "logout": "Abmelden",
            "loading": "Lade Annotationsoberfl\u00e4che...",
            "error_heading": "Fehler",
            "retry_button": "Wiederholen",
        },
        "assignment_strategy": "fixed_order",
        "max_annotations_per_user": 3,
        "max_annotations_per_item": 3,
        "phases": {"order": ["annotation"], "annotation": {"type": "annotation"}},
        "site_file": "base_template.html",
        "site_dir": "default",
        "output_annotation_dir": output_dir,
        "task_dir": test_dir,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": f"test-secret-{port}",
        "persist_sessions": False,
        "alert_time_each_instance": 0,
        "user_config": {"allow_all_users": True, "users": []},
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)
    return config_file


class TestMultilingualUI(unittest.TestCase):
    """Tests that UI strings are rendered in the configured language."""

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", f"multilingual_ui_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_german_ui_config(cls.test_dir, cls.port)

        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"de_user_{int(time.time() * 1000)}"

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(self.test_user)
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

    def test_next_button_shows_german_text(self):
        """Next button should show 'Weiter' instead of 'Next'."""
        self._login()
        next_btn = self.driver.find_element(By.ID, "next-btn")
        self.assertIn("Weiter", next_btn.text,
                       "Next button should display German text 'Weiter'")
        self.assertNotIn("Next", next_btn.text,
                          "Next button should not display English 'Next'")

    def test_previous_button_shows_german_text(self):
        """Previous button should show 'Zur\u00fcck' instead of 'Previous'."""
        self._login()
        prev_btn = self.driver.find_element(By.ID, "prev-btn")
        self.assertIn("Zur\u00fcck", prev_btn.text,
                       "Previous button should display German text")

    def test_not_labeled_badge_shows_german_text(self):
        """Status badge should show 'Nicht beschriftet' for unannotated items."""
        self._login()
        badge = self.driver.find_element(By.CSS_SELECTOR, ".status-badge")
        self.assertIn("nicht beschriftet", badge.text.lower(),
                       "Status badge should display German 'Nicht beschriftet'")

    def test_progress_label_shows_german_text(self):
        """Progress label should show 'Fortschritt'."""
        self._login()
        progress = self.driver.find_element(By.CSS_SELECTOR, ".progress-label")
        self.assertIn("Fortschritt", progress.text,
                       "Progress label should display German 'Fortschritt'")

    def test_logout_shows_german_text(self):
        """Logout link should show 'Abmelden'."""
        self._login()
        logout = self.driver.find_element(By.CSS_SELECTOR, ".logout-btn")
        self.assertIn("Abmelden", logout.text,
                       "Logout link should display German 'Abmelden'")

    def test_go_button_shows_german_text(self):
        """Go button should show 'Los'."""
        self._login()
        go_btn = self.driver.find_element(By.ID, "go-to-btn")
        self.assertIn("Los", go_btn.text,
                       "Go button should display German 'Los'")

    def test_labeled_badge_after_annotation(self):
        """After annotating, badge should show 'Beschriftet'."""
        self._login()
        time.sleep(0.5)

        # Select a radio option
        radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']")
        if radios:
            radio_id = radios[0].get_attribute("id")
            label = self.driver.find_element(By.CSS_SELECTOR, f"label[for='{radio_id}']")
            label.click()
            time.sleep(1.5)  # Wait for save debounce

            # Navigate away and back to see the badge update
            next_btn = self.driver.find_element(By.ID, "next-btn")
            next_btn.click()
            time.sleep(1)

            prev_btn = self.driver.find_element(By.ID, "prev-btn")
            prev_btn.click()
            time.sleep(1)

            badge = self.driver.find_element(By.CSS_SELECTOR, ".status-badge")
            self.assertIn("beschriftet", badge.text.lower(),
                           "Status badge should show German 'Beschriftet' after annotation")


if __name__ == "__main__":
    unittest.main()
