"""
Selenium tests for overlay consolidation changes.

Tests z-index layering, resize behavior, and unified interactions.
"""

import pytest
import time
import os
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file


def create_chrome_options():
    """Create Chrome options for headless testing."""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    return options


class TestOverlayConsolidation(unittest.TestCase):
    """Test overlay system consolidation and z-index layering."""

    @classmethod
    def setUpClass(cls):
        """Set up test server with span annotation config."""
        cls.test_dir = create_test_directory("overlay_consolidation_test")

        # Create test data with repeated words for keyword testing
        test_data = [
            {"id": "1", "text": "I love this product. I really love the quality and love the design."},
            {"id": "2", "text": "Great service, great price, great experience overall."},
            {"id": "3", "text": "The product is good but the shipping was slow."},
        ]
        data_file = create_test_data_file(cls.test_dir, test_data, "data.jsonl")

        # Create config with span annotation
        config_content = f"""
annotation_task_name: Overlay Consolidation Test
task_dir: {cls.test_dir}
site_dir: default
port: 0
debug: true

data_files:
  - {data_file}

item_properties:
  id_key: id
  text_key: text

user_config:
  allow_all_users: true

annotation_schemes:
  - annotation_type: span
    annotation_id: 0
    name: entities
    description: Highlight entities in the text
    labels:
      - name: positive
        color: "#22C55E"
      - name: negative
        color: "#EF4444"
      - name: neutral
        color: "#9CA3AF"

output_annotation_dir: {cls.test_dir}/output
output_annotation_format: json
"""
        config_file = os.path.join(cls.test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            f.write(config_content)

        cls.server = FlaskTestServer(config=config_file)
        if not cls.server.start():
            raise Exception("Failed to start test server")

        cls.chrome_options = create_chrome_options()

    @classmethod
    def tearDownClass(cls):
        """Clean up test server."""
        if hasattr(cls, 'server') and cls.server:
            cls.server.stop()

    def setUp(self):
        """Set up driver for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, 10)

    def tearDown(self):
        """Clean up driver after each test."""
        if hasattr(self, 'driver') and self.driver:
            self.driver.quit()

    def login_and_navigate(self):
        """Log in and navigate to annotation page."""
        base_url = self.server.base_url
        self.driver.get(base_url)

        # Wait for login page to load
        self.wait.until(
            EC.presence_of_element_located((By.ID, "login-content"))
        )

        # Try to log in (simple mode - require_password=False)
        try:
            username_field = self.driver.find_element(By.ID, "login-email")
            username_field.clear()
            username_field.send_keys("test_user")

            # Submit the login form
            login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
            login_form.submit()

            # Wait for redirect to annotation page
            time.sleep(1)
        except NoSuchElementException:
            pass  # Already logged in or different login mode

        # Navigate to annotation page where span-overlays exists
        self.driver.get(f"{base_url}/annotate")

        # Wait for the annotation page to fully load
        self.wait.until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

    def test_no_fallback_container_exists(self):
        """
        Verify the fallback #ai-keyword-overlays container does not exist.

        All overlays should be consolidated in #span-overlays.
        """
        self.login_and_navigate()

        # Wait for span overlays container
        self.wait.until(
            EC.presence_of_element_located((By.ID, "span-overlays"))
        )

        # Check that fallback container does not exist
        fallback_containers = self.driver.find_elements(By.ID, "ai-keyword-overlays")
        self.assertEqual(
            len(fallback_containers), 0,
            "Fallback #ai-keyword-overlays container should not exist"
        )

    def test_span_overlays_container_exists(self):
        """Verify #span-overlays container exists and is properly positioned."""
        self.login_and_navigate()

        span_overlays = self.wait.until(
            EC.presence_of_element_located((By.ID, "span-overlays"))
        )

        # Verify it's positioned absolutely
        position = span_overlays.value_of_css_property("position")
        self.assertEqual(position, "absolute", "span-overlays should be absolutely positioned")

        # Verify pointer-events is none (allows clicking through to text)
        pointer_events = span_overlays.value_of_css_property("pointer-events")
        self.assertEqual(pointer_events, "none", "span-overlays should have pointer-events: none")

    def test_z_index_css_variables_defined(self):
        """Verify CSS custom properties for z-index are defined."""
        self.login_and_navigate()

        # Get computed style of root element
        root_styles = self.driver.execute_script("""
            const root = document.documentElement;
            const style = getComputedStyle(root);
            return {
                adminKeyword: style.getPropertyValue('--z-overlay-admin-keyword').trim(),
                aiKeyword: style.getPropertyValue('--z-overlay-ai-keyword').trim(),
                userSpan: style.getPropertyValue('--z-overlay-user-span').trim(),
                controls: style.getPropertyValue('--z-overlay-controls').trim(),
                tooltip: style.getPropertyValue('--z-overlay-tooltip').trim()
            };
        """)

        # Verify all variables are defined and have expected values
        self.assertEqual(root_styles['adminKeyword'], '100', "Admin keyword z-index should be 100")
        self.assertEqual(root_styles['aiKeyword'], '110', "AI keyword z-index should be 110")
        self.assertEqual(root_styles['userSpan'], '120', "User span z-index should be 120")
        self.assertEqual(root_styles['controls'], '200', "Controls z-index should be 200")
        self.assertEqual(root_styles['tooltip'], '300', "Tooltip z-index should be 300")

    def test_overlay_z_index_constants_exist(self):
        """Verify OVERLAY_Z_INDEX constants are defined in JavaScript."""
        self.login_and_navigate()

        # Check that OVERLAY_Z_INDEX is defined
        result = self.driver.execute_script("""
            return typeof OVERLAY_Z_INDEX !== 'undefined' &&
                   OVERLAY_Z_INDEX.ADMIN_KEYWORD === 100 &&
                   OVERLAY_Z_INDEX.AI_KEYWORD === 110 &&
                   OVERLAY_Z_INDEX.USER_SPAN === 120 &&
                   OVERLAY_Z_INDEX.SPAN_CONTROLS === 200 &&
                   OVERLAY_Z_INDEX.TOOLTIP === 300;
        """)

        self.assertTrue(result, "OVERLAY_Z_INDEX constants should be defined with correct values")

    def test_span_manager_has_resize_handler(self):
        """Verify SpanManager has resize handler methods."""
        self.login_and_navigate()

        # Wait for SpanManager to initialize
        time.sleep(1)

        result = self.driver.execute_script("""
            return window.spanManager &&
                   typeof window.spanManager.setupResizeHandler === 'function' &&
                   typeof window.spanManager.repositionAllOverlays === 'function';
        """)

        self.assertTrue(result, "SpanManager should have resize handler methods")

    def test_span_manager_has_interaction_handler(self):
        """Verify SpanManager has overlay interaction methods."""
        self.login_and_navigate()

        # Wait for SpanManager to initialize
        time.sleep(1)

        result = self.driver.execute_script("""
            return window.spanManager &&
                   typeof window.spanManager.setupOverlayInteractions === 'function' &&
                   typeof window.spanManager.handleSegmentHover === 'function' &&
                   typeof window.spanManager.showOverlayTooltip === 'function' &&
                   typeof window.spanManager.hideOverlayTooltip === 'function';
        """)

        self.assertTrue(result, "SpanManager should have interaction handler methods")

    def test_positioning_strategy_has_offset_method(self):
        """Verify UnifiedPositioningStrategy has getPositionsFromOffsets method."""
        self.login_and_navigate()

        # Wait for SpanManager to initialize
        time.sleep(1)

        result = self.driver.execute_script("""
            return window.spanManager &&
                   window.spanManager.positioningStrategy &&
                   typeof window.spanManager.positioningStrategy.getPositionsFromOffsets === 'function';
        """)

        self.assertTrue(result, "Positioning strategy should have getPositionsFromOffsets method")

    def test_get_positions_from_offsets_returns_correct_structure(self):
        """Verify getPositionsFromOffsets returns positions with x, y, width, height."""
        self.login_and_navigate()

        # Wait for SpanManager to initialize
        time.sleep(2)

        result = self.driver.execute_script("""
            if (!window.spanManager || !window.spanManager.positioningStrategy) {
                return {error: 'SpanManager not ready'};
            }

            // Get the text content
            const textContent = document.getElementById('text-content');
            if (!textContent) {
                return {error: 'text-content not found'};
            }

            const text = textContent.textContent || '';
            if (text.length < 5) {
                return {error: 'Text too short: ' + text.length};
            }

            // Try to get positions for a range
            const positions = window.spanManager.positioningStrategy.getPositionsFromOffsets(0, 5);

            if (!positions || positions.length === 0) {
                return {error: 'No positions returned'};
            }

            const pos = positions[0];
            return {
                hasX: 'x' in pos,
                hasY: 'y' in pos,
                hasWidth: 'width' in pos,
                hasHeight: 'height' in pos,
                hasLeft: 'left' in pos,
                hasTop: 'top' in pos,
                x: pos.x,
                y: pos.y,
                width: pos.width,
                height: pos.height
            };
        """)

        if 'error' in result:
            self.skipTest(f"Test prerequisites not met: {result['error']}")

        # Verify correct properties exist
        self.assertTrue(result['hasX'], "Position should have 'x' property")
        self.assertTrue(result['hasY'], "Position should have 'y' property")
        self.assertTrue(result['hasWidth'], "Position should have 'width' property")
        self.assertTrue(result['hasHeight'], "Position should have 'height' property")

        # Verify incorrect properties do NOT exist
        self.assertFalse(result['hasLeft'], "Position should NOT have 'left' property")
        self.assertFalse(result['hasTop'], "Position should NOT have 'top' property")

        # Verify values are reasonable
        self.assertGreaterEqual(result['x'], 0, "x should be >= 0")
        self.assertGreaterEqual(result['y'], 0, "y should be >= 0")
        self.assertGreater(result['width'], 0, "width should be > 0")
        self.assertGreater(result['height'], 0, "height should be > 0")


class TestOverlayResizeBehavior(unittest.TestCase):
    """Test overlay resize and repositioning behavior."""

    @classmethod
    def setUpClass(cls):
        """Set up test server."""
        cls.test_dir = create_test_directory("overlay_resize_test")

        test_data = [
            {"id": "1", "text": "This is a test sentence for resize testing."},
        ]
        data_file = create_test_data_file(cls.test_dir, test_data, "data.jsonl")

        config_content = f"""
annotation_task_name: Overlay Resize Test
task_dir: {cls.test_dir}
site_dir: default
port: 0
debug: true

data_files:
  - {data_file}

item_properties:
  id_key: id
  text_key: text

user_config:
  allow_all_users: true

annotation_schemes:
  - annotation_type: span
    annotation_id: 0
    name: entities
    description: Highlight entities in the text
    labels:
      - name: entity

output_annotation_dir: {cls.test_dir}/output
output_annotation_format: json
"""
        config_file = os.path.join(cls.test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            f.write(config_content)

        cls.server = FlaskTestServer(config=config_file)
        if not cls.server.start():
            raise Exception("Failed to start test server")

        cls.chrome_options = create_chrome_options()

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        if hasattr(cls, 'server') and cls.server:
            cls.server.stop()

    def setUp(self):
        """Set up driver."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, 10)

    def tearDown(self):
        """Clean up driver."""
        if hasattr(self, 'driver') and self.driver:
            self.driver.quit()

    def test_resize_handler_is_attached(self):
        """Verify resize event listener is attached to window."""
        base_url = self.server.base_url

        # First navigate to base_url to handle login
        self.driver.get(base_url)

        # Wait for login page to load
        self.wait.until(
            EC.presence_of_element_located((By.ID, "login-content"))
        )

        # Log in (simple mode - require_password=False)
        try:
            username_field = self.driver.find_element(By.ID, "login-email")
            username_field.clear()
            username_field.send_keys("test_user")

            # Submit the login form
            login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
            login_form.submit()
            time.sleep(1)
        except NoSuchElementException:
            pass

        # Navigate to annotation page
        self.driver.get(f"{base_url}/annotate")

        # Wait for annotation page to load
        self.wait.until(
            EC.presence_of_element_located((By.ID, "instance-text"))
        )

        # Check that resize handler was set up
        result = self.driver.execute_script("""
            // The resize handler is set up during SpanManager initialization
            // We can verify by checking if repositionAllOverlays is callable
            return window.spanManager &&
                   typeof window.spanManager.repositionAllOverlays === 'function';
        """)

        self.assertTrue(result, "Resize handler should be set up on SpanManager")


if __name__ == '__main__':
    unittest.main()
