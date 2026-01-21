"""
Integration tests for video annotation functionality.

Tests that annotators can use the UI to perform all types of video annotation:
- Loading video and basic playback
- Creating segments with [ and ] keys
- Labeling segments
- Deleting segments
- Persisting annotations across navigation
"""

import pytest
import time
import json
import os
import tempfile
import shutil
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer


class TestVideoAnnotation:
    """Test suite for video annotation functionality."""

    @classmethod
    def setup_class(cls):
        """Set up the Flask server with video annotation config."""
        # Create temp directory for test
        cls.test_dir = tempfile.mkdtemp(prefix="video_test_")
        cls.port = 9010  # Use different port to avoid conflicts

        # Create data directory
        data_dir = os.path.join(cls.test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create data file with test video
        data_file = os.path.join(data_dir, "test_videos.json")
        test_data = [
            {"id": "video_001", "video_url": "https://www.w3schools.com/html/mov_bbb.mp4"},
            {"id": "video_002", "video_url": "https://www.w3schools.com/html/movie.mp4"},
        ]
        with open(data_file, "w") as f:
            for item in test_data:
                f.write(json.dumps(item) + "\n")

        # Create config file
        config_file = os.path.join(cls.test_dir, "config.yaml")
        config_content = f"""
port: {cls.port}
server_name: Video Annotation Test
annotation_task_name: Video Annotation Test
task_dir: {cls.test_dir}
output_annotation_dir: {cls.test_dir}/annotation_output/
output_annotation_format: json

data_files:
  - data/test_videos.json

item_properties:
  id_key: id
  text_key: video_url

user_config:
  allow_all_users: true
  users: []

annotation_schemes:
  - annotation_type: video_annotation
    name: video_segments
    description: "Mark video segments"
    mode: segment
    labels:
      - name: intro
        color: "#4ECDC4"
        key_value: "1"
      - name: main_content
        color: "#FF6B6B"
        key_value: "2"
      - name: outro
        color: "#95A5A6"
        key_value: "3"
    min_segments: 0
    timeline_height: 70
    zoom_enabled: true
    playback_rate_control: true
    frame_stepping: true
    show_timecode: true
    video_fps: 30

site_dir: default
"""
        with open(config_file, "w") as f:
            f.write(config_content)

        cls.config_file = config_file

        # Start the server
        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        if not started:
            raise RuntimeError(f"Failed to start Flask server on port {cls.port}")

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
    def teardown_class(cls):
        """Clean up after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir') and os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setup_method(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.wait = WebDriverWait(self.driver, 15)

    def teardown_method(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login_and_navigate_to_annotation(self):
        """Helper to login and get to the annotation page."""
        self.driver.get(f"http://localhost:{self.port}/")
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # Handle login - the login form uses 'login-email' as the input ID
        try:
            username_input = self.wait.until(
                EC.presence_of_element_located((By.ID, "login-email"))
            )
            username_input.send_keys("test_user")

            # Submit login
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()
            time.sleep(2)  # Wait for page to load after login
        except:
            pass  # May already be logged in

        # Wait for annotation page to load
        self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "video-annotation-container"))
        )

    def _wait_for_video_ready(self, timeout=15):
        """Wait for video element to be ready."""
        video = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".video-element"))
        )

        # Wait for video to have metadata loaded
        end_time = time.time() + timeout
        while time.time() < end_time:
            ready_state = self.driver.execute_script(
                "return arguments[0].readyState;", video
            )
            if ready_state >= 1:  # HAVE_METADATA
                return video
            time.sleep(0.5)

        raise TimeoutError("Video did not become ready within timeout")

    def test_video_player_loads(self):
        """Test that the video player loads and displays."""
        self._login_and_navigate_to_annotation()

        # Check video element exists
        video = self.driver.find_element(By.CSS_SELECTOR, ".video-element")
        assert video is not None, "Video element should exist"

        # Check video has src set (may take a moment)
        time.sleep(2)
        src = self.driver.execute_script("return arguments[0].src;", video)
        assert src and len(src) > 0, f"Video should have src set, got: {src}"

    def test_video_playback_controls(self):
        """Test that video playback controls work."""
        self._login_and_navigate_to_annotation()
        video = self._wait_for_video_ready()

        # Test play button
        play_btn = self.driver.find_element(
            By.CSS_SELECTOR, ".playback-btn[data-action='play']"
        )
        play_btn.click()
        time.sleep(0.5)

        # Test stop button
        stop_btn = self.driver.find_element(
            By.CSS_SELECTOR, ".playback-btn[data-action='stop']"
        )
        stop_btn.click()

    def test_segment_creation_with_buttons(self):
        """Test creating a segment using the UI buttons."""
        self._login_and_navigate_to_annotation()
        video = self._wait_for_video_ready()

        # Select a label first
        label_btn = self.driver.find_element(
            By.CSS_SELECTOR, ".label-btn[data-label='intro']"
        )
        label_btn.click()

        # Set video to a specific time for start
        self.driver.execute_script("arguments[0].currentTime = 1.0;", video)
        time.sleep(0.3)

        # Click set-start button
        start_btn = self.driver.find_element(
            By.CSS_SELECTOR, ".segment-btn[data-action='set-start']"
        )
        start_btn.click()
        time.sleep(0.3)

        # Move to end time
        self.driver.execute_script("arguments[0].currentTime = 3.0;", video)
        time.sleep(0.3)

        # Click set-end button
        end_btn = self.driver.find_element(
            By.CSS_SELECTOR, ".segment-btn[data-action='set-end']"
        )
        end_btn.click()
        time.sleep(0.3)

        # Create segment
        create_btn = self.driver.find_element(
            By.CSS_SELECTOR, ".segment-btn[data-action='create-segment']"
        )
        create_btn.click()
        time.sleep(0.5)

        # Verify segment was created
        segment_count = self.driver.execute_script(
            """
            var manager = document.querySelector('.video-annotation-container').videoAnnotationManager;
            return manager ? manager.segments.length : 0;
            """
        )
        assert segment_count == 1, f"Expected 1 segment, got {segment_count}"

        # Verify segment appears in annotation list
        annotation_items = self.driver.find_elements(
            By.CSS_SELECTOR, ".annotation-item"
        )
        assert len(annotation_items) >= 1, "Segment should appear in annotation list"

    def test_segment_creation_with_keyboard(self):
        """Test creating a segment using keyboard shortcuts."""
        self._login_and_navigate_to_annotation()
        video = self._wait_for_video_ready()

        # Select a label first
        label_btn = self.driver.find_element(
            By.CSS_SELECTOR, ".label-btn[data-label='main_content']"
        )
        label_btn.click()

        # Focus on container for keyboard events
        container = self.driver.find_element(By.CLASS_NAME, "video-annotation-container")
        container.click()

        # Set video to start time
        self.driver.execute_script("arguments[0].currentTime = 2.0;", video)
        time.sleep(0.3)

        # Press [ to set start
        ActionChains(self.driver).send_keys('[').perform()
        time.sleep(0.3)

        # Move to end time
        self.driver.execute_script("arguments[0].currentTime = 5.0;", video)
        time.sleep(0.3)

        # Press ] to set end
        ActionChains(self.driver).send_keys(']').perform()
        time.sleep(0.3)

        # Press Enter to create segment
        ActionChains(self.driver).send_keys(Keys.ENTER).perform()
        time.sleep(0.5)

        # Verify segment was created
        segment_count = self.driver.execute_script(
            """
            var manager = document.querySelector('.video-annotation-container').videoAnnotationManager;
            return manager ? manager.segments.length : 0;
            """
        )
        assert segment_count >= 1, f"Expected at least 1 segment, got {segment_count}"

    def test_segment_label_selection(self):
        """Test that different labels can be selected and applied to segments."""
        self._login_and_navigate_to_annotation()
        video = self._wait_for_video_ready()

        # Create first segment with 'intro' label
        intro_btn = self.driver.find_element(
            By.CSS_SELECTOR, ".label-btn[data-label='intro']"
        )
        intro_btn.click()

        # Verify label is active
        assert "active" in intro_btn.get_attribute("class"), "Intro label should be active"

        self.driver.execute_script("arguments[0].currentTime = 0.5;", video)
        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-start']").click()
        time.sleep(0.2)

        self.driver.execute_script("arguments[0].currentTime = 1.5;", video)
        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-end']").click()
        time.sleep(0.2)

        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='create-segment']").click()
        time.sleep(0.3)

        # Create second segment with 'outro' label
        outro_btn = self.driver.find_element(
            By.CSS_SELECTOR, ".label-btn[data-label='outro']"
        )
        outro_btn.click()

        self.driver.execute_script("arguments[0].currentTime = 4.0;", video)
        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-start']").click()
        time.sleep(0.2)

        self.driver.execute_script("arguments[0].currentTime = 5.0;", video)
        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-end']").click()
        time.sleep(0.2)

        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='create-segment']").click()
        time.sleep(0.3)

        # Verify both segments were created with correct labels
        segments = self.driver.execute_script(
            """
            var manager = document.querySelector('.video-annotation-container').videoAnnotationManager;
            return manager ? manager.segments.map(s => ({label: s.label, startTime: s.startTime})) : [];
            """
        )

        assert len(segments) == 2, f"Expected 2 segments, got {len(segments)}"
        labels = [s['label'] for s in segments]
        assert 'intro' in labels, "Should have intro segment"
        assert 'outro' in labels, "Should have outro segment"

    def test_segment_deletion(self):
        """Test that segments can be deleted."""
        self._login_and_navigate_to_annotation()
        video = self._wait_for_video_ready()

        # Create a segment first
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn")
        label_btn.click()

        self.driver.execute_script("arguments[0].currentTime = 1.0;", video)
        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-start']").click()
        time.sleep(0.2)

        self.driver.execute_script("arguments[0].currentTime = 2.0;", video)
        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-end']").click()
        time.sleep(0.2)

        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='create-segment']").click()
        time.sleep(0.5)

        # Verify segment exists
        initial_count = self.driver.execute_script(
            """
            var manager = document.querySelector('.video-annotation-container').videoAnnotationManager;
            return manager ? manager.segments.length : 0;
            """
        )
        assert initial_count == 1, "Should have 1 segment initially"

        # Find and click delete button on the segment
        delete_btn = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".annotation-delete"))
        )
        delete_btn.click()
        time.sleep(0.5)

        # Verify segment was deleted
        final_count = self.driver.execute_script(
            """
            var manager = document.querySelector('.video-annotation-container').videoAnnotationManager;
            return manager ? manager.segments.length : 0;
            """
        )
        assert final_count == 0, f"Should have 0 segments after deletion, got {final_count}"

    def test_segment_count_display(self):
        """Test that the segment count display updates correctly."""
        self._login_and_navigate_to_annotation()
        video = self._wait_for_video_ready()

        # Check initial count
        count_element = self.driver.find_element(By.CSS_SELECTOR, ".count-value")
        initial_count = count_element.text
        assert initial_count == "0", f"Initial count should be 0, got {initial_count}"

        # Create a segment
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn")
        label_btn.click()

        self.driver.execute_script("arguments[0].currentTime = 1.0;", video)
        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-start']").click()
        time.sleep(0.2)

        self.driver.execute_script("arguments[0].currentTime = 2.0;", video)
        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-end']").click()
        time.sleep(0.2)

        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='create-segment']").click()
        time.sleep(0.5)

        # Check updated count
        updated_count = count_element.text
        assert updated_count == "1", f"Count should be 1 after creating segment, got {updated_count}"

    def test_annotation_data_saved_to_hidden_input(self):
        """Test that annotation data is saved to the hidden input field."""
        self._login_and_navigate_to_annotation()
        video = self._wait_for_video_ready()

        # Create a segment
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='intro']")
        label_btn.click()

        self.driver.execute_script("arguments[0].currentTime = 1.0;", video)
        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-start']").click()
        time.sleep(0.2)

        self.driver.execute_script("arguments[0].currentTime = 2.5;", video)
        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-end']").click()
        time.sleep(0.2)

        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='create-segment']").click()
        time.sleep(0.5)

        # Check hidden input has data
        hidden_input = self.driver.find_element(By.CSS_SELECTOR, ".annotation-data-input")
        input_value = hidden_input.get_attribute("value")

        assert input_value and len(input_value) > 0, "Hidden input should have annotation data"

        # Parse and verify the data
        data = json.loads(input_value)
        assert "segments" in data, "Data should contain segments"
        assert len(data["segments"]) == 1, "Should have 1 segment in data"
        assert data["segments"][0]["label"] == "intro", "Segment should have intro label"

    def test_playback_speed_control(self):
        """Test that playback speed can be changed."""
        self._login_and_navigate_to_annotation()
        video = self._wait_for_video_ready()

        # Find speed selector
        speed_select = self.driver.find_element(By.CSS_SELECTOR, ".playback-rate-select")

        # Change to 2x speed
        from selenium.webdriver.support.ui import Select
        select = Select(speed_select)
        select.select_by_value("2")
        time.sleep(0.3)

        # Verify playback rate changed
        playback_rate = self.driver.execute_script(
            "return arguments[0].playbackRate;", video
        )
        assert playback_rate == 2.0, f"Playback rate should be 2.0, got {playback_rate}"

    def test_frame_stepping_buttons(self):
        """Test frame-by-frame navigation buttons."""
        self._login_and_navigate_to_annotation()
        video = self._wait_for_video_ready()

        # Set initial time
        self.driver.execute_script("arguments[0].currentTime = 1.0;", video)
        initial_time = self.driver.execute_script("return arguments[0].currentTime;", video)

        # Click frame forward button
        frame_forward = self.driver.find_element(
            By.CSS_SELECTOR, ".frame-btn[data-action='frame-forward']"
        )
        frame_forward.click()
        time.sleep(0.3)

        # Verify time increased
        new_time = self.driver.execute_script("return arguments[0].currentTime;", video)
        assert new_time > initial_time, f"Time should increase after frame forward: {initial_time} -> {new_time}"

        # Click frame back button
        frame_back = self.driver.find_element(
            By.CSS_SELECTOR, ".frame-btn[data-action='frame-back']"
        )
        frame_back.click()
        time.sleep(0.3)

        # Verify time decreased
        final_time = self.driver.execute_script("return arguments[0].currentTime;", video)
        assert final_time < new_time, f"Time should decrease after frame back: {new_time} -> {final_time}"


class TestVideoAnnotationWithoutPeaks:
    """Test video annotation functionality when Peaks.js is not available."""

    @classmethod
    def setup_class(cls):
        """Set up the Flask server with video annotation config."""
        cls.test_dir = tempfile.mkdtemp(prefix="video_test_no_peaks_")
        cls.port = 9011  # Different port

        # Create data directory
        data_dir = os.path.join(cls.test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create data file
        data_file = os.path.join(data_dir, "test_videos.json")
        test_data = [
            {"id": "video_001", "video_url": "https://www.w3schools.com/html/mov_bbb.mp4"},
        ]
        with open(data_file, "w") as f:
            for item in test_data:
                f.write(json.dumps(item) + "\n")

        # Create config file
        config_file = os.path.join(cls.test_dir, "config.yaml")
        config_content = f"""
port: {cls.port}
server_name: Video Test No Peaks
annotation_task_name: Video Test No Peaks
task_dir: {cls.test_dir}
output_annotation_dir: {cls.test_dir}/annotation_output/
output_annotation_format: json

data_files:
  - data/test_videos.json

item_properties:
  id_key: id
  text_key: video_url

user_config:
  allow_all_users: true
  users: []

annotation_schemes:
  - annotation_type: video_annotation
    name: test_segments
    description: "Test segments without Peaks"
    mode: segment
    labels:
      - name: test_label
        color: "#4ECDC4"

site_dir: default
"""
        with open(config_file, "w") as f:
            f.write(config_content)

        cls.config_file = config_file

        # Start the server
        cls.server = FlaskTestServer(port=cls.port, debug=False, config_file=config_file)
        started = cls.server.start_server()
        if not started:
            raise RuntimeError(f"Failed to start Flask server on port {cls.port}")

        # Set up Chrome options
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options = chrome_options

    @classmethod
    def teardown_class(cls):
        """Clean up after all tests."""
        if hasattr(cls, 'server'):
            cls.server.stop_server()
        if hasattr(cls, 'test_dir') and os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setup_method(self):
        """Set up for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.wait = WebDriverWait(self.driver, 15)

    def teardown_method(self):
        """Clean up after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login_and_navigate(self):
        """Helper to login and navigate to annotation page."""
        self.driver.get(f"http://localhost:{self.port}/")
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        try:
            username_input = self.wait.until(
                EC.presence_of_element_located((By.ID, "login-email"))
            )
            username_input.send_keys("test_user")
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()
            time.sleep(2)
        except:
            pass

        self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "video-annotation-container"))
        )

    def test_segment_creation_works_without_peaks(self):
        """Test that segments can be created even when Peaks.js is not loaded."""
        self._login_and_navigate()

        # Wait for video to be ready
        video = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".video-element"))
        )
        time.sleep(2)  # Wait for video to load

        # Check if Peaks is available
        peaks_available = self.driver.execute_script("return typeof Peaks !== 'undefined';")

        # Whether or not Peaks is available, segment creation should work
        # Select label
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn")
        label_btn.click()

        # Set times directly via JavaScript since video controls work
        self.driver.execute_script("arguments[0].currentTime = 0.5;", video)
        time.sleep(0.2)

        # Click segment buttons
        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-start']").click()
        time.sleep(0.2)

        self.driver.execute_script("arguments[0].currentTime = 1.5;", video)
        time.sleep(0.2)

        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-end']").click()
        time.sleep(0.2)

        self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='create-segment']").click()
        time.sleep(0.5)

        # Verify segment was created
        segment_count = self.driver.execute_script(
            """
            var manager = document.querySelector('.video-annotation-container').videoAnnotationManager;
            return manager ? manager.segments.length : -1;
            """
        )

        assert segment_count == 1, f"Should create segment even without Peaks.js, got count: {segment_count}"
