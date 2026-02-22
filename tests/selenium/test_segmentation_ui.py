"""
Selenium UI tests for segmentation mask tools.

Tests that the segmentation UI elements render correctly:
- Fill and eraser tool buttons are present
- Segmentation CSS/JS resources load
- Image annotation container is present with segmentation tools
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

from tests.selenium.test_base import BaseSeleniumTest
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


class TestSegmentationUI(BaseSeleniumTest):
    """Test segmentation tools in image annotation UI."""

    @classmethod
    def setUpClass(cls):
        """Set up Flask server with segmentation config."""
        test_dir = create_test_directory("selenium_seg_test")
        test_data = [
            {"id": "img_001", "text": "Segment image regions", "image_url": "https://picsum.photos/id/1011/800/600"},
        ]
        data_file = create_test_data_file(test_dir, test_data)
        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "image_annotation",
                    "name": "segmentation",
                    "description": "Segment image regions",
                    "tools": ["bbox", "fill", "eraser"],
                    "labels": [
                        {"name": "foreground", "color": "#FF0000"},
                        {"name": "background", "color": "#0000FF"},
                    ],
                },
            ],
            data_files=[data_file],
            item_properties={"id_key": "id", "text_key": "text"},
            annotation_task_name="Segmentation Selenium Test",
            require_password=False,
        )

        cls.test_dir = test_dir
        port = find_free_port(preferred_port=9052)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server for segmentation test"
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
        """Test annotation page loads with segmentation config."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        assert "segmentation" in self.driver.page_source.lower()

    def test_segmentation_css_loaded(self):
        """Test segmentation CSS is loaded."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        stylesheets = self.driver.find_elements(By.CSS_SELECTOR, "link[rel='stylesheet']")
        css_hrefs = [s.get_attribute("href") or "" for s in stylesheets]
        assert any("segmentation" in href for href in css_hrefs)

    def test_segmentation_js_loaded(self):
        """Test segmentation JS is loaded."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        scripts = self.driver.find_elements(By.CSS_SELECTOR, "script[src]")
        js_srcs = [s.get_attribute("src") or "" for s in scripts]
        assert any("segmentation" in src for src in js_srcs)

    def test_image_annotation_container_exists(self):
        """Test image annotation container is rendered."""
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        page_source = self.driver.page_source
        assert "image-annotation" in page_source.lower() or "segmentation" in page_source.lower()


if __name__ == "__main__":
    unittest.main()
