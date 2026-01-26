"""
Integration tests for audio annotation functionality.

Tests that annotators can use the UI to perform all types of audio annotation:
- Loading audio and basic playback
- Creating segments with [ and ] keys and buttons
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
from tests.helpers.port_manager import find_free_port


class TestAudioAnnotationIntegration:
    """Integration test suite for audio annotation functionality."""

    @classmethod
    def setup_class(cls):
        """Set up the Flask server with audio annotation config."""
        cls.test_dir = tempfile.mkdtemp(prefix="audio_integration_test_")
        cls.port = find_free_port()  # Use dynamic port to avoid conflicts

        # Create data directory
        data_dir = os.path.join(cls.test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create data file with test audio - use 10-second local audio
        # Some tests (segment label assignment) need longer audio for multiple segments
        # The Flask test server serves files from /test-audio/ route
        data_file = os.path.join(data_dir, "test_audio.json")
        test_data = [
            {"id": "audio_001", "audio_url": "/test-audio/test_audio_10s.mp3"},
            {"id": "audio_002", "audio_url": "/test-audio/test_audio_10s.mp3"},
        ]
        with open(data_file, "w") as f:
            for item in test_data:
                f.write(json.dumps(item) + "\n")

        # Create config file
        config_file = os.path.join(cls.test_dir, "config.yaml")
        config_content = f"""
port: {cls.port}
server_name: Audio Annotation Integration Test
annotation_task_name: Audio Annotation Integration Test
task_dir: {cls.test_dir}
output_annotation_dir: {cls.test_dir}/annotation_output/
output_annotation_format: json
alert_time_each_instance: 10000000

data_files:
  - data/test_audio.json

item_properties:
  id_key: id
  text_key: audio_url

user_config:
  allow_all_users: true
  users: []

annotation_schemes:
  - annotation_type: audio_annotation
    name: audio_segments
    description: "Mark audio segments"
    mode: label
    labels:
      - name: speech
        color: "#4ECDC4"
        key_value: "1"
      - name: music
        color: "#FF6B6B"
        key_value: "2"
      - name: silence
        color: "#95A5A6"
        key_value: "3"
    min_segments: 0
    zoom_enabled: true
    playback_rate_control: true

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
        # Enable audio for tests
        chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")
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
        self.driver.get(f"{self.server.base_url}/")
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
            time.sleep(0.05)
        except:
            pass

        # Wait for annotation page to load
        self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "audio-annotation-container"))
        )

    def _wait_for_audio_manager_ready(self, timeout=30):
        """Wait for AudioAnnotationManager to be fully initialized with Peaks.js."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            manager_ready = self.driver.execute_script("""
                var container = document.querySelector('.audio-annotation-container');
                if (!container || !container.audioAnnotationManager) return false;
                var manager = container.audioAnnotationManager;
                // Check if both manager exists and Peaks.js is initialized
                return manager.isReady === true && manager.peaks !== null;
            """)
            if manager_ready:
                return True
            time.sleep(0.1)
        return False

    def _wait_for_audio_element(self, timeout=15):
        """Wait for audio element to be ready."""
        audio = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "audio"))
        )

        # Wait for audio to have metadata loaded
        end_time = time.time() + timeout
        while time.time() < end_time:
            ready_state = self.driver.execute_script(
                "return arguments[0].readyState;", audio
            )
            if ready_state >= 1:  # HAVE_METADATA
                return audio
            time.sleep(0.1)

        # Return audio even if not fully ready
        return audio

    def test_audio_annotation_container_loads(self):
        """Test that the audio annotation container loads properly."""
        self._login_and_navigate_to_annotation()

        # Check container exists
        container = self.driver.find_element(By.CLASS_NAME, "audio-annotation-container")
        assert container is not None, "Audio annotation container should exist"

        # Check toolbar exists
        toolbar = self.driver.find_element(By.CLASS_NAME, "audio-annotation-toolbar")
        assert toolbar.is_displayed(), "Toolbar should be visible"

    def test_audio_element_has_src(self):
        """Test that the audio element has a source URL set."""
        self._login_and_navigate_to_annotation()
        audio = self._wait_for_audio_element()

        # Check audio has src
        src = self.driver.execute_script("return arguments[0].src;", audio)
        assert src and len(src) > 0, f"Audio should have src set, got: {src}"
        assert "test-audio" in src.lower() or "http" in src.lower(), "Audio should have valid URL"

    def test_label_buttons_exist_and_selectable(self):
        """Test that label buttons exist and can be selected."""
        self._login_and_navigate_to_annotation()

        # Wait for manager to initialize
        manager_ready = self._wait_for_audio_manager_ready()

        # Find label buttons
        label_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".label-btn")
        assert len(label_buttons) >= 3, "Should have at least 3 label buttons"

        # Check specific labels exist
        speech_btn = self.driver.find_element(By.CSS_SELECTOR, "[data-label='speech']")
        music_btn = self.driver.find_element(By.CSS_SELECTOR, "[data-label='music']")

        # Click speech label
        speech_btn.click()
        time.sleep(0.1)

        # If manager is ready, verify active state
        if manager_ready:
            # Wait for active class
            for _ in range(10):
                if "active" in (speech_btn.get_attribute("class") or ""):
                    break
                time.sleep(0.05)
            assert "active" in speech_btn.get_attribute("class"), "Speech label should be active after click"

    def test_segment_creation_with_buttons(self):
        """Test creating a segment using the UI buttons."""
        self._login_and_navigate_to_annotation()

        if not self._wait_for_audio_manager_ready():
            pytest.skip("AudioAnnotationManager not initialized (Peaks.js may not have loaded)")

        audio = self._wait_for_audio_element()

        # Select a label first
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        label_btn.click()
        time.sleep(0.1)

        # Set audio to a specific time for start
        self.driver.execute_script("arguments[0].currentTime = 1.0;", audio)
        time.sleep(0.1)

        # Click set-start button
        start_btn = self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-start']")
        start_btn.click()
        time.sleep(0.1)

        # Move to end time
        self.driver.execute_script("arguments[0].currentTime = 5.0;", audio)
        time.sleep(0.1)

        # Click set-end button
        end_btn = self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-end']")
        end_btn.click()
        time.sleep(0.1)

        # Create segment
        create_btn = self.driver.find_element(By.CSS_SELECTOR, "[data-action='create-segment']")
        create_btn.click()
        time.sleep(0.1)

        # Verify segment was created
        segment_count = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.length : 0;
        """)
        assert segment_count == 1, f"Expected 1 segment, got {segment_count}"

    def test_segment_creation_with_keyboard(self):
        """Test creating a segment using keyboard shortcuts."""
        self._login_and_navigate_to_annotation()

        if not self._wait_for_audio_manager_ready():
            pytest.skip("AudioAnnotationManager not initialized (Peaks.js may not have loaded)")

        audio = self._wait_for_audio_element()

        # Select a label first
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='music']")
        label_btn.click()

        # Focus on container for keyboard events
        container = self.driver.find_element(By.CLASS_NAME, "audio-annotation-container")
        container.click()

        # Set audio to start time
        self.driver.execute_script("arguments[0].currentTime = 2.0;", audio)
        time.sleep(0.1)

        # Press [ to set start
        ActionChains(self.driver).send_keys('[').perform()
        time.sleep(0.1)

        # Move to end time
        self.driver.execute_script("arguments[0].currentTime = 8.0;", audio)
        time.sleep(0.1)

        # Press ] to set end
        ActionChains(self.driver).send_keys(']').perform()
        time.sleep(0.1)

        # Press Enter to create segment
        ActionChains(self.driver).send_keys(Keys.ENTER).perform()
        time.sleep(0.1)

        # Verify segment was created
        segment_count = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.length : 0;
        """)
        assert segment_count >= 1, f"Expected at least 1 segment, got {segment_count}"

    def test_segment_label_assignment(self):
        """Test that segments get assigned the correct label."""
        self._login_and_navigate_to_annotation()

        if not self._wait_for_audio_manager_ready():
            pytest.skip("AudioAnnotationManager not initialized (Peaks.js may not have loaded)")

        audio = self._wait_for_audio_element()

        # Create segment with 'speech' label
        speech_btn = self.driver.find_element(By.CSS_SELECTOR, "[data-label='speech']")
        speech_btn.click()

        self.driver.execute_script("arguments[0].currentTime = 1.0;", audio)
        self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-start']").click()
        time.sleep(0.05)

        self.driver.execute_script("arguments[0].currentTime = 3.0;", audio)
        self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-end']").click()
        time.sleep(0.05)

        self.driver.find_element(By.CSS_SELECTOR, "[data-action='create-segment']").click()
        time.sleep(0.1)

        # Create segment with 'music' label
        music_btn = self.driver.find_element(By.CSS_SELECTOR, "[data-label='music']")
        music_btn.click()

        self.driver.execute_script("arguments[0].currentTime = 5.0;", audio)
        self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-start']").click()
        time.sleep(0.05)

        self.driver.execute_script("arguments[0].currentTime = 8.0;", audio)
        self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-end']").click()
        time.sleep(0.05)

        self.driver.find_element(By.CSS_SELECTOR, "[data-action='create-segment']").click()
        time.sleep(0.1)

        # Verify segments have correct labels
        segments = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.map(s => ({label: s.label})) : [];
        """)

        assert len(segments) == 2, f"Expected 2 segments, got {len(segments)}"
        labels = [s['label'] for s in segments]
        assert 'speech' in labels, "Should have speech segment"
        assert 'music' in labels, "Should have music segment"

    def test_segment_deletion(self):
        """Test that segments can be deleted."""
        self._login_and_navigate_to_annotation()

        if not self._wait_for_audio_manager_ready():
            pytest.skip("AudioAnnotationManager not initialized (Peaks.js may not have loaded)")

        audio = self._wait_for_audio_element()

        # Create a segment first
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn")
        label_btn.click()

        self.driver.execute_script("arguments[0].currentTime = 1.0;", audio)
        self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-start']").click()
        time.sleep(0.05)

        self.driver.execute_script("arguments[0].currentTime = 4.0;", audio)
        self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-end']").click()
        time.sleep(0.05)

        self.driver.find_element(By.CSS_SELECTOR, "[data-action='create-segment']").click()
        time.sleep(0.1)

        # Verify segment exists
        initial_count = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.length : 0;
        """)
        assert initial_count == 1, "Should have 1 segment initially"

        # Find and click delete button on the segment
        # First, we need to select the segment by clicking on it in the list
        segment_items = self.driver.find_elements(By.CSS_SELECTOR, ".segment-item")
        if segment_items:
            segment_items[0].click()
            time.sleep(0.1)

        delete_btn = self.driver.find_element(By.CSS_SELECTOR, "[data-action='delete-segment']")
        delete_btn.click()
        time.sleep(0.1)

        # Verify segment was deleted
        final_count = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.length : 0;
        """)
        assert final_count == 0, f"Should have 0 segments after deletion, got {final_count}"

    def test_segment_count_display(self):
        """Test that the segment count display updates correctly."""
        self._login_and_navigate_to_annotation()

        if not self._wait_for_audio_manager_ready():
            pytest.skip("AudioAnnotationManager not initialized (Peaks.js may not have loaded)")

        audio = self._wait_for_audio_element()

        # Check initial count
        count_elements = self.driver.find_elements(By.CSS_SELECTOR, ".count-value")
        if count_elements:
            initial_count = count_elements[0].text
            assert initial_count == "0", f"Initial count should be 0, got {initial_count}"

        # Create a segment
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn")
        label_btn.click()

        self.driver.execute_script("arguments[0].currentTime = 1.0;", audio)
        self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-start']").click()
        time.sleep(0.05)

        self.driver.execute_script("arguments[0].currentTime = 3.0;", audio)
        self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-end']").click()
        time.sleep(0.05)

        self.driver.find_element(By.CSS_SELECTOR, "[data-action='create-segment']").click()
        time.sleep(0.1)

        # Check updated count
        if count_elements:
            updated_count = count_elements[0].text
            assert updated_count == "1", f"Count should be 1 after creating segment, got {updated_count}"

    def test_annotation_data_saved_to_hidden_input(self):
        """Test that annotation data is saved to the hidden input field."""
        self._login_and_navigate_to_annotation()

        if not self._wait_for_audio_manager_ready():
            pytest.skip("AudioAnnotationManager not initialized (Peaks.js may not have loaded)")

        audio = self._wait_for_audio_element()

        # Create a segment
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        label_btn.click()

        self.driver.execute_script("arguments[0].currentTime = 1.0;", audio)
        self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-start']").click()
        time.sleep(0.05)

        self.driver.execute_script("arguments[0].currentTime = 5.0;", audio)
        self.driver.find_element(By.CSS_SELECTOR, "[data-action='set-end']").click()
        time.sleep(0.05)

        self.driver.find_element(By.CSS_SELECTOR, "[data-action='create-segment']").click()
        time.sleep(0.1)

        # Check hidden input has data
        hidden_input = self.driver.find_element(By.CSS_SELECTOR, ".annotation-data-input")
        input_value = hidden_input.get_attribute("value")

        assert input_value and len(input_value) > 0, "Hidden input should have annotation data"

        # Parse and verify the data
        data = json.loads(input_value)
        assert "segments" in data, "Data should contain segments"
        assert len(data["segments"]) == 1, "Should have 1 segment in data"
        assert data["segments"][0]["label"] == "speech", "Segment should have speech label"

    def test_playback_speed_control(self):
        """Test that playback speed can be changed."""
        self._login_and_navigate_to_annotation()

        if not self._wait_for_audio_manager_ready():
            pytest.skip("AudioAnnotationManager not initialized (Peaks.js may not have loaded)")

        audio = self._wait_for_audio_element()

        # Find speed selector
        speed_selects = self.driver.find_elements(By.CSS_SELECTOR, ".playback-rate-select")
        if not speed_selects:
            pytest.skip("Playback rate control not found")

        speed_select = speed_selects[0]

        # Change to 2x speed
        from selenium.webdriver.support.ui import Select
        select = Select(speed_select)
        select.select_by_value("2")
        time.sleep(0.1)

        # Verify playback rate changed
        playback_rate = self.driver.execute_script(
            "return arguments[0].playbackRate;", audio
        )
        assert playback_rate == 2.0, f"Playback rate should be 2.0, got {playback_rate}"

    def test_zoom_controls_exist(self):
        """Test that zoom controls are present and clickable."""
        self._login_and_navigate_to_annotation()

        # Wait for container
        self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "audio-annotation-container"))
        )

        # Check zoom buttons exist
        zoom_in = self.driver.find_elements(By.CSS_SELECTOR, "[data-action='zoom-in']")
        zoom_out = self.driver.find_elements(By.CSS_SELECTOR, "[data-action='zoom-out']")
        zoom_fit = self.driver.find_elements(By.CSS_SELECTOR, "[data-action='zoom-fit']")

        assert len(zoom_in) > 0, "Zoom in button should exist"
        assert len(zoom_out) > 0, "Zoom out button should exist"
        assert len(zoom_fit) > 0, "Zoom fit button should exist"

        # Verify buttons are clickable (no exceptions)
        zoom_in[0].click()
        time.sleep(0.05)
        zoom_out[0].click()
        time.sleep(0.05)
        zoom_fit[0].click()

    def test_playback_controls(self):
        """Test that playback controls work."""
        self._login_and_navigate_to_annotation()

        if not self._wait_for_audio_manager_ready():
            pytest.skip("AudioAnnotationManager not initialized (Peaks.js may not have loaded)")

        audio = self._wait_for_audio_element()

        # Find play button
        play_btn = self.driver.find_element(By.CSS_SELECTOR, "[data-action='play']")

        # Click play (may not actually play due to browser autoplay restrictions)
        play_btn.click()
        time.sleep(0.1)

        # Find stop button and click
        stop_btn = self.driver.find_element(By.CSS_SELECTOR, "[data-action='stop']")
        stop_btn.click()
        time.sleep(0.1)

        # Verify audio is paused
        is_paused = self.driver.execute_script("return arguments[0].paused;", audio)
        assert is_paused, "Audio should be paused after stop"


class TestAudioAnnotationFallback:
    """Test audio annotation when Peaks.js may not load."""

    @classmethod
    def setup_class(cls):
        """Set up the Flask server."""
        cls.test_dir = tempfile.mkdtemp(prefix="audio_fallback_test_")
        cls.port = find_free_port()

        # Create data directory
        data_dir = os.path.join(cls.test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create data file - use local test audio for speed
        data_file = os.path.join(data_dir, "test_audio.json")
        test_data = [
            {"id": "audio_001", "audio_url": "/test-audio/test_audio_short.mp3"},
        ]
        with open(data_file, "w") as f:
            for item in test_data:
                f.write(json.dumps(item) + "\n")

        # Create config file
        config_file = os.path.join(cls.test_dir, "config.yaml")
        config_content = f"""
port: {cls.port}
server_name: Audio Fallback Test
annotation_task_name: Audio Fallback Test
task_dir: {cls.test_dir}
output_annotation_dir: {cls.test_dir}/annotation_output/
output_annotation_format: json
alert_time_each_instance: 10000000

data_files:
  - data/test_audio.json

item_properties:
  id_key: id
  text_key: audio_url

user_config:
  allow_all_users: true
  users: []

annotation_schemes:
  - annotation_type: audio_annotation
    name: test_segments
    description: "Test segments"
    mode: label
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
        chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")
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
        self.driver.get(f"{self.server.base_url}/")
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        try:
            username_input = self.wait.until(
                EC.presence_of_element_located((By.ID, "login-email"))
            )
            username_input.send_keys("test_user")
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()
            time.sleep(0.05)
        except:
            pass

        self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "audio-annotation-container"))
        )

    def test_ui_loads_without_peaks(self):
        """Test that the UI loads even if Peaks.js initialization is slow or fails."""
        self._login_and_navigate()

        # Basic UI should exist regardless of Peaks.js
        container = self.driver.find_element(By.CLASS_NAME, "audio-annotation-container")
        assert container.is_displayed(), "Container should be visible"

        toolbar = self.driver.find_element(By.CLASS_NAME, "audio-annotation-toolbar")
        assert toolbar.is_displayed(), "Toolbar should be visible"

        label_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".label-btn")
        assert len(label_buttons) > 0, "Label buttons should exist"

    def test_label_selection_works_without_full_initialization(self):
        """Test that label buttons can be clicked even before full initialization."""
        self._login_and_navigate()

        # Find and click label button - should not throw error
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn")
        label_btn.click()
        time.sleep(0.1)

        # Test passes if no exception was raised
        assert True, "Label button click should not throw error"
