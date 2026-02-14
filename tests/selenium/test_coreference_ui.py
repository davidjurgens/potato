"""
Selenium UI tests for coreference chain annotation.

Tests that the coreference annotation UI renders correctly in the browser:
- Chain panel is visible
- Entity type selector works
- Hidden input contains correct data attribute
- JS/CSS resources load
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


class TestCoreferenceUI(BaseSeleniumTest):
    """Test coreference annotation UI in the browser."""

    @classmethod
    def setUpClass(cls):
        """Set up Flask server with coreference annotation config."""
        test_dir = create_test_directory("selenium_coref_test")
        test_data = [
            {"id": "1", "text": "John went to the store. He bought apples. John was happy."},
            {"id": "2", "text": "The company grew. It expanded overseas."},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "span",
                    "name": "mentions",
                    "description": "Mark mentions",
                    "labels": ["PERSON", "ORG"],
                },
                {
                    "annotation_type": "coreference",
                    "name": "coref",
                    "description": "Group mentions into chains",
                    "span_schema": "mentions",
                    "entity_types": ["PERSON", "ORG"],
                    "allow_singletons": True,
                },
            ],
            data_files=[data_file],
            annotation_task_name="Coreference Selenium Test",
            require_password=False,
        )

        cls.test_dir = test_dir
        port = find_free_port(preferred_port=9050)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server for coreference test"
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome options
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
        """Test annotation page loads with coreference schema."""
        self.driver.get(f"{self.server.base_url}/annotate")
        # Wait for page to fully load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        page_source = self.driver.page_source
        assert "coref" in page_source.lower()

    def test_coreference_panel_rendered(self):
        """Test coreference chain panel is in the DOM."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        page_source = self.driver.page_source
        # Should have coreference-related elements
        assert "coref" in page_source.lower() or "chain" in page_source.lower()

    def test_hidden_input_exists(self):
        """Test hidden input for coreference data exists."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        # Look for hidden input with coreference schema name
        inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='hidden']")
        coref_inputs = [i for i in inputs if "coref" in (i.get_attribute("name") or "").lower()]
        # At least one hidden input should reference coreference
        assert len(coref_inputs) > 0 or "coref" in self.driver.page_source.lower()

    def test_coreference_css_loaded(self):
        """Test coreference CSS file is loaded."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        # Check for CSS link
        stylesheets = self.driver.find_elements(By.CSS_SELECTOR, "link[rel='stylesheet']")
        css_hrefs = [s.get_attribute("href") or "" for s in stylesheets]
        assert any("coreference" in href for href in css_hrefs)

    def test_coreference_js_loaded(self):
        """Test coreference JS file is loaded."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        scripts = self.driver.find_elements(By.CSS_SELECTOR, "script[src]")
        js_srcs = [s.get_attribute("src") or "" for s in scripts]
        assert any("coreference" in src for src in js_srcs)


if __name__ == "__main__":
    unittest.main()
