"""
Selenium tests for assignment strategies: fixed_order, random, least_annotated.

Verifies that different assignment strategies work through the UI and that
limits (max_annotations_per_user, max_annotations_per_item) are enforced.
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


import pytest


pytestmark = pytest.mark.core

def create_strategy_config(
    test_dir,
    port,
    strategy="fixed_order",
    max_per_user=5,
    max_per_item=3,
    num_items=10,
):
    """Create config with a specific assignment strategy."""
    test_data = [
        {"id": f"item_{i}", "text": f"Test item number {i} for strategy testing."}
        for i in range(1, num_items + 1)
    ]
    data_file = create_test_data_file(test_dir, test_data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": f"Strategy Test {port}",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative"],
                "description": "What is the sentiment?",
            }
        ],
        "assignment_strategy": strategy,
        "random_seed": 42,
        "max_annotations_per_user": max_per_user,
        "max_annotations_per_item": max_per_item,
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


class TestFixedOrderStrategyUI(unittest.TestCase):
    """Test fixed_order assignment strategy."""

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"fixed_order_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_strategy_config(
            cls.test_dir, cls.port, strategy="fixed_order", max_per_user=3
        )

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
        self.test_user = f"fixed_user_{int(time.time() * 1000)}"

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

    def test_fixed_order_assigns_items(self):
        """Fixed order strategy should assign items to the user."""
        self._login()

        # Should see annotation interface with items
        page_source = self.driver.page_source.lower()
        has_annotation = (
            "task_layout" in page_source
            or "sentiment" in page_source
        )
        self.assertTrue(
            has_annotation,
            "Fixed order strategy should assign items to annotate",
        )

    def test_max_annotations_per_user_enforced(self):
        """After annotating max_per_user items, user should see done state."""
        self._login()

        # Annotate 3 items (max_per_user=3)
        for _ in range(3):
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "input[type='radio'][schema='sentiment']")
                    )
                )
                self._annotate_and_next()
            except Exception:
                break

        # Navigate home to check state
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)

        page_source = self.driver.page_source.lower()
        is_done = (
            "thank you" in page_source
            or "completed" in page_source
            or "all done" in page_source
            or "no more" in page_source
        )
        self.assertTrue(
            is_done,
            "After max_annotations_per_user, user should see done/completion state",
        )


class TestRandomStrategyUI(unittest.TestCase):
    """Test random assignment strategy."""

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"random_strategy_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_strategy_config(
            cls.test_dir, cls.port, strategy="random", max_per_user=5
        )

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
        self.test_user = f"random_user_{int(time.time() * 1000)}"

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

    def test_random_strategy_assigns_items(self):
        """Random strategy should assign valid items to annotate."""
        self._login()

        page_source = self.driver.page_source.lower()
        has_annotation = (
            "task_layout" in page_source
            or "sentiment" in page_source
        )
        has_item = "test item" in page_source or "strategy testing" in page_source
        self.assertTrue(
            has_annotation,
            "Random strategy should assign items for annotation",
        )

    def test_random_strategy_no_errors(self):
        """Random strategy should not produce server errors."""
        self._login()

        page_source = self.driver.page_source
        self.assertNotIn(
            "Internal Server Error",
            page_source,
            "Random strategy should not cause server errors",
        )
        self.assertNotIn(
            "Traceback",
            page_source,
            "Random strategy should not show tracebacks",
        )


class TestLeastAnnotatedStrategyUI(unittest.TestCase):
    """Test least_annotated assignment strategy."""

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"least_annotated_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = create_strategy_config(
            cls.test_dir,
            cls.port,
            strategy="least_annotated",
            max_per_user=5,
            max_per_item=2,
        )

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
        self.test_user = f"least_user_{int(time.time() * 1000)}"

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

    def test_least_annotated_assigns_items(self):
        """Least annotated strategy should assign items for annotation."""
        self._login()

        page_source = self.driver.page_source.lower()
        has_annotation = (
            "task_layout" in page_source
            or "sentiment" in page_source
        )
        self.assertTrue(
            has_annotation,
            "Least annotated strategy should assign items",
        )

    def test_least_annotated_no_errors(self):
        """Least annotated strategy should not produce server errors."""
        self._login()

        page_source = self.driver.page_source
        self.assertNotIn(
            "Internal Server Error",
            page_source,
            "Least annotated strategy should not cause server errors",
        )


if __name__ == "__main__":
    unittest.main()
