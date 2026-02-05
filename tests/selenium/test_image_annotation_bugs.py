#!/usr/bin/env python3
"""
Selenium tests for image annotation bugs:
1. Annotation count not updating when creating bounding box
2. Annotations persisting when navigating to new instance

These tests reproduce the reported bugs and verify the fixes.
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

# Add project to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_image_annotation_config,
    cleanup_test_directory
)


class ImageAnnotationTestBase(unittest.TestCase):
    """Base class for image annotation tests with common setup."""

    test_dir_name = "image_annotation_test"
    task_name = "Image Annotation Test"

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server."""
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output", cls.test_dir_name)
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.config_file, cls.data_file = create_image_annotation_config(
            cls.test_dir,
            annotation_task_name=cls.task_name,
            require_password=True
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
        self.test_user = f"test_user_{timestamp}"
        self.test_password = "test_password_123"

        self._register_and_login()

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _register_and_login(self):
        """Register and login a test user."""
        self.driver.get(f"{self.server.base_url}/")

        # Wait for page to fully load
        WebDriverWait(self.driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # Wait for login page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-tab"))
        )

        # Register
        register_tab = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, "register-tab"))
        )
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

        # Wait for page navigation to complete after registration
        # This is critical - wait for the URL to change or the new page to load
        time.sleep(2)

        # Wait for page to stabilize
        WebDriverWait(self.driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # After registration, we might be on the annotation page already
        # or we might need to login. Check what page we're on.
        try:
            # If we can find the annotation container, we're already logged in
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
            )
            return  # Already logged in
        except:
            pass

        # Navigate to annotate page - this will redirect to login if not authenticated
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for page to load
        WebDriverWait(self.driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # Check if we're on the annotation page now
        try:
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
            )
            return  # Already on annotation page
        except:
            pass

        # Still need to login
        try:
            login_tab = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, "login-tab"))
            )
            login_tab.click()

            WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.ID, "login-content"))
            )

            username_field = self.driver.find_element(By.ID, "login-email")
            password_field = self.driver.find_element(By.ID, "login-pass")
            username_field.send_keys(self.test_user)
            password_field.send_keys(self.test_password)

            login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
            login_form.submit()

            # Wait for navigation after login
            time.sleep(1)
            WebDriverWait(self.driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except:
            pass  # May already be logged in

    def _wait_for_image_loaded(self):
        """Wait for the image annotation manager to be ready."""
        # First wait for page to be fully loaded
        WebDriverWait(self.driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # Wait for image annotation container to exist
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "image-annotation-container"))
        )

        # Wait for manager to initialize (up to 10 seconds)
        for _ in range(100):
            try:
                manager_ready = self.driver.execute_script("""
                    var container = document.querySelector('.image-annotation-container');
                    return container && container.annotationManager && container.annotationManager.canvas;
                """)
                if manager_ready:
                    # Also wait for canvas to be ready
                    canvas_ready = self.driver.execute_script("""
                        var container = document.querySelector('.image-annotation-container');
                        if (!container || !container.annotationManager) return false;
                        var canvas = container.annotationManager.canvas;
                        return canvas && canvas.getElement();
                    """)
                    if canvas_ready:
                        time.sleep(0.3)  # Small additional wait for stability
                        return
            except Exception:
                pass  # Ignore stale element errors during polling
            time.sleep(0.1)

    def _create_bounding_box(self, x_offset=100, y_offset=100, width=100, height=80):
        """Create a bounding box on the canvas using mouse actions."""
        canvas = self.driver.find_element(By.CLASS_NAME, "upper-canvas")

        actions = ActionChains(self.driver)
        actions.move_to_element_with_offset(canvas, x_offset, y_offset)
        actions.click_and_hold()
        actions.move_by_offset(width, height)
        actions.release()
        actions.perform()

        time.sleep(0.3)  # Allow time for annotation to be processed

    def _get_annotation_count_from_canvas(self):
        """Get the actual number of annotation objects on the canvas."""
        return self.driver.execute_script("""
            var container = document.querySelector('.image-annotation-container');
            if (container && container.annotationManager && container.annotationManager.canvas) {
                var objects = container.annotationManager.canvas.getObjects();
                return objects.filter(function(obj) {
                    return obj.annotationData !== undefined;
                }).length;
            }
            return -1;
        """)

    def _get_hidden_input_value(self):
        """Get the value of the hidden annotation data input."""
        return self.driver.execute_script("""
            var input = document.querySelector('.annotation-data-input');
            return input ? input.value : null;
        """)


class TestImageAnnotationCountBug(ImageAnnotationTestBase):
    """
    Test that annotation count updates when creating bounding boxes.

    Bug: When a user creates a bounding box, the annotation count display
    does not update to reflect the new annotation.
    """

    test_dir_name = "image_annotation_count_bug_test"
    task_name = "Image Annotation Count Bug Test"

    def test_annotation_count_updates_after_creating_bbox(self):
        """
        Test that the annotation count increases when a bounding box is created.

        This test reproduces the bug where the count display stays at 0
        even after creating annotations.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait_for_image_loaded()

        # Get initial count
        count_element = self.driver.find_element(By.CLASS_NAME, "count-value")
        initial_count = int(count_element.text)
        self.assertEqual(initial_count, 0, "Initial count should be 0")

        # Select bbox tool
        bbox_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-tool="bbox"]')
        bbox_btn.click()
        time.sleep(0.1)

        # Select a label
        label_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-label="person"]')
        label_btn.click()
        time.sleep(0.1)

        # Create a bounding box
        self._create_bounding_box()

        # Check that count increased
        count_element = self.driver.find_element(By.CLASS_NAME, "count-value")
        new_count = int(count_element.text)

        self.assertEqual(new_count, 1,
            f"Annotation count should be 1 after creating bbox, but was {new_count}")

    def test_annotation_count_updates_after_multiple_bboxes(self):
        """Test that count updates correctly after creating multiple bounding boxes."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait_for_image_loaded()

        # Select bbox tool and label
        bbox_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-tool="bbox"]')
        bbox_btn.click()
        label_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-label="person"]')
        label_btn.click()
        time.sleep(0.1)

        # Create first bounding box
        self._create_bounding_box(x_offset=50, y_offset=50)
        count_element = self.driver.find_element(By.CLASS_NAME, "count-value")
        self.assertEqual(int(count_element.text), 1, "Count should be 1 after first bbox")

        # Create second bounding box
        self._create_bounding_box(x_offset=200, y_offset=50)
        count_element = self.driver.find_element(By.CLASS_NAME, "count-value")
        self.assertEqual(int(count_element.text), 2, "Count should be 2 after second bbox")

        # Create third bounding box
        self._create_bounding_box(x_offset=50, y_offset=200)
        count_element = self.driver.find_element(By.CLASS_NAME, "count-value")
        self.assertEqual(int(count_element.text), 3, "Count should be 3 after third bbox")


class TestImageAnnotationPersistenceBug(ImageAnnotationTestBase):
    """
    Test that annotations do NOT persist when navigating to a new instance.

    Bug: When a user creates annotations on instance 1 and navigates to
    instance 2, the annotations from instance 1 incorrectly appear on instance 2.
    """

    test_dir_name = "image_annotation_persistence_bug_test"
    task_name = "Image Annotation Persistence Bug Test"

    def test_annotations_cleared_on_navigation_to_new_instance(self):
        """
        Test that annotations are cleared when navigating to a new instance.

        This test reproduces the bug where annotations from instance 1
        incorrectly appear on instance 2.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait_for_image_loaded()

        # Get the first instance ID
        first_instance_id = self.driver.execute_script("""
            return document.getElementById('instance_id').value;
        """)

        # Select bbox tool and label
        bbox_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-tool="bbox"]')
        bbox_btn.click()
        label_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-label="person"]')
        label_btn.click()
        time.sleep(0.1)

        # Create annotations on instance 1
        self._create_bounding_box(x_offset=50, y_offset=50)
        self._create_bounding_box(x_offset=200, y_offset=50)

        # Verify we have 2 annotations
        count_on_instance_1 = self._get_annotation_count_from_canvas()
        self.assertEqual(count_on_instance_1, 2,
            "Should have 2 annotations on instance 1")

        # Navigate to next instance
        next_btn = self.driver.find_element(By.ID, "next-btn")
        next_btn.click()

        # Wait for page to reload and new instance to load
        WebDriverWait(self.driver, 10).until(
            EC.staleness_of(next_btn)
        )
        self._wait_for_image_loaded()

        # Get the second instance ID
        second_instance_id = self.driver.execute_script("""
            return document.getElementById('instance_id').value;
        """)

        # Verify we're on a different instance
        self.assertNotEqual(first_instance_id, second_instance_id,
            "Should be on a different instance after navigation")

        # Check that annotations are cleared on the new instance
        count_on_instance_2 = self._get_annotation_count_from_canvas()
        self.assertEqual(count_on_instance_2, 0,
            f"New instance should have 0 annotations, but has {count_on_instance_2}")

        # Also check the hidden input is empty
        hidden_input_value = self._get_hidden_input_value()
        self.assertTrue(
            hidden_input_value is None or hidden_input_value == "" or hidden_input_value == "[]",
            f"Hidden input should be empty on new instance, but was: {hidden_input_value}"
        )

    def test_annotations_persist_when_returning_to_previous_instance(self):
        """
        Test that annotations ARE preserved when returning to a previously annotated instance.

        This verifies that the fix doesn't break the expected persistence behavior.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait_for_image_loaded()

        # Create annotations on instance 1
        bbox_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-tool="bbox"]')
        bbox_btn.click()
        label_btn = self.driver.find_element(By.CSS_SELECTOR, '[data-label="person"]')
        label_btn.click()
        time.sleep(0.1)

        self._create_bounding_box(x_offset=100, y_offset=100)

        count_before = self._get_annotation_count_from_canvas()
        self.assertEqual(count_before, 1, "Should have 1 annotation before navigation")

        # Navigate to next instance
        next_btn = self.driver.find_element(By.ID, "next-btn")
        next_btn.click()

        WebDriverWait(self.driver, 10).until(
            EC.staleness_of(next_btn)
        )
        self._wait_for_image_loaded()

        # Navigate back to previous instance
        prev_btn = self.driver.find_element(By.ID, "prev-btn")
        prev_btn.click()

        WebDriverWait(self.driver, 10).until(
            EC.staleness_of(prev_btn)
        )
        self._wait_for_image_loaded()

        # Check that annotations are restored
        count_after_return = self._get_annotation_count_from_canvas()
        self.assertEqual(count_after_return, 1,
            f"Annotations should be restored when returning to instance, but count was {count_after_return}")


if __name__ == "__main__":
    unittest.main()
