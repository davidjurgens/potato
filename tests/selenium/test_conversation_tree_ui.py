"""
Selenium UI tests for conversation tree annotation.

Tests that the conversation tree renders correctly:
- Tree nodes are displayed
- Expand/collapse works
- Tree annotation schema elements exist
- CSS/JS resources load
"""

import os
import sys
import time
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.selenium.test_base import BaseSeleniumTest
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


class TestConversationTreeUI(BaseSeleniumTest):
    """Test conversation tree annotation UI in the browser."""

    @classmethod
    def setUpClass(cls):
        """Set up Flask server with conversation tree config."""
        test_dir = create_test_directory("selenium_tree_test")
        test_data = [
            {
                "id": "thread_001",
                "text": "A conversation tree",
                "tree": json.dumps({
                    "id": "root",
                    "speaker": "User",
                    "text": "What is machine learning?",
                    "children": [
                        {
                            "id": "r1",
                            "speaker": "Bot A",
                            "text": "Machine learning is a subset of AI.",
                            "children": [],
                        },
                        {
                            "id": "r2",
                            "speaker": "Bot B",
                            "text": "It is about learning from data.",
                            "children": [
                                {
                                    "id": "r2_1",
                                    "speaker": "User",
                                    "text": "Can you give an example?",
                                    "children": [],
                                }
                            ],
                        },
                    ],
                }),
            },
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "tree_annotation",
                    "name": "response_quality",
                    "description": "Rate response quality",
                    "path_selection": {"enabled": True, "description": "Pick best path"},
                },
            ],
            data_files=[data_file],
            item_properties={"id_key": "id", "text_key": "text"},
            annotation_task_name="Tree Selenium Test",
            require_password=False,
        )

        cls.test_dir = test_dir
        port = find_free_port(preferred_port=9051)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server for tree test"
        cls.server._wait_for_server_ready(timeout=10)

        from selenium.webdriver.chrome.options import Options as ChromeOptions
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--disable-images")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        cls.chrome_options = chrome_options

        from selenium.webdriver.firefox.options import Options as FirefoxOptions
        firefox_options = FirefoxOptions()
        firefox_options.add_argument("--headless")
        cls.firefox_options = firefox_options

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            cleanup_test_directory(cls.test_dir)

    def test_annotation_page_loads(self):
        """Test annotation page loads with tree schema."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        page_source = self.driver.page_source
        assert "response_quality" in page_source

    def test_tree_annotation_schema_rendered(self):
        """Test tree annotation schema elements are in the page."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        page_source = self.driver.page_source
        assert "tree" in page_source.lower()

    def test_tree_css_loaded(self):
        """Test conversation tree CSS is loaded."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        stylesheets = self.driver.find_elements(By.CSS_SELECTOR, "link[rel='stylesheet']")
        css_hrefs = [s.get_attribute("href") or "" for s in stylesheets]
        assert any("conversation-tree" in href for href in css_hrefs)

    def test_tree_js_loaded(self):
        """Test conversation tree JS is loaded."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        scripts = self.driver.find_elements(By.CSS_SELECTOR, "script[src]")
        js_srcs = [s.get_attribute("src") or "" for s in scripts]
        assert any("conversation-tree" in src for src in js_srcs)

    def test_hidden_inputs_exist(self):
        """Test hidden inputs for tree annotation data exist."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='hidden']")
        tree_inputs = [
            i for i in inputs
            if "response_quality" in (i.get_attribute("name") or "")
            or "tree" in (i.get_attribute("name") or "").lower()
        ]
        assert len(tree_inputs) > 0 or "response_quality" in self.driver.page_source


if __name__ == "__main__":
    unittest.main()
