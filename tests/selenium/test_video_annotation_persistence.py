#!/usr/bin/env python3
"""
Selenium tests for video annotation persistence.

Tests that video annotations (segments, keyframes, etc.) are properly saved
when navigating between instances and restored when returning to a previously
annotated instance.
"""

import os
import time
import json
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.common.exceptions import TimeoutException
from tests.helpers.flask_test_setup import FlaskTestServer


class TestVideoAnnotationPersistence(unittest.TestCase):
    """
    Test video annotation persistence across navigation.

    Uses Firefox by default since Chrome has keyboard shortcut issues
    with video annotation.
    """

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server with video annotation config."""
        # Get paths
        cls.project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        cls.test_output_dir = os.path.join(cls.project_root, "tests", "output", "video_annotation_test")

        # Create test output directory
        os.makedirs(cls.test_output_dir, exist_ok=True)

        # Create test config and data files
        cls.config_file = cls._create_test_config()
        cls.data_file = cls._create_test_data()

        # Start server
        cls.server = FlaskTestServer(port=9020, debug=True, config_file=cls.config_file)
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"

        # Wait for server to be ready
        cls.server._wait_for_server_ready(timeout=15)

        # Set up Firefox options (Firefox works better for video annotation)
        firefox_options = FirefoxOptions()
        firefox_options.add_argument("--headless")
        firefox_options.add_argument("--width=1920")
        firefox_options.add_argument("--height=1080")
        cls.firefox_options = firefox_options

        # Also set up Chrome for cross-browser testing
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_options

    @classmethod
    def _create_test_config(cls):
        """Create a test configuration file for video annotation."""
        config_content = f"""
port: 9020
debug: true
debug_phase: annotation
server_name: Video Annotation Test Server
annotation_task_name: Video Annotation Persistence Test
task_dir: {cls.test_output_dir}
output_annotation_dir: annotation_output/
output_annotation_format: json
annotation_codebook_url: ''

data_files:
  - {os.path.join(cls.test_output_dir, 'test_videos.json')}

item_properties:
  id_key: id
  text_key: video_url

user_config:
  allow_all_users: true
  users: []

alert_time_each_instance: 10000000

annotation_schemes:
  - annotation_type: video_annotation
    name: test_video_segments
    description: "Test video segment annotation"
    mode: segment
    labels:
      - name: label_a
        color: "#4ECDC4"
        key_value: "1"
      - name: label_b
        color: "#FF6B6B"
        key_value: "2"
    min_segments: 0
    timeline_height: 70
    zoom_enabled: true
    playback_rate_control: true
    frame_stepping: true
    show_timecode: true
    video_fps: 30

site_dir: default
"""
        config_path = os.path.join(cls.test_output_dir, "test_video_config.yaml")
        with open(config_path, 'w') as f:
            f.write(config_content)
        return config_path

    @classmethod
    def _create_test_data(cls):
        """Create test data file with three video instances.

        We need at least 3 instances because navigating through all instances
        triggers the 'completion' phase. With 3 instances, we can test:
        - Create segment on instance 1
        - Navigate to instance 2
        - Navigate back to instance 1 (without completing all instances)
        """
        data = [
            {
                "id": "test_video_001",
                "video_url": "https://www.w3schools.com/html/mov_bbb.mp4",
                "title": "Test Video 1"
            },
            {
                "id": "test_video_002",
                "video_url": "https://www.w3schools.com/html/movie.mp4",
                "title": "Test Video 2"
            },
            {
                "id": "test_video_003",
                "video_url": "https://www.w3schools.com/html/mov_bbb.mp4",
                "title": "Test Video 3"
            }
        ]
        data_path = os.path.join(cls.test_output_dir, "test_videos.json")
        with open(data_path, 'w') as f:
            for item in data:
                f.write(json.dumps(item) + '\n')
        return data_path

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()

        # Clean up test files
        import shutil
        if hasattr(cls, 'test_output_dir') and os.path.exists(cls.test_output_dir):
            shutil.rmtree(cls.test_output_dir, ignore_errors=True)

    def setUp(self):
        """Set up WebDriver for each test."""
        # Use Firefox by default (better keyboard support for video annotation)
        self.driver = webdriver.Firefox(options=self.firefox_options)
        self.driver.implicitly_wait(5)

    def _get_browser_logs(self):
        """Get browser console logs (Firefox)."""
        try:
            # For Firefox, use JavaScript to capture logs
            logs = self.driver.execute_script("""
                if (window._consoleLogs) {
                    return window._consoleLogs;
                }
                return [];
            """)
            return logs
        except:
            return []

    def _setup_console_capture(self):
        """Set up console log capture."""
        self.driver.execute_script("""
            window._consoleLogs = [];
            var originalLog = console.log;
            console.log = function() {
                window._consoleLogs.push(Array.from(arguments).join(' '));
                originalLog.apply(console, arguments);
            };
        """)

    def tearDown(self):
        """Clean up WebDriver after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _wait_for_video_container(self, timeout=15):
        """Wait for video annotation container to be present."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.CLASS_NAME, "video-annotation-container"))
        )

    def _wait_for_video_loaded(self, timeout=20):
        """Wait for video element to have loaded metadata."""
        def video_has_duration(driver):
            try:
                result = driver.execute_script("""
                    var video = document.querySelector('.video-element');
                    return video && video.readyState >= 1 && video.duration > 0;
                """)
                return result
            except:
                return False

        WebDriverWait(self.driver, timeout).until(video_has_duration)

    def _get_segment_count(self):
        """Get the number of segments currently displayed."""
        try:
            count_el = self.driver.find_element(By.CSS_SELECTOR, ".count-value")
            return int(count_el.text)
        except:
            return 0

    def _get_hidden_input_value(self):
        """Get the value of the hidden annotation data input."""
        try:
            input_el = self.driver.find_element(By.CSS_SELECTOR, ".annotation-data-input")
            return input_el.get_attribute("value")
        except:
            return None

    def _create_segment_via_ui(self, label_index=0):
        """Create a segment using UI buttons."""
        container = self._wait_for_video_container()

        # Select label first
        label_buttons = container.find_elements(By.CSS_SELECTOR, ".label-btn")
        if label_buttons and label_index < len(label_buttons):
            label_buttons[label_index].click()
            time.sleep(0.3)

        # Click set-start button
        start_btn = container.find_element(By.CSS_SELECTOR, '[data-action="set-start"]')
        start_btn.click()
        time.sleep(0.5)

        # Seek video forward a bit (use JavaScript since video controls may vary)
        self.driver.execute_script("""
            var video = document.querySelector('.video-element');
            if (video) {
                video.currentTime = Math.min(video.currentTime + 2, video.duration - 1);
            }
        """)
        time.sleep(0.5)

        # Click set-end button
        end_btn = container.find_element(By.CSS_SELECTOR, '[data-action="set-end"]')
        end_btn.click()
        time.sleep(0.3)

        # Click create segment button
        create_btn = container.find_element(By.CSS_SELECTOR, '[data-action="create-segment"]')
        create_btn.click()
        time.sleep(0.5)

    def _navigate_to_next(self):
        """Click the Next button to navigate to next instance."""
        next_btn = self.driver.find_element(By.ID, "next-btn")
        next_btn.click()
        time.sleep(2)  # Wait for navigation and page load

    def _navigate_to_previous(self):
        """Click the Previous button to navigate to previous instance."""
        prev_btn = self.driver.find_element(By.ID, "prev-btn")
        prev_btn.click()
        time.sleep(2)  # Wait for navigation and page load

    def _get_current_instance_id(self):
        """Get the current instance ID from the hidden input."""
        try:
            instance_input = self.driver.find_element(By.ID, "instance_id")
            return instance_input.get_attribute("value")
        except:
            return None

    def test_segment_saved_to_hidden_input(self):
        """Test that creating a segment saves data to the hidden input."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(3)  # Wait for page and video to load

        # Wait for video annotation container
        self._wait_for_video_container()
        self._wait_for_video_loaded()

        # Verify initial state - no segments
        initial_count = self._get_segment_count()
        self.assertEqual(initial_count, 0, "Should start with 0 segments")

        # Create a segment
        self._create_segment_via_ui(label_index=0)

        # Verify segment was created
        new_count = self._get_segment_count()
        self.assertEqual(new_count, 1, "Should have 1 segment after creation")

        # Verify hidden input has data
        input_value = self._get_hidden_input_value()
        self.assertIsNotNone(input_value, "Hidden input should have a value")
        self.assertGreater(len(input_value), 10, "Hidden input value should contain JSON data")

        # Parse and verify the JSON
        data = json.loads(input_value)
        self.assertIn("segments", data, "Data should contain segments key")
        self.assertEqual(len(data["segments"]), 1, "Should have 1 segment in data")

    def test_segment_persisted_after_navigation(self):
        """Test that segments are preserved when navigating away and back."""
        # Clean up any previous annotation output
        import shutil
        annotation_dir = os.path.join(self.test_output_dir, "annotation_output")
        if os.path.exists(annotation_dir):
            shutil.rmtree(annotation_dir)
            os.makedirs(annotation_dir)

        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(3)

        # Wait for video annotation container
        self._wait_for_video_container()
        self._wait_for_video_loaded()

        # Get initial instance ID
        first_instance_id = self._get_current_instance_id()
        self.assertIsNotNone(first_instance_id, "Should have an instance ID")
        print(f"[TEST] Initial instance ID: {first_instance_id}")

        # Create a segment
        self._create_segment_via_ui(label_index=0)

        # Verify segment was created
        self.assertEqual(self._get_segment_count(), 1, "Should have 1 segment")

        # Store the hidden input value before navigation
        saved_value_before = self._get_hidden_input_value()
        self.assertIsNotNone(saved_value_before, "Should have saved data before navigation")
        print(f"[TEST] Hidden input value before navigation: {saved_value_before[:100]}...")

        # Navigate to next instance
        print("[TEST] Navigating to next instance...")
        self._navigate_to_next()

        # Wait for new page to load
        time.sleep(3)
        self._wait_for_video_container()
        time.sleep(2)

        # Verify we're on a different instance
        second_instance_id = self._get_current_instance_id()
        print(f"[TEST] Second instance ID: {second_instance_id}")
        self.assertNotEqual(first_instance_id, second_instance_id,
                          "Should be on a different instance after navigation")

        # Debug: Check hidden input value on second instance
        second_input_value = self._get_hidden_input_value()
        print(f"[TEST] Second instance hidden input value: {second_input_value[:100] if second_input_value else 'EMPTY'}...")

        # Debug: Check segment count
        second_segment_count = self._get_segment_count()
        print(f"[TEST] Second instance segment count: {second_segment_count}")

        # Verify segment count is 0 on new instance
        self.assertEqual(second_segment_count, 0,
                        "New instance should have 0 segments")

        # Navigate back to first instance
        print("[TEST] Navigating back to first instance...")
        self._navigate_to_previous()

        # Wait for page to fully load after navigation
        time.sleep(4)

        # Set up console capture for debugging
        self._setup_console_capture()
        time.sleep(2)  # Wait for any async operations

        # Check what instance we're on now
        current_instance_after_back = self._get_current_instance_id()
        print(f"[TEST] Instance ID after navigating back: {current_instance_after_back}")

        # Wait for video annotation container
        try:
            self._wait_for_video_container(timeout=20)
        except TimeoutException:
            # Debug output
            print(f"[TEST] Page URL: {self.driver.current_url}")
            print(f"[TEST] Page title: {self.driver.title}")
            print(f"[TEST] Page source sample: {self.driver.page_source[:2000]}")
            raise

        # Wait for video to load
        try:
            self._wait_for_video_loaded(timeout=20)
        except:
            print("[TEST] Video did not load, but continuing with test...")

        time.sleep(2)

        # Verify we're back on first instance
        restored_instance_id = self._get_current_instance_id()
        self.assertEqual(first_instance_id, restored_instance_id,
                        "Should be back on the first instance")

        # Check hidden input value after returning
        restored_value = self._get_hidden_input_value()
        print(f"[TEST] Hidden input value after returning: {restored_value[:100] if restored_value else 'EMPTY'}...")

        # Print browser console logs for debugging
        console_logs = self._get_browser_logs()
        print(f"[TEST] Browser console logs ({len(console_logs)} entries):")
        for log in console_logs[-20:]:  # Last 20 logs
            if 'VideoAnnotation' in str(log):
                print(f"  {log}")

        # CRITICAL: Verify segment was restored
        restored_count = self._get_segment_count()
        print(f"[TEST] Segment count after returning: {restored_count}")
        self.assertEqual(restored_count, 1,
                        "Segment should be restored after navigating back")

        # Verify hidden input has the restored data
        self.assertIsNotNone(restored_value, "Hidden input should have restored data")

        # Parse and verify the restored data
        restored_data = json.loads(restored_value)
        self.assertIn("segments", restored_data, "Restored data should contain segments")
        self.assertEqual(len(restored_data["segments"]), 1,
                        "Should have 1 segment in restored data")

    def test_multiple_segments_persisted(self):
        """Test that multiple segments are all preserved."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(3)

        self._wait_for_video_container()
        self._wait_for_video_loaded()

        # Create first segment with label A
        self._create_segment_via_ui(label_index=0)
        self.assertEqual(self._get_segment_count(), 1)

        # Seek video forward
        self.driver.execute_script("""
            var video = document.querySelector('.video-element');
            if (video) video.currentTime = 5;
        """)
        time.sleep(0.5)

        # Create second segment with label B
        self._create_segment_via_ui(label_index=1)
        self.assertEqual(self._get_segment_count(), 2)

        # Navigate away and back
        self._navigate_to_next()
        time.sleep(2)
        self._navigate_to_previous()
        time.sleep(2)

        self._wait_for_video_container()
        self._wait_for_video_loaded()

        # Verify both segments were restored
        restored_count = self._get_segment_count()
        self.assertEqual(restored_count, 2,
                        "Both segments should be restored")

    def test_annotation_list_shows_restored_segments(self):
        """Test that the annotation list UI shows restored segments."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(3)

        self._wait_for_video_container()
        self._wait_for_video_loaded()

        # Create a segment
        self._create_segment_via_ui(label_index=0)

        # Verify annotation list has the segment
        annotation_list = self.driver.find_element(By.CSS_SELECTOR, ".annotation-list")
        items_before = annotation_list.find_elements(By.CSS_SELECTOR, ".annotation-item")
        self.assertEqual(len(items_before), 1, "Annotation list should show 1 item")

        # Navigate away and back
        self._navigate_to_next()
        time.sleep(2)
        self._navigate_to_previous()
        time.sleep(2)

        self._wait_for_video_container()
        self._wait_for_video_loaded()

        # Verify annotation list still shows the segment
        annotation_list = self.driver.find_element(By.CSS_SELECTOR, ".annotation-list")
        items_after = annotation_list.find_elements(By.CSS_SELECTOR, ".annotation-item")
        self.assertEqual(len(items_after), 1,
                        "Annotation list should show restored segment")


class TestVideoAnnotationPersistenceChrome(TestVideoAnnotationPersistence):
    """Run video annotation persistence tests on Chrome."""

    def setUp(self):
        """Set up Chrome WebDriver."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)


if __name__ == "__main__":
    unittest.main()
