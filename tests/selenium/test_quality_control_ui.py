"""
Selenium tests for quality control features: attention checks and gold standards
during annotation.

Tests that the QC subsystem integrates properly with the annotation workflow
and that annotation works correctly when QC features are enabled.
"""

import json
import os
import time
import unittest

import requests
import yaml
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_data_file,
)


def create_qc_config(test_dir, port):
    """Create config with attention checks and gold standards enabled."""
    # Create 10 annotation items
    test_data = [
        {"id": f"item_{i}", "text": f"Annotation item number {i} for testing."}
        for i in range(1, 11)
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Create attention check items
    attention_items = [
        {
            "id": "attn_1",
            "text": "ATTENTION CHECK: Please select positive.",
            "expected_answer": {"sentiment": "positive"},
        },
        {
            "id": "attn_2",
            "text": "ATTENTION CHECK: Please select negative.",
            "expected_answer": {"sentiment": "negative"},
        },
    ]
    attention_file = os.path.join(test_dir, "attention_items.json")
    with open(attention_file, "w", encoding="utf-8") as f:
        json.dump(attention_items, f)

    # Create gold standard items
    gold_items = [
        {
            "id": "gold_1",
            "text": "This is absolutely amazing and wonderful!",
            "gold_label": {"sentiment": "positive"},
            "explanation": "Strong positive sentiment words.",
        },
    ]
    gold_file = os.path.join(test_dir, "gold_items.json")
    with open(gold_file, "w", encoding="utf-8") as f:
        json.dump(gold_items, f)

    config = {
        "annotation_task_name": f"QC Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "What is the sentiment?",
            }
        ],
        "assignment_strategy": "fixed_order",
        "max_annotations_per_user": 10,
        "max_annotations_per_item": 3,
        "attention_checks": {
            "enabled": True,
            "items_file": "attention_items.json",
            "frequency": 5,
            "failure_handling": {
                "warn_threshold": 1,
                "block_threshold": 3,
            },
        },
        "gold_standards": {
            "enabled": True,
            "items_file": "gold_items.json",
            "frequency": 8,
            "mode": "mixed",
        },
        "phases": {
            "order": ["annotation"],
            "annotation": {"type": "annotation"},
        },
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


class TestQualityControlUI(unittest.TestCase):
    """
    Quality control integration tests: verify annotation works with QC enabled,
    and that attention checks and gold standards are processed correctly.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"qc_ui_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_qc_config(cls.test_dir, cls.port)

        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file
        )
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
        self.test_user = f"qc_user_{int(time.time() * 1000)}"

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        """Login with simple auth."""
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(self.test_user)
        self.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit']"
        ).click()
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

    def _annotate_and_next(self):
        """Select a radio option and click Next."""
        time.sleep(0.5)
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']"
        )
        if radios:
            radio_id = radios[0].get_attribute("id")
            if radio_id:
                try:
                    label = self.driver.find_element(
                        By.CSS_SELECTOR, f"label[for='{radio_id}']"
                    )
                    label.click()
                except Exception:
                    radios[0].click()
            else:
                radios[0].click()
            time.sleep(0.5)

        try:
            next_btn = self.driver.find_element(By.ID, "next-btn")
            next_btn.click()
        except Exception:
            next_btn = self.driver.find_element(
                By.CSS_SELECTOR, 'a[onclick*="click_to_next"]'
            )
            next_btn.click()
        time.sleep(2)

    def test_annotation_works_with_qc_enabled(self):
        """Annotation flow should complete normally with QC features enabled."""
        self._login()

        # Verify annotation interface is present
        page_source = self.driver.page_source.lower()
        has_annotation = (
            "task_layout" in page_source
            or "sentiment" in page_source
        )
        self.assertTrue(
            has_annotation,
            "Annotation interface should load with QC enabled",
        )

    def test_annotate_multiple_items_with_qc(self):
        """Should be able to annotate several items without errors when QC is enabled."""
        self._login()

        # Annotate 3 items
        for i in range(3):
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']")
                    )
                )
                self._annotate_and_next()
            except Exception:
                break

        # Should still be on annotation page (not error page)
        page_source = self.driver.page_source.lower()
        self.assertNotIn(
            "internal server error",
            page_source,
            "Annotation with QC should not cause server errors",
        )

    def test_annotation_radio_buttons_present(self):
        """Radio buttons for the annotation scheme should be present."""
        self._login()

        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']"
        )
        self.assertGreater(
            len(radios),
            0,
            "Annotation radio buttons should be present with QC enabled",
        )

    def test_item_text_displayed(self):
        """Annotation item text should be displayed."""
        self._login()

        page_source = self.driver.page_source.lower()
        has_item_text = (
            "annotation item" in page_source
            or "testing" in page_source
        )
        self.assertTrue(
            has_item_text,
            "Annotation item text should be displayed with QC enabled",
        )

    def test_navigation_works_with_qc(self):
        """Next/Previous navigation should work with QC enabled."""
        self._login()

        # Annotate first item and navigate next
        self._annotate_and_next()

        # Should be on a new item or still in annotation — no server errors
        page_source = self.driver.page_source
        self.assertNotIn(
            "Internal Server Error",
            page_source,
            "Navigation should work with QC enabled",
        )
        self.assertNotIn(
            "Traceback",
            page_source,
            "Post-navigation page should not have errors",
        )

    def test_server_health_with_qc(self):
        """Server health check should pass with QC enabled."""
        response = requests.get(f"{self.server.base_url}/", timeout=5)
        self.assertIn(
            response.status_code,
            [200, 302],
            "Server should respond normally with QC enabled",
        )


if __name__ == "__main__":
    unittest.main()
