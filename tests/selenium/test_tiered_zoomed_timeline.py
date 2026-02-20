#!/usr/bin/env python3
"""
Selenium test for tiered annotation zoomed timeline view.

Tests that:
1. The zoomed timeline container is present in the DOM
2. The zoomed timeline canvas is present and visible
3. The zoomed timeline controls (slider, buttons) are present
4. The zoomed timeline has proper dimensions (not collapsed)
"""

import os
import time
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)


class TestTieredZoomedTimeline(unittest.TestCase):
    """Test that the tiered annotation zoomed timeline view appears correctly."""

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server with tiered annotation config."""
        cls.test_dir = create_test_directory("tiered_zoomed_test")

        # Create test data
        test_data = [
            {
                "id": "zoom_test_001",
                "text": "Test audio for zoomed timeline",
                "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"
            }
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        # Create tiered annotation scheme
        annotation_schemes = [
            {
                "annotation_type": "tiered_annotation",
                "name": "test_tiers",
                "description": "Test tiered annotation",
                "source_field": "audio_url",
                "media_type": "audio",
                "tiers": [
                    {
                        "name": "utterance",
                        "tier_type": "independent",
                        "labels": [
                            {"name": "Speaker_A", "color": "#4ECDC4"},
                            {"name": "Speaker_B", "color": "#FF6B6B"}
                        ]
                    },
                    {
                        "name": "word",
                        "tier_type": "dependent",
                        "parent_tier": "utterance",
                        "constraint_type": "time_subdivision",
                        "labels": [
                            {"name": "Word", "color": "#95E1D3"}
                        ]
                    }
                ]
            }
        ]

        config_file = create_test_config(
            cls.test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Tiered Zoomed Timeline Test",
            require_password=False,
            item_properties={"id_key": "id", "text_key": "text", "audio_key": "audio_url"}
        )

        # Start server
        port = find_free_port(preferred_port=9250)
        cls.server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        started = cls.server.start()
        if not started:
            raise unittest.SkipTest("Failed to start Flask server")
        cls.server._wait_for_server_ready(timeout=15)

        # Set up Chrome options
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        try:
            cls.driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            cls.server.stop()
            raise unittest.SkipTest(f"Chrome driver not available: {e}")

        cls.driver.implicitly_wait(5)

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        if hasattr(cls, 'driver') and cls.driver:
            cls.driver.quit()
        if hasattr(cls, 'server') and cls.server:
            cls.server.stop()
        if hasattr(cls, 'test_dir'):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        """Login for each test."""
        self.username = f"zoom_test_user_{int(time.time() * 1000)}"

        # Register
        self.driver.get(f"{self.server.base_url}/register")
        time.sleep(0.5)
        try:
            email_input = self.driver.find_element(By.NAME, "email")
            email_input.clear()
            email_input.send_keys(self.username)
            submit = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
            submit.click()
            time.sleep(0.5)
        except Exception:
            pass

        # Login
        self.driver.get(f"{self.server.base_url}/auth")
        time.sleep(0.5)
        try:
            email_input = self.driver.find_element(By.NAME, "email")
            email_input.clear()
            email_input.send_keys(self.username)
            submit = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
            submit.click()
            time.sleep(1)
        except Exception:
            pass

    def test_zoomed_container_exists(self):
        """Test that the zoomed timeline container element exists in the DOM."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(3)  # Wait for JavaScript initialization

        # Look for the zoomed container
        try:
            container = self.driver.find_element(By.ID, "zoomed-container-test_tiers")
            self.assertIsNotNone(container, "Zoomed container should exist")
        except NoSuchElementException:
            # Try with CSS selector as fallback
            containers = self.driver.find_elements(By.CSS_SELECTOR, "[id^='zoomed-container-']")
            self.assertGreater(len(containers), 0, "Should find at least one zoomed container")

    def test_zoomed_canvas_exists(self):
        """Test that the zoomed timeline canvas element exists."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(3)

        try:
            canvas = self.driver.find_element(By.ID, "zoomed-canvas-test_tiers")
            self.assertIsNotNone(canvas, "Zoomed canvas should exist")
        except NoSuchElementException:
            canvases = self.driver.find_elements(By.CSS_SELECTOR, ".zoomed-timeline-canvas")
            self.assertGreater(len(canvases), 0, "Should find at least one zoomed canvas")

    def test_zoomed_timeline_has_dimensions(self):
        """Test that the zoomed timeline has visible dimensions (not collapsed)."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(3)

        # Find the zoomed container
        containers = self.driver.find_elements(By.CSS_SELECTOR, ".zoomed-timeline-container")

        if len(containers) == 0:
            self.fail("No zoomed timeline container found - HTML may not be generated")

        container = containers[0]

        # Get dimensions
        size = container.size
        location = container.location

        print(f"Zoomed container size: {size}")
        print(f"Zoomed container location: {location}")

        # Container should have non-zero height
        self.assertGreater(size['height'], 0,
            f"Zoomed container should have height > 0, got {size['height']}")
        self.assertGreater(size['width'], 0,
            f"Zoomed container should have width > 0, got {size['width']}")

    def test_zoomed_controls_exist(self):
        """Test that the zoomed timeline controls (slider, buttons) exist."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(3)

        # Check for slider
        sliders = self.driver.find_elements(By.CSS_SELECTOR, ".zoomed-timeline-slider")
        self.assertGreater(len(sliders), 0, "Should find zoomed timeline slider")

        # Check for navigation buttons
        left_btns = self.driver.find_elements(By.CSS_SELECTOR, "[id^='zoomed-left-']")
        right_btns = self.driver.find_elements(By.CSS_SELECTOR, "[id^='zoomed-right-']")

        self.assertGreater(len(left_btns), 0, "Should find left navigation button")
        self.assertGreater(len(right_btns), 0, "Should find right navigation button")

    def test_zoomed_canvas_has_dimensions(self):
        """Test that the zoomed canvas has proper dimensions."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(3)

        canvases = self.driver.find_elements(By.CSS_SELECTOR, ".zoomed-timeline-canvas")

        if len(canvases) == 0:
            self.fail("No zoomed canvas found")

        canvas = canvases[0]
        size = canvas.size

        print(f"Zoomed canvas size: {size}")

        # Canvas should have meaningful dimensions
        self.assertGreater(size['height'], 50,
            f"Zoomed canvas should have height > 50px, got {size['height']}")
        self.assertGreater(size['width'], 100,
            f"Zoomed canvas should have width > 100px, got {size['width']}")

    def test_zoomed_range_display_exists(self):
        """Test that the zoomed range display shows the time range."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(3)

        # Find range display
        range_displays = self.driver.find_elements(By.CSS_SELECTOR, ".zoomed-timeline-range")

        self.assertGreater(len(range_displays), 0, "Should find zoomed range display")

        if range_displays:
            text = range_displays[0].text
            print(f"Zoomed range text: {text}")
            # Should contain time format like "0:00" or similar
            self.assertTrue(
                ':' in text or text == '',
                f"Range display should show time format, got: {text}"
            )

    def test_page_contains_tiered_annotation_form(self):
        """Test that the page contains a tiered annotation form at all."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(3)

        # Check for tiered annotation container
        forms = self.driver.find_elements(By.CSS_SELECTOR, ".tiered-annotation-container")

        print(f"Found {len(forms)} tiered annotation containers")

        if len(forms) == 0:
            # Debug: print page source snippet
            page_source = self.driver.page_source
            if 'tiered' in page_source.lower():
                print("'tiered' found in page source")
            else:
                print("'tiered' NOT found in page source")

            if 'zoomed' in page_source.lower():
                print("'zoomed' found in page source")
            else:
                print("'zoomed' NOT found in page source")

        self.assertGreater(len(forms), 0, "Should find tiered annotation container")

    def test_peaks_zoomview_container_exists(self):
        """Test that the Peaks.js zoomview waveform container exists."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(3)

        # Check for the zoomview container (Peaks.js waveform)
        zoomviews = self.driver.find_elements(By.CSS_SELECTOR, "[id^='zoomview-']")

        self.assertGreater(len(zoomviews), 0, "Should find Peaks.js zoomview container")

        if zoomviews:
            zoomview = zoomviews[0]
            size = zoomview.size
            print(f"Zoomview container size: {size}")

            # Container should have non-zero height (CSS sets 60px min)
            self.assertGreater(size['height'], 0,
                f"Zoomview container should have height > 0, got {size['height']}")

    def test_zoomed_waveform_class_exists(self):
        """Test that the zoomed waveform container with proper class exists."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(3)

        # Check for the zoomed-waveform class
        waveforms = self.driver.find_elements(By.CSS_SELECTOR, ".zoomed-waveform")

        self.assertGreater(len(waveforms), 0, "Should find zoomed-waveform container")

        if waveforms:
            waveform = waveforms[0]
            size = waveform.size
            print(f"Zoomed waveform size: {size}")

            # Should have CSS height of 60px
            self.assertGreaterEqual(size['height'], 50,
                f"Zoomed waveform should have height >= 50px, got {size['height']}")


if __name__ == "__main__":
    unittest.main()
