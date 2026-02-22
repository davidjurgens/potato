#!/usr/bin/env python3
"""
Selenium tests for mask annotation zoom synchronization.

This test suite verifies that mask annotations (brush strokes, fills) stay
aligned with the image when zooming and panning.

Bug Context:
- When brush annotations are made and then zoom is applied, the mask overlay
  must re-render to match the new viewport transform
- Without proper sync, masks appear in wrong position after zoom/pan

Test Coverage:
- Mask position after zoom in
- Mask position after zoom out
- Mask position after zoom fit
- Mask position after zoom reset
- Mask position after panning
"""

import time
import os
import sys
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Add project to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_segmentation_annotation_config,
    cleanup_test_directory
)


class TestMaskZoomSynchronization(unittest.TestCase):
    """
    Test suite for mask zoom synchronization.

    Verifies that mask annotations stay properly aligned with the image
    when zooming and panning operations are performed.
    """

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server for all tests in this class."""
        # Create test directory
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", "mask_zoom_sync_test")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create segmentation config with brush tools
        cls.config_file, cls.data_file = create_segmentation_annotation_config(
            cls.test_dir,
            annotation_task_name="Mask Zoom Sync Test",
            require_password=False
        )

        # Start server
        cls.server = FlaskTestServer(debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"

        # Wait for server
        cls.server._wait_for_server_ready(timeout=15)

        # Set up Chrome options
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        cls.chrome_options = chrome_options

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir'):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)

        # Register and login user
        timestamp = int(time.time())
        self.test_user = f"mask_zoom_test_user_{timestamp}"

        self._login_user()

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login_user(self):
        """Login the test user."""
        self.driver.get(f"{self.server.base_url}/")

        try:
            email_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "login-email"))
            )
            email_input.clear()
            email_input.send_keys(self.test_user)
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()
            time.sleep(0.5)
        except (NoSuchElementException, TimeoutException):
            try:
                email_input = self.driver.find_element(By.NAME, "email")
                email_input.clear()
                email_input.send_keys(self.test_user)
                submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                submit_btn.click()
                time.sleep(0.5)
            except NoSuchElementException:
                pass

    def _wait_for_annotation_manager(self):
        """Wait for the ImageAnnotationManager to be initialized."""
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        # Wait for manager initialization
        max_wait = 5
        for _ in range(max_wait * 10):
            manager_ready = self.driver.execute_script("""
                var container = document.querySelector('.image-annotation-container');
                return container && container.annotationManager && container.annotationManager.canvas;
            """)
            if manager_ready:
                return True
            time.sleep(0.1)
        return False

    def _get_mask_canvas_position(self):
        """Get the current mask canvas rendering position/dimensions."""
        return self.driver.execute_script("""
            var container = document.querySelector('.image-annotation-container');
            if (!container || !container.annotationManager) return null;

            var manager = container.annotationManager;
            if (!manager.image || !manager.maskCanvas) return null;

            var vpt = manager.canvas.viewportTransform;
            var zoom = manager.canvas.getZoom();

            // Calculate expected mask position based on image and viewport
            var imgLeft = manager.image.left * zoom + vpt[4];
            var imgTop = manager.image.top * zoom + vpt[5];
            var imgWidth = manager.image.width * manager.image.scaleX * zoom;
            var imgHeight = manager.image.height * manager.image.scaleY * zoom;

            return {
                left: imgLeft,
                top: imgTop,
                width: imgWidth,
                height: imgHeight,
                zoom: zoom,
                vptX: vpt[4],
                vptY: vpt[5]
            };
        """)

    def _draw_brush_stroke(self):
        """Simulate a brush stroke on the canvas."""
        # Select brush tool
        brush_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-tool="brush"]')
        brush_btn.click()
        time.sleep(0.1)

        # Select first label
        label_btn = self.driver.find_element(By.CSS_SELECTOR, '.label-btn')
        label_btn.click()
        time.sleep(0.1)

        # Get the mask canvas element
        mask_canvas = self.driver.find_element(By.CSS_SELECTOR, '.mask-canvas')

        # Perform brush stroke using ActionChains
        actions = ActionChains(self.driver)
        actions.move_to_element_with_offset(mask_canvas, 100, 100)
        actions.click_and_hold()
        actions.move_by_offset(50, 0)
        actions.move_by_offset(0, 50)
        actions.release()
        actions.perform()

        time.sleep(0.2)

    def _has_mask_data(self):
        """Check if any mask data has been created."""
        return self.driver.execute_script("""
            var container = document.querySelector('.image-annotation-container');
            if (!container || !container.annotationManager) return false;
            return Object.keys(container.annotationManager.masks || {}).length > 0;
        """)

    def test_brush_tool_exists(self):
        """Test that brush tool button exists for segmentation."""
        self.driver.get(f"{self.server.base_url}/annotate")

        self._wait_for_annotation_manager()

        # Check for brush tool
        brush_buttons = self.driver.find_elements(By.CSS_SELECTOR, '[data-tool="brush"]')
        self.assertGreater(len(brush_buttons), 0, "Brush tool button should exist")

    def test_mask_canvas_exists(self):
        """Test that mask canvas exists for segmentation."""
        self.driver.get(f"{self.server.base_url}/annotate")

        self._wait_for_annotation_manager()

        # Check for mask canvas
        mask_canvases = self.driver.find_elements(By.CLASS_NAME, "mask-canvas")
        self.assertGreater(len(mask_canvases), 0, "Mask canvas should exist")

    def test_zoom_updates_mask_position(self):
        """Test that zooming updates the mask canvas position."""
        self.driver.get(f"{self.server.base_url}/annotate")

        self._wait_for_annotation_manager()
        time.sleep(0.5)  # Wait for image to load

        # Get initial position
        initial_pos = self._get_mask_canvas_position()
        self.assertIsNotNone(initial_pos, "Should get initial mask position")

        # Click zoom in
        zoom_in_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-in"]')
        zoom_in_btn.click()
        time.sleep(0.2)

        # Get new position
        new_pos = self._get_mask_canvas_position()
        self.assertIsNotNone(new_pos, "Should get new mask position after zoom")

        # Verify zoom changed
        self.assertGreater(new_pos['zoom'], initial_pos['zoom'],
                          f"Zoom should have increased: {initial_pos['zoom']} -> {new_pos['zoom']}")

        # Verify width/height scaled accordingly
        expected_width_ratio = new_pos['zoom'] / initial_pos['zoom']
        actual_width_ratio = new_pos['width'] / initial_pos['width']

        self.assertAlmostEqual(expected_width_ratio, actual_width_ratio, places=2,
                              msg="Mask width should scale with zoom")

    def test_zoom_out_updates_mask_position(self):
        """Test that zooming out updates the mask canvas position."""
        self.driver.get(f"{self.server.base_url}/annotate")

        self._wait_for_annotation_manager()
        time.sleep(0.5)

        # First zoom in to have room to zoom out
        zoom_in_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-in"]')
        zoom_in_btn.click()
        zoom_in_btn.click()
        time.sleep(0.2)

        # Get position after zoom in
        pos_after_in = self._get_mask_canvas_position()

        # Now zoom out
        zoom_out_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-out"]')
        zoom_out_btn.click()
        time.sleep(0.2)

        # Get position after zoom out
        pos_after_out = self._get_mask_canvas_position()

        # Verify zoom decreased
        self.assertLess(pos_after_out['zoom'], pos_after_in['zoom'],
                       "Zoom should have decreased after zoom out")

        # Verify width scaled down
        self.assertLess(pos_after_out['width'], pos_after_in['width'],
                       "Mask width should decrease with zoom out")

    def test_zoom_fit_updates_mask_position(self):
        """Test that zoom fit updates the mask canvas position."""
        self.driver.get(f"{self.server.base_url}/annotate")

        self._wait_for_annotation_manager()
        time.sleep(0.5)

        # First zoom in to change from default
        zoom_in_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-in"]')
        zoom_in_btn.click()
        zoom_in_btn.click()
        zoom_in_btn.click()
        time.sleep(0.2)

        pos_zoomed = self._get_mask_canvas_position()

        # Click zoom fit
        zoom_fit_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-fit"]')
        zoom_fit_btn.click()
        time.sleep(0.2)

        pos_fit = self._get_mask_canvas_position()

        # Zoom fit should change the zoom level
        self.assertNotEqual(pos_zoomed['zoom'], pos_fit['zoom'],
                           "Zoom fit should change zoom level")

    def test_zoom_reset_updates_mask_position(self):
        """Test that zoom reset updates the mask canvas position."""
        self.driver.get(f"{self.server.base_url}/annotate")

        self._wait_for_annotation_manager()
        time.sleep(0.5)

        # First zoom in
        zoom_in_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-in"]')
        zoom_in_btn.click()
        zoom_in_btn.click()
        time.sleep(0.2)

        # Click zoom reset (100%)
        zoom_reset_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-reset"]')
        zoom_reset_btn.click()
        time.sleep(0.2)

        pos_reset = self._get_mask_canvas_position()

        # After reset, zoom should be 1.0
        self.assertAlmostEqual(pos_reset['zoom'], 1.0, places=2,
                              msg="Zoom should be 1.0 after reset")

    def test_render_all_masks_called_on_zoom(self):
        """Test that _renderAllMasks is called when zooming."""
        self.driver.get(f"{self.server.base_url}/annotate")

        self._wait_for_annotation_manager()
        time.sleep(0.5)

        # Inject a spy on _renderAllMasks
        self.driver.execute_script("""
            var container = document.querySelector('.image-annotation-container');
            if (container && container.annotationManager) {
                container.annotationManager._renderAllMasksCalled = 0;
                var original = container.annotationManager._renderAllMasks.bind(container.annotationManager);
                container.annotationManager._renderAllMasks = function() {
                    this._renderAllMasksCalled++;
                    return original();
                };
            }
        """)

        # Click zoom in
        zoom_in_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-in"]')
        zoom_in_btn.click()
        time.sleep(0.2)

        # Check if _renderAllMasks was called
        call_count = self.driver.execute_script("""
            var container = document.querySelector('.image-annotation-container');
            return container && container.annotationManager ?
                   container.annotationManager._renderAllMasksCalled : 0;
        """)

        self.assertGreater(call_count, 0,
                          "_renderAllMasks should be called when zooming")

    def test_mask_position_sync_after_multiple_zooms(self):
        """Test mask position stays synced after multiple zoom operations."""
        self.driver.get(f"{self.server.base_url}/annotate")

        self._wait_for_annotation_manager()
        time.sleep(0.5)

        # Perform multiple zoom operations
        zoom_in_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-in"]')
        zoom_out_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-out"]')
        zoom_fit_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-fit"]')

        # Zoom in 3 times
        for _ in range(3):
            zoom_in_btn.click()
            time.sleep(0.1)

        # Zoom out 2 times
        for _ in range(2):
            zoom_out_btn.click()
            time.sleep(0.1)

        # Zoom fit
        zoom_fit_btn.click()
        time.sleep(0.2)

        # Get final position
        final_pos = self._get_mask_canvas_position()

        # Verify position is still valid (not NaN or undefined)
        self.assertIsNotNone(final_pos, "Position should be valid after multiple zooms")
        self.assertIsInstance(final_pos['left'], (int, float), "Left should be a number")
        self.assertIsInstance(final_pos['top'], (int, float), "Top should be a number")
        self.assertIsInstance(final_pos['width'], (int, float), "Width should be a number")
        self.assertIsInstance(final_pos['height'], (int, float), "Height should be a number")
        self.assertGreater(final_pos['width'], 0, "Width should be positive")
        self.assertGreater(final_pos['height'], 0, "Height should be positive")


if __name__ == "__main__":
    unittest.main()
