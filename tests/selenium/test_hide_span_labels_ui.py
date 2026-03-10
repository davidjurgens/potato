"""
Selenium tests for Issue #73: Option to hide span labels.

Verifies that when show_span_labels: false is set in the span schema config,
span overlay labels are not rendered above annotated text.
"""

import json
import os
import time
import unittest

import yaml
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory, create_test_data_file


def create_span_config(test_dir, port, show_labels=True):
    """Create a span annotation config with configurable label visibility."""
    test_data = [
        {"id": "item_1", "text": "The quick brown fox jumps over the lazy dog near the river bank."},
        {"id": "item_2", "text": "Alice visited Paris and met Bob at the Eiffel Tower yesterday."},
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    span_scheme = {
        "name": "entities",
        "annotation_type": "span",
        "labels": ["PER", "LOC", "ORG"],
        "description": "Select entity spans",
    }
    if not show_labels:
        span_scheme["show_span_labels"] = False

    config = {
        "annotation_task_name": f"Span Labels Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [span_scheme],
        "assignment_strategy": "fixed_order",
        "max_annotations_per_user": 2,
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
    with open(config_file, "w") as f:
        yaml.dump(config, f)
    return config_file


class TestHideSpanLabelsUI(unittest.TestCase):
    """Tests that show_span_labels=false hides labels on span overlays."""

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", f"hide_span_labels_ui_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        # Create config with show_span_labels: false
        cls.config_file = create_span_config(cls.test_dir, cls.port, show_labels=False)

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
        self.test_user = f"span_user_{int(time.time() * 1000)}"

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

    def test_span_form_has_show_labels_false_attribute(self):
        """The span annotation form should have data-show-span-labels='false'."""
        self._login()
        time.sleep(0.5)

        form = self.driver.find_element(By.CSS_SELECTOR,
            '.annotation-form.span[data-show-span-labels="false"]')
        self.assertIsNotNone(form,
            "Span form should have data-show-span-labels='false' attribute")

    def test_span_checkboxes_render(self):
        """Span label checkboxes should still render even when labels are hidden."""
        self._login()
        time.sleep(0.5)

        checkboxes = self.driver.find_elements(By.CSS_SELECTOR,
            "input[type='checkbox'][for_span='true']")
        self.assertGreaterEqual(len(checkboxes), 3,
            "Should have at least 3 span label checkboxes (PER, LOC, ORG)")

    def test_creating_span_has_no_label_element(self):
        """After creating a span annotation, no .span-label div should appear in overlays."""
        self._login()
        time.sleep(0.5)

        # Activate the first label (PER)
        checkboxes = self.driver.find_elements(By.CSS_SELECTOR,
            "input[type='checkbox'][schema='entities']")
        if checkboxes:
            cb_id = checkboxes[0].get_attribute("id")
            label = self.driver.find_element(By.CSS_SELECTOR, f"label[for='{cb_id}']")
            label.click()
            time.sleep(0.3)

        # Select text to create a span
        text_el = self.driver.find_element(By.ID, "text-content")
        if text_el:
            # Use JavaScript to simulate text selection
            self.driver.execute_script("""
                var el = document.getElementById('text-content');
                if (el && el.firstChild) {
                    var range = document.createRange();
                    range.setStart(el.firstChild, 0);
                    range.setEnd(el.firstChild, Math.min(5, el.firstChild.length));
                    var sel = window.getSelection();
                    sel.removeAllRanges();
                    sel.addRange(range);
                    // Trigger mouseup to create span
                    el.dispatchEvent(new Event('mouseup', {bubbles: true}));
                }
            """)
            time.sleep(1)

            # Check that no span-label elements exist
            labels = self.driver.find_elements(By.CSS_SELECTOR, ".span-label")
            self.assertEqual(len(labels), 0,
                "No .span-label elements should exist when show_span_labels is false")


class TestShowSpanLabelsDefaultUI(unittest.TestCase):
    """Tests that span labels appear by default (show_span_labels not set)."""

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", f"show_span_labels_ui_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        # Create config with default show_span_labels (true)
        cls.config_file = create_span_config(cls.test_dir, cls.port, show_labels=True)

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
        self.test_user = f"span_default_{int(time.time() * 1000)}"

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

    def test_span_form_has_no_show_labels_attribute(self):
        """By default, span form should NOT have data-show-span-labels='false'."""
        self._login()
        time.sleep(0.5)

        forms_with_attr = self.driver.find_elements(By.CSS_SELECTOR,
            '.annotation-form.span[data-show-span-labels="false"]')
        self.assertEqual(len(forms_with_attr), 0,
            "Span form should not have data-show-span-labels='false' by default")


if __name__ == "__main__":
    unittest.main()
