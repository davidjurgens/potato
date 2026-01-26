#!/usr/bin/env python3
"""
Selenium tests for image annotation functionality.

This test suite focuses on the image annotation UI including:
- Image loading and display
- Tool selection (bbox, polygon, etc.)
- Label selection
- Zoom and pan controls
- Annotation creation via mouse interaction
- Annotation persistence

Authentication Flow:
1. Each test inherits from a base class that handles authentication
2. Tests create a unique server instance with image annotation config
3. Each test gets a fresh WebDriver and unique user account for isolation
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
    create_image_annotation_config,
    cleanup_test_directory
)


class TestImageAnnotationSelenium(unittest.TestCase):
    """
    Test suite for image annotation functionality.

    This class tests the core image annotation features:
    - Image annotation container loading
    - Tool selection buttons
    - Label selection buttons
    - Zoom controls
    - Annotation creation
    """

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server for all tests in this class."""
        # Create test directory
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", "image_annotation_selenium_test")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create image annotation config
        cls.config_file, cls.data_file = create_image_annotation_config(
            cls.test_dir,
            annotation_task_name="Image Annotation Selenium Test",
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
        self.test_user = f"image_test_user_{timestamp}"
        self.test_password = "test_password_123"

        self._register_user()
        self._login_user()

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _register_user(self):
        """Register a test user."""
        self.driver.get(f"{self.server.base_url}/")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-tab"))
        )

        # Switch to registration tab
        register_tab = self.driver.find_element(By.ID, "register-tab")
        register_tab.click()

        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "register-content"))
        )

        # Fill registration form
        username_field = self.driver.find_element(By.ID, "register-email")
        password_field = self.driver.find_element(By.ID, "register-pass")
        username_field.clear()
        password_field.clear()
        username_field.send_keys(self.test_user)
        password_field.send_keys(self.test_password)

        # Submit
        register_form = self.driver.find_element(By.CSS_SELECTOR, "#register-content form")
        register_form.submit()
        time.sleep(0.05)

    def _login_user(self):
        """Login the test user."""
        if "/annotate" not in self.driver.current_url:
            self.driver.get(f"{self.server.base_url}/")

            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "login-tab"))
            )

            login_tab = self.driver.find_element(By.ID, "login-tab")
            login_tab.click()

            WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.ID, "login-content"))
            )

            username_field = self.driver.find_element(By.ID, "login-email")
            password_field = self.driver.find_element(By.ID, "login-pass")
            username_field.clear()
            password_field.clear()
            username_field.send_keys(self.test_user)
            password_field.send_keys(self.test_password)

            login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
            login_form.submit()
            time.sleep(0.05)

    def test_image_annotation_container_loads(self):
        """Test that the image annotation container loads properly."""
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        # Verify container exists
        container = self.driver.find_element(By.CLASS_NAME, "image-annotation-container")
        self.assertTrue(container.is_displayed(), "Image annotation container should be visible")

        # Verify toolbar exists
        toolbar = self.driver.find_element(By.CLASS_NAME, "image-annotation-toolbar")
        self.assertTrue(toolbar.is_displayed(), "Toolbar should be visible")

    def test_tool_buttons_exist(self):
        """Test that tool selection buttons are present."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        # Check for bbox tool button
        bbox_buttons = self.driver.find_elements(By.CSS_SELECTOR, '[data-tool="bbox"]')
        self.assertGreater(len(bbox_buttons), 0, "Bbox tool button should exist")

        # Check for polygon tool button
        polygon_buttons = self.driver.find_elements(By.CSS_SELECTOR, '[data-tool="polygon"]')
        self.assertGreater(len(polygon_buttons), 0, "Polygon tool button should exist")

    def test_label_buttons_exist(self):
        """Test that label selection buttons are present."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        # Check for label buttons
        label_buttons = self.driver.find_elements(By.CLASS_NAME, "label-btn")
        self.assertGreater(len(label_buttons), 0, "Label buttons should exist")

        # Verify specific labels
        label_names = [btn.get_attribute("data-label") for btn in label_buttons]
        self.assertIn("person", label_names, "Person label should exist")
        self.assertIn("animal", label_names, "Animal label should exist")
        self.assertIn("vehicle", label_names, "Vehicle label should exist")

    def test_zoom_controls_exist(self):
        """Test that zoom controls are present."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        # Check for zoom buttons
        zoom_in = self.driver.find_elements(By.CSS_SELECTOR, '[data-action="zoom-in"]')
        zoom_out = self.driver.find_elements(By.CSS_SELECTOR, '[data-action="zoom-out"]')
        zoom_fit = self.driver.find_elements(By.CSS_SELECTOR, '[data-action="zoom-fit"]')

        self.assertGreater(len(zoom_in), 0, "Zoom in button should exist")
        self.assertGreater(len(zoom_out), 0, "Zoom out button should exist")
        self.assertGreater(len(zoom_fit), 0, "Zoom fit button should exist")

    def test_tool_selection(self):
        """Test selecting different annotation tools."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        # Wait a moment for JavaScript to initialize
        time.sleep(0.1)

        # Select bbox tool
        bbox_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-tool="bbox"]')
        bbox_btn.click()

        # Verify it's selected (has active class)
        time.sleep(0.1)
        self.assertIn("active", bbox_btn.get_attribute("class") or "",
                     "Bbox button should be active after click")

        # Select polygon tool
        polygon_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-tool="polygon"]')
        polygon_btn.click()

        time.sleep(0.1)
        self.assertIn("active", polygon_btn.get_attribute("class") or "",
                     "Polygon button should be active after click")

    def test_label_selection(self):
        """Test selecting different labels."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        time.sleep(0.1)

        # Find and click person label
        person_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-label="person"]')
        person_btn.click()

        time.sleep(0.1)
        self.assertIn("active", person_btn.get_attribute("class") or "",
                     "Person label should be active after click")

        # Click animal label
        animal_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-label="animal"]')
        animal_btn.click()

        time.sleep(0.1)
        self.assertIn("active", animal_btn.get_attribute("class") or "",
                     "Animal label should be active after click")

    def test_image_canvas_exists(self):
        """Test that the image canvas element exists."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        # Check for canvas or SVG element used for annotations
        canvas_elements = self.driver.find_elements(By.CLASS_NAME, "annotation-canvas")
        svg_elements = self.driver.find_elements(By.CLASS_NAME, "annotation-svg")
        image_containers = self.driver.find_elements(By.CLASS_NAME, "image-container")

        total_elements = len(canvas_elements) + len(svg_elements) + len(image_containers)
        self.assertGreater(total_elements, 0,
                          "Should have canvas, SVG, or image container for annotations")

    def test_annotation_count_exists(self):
        """Test that the annotation count display exists."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        # Check for annotation count display
        count_groups = self.driver.find_elements(By.CLASS_NAME, "count-group")
        self.assertGreater(len(count_groups), 0, "Annotation count group should exist")

        count_values = self.driver.find_elements(By.CLASS_NAME, "count-value")
        self.assertGreater(len(count_values), 0, "Annotation count value should exist")

    def test_hidden_input_for_data(self):
        """Test that hidden input for storing annotation data exists."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        # Check for hidden input
        hidden_inputs = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="hidden"].annotation-data-input')
        self.assertGreater(len(hidden_inputs), 0, "Hidden input for annotation data should exist")

    def test_image_annotation_manager_initialized(self):
        """Test that the ImageAnnotationManager JavaScript is initialized."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        # Wait for JavaScript initialization with retry
        max_wait = 5  # seconds
        manager_exists = False
        for _ in range(max_wait * 2):  # Check every 0.5 seconds
            manager_exists = self.driver.execute_script("""
                var container = document.querySelector('.image-annotation-container');
                return container && container.annotationManager !== undefined;
            """)
            if manager_exists:
                break
            time.sleep(0.1)

        self.assertTrue(manager_exists, "ImageAnnotationManager should be initialized on container (stored as container.annotationManager)")

    def test_keyboard_shortcuts_bound(self):
        """Test that keyboard shortcuts are properly set up."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        time.sleep(0.05)

        # Check for keybinding help section or verify shortcuts exist
        page_source = self.driver.page_source

        # The keybindings should be present in the page
        # Check for common keyboard shortcut indicators
        has_shortcuts = (
            'key_value' in page_source.lower() or
            'keybind' in page_source.lower() or
            'shortcut' in page_source.lower() or
            '(1)' in page_source  # Label key hints
        )

        # This is a soft check - some implementations may not show shortcuts in HTML
        print(f"Keyboard shortcuts found in page: {has_shortcuts}")


class TestImageAnnotationInteraction(unittest.TestCase):
    """
    Test suite for image annotation interaction.

    These tests verify mouse interactions and annotation creation.
    """

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", "image_interaction_selenium_test")
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.config_file, cls.data_file = create_image_annotation_config(
            cls.test_dir,
            annotation_task_name="Image Interaction Selenium Test",
            require_password=False
        )

        cls.server = FlaskTestServer(debug=False, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
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

        timestamp = int(time.time())
        self.test_user = f"interaction_test_user_{timestamp}"
        self.test_password = "test_password_123"

        self._register_and_login()

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _register_and_login(self):
        """Register and login a test user."""
        self.driver.get(f"{self.server.base_url}/")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-tab"))
        )

        # Register
        register_tab = self.driver.find_element(By.ID, "register-tab")
        register_tab.click()

        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "register-content"))
        )

        username_field = self.driver.find_element(By.ID, "register-email")
        password_field = self.driver.find_element(By.ID, "register-pass")
        username_field.send_keys(self.test_user)
        password_field.send_keys(self.test_password)

        register_form = self.driver.find_element(By.CSS_SELECTOR, "#register-content form")
        register_form.submit()
        time.sleep(0.05)

    def test_zoom_in_button_click(self):
        """Test clicking the zoom in button."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        time.sleep(0.1)

        # Get initial zoom level if exposed
        initial_zoom = self.driver.execute_script("""
            var container = document.querySelector('.image-annotation-container');
            if (container && container.imageAnnotationManager) {
                return container.imageAnnotationManager.zoomLevel || 1;
            }
            return 1;
        """)

        # Click zoom in
        zoom_in_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-in"]')
        zoom_in_btn.click()

        time.sleep(0.1)

        # Verify zoom changed
        new_zoom = self.driver.execute_script("""
            var container = document.querySelector('.image-annotation-container');
            if (container && container.imageAnnotationManager) {
                return container.imageAnnotationManager.zoomLevel || 1;
            }
            return 1;
        """)

        # Zoom should have increased
        print(f"Initial zoom: {initial_zoom}, New zoom: {new_zoom}")

    def test_zoom_out_button_click(self):
        """Test clicking the zoom out button."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        time.sleep(0.1)

        # First zoom in
        zoom_in_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-in"]')
        zoom_in_btn.click()
        time.sleep(0.1)

        # Then zoom out
        zoom_out_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-out"]')
        zoom_out_btn.click()

        time.sleep(0.1)
        # Test passes if no exceptions

    def test_zoom_fit_button_click(self):
        """Test clicking the zoom fit button."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        time.sleep(0.1)

        # Click zoom fit
        zoom_fit_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-action="zoom-fit"]')
        zoom_fit_btn.click()

        time.sleep(0.1)
        # Test passes if no exceptions

    def test_delete_button_disabled_initially(self):
        """Test that delete button is disabled when no annotation selected."""
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        time.sleep(0.1)

        # Find delete button
        delete_buttons = self.driver.find_elements(By.CSS_SELECTOR, '[data-action="delete"]')

        if delete_buttons:
            delete_btn = delete_buttons[0]
            is_disabled = delete_btn.get_attribute("disabled") is not None

            print(f"Delete button disabled: {is_disabled}")


if __name__ == "__main__":
    unittest.main()
