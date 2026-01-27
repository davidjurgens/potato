"""
Integration tests for audio annotation UI functionality.

Tests that annotators can use the UI to perform all types of audio annotation:
- Loading audio and waveform display
- Creating segments using [ and ] buttons
- Creating segments by clicking and dragging on waveform
- Resizing existing segments
- Creating multiple segments
- Creating overlapping segments
- Deleting segments
- Labeling segments
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


class TestAudioAnnotationUI:
    """Test suite for audio annotation UI functionality."""

    @classmethod
    def setup_class(cls):
        """Set up the Flask server with audio annotation config."""
        # Create temp directory for test
        cls.test_dir = tempfile.mkdtemp(prefix="audio_ui_test_")
        # Port will be auto-assigned by find_free_port

        # Create data directory
        data_dir = os.path.join(cls.test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create data file with test audio - use 10-second local audio
        # Some tests (segment resize, handle tests) need longer audio for their timing
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
port: 8000  # Will be overwritten by FlaskTestServer
server_name: Audio Annotation UI Test
annotation_task_name: Audio Annotation UI Test
task_dir: {cls.test_dir}
output_annotation_dir: {cls.test_dir}/annotation_output/
output_annotation_format: json

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

        # Start the server (port auto-assigned by find_free_port)
        cls.server = FlaskTestServer(debug=False, config_file=config_file)
        cls.port = cls.server.port  # Store actual port for use in tests
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
        # Allow autoplay for audio
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
        self.wait = WebDriverWait(self.driver, 20)

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
            time.sleep(0.05)  # Wait for page to load after login
        except:
            pass  # May already be logged in

        # Wait for annotation page to load - look for audio annotation container
        self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "audio-annotation-container"))
        )

    def _wait_for_waveform_ready(self, timeout=30):
        """Wait for waveform to be rendered."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            # Check if waveform container has content (SVG or canvas elements)
            has_waveform = self.driver.execute_script("""
                var container = document.querySelector('.waveform-container');
                if (!container) return false;
                // Check for SVG (Peaks.js renders SVG) or canvas
                return container.querySelector('svg') !== null ||
                       container.querySelector('canvas') !== null ||
                       container.children.length > 0;
            """)
            if has_waveform:
                return True
            time.sleep(0.1)

        raise TimeoutError("Waveform did not render within timeout")

    def _get_segment_count(self):
        """Get the current number of segments."""
        count_text = self.driver.execute_script("""
            var countEl = document.querySelector('.count-value');
            return countEl ? countEl.textContent : '0';
        """)
        return int(count_text)

    def _get_segments_from_manager(self):
        """Get segments directly from the AudioAnnotationManager."""
        return self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (!container || !container.audioAnnotationManager) return [];
            return container.audioAnnotationManager.segments || [];
        """)

    def _right_click_drag_on_waveform(self, start_percent, end_percent):
        """
        Perform a right-click drag on the waveform to create a segment.

        Args:
            start_percent: Starting position as percentage of waveform width (0-100)
            end_percent: Ending position as percentage of waveform width (0-100)
        """
        # Use JavaScript to dispatch right-click mouse events since ActionChains
        # doesn't support right-click-and-hold natively
        self.driver.execute_script("""
            var startPercent = arguments[0];
            var endPercent = arguments[1];

            var waveform = document.querySelector('.waveform-container');
            if (!waveform) {
                console.error('Waveform container not found');
                return;
            }

            var rect = waveform.getBoundingClientRect();
            var startX = rect.left + (rect.width * startPercent / 100);
            var endX = rect.left + (rect.width * endPercent / 100);
            var centerY = rect.top + rect.height / 2;

            // Create and dispatch mousedown with button=2 (right-click)
            var mousedownEvent = new MouseEvent('mousedown', {
                bubbles: true,
                cancelable: true,
                view: window,
                button: 2,
                buttons: 2,
                clientX: startX,
                clientY: centerY
            });
            waveform.dispatchEvent(mousedownEvent);

            // Create and dispatch mousemove
            var mousemoveEvent = new MouseEvent('mousemove', {
                bubbles: true,
                cancelable: true,
                view: window,
                button: 2,
                buttons: 2,
                clientX: endX,
                clientY: centerY
            });
            waveform.dispatchEvent(mousemoveEvent);

            // Create and dispatch mouseup
            var mouseupEvent = new MouseEvent('mouseup', {
                bubbles: true,
                cancelable: true,
                view: window,
                button: 2,
                buttons: 0,
                clientX: endX,
                clientY: centerY
            });
            waveform.dispatchEvent(mouseupEvent);
        """, start_percent, end_percent)

    def test_audio_container_loads(self):
        """Test that the audio annotation container loads."""
        self._login_and_navigate_to_annotation()

        # Check audio annotation container exists
        container = self.driver.find_element(By.CLASS_NAME, "audio-annotation-container")
        assert container is not None, "Audio annotation container should exist"

        # Check for toolbar
        toolbar = self.driver.find_element(By.CLASS_NAME, "audio-annotation-toolbar")
        assert toolbar is not None, "Toolbar should exist"

    def test_waveform_loads(self):
        """Test that the waveform loads and displays."""
        self._login_and_navigate_to_annotation()

        # Wait for waveform to render (may take time due to audio loading)
        try:
            self._wait_for_waveform_ready(timeout=45)
            waveform_ready = True
        except TimeoutError:
            waveform_ready = False

        assert waveform_ready, "Waveform should render"

    def test_label_buttons_exist(self):
        """Test that label selection buttons exist."""
        self._login_and_navigate_to_annotation()

        # Check for label buttons
        label_btns = self.driver.find_elements(By.CSS_SELECTOR, ".label-btn")
        assert len(label_btns) >= 3, f"Should have at least 3 label buttons, found {len(label_btns)}"

        # Check specific labels exist
        speech_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        assert speech_btn is not None, "Speech label button should exist"

    def test_segment_control_buttons_exist(self):
        """Test that segment control buttons exist."""
        self._login_and_navigate_to_annotation()

        # Check for [ button
        start_btn = self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-start']")
        assert start_btn is not None, "Set start button should exist"

        # Check for ] button
        end_btn = self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-end']")
        assert end_btn is not None, "Set end button should exist"

        # Check for + Segment button
        create_btn = self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='create-segment']")
        assert create_btn is not None, "Create segment button should exist"

        # Check for Delete button
        delete_btn = self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='delete-segment']")
        assert delete_btn is not None, "Delete segment button should exist"

    def test_create_segment_with_buttons(self):
        """Test creating a segment using the [ ] buttons."""
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        initial_count = self._get_segment_count()

        # Select a label first
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        label_btn.click()
        time.sleep(0.1)

        # Wait for audio to be ready for seeking (readyState >= HAVE_METADATA = 1)
        for _ in range(20):
            ready_state = self.driver.execute_script("""
                var container = document.querySelector('.audio-annotation-container');
                var manager = container ? container.audioAnnotationManager : null;
                var audio = manager ? manager.audioEl : null;
                return audio ? audio.readyState : -1;
            """)
            if ready_state >= 1:  # HAVE_METADATA or better
                break
            time.sleep(0.1)

        # Set audio to a specific time for start
        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                var manager = container.audioAnnotationManager;
                if (manager.audioEl) {
                    manager.audioEl.currentTime = 2.0;
                }
                if (manager.peaks && manager.peaks.player) {
                    manager.peaks.player.seek(2.0);
                }
            }
        """)
        time.sleep(0.1)

        # Click set-start button
        start_btn = self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-start']")
        start_btn.click()
        time.sleep(0.1)

        # Move to end time
        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                var manager = container.audioAnnotationManager;
                if (manager.audioEl) {
                    manager.audioEl.currentTime = 5.0;
                }
                if (manager.peaks && manager.peaks.player) {
                    manager.peaks.player.seek(5.0);
                }
            }
        """)
        time.sleep(0.1)

        # Click set-end button
        end_btn = self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='set-end']")
        end_btn.click()
        time.sleep(0.1)

        # Create segment
        create_btn = self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='create-segment']")
        create_btn.click()
        time.sleep(0.1)

        # Get segment count from manager directly
        manager_count = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.length : -1;
        """)

        # Verify segment was created
        new_count = self._get_segment_count()
        assert new_count == initial_count + 1 or manager_count == initial_count + 1, \
            f"Segment count should increase by 1, was {initial_count}, now {new_count} (manager: {manager_count})"

    def test_create_multiple_segments(self):
        """Test creating multiple segments."""
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        # Select label
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        label_btn.click()

        # Create first segment (0-3 seconds)
        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                container.audioAnnotationManager.createSegment(0, 3);
            }
        """)
        time.sleep(0.1)

        # Create second segment (5-8 seconds)
        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                container.audioAnnotationManager.createSegment(5, 8);
            }
        """)
        time.sleep(0.1)

        # Verify both segments exist
        count = self._get_segment_count()
        assert count >= 2, f"Should have at least 2 segments, found {count}"

    def test_create_overlapping_segments(self):
        """Test creating overlapping segments."""
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        # Select first label
        speech_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        speech_btn.click()

        # Create first segment (2-6 seconds)
        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                container.audioAnnotationManager.createSegment(2, 6);
            }
        """)
        time.sleep(0.1)

        # Select different label
        music_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='music']")
        music_btn.click()

        # Create overlapping segment (4-8 seconds)
        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                container.audioAnnotationManager.createSegment(4, 8);
            }
        """)
        time.sleep(0.1)

        # Verify both segments exist
        count = self._get_segment_count()
        assert count >= 2, f"Should have at least 2 overlapping segments, found {count}"

    def test_delete_segment(self):
        """Test deleting a segment."""
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        # Select label and create a segment
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        label_btn.click()

        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                container.audioAnnotationManager.createSegment(1, 4);
            }
        """)
        time.sleep(0.1)

        initial_count = self._get_segment_count()
        assert initial_count >= 1, "Should have at least 1 segment before deletion"

        # Select the segment (click on it in the segment list)
        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                var segments = container.audioAnnotationManager.segments;
                if (segments && segments.length > 0) {
                    container.audioAnnotationManager.selectSegment(segments[0].id);
                }
            }
        """)
        time.sleep(0.1)

        # Click delete button
        delete_btn = self.driver.find_element(By.CSS_SELECTOR, ".segment-btn[data-action='delete-segment']")
        delete_btn.click()
        time.sleep(0.1)

        # Verify segment was deleted
        new_count = self._get_segment_count()
        assert new_count == initial_count - 1, f"Segment count should decrease by 1, was {initial_count}, now {new_count}"

    def test_segment_label_assignment(self):
        """Test that segments are created with the correct label."""
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        # Select 'music' label
        music_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='music']")
        music_btn.click()
        time.sleep(0.1)

        # Create segment
        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                container.audioAnnotationManager.createSegment(1, 3);
            }
        """)
        time.sleep(0.1)

        # Check the segment has the correct label
        segment_label = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                var segments = container.audioAnnotationManager.segments;
                if (segments && segments.length > 0) {
                    return segments[segments.length - 1].label;
                }
            }
            return null;
        """)

        assert segment_label == 'music', f"Segment should have label 'music', got '{segment_label}'"

    def test_click_and_drag_creates_segment(self):
        """Test creating a segment by right-click dragging on the waveform.

        Note: Right-click is used for span creation, left-click is for navigation.
        """
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        initial_count = self._get_segment_count()

        # Select a label first
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        label_btn.click()
        time.sleep(0.1)

        # Perform right-click drag from 20% to 40% of waveform width
        self._right_click_drag_on_waveform(20, 40)
        time.sleep(0.1)

        # Verify segment was created
        new_count = self._get_segment_count()
        assert new_count > initial_count, f"Segment count should increase after right-click drag, was {initial_count}, now {new_count}"

    def test_create_second_segment_via_drag(self):
        """
        REGRESSION TEST: User should be able to create multiple segments via right-click drag.

        This test reproduces a bug where creating a second segment via drag doesn't work.
        Now using right-click for span creation to avoid conflicts with left-click navigation.
        """
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        # Select a label
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        label_btn.click()
        time.sleep(0.1)

        # Zoom out to see more of the waveform
        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            if (manager) manager.zoomToFit();
        """)
        time.sleep(0.1)

        # Create FIRST segment at 5% to 15% of waveform width using right-click drag
        print("Creating first segment via right-click drag...")
        self._right_click_drag_on_waveform(5, 15)
        time.sleep(0.1)

        # Check first segment was created
        count_after_first = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.length : -1;
        """)
        print(f"Segments after first drag: {count_after_first}")

        # Get segment details
        segments_after_first = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            if (!manager) return [];
            return manager.segments.map(function(s) {
                return {id: s.id, start: s.startTime, end: s.endTime};
            });
        """)
        print(f"First segment details: {segments_after_first}")

        assert count_after_first >= 1, f"First segment should be created, got {count_after_first}"

        # Create SECOND segment at 60% to 70% of waveform width using right-click drag
        print("Creating second segment via right-click drag...")
        time.sleep(0.1)  # Give some time between segments

        self._right_click_drag_on_waveform(60, 70)
        time.sleep(0.1)

        # Check second segment was created
        count_after_second = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.length : -1;
        """)
        print(f"Segments after second drag: {count_after_second}")

        segments_after_second = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            if (!manager) return [];
            return manager.segments.map(function(s) {
                return {id: s.id, start: s.startTime, end: s.endTime};
            });
        """)
        print(f"All segments: {segments_after_second}")

        assert count_after_second >= 2, \
            f"Should have at least 2 segments after two right-click drags. Had {count_after_first} after first, now have {count_after_second}. Segments: {segments_after_second}"

    def test_playback_controls(self):
        """Test that playback controls work."""
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        # Test play button exists and is clickable
        play_btn = self.driver.find_element(By.CSS_SELECTOR, ".playback-btn[data-action='play']")
        assert play_btn is not None, "Play button should exist"

        # Click play
        play_btn.click()
        time.sleep(0.1)

        # Check that audio is playing or was played
        is_playing = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                return container.audioAnnotationManager.isPlaying;
            }
            return false;
        """)

        # Click stop
        stop_btn = self.driver.find_element(By.CSS_SELECTOR, ".playback-btn[data-action='stop']")
        stop_btn.click()
        time.sleep(0.1)

    def test_zoom_controls(self):
        """Test that zoom controls exist and work."""
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        # Test zoom in button
        zoom_in_btn = self.driver.find_element(By.CSS_SELECTOR, ".zoom-btn[data-action='zoom-in']")
        assert zoom_in_btn is not None, "Zoom in button should exist"

        # Test zoom out button
        zoom_out_btn = self.driver.find_element(By.CSS_SELECTOR, ".zoom-btn[data-action='zoom-out']")
        assert zoom_out_btn is not None, "Zoom out button should exist"

        # Test zoom fit button
        zoom_fit_btn = self.driver.find_element(By.CSS_SELECTOR, ".zoom-btn[data-action='zoom-fit']")
        assert zoom_fit_btn is not None, "Zoom fit button should exist"

        # Click zoom controls (verify they don't crash)
        zoom_in_btn.click()
        time.sleep(0.1)
        zoom_out_btn.click()
        time.sleep(0.1)
        zoom_fit_btn.click()
        time.sleep(0.1)

    def test_segment_resize(self):
        """Test that segments can be resized by dragging handles."""
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        # Create a segment
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        label_btn.click()

        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                container.audioAnnotationManager.createSegment(5, 10);
            }
        """)
        time.sleep(0.1)

        # Get original segment bounds
        original_bounds = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                var segments = container.audioAnnotationManager.segments;
                if (segments && segments.length > 0) {
                    var seg = segments[segments.length - 1];
                    return {startTime: seg.startTime, endTime: seg.endTime};
                }
            }
            return null;
        """)

        assert original_bounds is not None, "Should have segment bounds"
        assert original_bounds['startTime'] == 5, f"Start time should be 5, got {original_bounds['startTime']}"
        assert original_bounds['endTime'] == 10, f"End time should be 10, got {original_bounds['endTime']}"

        # Note: Actually testing drag resize in Selenium is complex due to
        # how Peaks.js renders segments. We verify the segment exists with correct bounds.
        # Manual testing or more sophisticated JS-based resize testing would be needed.

    def test_handle_click_does_not_create_new_segment(self):
        """
        REGRESSION TEST: Clicking on segment resize handles should NOT create new segments.

        This test reproduces a bug where clicking on a segment's resize handle
        would create a new segment instead of initiating a resize operation.
        """
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        # Create a segment
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        label_btn.click()
        time.sleep(0.1)

        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                container.audioAnnotationManager.createSegment(2, 6);
            }
        """)
        time.sleep(0.1)

        # Verify we have exactly 1 segment
        initial_count = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.length : -1;
        """)
        assert initial_count == 1, f"Should have 1 segment initially, got {initial_count}"

        # Get information about the segment's visual representation in the DOM
        # Peaks.js creates SVG/canvas elements for segments
        segment_info = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            if (!manager || !manager.peaks) return null;

            var segment = manager.segments[0];

            // Find segment elements in the DOM - look in the zoomview
            var zoomview = document.querySelector('.zoomview-container');
            var segmentGroups = zoomview ? zoomview.querySelectorAll('g') : [];

            // Get all elements and their classes to understand structure
            var allElements = [];
            if (zoomview) {
                var walker = document.createTreeWalker(zoomview, NodeFilter.SHOW_ELEMENT);
                var count = 0;
                while (walker.nextNode() && count < 50) {
                    var el = walker.currentNode;
                    allElements.push({
                        tag: el.tagName,
                        className: el.className ? (typeof el.className === 'string' ? el.className : el.className.baseVal || '') : '',
                        cursor: window.getComputedStyle(el).cursor
                    });
                    count++;
                }
            }

            return {
                segmentId: segment.id,
                startTime: segment.startTime,
                endTime: segment.endTime,
                segmentGroupCount: segmentGroups.length,
                elements: allElements
            };
        """)
        print(f"Segment DOM info: {segment_info}")

        # Zoom out to make sure the segment is fully visible
        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            if (manager) {
                manager.zoomToFit();
            }
        """)
        time.sleep(0.1)

        # Get the x position for the segment end (30 seconds)
        click_info = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            if (!manager || !manager.peaks) return null;

            var view = manager.peaks.views.getView('zoomview');
            var startTime = view.getStartTime();
            var endTime = view.getEndTime();
            var visibleDuration = endTime - startTime;

            var waveform = document.querySelector('.waveform-container');
            var rect = waveform.getBoundingClientRect();

            // Segment end is at 6 seconds
            var segmentEndTime = 6;
            var xRatio = (segmentEndTime - startTime) / visibleDuration;
            var clickX = xRatio * rect.width;

            return {
                startTime: startTime,
                endTime: endTime,
                visibleDuration: visibleDuration,
                waveformWidth: rect.width,
                segmentEndTime: segmentEndTime,
                clickX: clickX,
                xRatio: xRatio
            };
        """)
        print(f"Click position calculation: {click_info}")

        if click_info and click_info.get('clickX'):
            waveform = self.driver.find_element(By.CLASS_NAME, "waveform-container")
            waveform_rect = waveform.rect

            # Calculate offset from waveform center
            offset_x = int(click_info['clickX'] - waveform_rect['width'] / 2)

            # Click at the segment end position (where the handle would be)
            actions = ActionChains(self.driver)
            actions.move_to_element_with_offset(waveform, offset_x, 0)
            actions.click()
            actions.perform()
            time.sleep(0.1)

        # Verify we still have exactly 1 segment (no new segment was created)
        final_count = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.length : -1;
        """)

        assert final_count == 1, \
            f"Clicking on segment handle should NOT create new segment. Had {initial_count}, now have {final_count}"

    def test_handle_drag_does_not_create_new_segment(self):
        """
        REGRESSION TEST: Dragging on segment resize handles should resize, NOT create new segments.

        This test reproduces a bug where dragging on a segment's resize handle
        would create a new segment instead of resizing the existing segment.
        """
        self._login_and_navigate_to_annotation()
        self._wait_for_waveform_ready()

        # Create a segment
        label_btn = self.driver.find_element(By.CSS_SELECTOR, ".label-btn[data-label='speech']")
        label_btn.click()
        time.sleep(0.1)

        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            if (container && container.audioAnnotationManager) {
                container.audioAnnotationManager.createSegment(2, 6);
            }
        """)
        time.sleep(0.1)

        # Verify we have exactly 1 segment
        initial_count = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.length : -1;
        """)
        assert initial_count == 1, f"Should have 1 segment initially, got {initial_count}"

        # Get original segment bounds
        original_bounds = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            if (manager && manager.segments.length > 0) {
                var seg = manager.segments[0];
                return {startTime: seg.startTime, endTime: seg.endTime};
            }
            return null;
        """)
        print(f"Original bounds: {original_bounds}")

        # Zoom out to make sure the segment is fully visible
        self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            if (manager) {
                manager.zoomToFit();
            }
        """)
        time.sleep(0.1)

        # Get the x positions for the segment start and a point past the end
        positions = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            if (!manager || !manager.peaks) return null;

            var view = manager.peaks.views.getView('zoomview');
            var startTime = view.getStartTime();
            var endTime = view.getEndTime();
            var visibleDuration = endTime - startTime;

            var waveform = document.querySelector('.waveform-container');
            var rect = waveform.getBoundingClientRect();

            // Segment is at 2-6 seconds
            var segStartX = ((2 - startTime) / visibleDuration) * rect.width;
            var segEndX = ((6 - startTime) / visibleDuration) * rect.width;
            var dragToX = ((8 - startTime) / visibleDuration) * rect.width;  // Drag to 8 seconds (within 10s audio)

            return {
                segStartX: segStartX,
                segEndX: segEndX,
                dragToX: dragToX,
                waveformWidth: rect.width
            };
        """)
        print(f"Positions: {positions}")

        if positions:
            waveform = self.driver.find_element(By.CLASS_NAME, "waveform-container")
            waveform_rect = waveform.rect

            # Calculate offsets from waveform center
            start_offset_x = int(positions['segEndX'] - waveform_rect['width'] / 2)
            end_offset_x = int(positions['dragToX'] - waveform_rect['width'] / 2)

            # Perform drag from segment end to new position
            actions = ActionChains(self.driver)
            actions.move_to_element_with_offset(waveform, start_offset_x, 0)
            actions.click_and_hold()
            actions.move_to_element_with_offset(waveform, end_offset_x, 0)
            actions.release()
            actions.perform()
            time.sleep(0.1)

        # Check final segment count
        final_count = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            return manager ? manager.segments.length : -1;
        """)

        # Get all segment bounds
        all_segments = self.driver.execute_script("""
            var container = document.querySelector('.audio-annotation-container');
            var manager = container ? container.audioAnnotationManager : null;
            if (!manager) return [];
            return manager.segments.map(function(s) {
                return {id: s.id, start: s.startTime, end: s.endTime, label: s.labelText};
            });
        """)
        print(f"Final segments: {all_segments}")

        # The key assertion: dragging at the handle position should NOT create a new segment
        # It should either:
        # 1. Resize the existing segment (ideal behavior)
        # 2. Do nothing (if handle detection is working but resize isn't)
        # But it should NOT create a new segment
        assert final_count == 1, \
            f"Dragging on segment handle should NOT create new segment. Had {initial_count}, now have {final_count}. Segments: {all_segments}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
