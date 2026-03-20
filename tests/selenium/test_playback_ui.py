"""
Selenium UI tests for the auto-playback feature on web_agent_trace display.

Tests:
1. Playback JS is loaded (PlaybackController available on window)
2. Agent trace viewer renders with steps data
3. Playback controls appear when auto_playback is enabled
4. Play/pause button exists and is functional
5. Speed control buttons are rendered
6. Progress bar/slider is present
7. Playback does not appear when auto_playback is not set

These tests use the agent trace evaluation example with auto_playback
enabled via a modified config.
"""

import json
import os
import shutil
import time
import unittest

import yaml
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


def get_project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def create_playback_config():
    """Create a modified agent trace config with auto_playback enabled.

    Copies the agent trace evaluation example and adds playback options
    to the web_agent_trace display field.
    """
    project_root = get_project_root()
    original_config_path = os.path.join(
        project_root, "examples/agent-traces/agent-trace-evaluation/config.yaml"
    )

    with open(original_config_path, "r") as f:
        config = yaml.safe_load(f)

    # Modify the instance_display to use web_agent_trace type with playback
    # The original config uses dialogue type for conversation field.
    # We need to add a web_agent_trace field with auto_playback enabled.
    # Since the original data is dialogue-based (not screenshot-based),
    # we will create a separate data file with web_agent_trace format
    # and modify the config accordingly.

    tests_dir = os.path.join(project_root, "tests")
    test_output_dir = os.path.join(tests_dir, "output", "playback_test")
    os.makedirs(test_output_dir, exist_ok=True)
    data_dir = os.path.join(test_output_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    # Create test data with web_agent_trace format (screenshot steps)
    test_data = [
        {
            "id": "playback_trace_001",
            "task_description": "Search for climate change on Wikipedia",
            "agent_trace": {
                "steps": [
                    {
                        "step_index": 0,
                        "screenshot_url": "",
                        "action_type": "navigate",
                        "thought": "I need to go to Wikipedia first.",
                        "observation": "Page loaded successfully",
                        "coordinates": {},
                        "element": {},
                        "mouse_path": [],
                        "timestamp": 0.0,
                        "viewport": {"width": 1280, "height": 720},
                    },
                    {
                        "step_index": 1,
                        "screenshot_url": "",
                        "action_type": "click",
                        "thought": "I see the search box, let me click on it.",
                        "observation": "Search box is focused",
                        "coordinates": {"x": 640, "y": 50},
                        "element": {"tag": "input", "text": "Search"},
                        "mouse_path": [[400, 200], [640, 50]],
                        "timestamp": 1.5,
                        "viewport": {"width": 1280, "height": 720},
                    },
                    {
                        "step_index": 2,
                        "screenshot_url": "",
                        "action_type": "type",
                        "thought": "Now I will type the search query.",
                        "observation": "Text entered in search box",
                        "coordinates": {"x": 640, "y": 50},
                        "element": {"tag": "input", "text": "Search"},
                        "typed_text": "climate change",
                        "mouse_path": [],
                        "timestamp": 3.0,
                        "viewport": {"width": 1280, "height": 720},
                    },
                    {
                        "step_index": 3,
                        "screenshot_url": "",
                        "action_type": "done",
                        "thought": "Found the article, task complete.",
                        "observation": "Climate change article displayed",
                        "coordinates": {},
                        "element": {},
                        "mouse_path": [],
                        "timestamp": 5.0,
                        "viewport": {"width": 1280, "height": 720},
                    },
                ],
                "task_description": "Search for climate change on Wikipedia",
                "site": "wikipedia.org",
            },
        },
        {
            "id": "playback_trace_002",
            "task_description": "Find Python download page",
            "agent_trace": {
                "steps": [
                    {
                        "step_index": 0,
                        "screenshot_url": "",
                        "action_type": "navigate",
                        "thought": "Going to python.org.",
                        "observation": "Page loaded",
                        "coordinates": {},
                        "element": {},
                        "mouse_path": [],
                        "timestamp": 0.0,
                        "viewport": {"width": 1280, "height": 720},
                    },
                    {
                        "step_index": 1,
                        "screenshot_url": "",
                        "action_type": "click",
                        "thought": "Click on Downloads tab.",
                        "observation": "Downloads page opened",
                        "coordinates": {"x": 300, "y": 80},
                        "element": {"tag": "a", "text": "Downloads"},
                        "mouse_path": [[100, 100], [300, 80]],
                        "timestamp": 2.0,
                        "viewport": {"width": 1280, "height": 720},
                    },
                ],
                "task_description": "Find Python download page",
                "site": "python.org",
            },
        },
    ]

    data_file = os.path.join(data_dir, "playback-traces.json")
    with open(data_file, "w") as f:
        for item in test_data:
            f.write(json.dumps(item) + "\n")

    # Build the config for playback testing
    playback_config = {
        "annotation_task_name": "Playback Test",
        "data_files": ["data/playback-traces.json"],
        "item_properties": {"id_key": "id", "text_key": "task_description"},
        "task_dir": test_output_dir,
        "output_annotation_dir": os.path.join(test_output_dir, "annotation_output"),
        "output_annotation_format": "json",
        "instance_display": {
            "layout": {"direction": "vertical", "gap": "16px"},
            "fields": [
                {"key": "task_description", "type": "text", "label": "Task"},
                {
                    "key": "agent_trace",
                    "type": "web_agent_trace",
                    "label": "Agent Trace",
                    "display_options": {
                        "show_overlays": True,
                        "show_filmstrip": True,
                        "show_thought": True,
                        "auto_playback": True,
                        "playback_step_delay": 1.0,
                    },
                },
            ],
        },
        "annotation_schemes": [
            {
                "annotation_type": "radio",
                "name": "task_success",
                "description": "Did the agent complete the task?",
                "labels": [
                    {"name": "success", "tooltip": "Fully completed"},
                    {"name": "partial", "tooltip": "Partially completed"},
                    {"name": "failure", "tooltip": "Not completed"},
                ],
                "sequential_key_binding": True,
            },
        ],
        "user_config": {"allow_all_users": True},
        "require_password": False,
    }

    config_path = os.path.join(test_output_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(playback_config, f)

    return config_path, test_output_dir


class TestPlaybackUI(unittest.TestCase):
    """Selenium tests for the auto-playback feature on web_agent_trace display."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server with playback-enabled agent trace config."""
        cls.config_path, cls.test_output_dir = create_playback_config()

        port = find_free_port(preferred_port=9061)
        cls.server = FlaskTestServer(config=cls.config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start Flask server for playback UI test"

        # Set up Chrome options for headless testing
        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options.add_argument("--disable-extensions")
        cls.chrome_options.add_argument("--disable-plugins")
        cls.chrome_options.add_experimental_option(
            "excludeSwitches", ["enable-automation"]
        )
        cls.chrome_options.add_experimental_option("useAutomationExtension", False)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()
        # Clean up test output directory
        if hasattr(cls, "test_output_dir") and os.path.exists(cls.test_output_dir):
            try:
                shutil.rmtree(cls.test_output_dir)
            except Exception:
                pass

    def setUp(self):
        """Create browser and login for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"test_playback_{int(time.time())}"

        # Login (no password mode)
        self.driver.get(f"{self.server.base_url}/")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )

        try:
            self.driver.find_element(By.ID, "login-tab")
            register_tab = self.driver.find_element(By.ID, "register-tab")
            register_tab.click()
            WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.ID, "register-content"))
            )
            self.driver.find_element(By.ID, "register-email").send_keys(self.test_user)
            self.driver.find_element(By.ID, "register-pass").send_keys("test123")
            self.driver.find_element(
                By.CSS_SELECTOR, "#register-content form"
            ).submit()
        except NoSuchElementException:
            # Simple login - just enter username
            username_field = self.driver.find_element(By.ID, "login-email")
            username_field.clear()
            username_field.send_keys(self.test_user)
            submit_btn = self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit']"
            )
            submit_btn.click()

        time.sleep(0.5)

        # Wait for annotation page to load
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.ID, "task_layout"))
            )
        except TimeoutException:
            pass

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_page_loads_with_main_content(self):
        """Annotation page should load with main content visible."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        main_content = self.driver.find_element(By.ID, "main-content")
        assert main_content.is_displayed(), "Main content should be visible"

    def test_web_agent_viewer_container_exists(self):
        """The web-agent-viewer container should be rendered."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        viewers = self.driver.find_elements(By.CSS_SELECTOR, ".web-agent-viewer")
        assert len(viewers) > 0, "Should have at least one web-agent-viewer container"

    def test_auto_playback_data_attribute_set(self):
        """The viewer container should have data-auto-playback='true'."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        viewer = self.driver.find_element(By.CSS_SELECTOR, ".web-agent-viewer")
        auto_playback = viewer.get_attribute("data-auto-playback")
        assert auto_playback == "true", \
            f"data-auto-playback should be 'true', got '{auto_playback}'"

    def test_playback_step_delay_data_attribute(self):
        """The viewer should have the configured playback step delay."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        viewer = self.driver.find_element(By.CSS_SELECTOR, ".web-agent-viewer")
        delay = viewer.get_attribute("data-playback-step-delay")
        assert delay == "1.0", \
            f"data-playback-step-delay should be '1.0', got '{delay}'"

    def test_playback_js_loaded(self):
        """The PlaybackController should be available on window."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        result = self.driver.execute_script(
            "return typeof window.PlaybackController !== 'undefined';"
        )
        assert result, "PlaybackController should be available on window"

    def test_web_agent_viewer_js_loaded(self):
        """The WebAgentViewer class should be available."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        result = self.driver.execute_script(
            "return typeof WebAgentViewer !== 'undefined';"
        )
        assert result, "WebAgentViewer should be available on window"

    def test_playback_controls_rendered(self):
        """Playback controls bar should be rendered in the page."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # Give time for auto-attach (setTimeout 100ms in JS)
        time.sleep(0.5)

        controls = self.driver.find_elements(By.CSS_SELECTOR, ".playback-controls")
        assert len(controls) > 0, \
            "Playback controls should be rendered when auto_playback is enabled"

    def test_playback_play_button_exists(self):
        """The play/pause button should exist in playback controls."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        play_btns = self.driver.find_elements(
            By.CSS_SELECTOR, ".playback-play-btn"
        )
        assert len(play_btns) > 0, "Should have a play/pause button"

    def test_playback_speed_buttons_exist(self):
        """Speed control buttons (0.5x, 1x, 2x, 4x) should be present."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        speed_btns = self.driver.find_elements(
            By.CSS_SELECTOR, ".playback-speed-btn"
        )
        assert len(speed_btns) >= 3, \
            f"Should have at least 3 speed buttons, got {len(speed_btns)}"

        # Verify speed values
        speed_values = [btn.get_attribute("data-speed") for btn in speed_btns]
        assert "1" in speed_values, "Should have a 1x speed button"
        assert "2" in speed_values, "Should have a 2x speed button"

    def test_playback_1x_speed_active_by_default(self):
        """The 1x speed button should be active by default."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        active_speed = self.driver.find_elements(
            By.CSS_SELECTOR, ".playback-speed-btn.active"
        )
        assert len(active_speed) == 1, "Exactly one speed button should be active"
        assert active_speed[0].get_attribute("data-speed") == "1", \
            "1x speed should be active by default"

    def test_playback_progress_bar_exists(self):
        """A progress bar (range input) should be present."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        progress_bars = self.driver.find_elements(
            By.CSS_SELECTOR, ".playback-progress"
        )
        assert len(progress_bars) > 0, "Should have a playback progress bar"

        # Verify max is set to steps count - 1
        max_val = progress_bars[0].get_attribute("max")
        assert max_val is not None, "Progress bar should have a max value"
        assert int(max_val) >= 1, \
            f"Progress bar max should be >= 1 (steps - 1), got {max_val}"

    def test_playback_time_display_exists(self):
        """The time/step display should show current position."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        time_displays = self.driver.find_elements(
            By.CSS_SELECTOR, ".playback-time"
        )
        assert len(time_displays) > 0, "Should have a playback time display"

        # Should show something like "0 / 4" or "1 / 4"
        text = time_displays[0].text
        assert "/" in text, \
            f"Time display should show 'N / total' format, got '{text}'"

    def test_step_navigation_buttons_exist(self):
        """Previous and Next step buttons should exist."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        prev_btns = self.driver.find_elements(By.CSS_SELECTOR, ".step-prev")
        assert len(prev_btns) > 0, "Should have a previous step button"

        next_btns = self.driver.find_elements(By.CSS_SELECTOR, ".step-next")
        assert len(next_btns) > 0, "Should have a next step button"

    def test_step_counter_shows_position(self):
        """Step counter should display the current step position."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        counters = self.driver.find_elements(By.CSS_SELECTOR, ".step-counter")
        assert len(counters) > 0, "Should have a step counter"

        text = counters[0].text
        assert "Step" in text or "of" in text, \
            f"Step counter should show position, got '{text}'"

    def test_filmstrip_renders(self):
        """The filmstrip should render with thumbnail entries."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        filmstrips = self.driver.find_elements(By.CSS_SELECTOR, ".filmstrip")
        assert len(filmstrips) > 0, "Should have a filmstrip"

        thumbs = self.driver.find_elements(By.CSS_SELECTOR, ".filmstrip-thumb")
        assert len(thumbs) >= 2, \
            f"Should have at least 2 filmstrip thumbnails, got {len(thumbs)}"

    def test_overlay_controls_present(self):
        """Overlay toggle checkboxes should be present."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        controls = self.driver.find_elements(By.CSS_SELECTOR, ".overlay-controls")
        assert len(controls) > 0, "Should have overlay controls"

        toggles = self.driver.find_elements(By.CSS_SELECTOR, ".overlay-toggle")
        assert len(toggles) >= 2, \
            f"Should have at least 2 overlay toggles, got {len(toggles)}"

    def test_step_details_panel_exists(self):
        """The step details panel with action info should be present."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        panels = self.driver.find_elements(By.CSS_SELECTOR, ".step-details-panel")
        assert len(panels) > 0, "Should have a step details panel"

        # Check that action badge is present
        badges = self.driver.find_elements(By.CSS_SELECTOR, ".action-badge")
        assert len(badges) > 0, "Should have an action badge in the details"

    def test_thought_display_present(self):
        """The thought display should show agent reasoning text."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source
        # The first step's thought should be displayed
        assert "Thought" in page_source or "thought" in page_source, \
            "Should display thought content from the trace"

    def test_annotation_schema_renders(self):
        """The task_success radio schema should render on the page."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source
        assert "task_success" in page_source, "task_success schema should be present"

    def test_playback_controller_attached(self):
        """PlaybackController should be attached to the viewer with auto_playback."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        result = self.driver.execute_script("""
            var viewers = document.querySelectorAll('.web-agent-viewer[data-auto-playback="true"]');
            if (viewers.length === 0) return 'no_viewer';
            if (!viewers[0]._playbackController) return 'no_controller';
            return 'attached';
        """)
        assert result == "attached", \
            f"PlaybackController should be attached to viewer, got '{result}'"

    def test_play_button_toggles_icon(self):
        """Clicking the play button should toggle between play and pause icons."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        play_btn = self.driver.find_element(By.CSS_SELECTOR, ".playback-play-btn")
        play_icon = self.driver.find_element(By.CSS_SELECTOR, ".play-icon")
        pause_icon = self.driver.find_element(By.CSS_SELECTOR, ".pause-icon")

        # Initially play icon should be visible, pause hidden
        play_display = play_icon.value_of_css_property("display")
        pause_display = pause_icon.value_of_css_property("display")
        assert play_display != "none", "Play icon should be visible initially"
        assert pause_display == "none", "Pause icon should be hidden initially"

        # Click play
        play_btn.click()
        time.sleep(0.3)

        # Now pause icon should be visible, play hidden
        play_display = play_icon.value_of_css_property("display")
        pause_display = pause_icon.value_of_css_property("display")
        assert play_display == "none", "Play icon should be hidden after clicking play"
        assert pause_display != "none", \
            "Pause icon should be visible after clicking play"

        # Click again to pause
        play_btn.click()
        time.sleep(0.3)

        play_display = play_icon.value_of_css_property("display")
        assert play_display != "none", \
            "Play icon should be visible again after clicking pause"

    def test_speed_button_click_changes_active(self):
        """Clicking a speed button should change the active speed."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.5)

        # Find the 2x speed button
        speed_2x = self.driver.find_element(
            By.CSS_SELECTOR, ".playback-speed-btn[data-speed='2']"
        )
        speed_2x.click()
        time.sleep(0.2)

        # Verify 2x is now active
        assert "active" in speed_2x.get_attribute("class"), \
            "2x speed button should be active after click"

        # Verify 1x is no longer active
        speed_1x = self.driver.find_element(
            By.CSS_SELECTOR, ".playback-speed-btn[data-speed='1']"
        )
        assert "active" not in speed_1x.get_attribute("class"), \
            "1x speed button should not be active after selecting 2x"


class TestPlaybackNotPresentWithoutConfig(unittest.TestCase):
    """Verify that playback controls do NOT appear without auto_playback config."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server with standard agent trace config (no playback)."""
        project_root = get_project_root()
        config_path = os.path.join(
            project_root, "examples/agent-traces/agent-trace-evaluation/config.yaml"
        )

        port = find_free_port(preferred_port=9062)
        cls.server = FlaskTestServer(config=config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start Flask server for no-playback test"

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")
        cls.chrome_options.add_experimental_option(
            "excludeSwitches", ["enable-automation"]
        )
        cls.chrome_options.add_experimental_option("useAutomationExtension", False)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"test_noplay_{int(time.time())}"

        # Login
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )

        try:
            self.driver.find_element(By.ID, "login-tab")
            register_tab = self.driver.find_element(By.ID, "register-tab")
            register_tab.click()
            WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.ID, "register-content"))
            )
            self.driver.find_element(By.ID, "register-email").send_keys(self.test_user)
            self.driver.find_element(By.ID, "register-pass").send_keys("test123")
            self.driver.find_element(
                By.CSS_SELECTOR, "#register-content form"
            ).submit()
        except NoSuchElementException:
            username_field = self.driver.find_element(By.ID, "login-email")
            username_field.clear()
            username_field.send_keys(self.test_user)
            submit_btn = self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit']"
            )
            submit_btn.click()

        time.sleep(0.5)

        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.ID, "task_layout"))
            )
        except TimeoutException:
            pass

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_no_playback_controls_without_config(self):
        """Playback controls should NOT appear when auto_playback is not set."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # Wait a moment for any potential auto-attach
        time.sleep(0.5)

        controls = self.driver.find_elements(By.CSS_SELECTOR, ".playback-controls")
        assert len(controls) == 0, \
            "Playback controls should NOT be present without auto_playback config"

    def test_no_auto_playback_attribute(self):
        """The viewer should not have data-auto-playback attribute."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # The standard agent trace config uses dialogue display, not web_agent_trace,
        # so there should be no web-agent-viewer at all. But even if there were,
        # there should be no auto-playback attribute.
        viewers = self.driver.find_elements(
            By.CSS_SELECTOR, '.web-agent-viewer[data-auto-playback="true"]'
        )
        assert len(viewers) == 0, \
            "No viewer should have data-auto-playback='true' without config"


if __name__ == "__main__":
    unittest.main()
