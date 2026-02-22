"""
Selenium tests for pairwise annotation content population.
Tests that the pairwise item boxes are correctly populated with content.
"""

import os
import pytest
import time
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)
from tests.helpers.port_manager import find_free_port


class TestPairwiseContent(unittest.TestCase):
    """Test pairwise annotation content population."""

    @classmethod
    def setUpClass(cls):
        """Set up server with pairwise annotation config."""
        annotation_schemes = [
            {
                "annotation_type": "pairwise",
                "name": "preference",
                "description": "Which response is better?",
                "mode": "scale",
                "items_key": "responses",
                "labels": ["Response A", "Response B"],
                "scale": {
                    "min": 1,
                    "max": 6,
                    "step": 1,
                    "default": 3,
                    "labels": {
                        "min": "A is much better",
                        "max": "B is much better"
                    }
                }
            },
            {
                "annotation_type": "pairwise",
                "name": "helpfulness",
                "description": "Which is more helpful?",
                "mode": "binary",
                "items_key": "responses",
                "labels": ["A", "B"],
                "allow_tie": True,
                "tie_label": "Equally helpful"
            }
        ]

        # Create test data with responses list
        test_data = [
            {
                "id": "1",
                "responses": [
                    "This is response A - a detailed explanation that provides comprehensive information.",
                    "This is response B - a concise and direct answer."
                ]
            },
            {
                "id": "2",
                "responses": [
                    "Second item response A with more content here.",
                    "Second item response B with different content."
                ]
            }
        ]

        # Find a free port
        port = find_free_port(preferred_port=9876)

        # Create test directory and data manually
        cls.test_dir = create_test_directory("pairwise_content_test")
        cls.data_file = create_test_data_file(cls.test_dir, test_data)
        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes,
            data_files=[cls.data_file],
            port=port,
            item_properties={
                "id_key": "id",
                "text_key": "responses"
            },
            user_config={
                "allow_all_users": True,
                "users": []
            },
            list_as_text={
                "text_list_prefix_type": "alphabet"
            }
        )

        # Start server
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"

        # Wait for server
        cls.server._wait_for_server_ready(timeout=10)

        # Set up Chrome driver
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        cls.driver = webdriver.Chrome(options=chrome_options)
        cls.driver.implicitly_wait(5)

        # Register and login
        cls._register_and_login()

    @classmethod
    def _register_and_login(cls):
        """Register a test user and log in."""
        cls.driver.get(f"{cls.server.base_url}/")

        try:
            # Wait for email field
            WebDriverWait(cls.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "email"))
            )

            email_field = cls.driver.find_element(By.NAME, "email")
            email_field.send_keys("test_pairwise_user")

            # Check if password field exists (might not be required)
            try:
                pass_field = cls.driver.find_element(By.NAME, "pass")
                pass_field.send_keys("testpass")
            except:
                pass  # No password field, that's OK

            # Submit the form
            submit_btn = cls.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()

            # Wait for redirect to complete
            time.sleep(2)

            # Check if we're on annotate page or need to try again
            current_url = cls.driver.current_url
            print(f"After login, URL is: {current_url}")

        except Exception as e:
            print(f"Login failed: {e}")

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests."""
        if hasattr(cls, 'driver'):
            cls.driver.quit()
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            cleanup_test_directory(cls.test_dir)

    def test_pairwise_item_boxes_exist(self):
        """Test that pairwise item boxes are present in the DOM."""
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for annotation forms to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "annotation-form"))
        )

        # Give JavaScript time to execute
        time.sleep(2)

        # Check for pairwise forms
        pairwise_forms = self.driver.find_elements(By.CSS_SELECTOR, ".annotation-form.pairwise")
        print(f"Found {len(pairwise_forms)} pairwise forms")

        # Debug: Print form IDs and classes
        for form in pairwise_forms:
            print(f"  Form: id={form.get_attribute('id')}, class={form.get_attribute('class')}")

        # Check for item boxes (single display at top with 2 boxes - one per response)
        item_boxes = self.driver.find_elements(By.CLASS_NAME, "pairwise-item-box")
        print(f"Found {len(item_boxes)} item boxes")

        # Check for item titles
        item_titles = self.driver.find_elements(By.CLASS_NAME, "pairwise-item-title")
        print(f"Found {len(item_titles)} item titles")

        assert len(pairwise_forms) >= 2, f"Expected at least 2 pairwise forms, found {len(pairwise_forms)}"
        # There should be 2 item boxes in the single pairwise items display (one per response)
        assert len(item_boxes) >= 2, f"Expected at least 2 item boxes, found {len(item_boxes)}"

    def test_pairwise_item_boxes_populated(self):
        """Test that pairwise item boxes contain the response content."""
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to fully load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "annotation-form"))
        )

        # Give JavaScript time to populate content
        time.sleep(2)

        # Get browser console logs
        try:
            logs = self.driver.get_log('browser')
            print("\nBrowser console logs:")
            for log in logs:
                if 'PAIRWISE' in log.get('message', ''):
                    print(f"  {log['level']}: {log['message']}")
        except Exception as e:
            print(f"Could not get browser logs: {e}")

        # Check instance-text content
        instance_text = self.driver.find_element(By.ID, "instance-text")
        print(f"\nInstance text preview: {instance_text.text[:200]}..." if len(instance_text.text) > 200 else f"\nInstance text: {instance_text.text}")

        # Find all pairwise item boxes
        item_boxes = self.driver.find_elements(By.CLASS_NAME, "pairwise-item-box")

        # Debug: Print box contents
        print(f"\nFound {len(item_boxes)} item boxes:")
        for i, box in enumerate(item_boxes):
            content = box.text.strip()
            print(f"  Box {i}: '{content[:80]}...'" if len(content) > 80 else f"  Box {i}: '{content}'")

        # Count boxes with content
        boxes_with_content = sum(1 for box in item_boxes if len(box.text.strip()) > 10)
        print(f"Boxes with content (>10 chars): {boxes_with_content}")

        # At least some boxes should have content
        assert boxes_with_content >= 2, f"Expected at least 2 boxes with content, found {boxes_with_content}"

    def test_pairwise_scale_labels_visible(self):
        """Test that scale labels are visible with proper font size."""
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for scale slider
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "pairwise-scale-slider"))
        )

        # Check scale labels
        labels = self.driver.find_elements(By.CLASS_NAME, "pairwise-scale-label-min")
        if labels:
            label = labels[0]
            font_size = label.value_of_css_property("font-size")
            print(f"Scale label font-size: {font_size}")

            # Font size should be at least 14px (0.875rem or more)
            size_value = float(font_size.replace("px", ""))
            assert size_value >= 14, f"Scale label font too small: {font_size}"

    def test_binary_tiles_clickable(self):
        """Test that binary mode tiles are clickable."""
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for tiles
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "pairwise-tile"))
        )

        tiles = self.driver.find_elements(By.CLASS_NAME, "pairwise-tile")
        print(f"Found {len(tiles)} pairwise tiles")

        assert len(tiles) >= 2, "Should have at least 2 tiles"

        # Click first tile
        tiles[0].click()
        time.sleep(0.5)

        # Check it's selected
        classes = tiles[0].get_attribute("class")
        assert "selected" in classes, f"Tile should be selected after click, but classes are: {classes}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
