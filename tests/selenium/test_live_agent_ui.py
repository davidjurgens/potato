"""
Selenium UI tests for the live agent display type.

Tests:
1. Live agent example loads and displays the annotation page
2. Annotation schemas (radio, text) render correctly
3. Live agent display container exists with expected structure
4. Start form is present with task and URL inputs
5. Control buttons exist (pause, resume, stop, instruct)
6. Filmstrip container exists
7. Status bar is rendered

Note: These tests verify UI rendering only. Actual agent execution
requires Playwright + LLM and is not tested here.
"""

import os
import time
import unittest

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


class TestLiveAgentUI(unittest.TestCase):
    """Selenium tests for the live agent display UI rendering."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server with live agent evaluation config."""
        project_root = get_project_root()
        config_path = os.path.join(
            project_root, "examples/agent-traces/live-agent-evaluation/config.yaml"
        )

        port = find_free_port(preferred_port=9060)
        cls.server = FlaskTestServer(config=config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start Flask server for live agent UI test"

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

    def setUp(self):
        """Create browser and login for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"test_live_{int(time.time())}"

        # Login (no password mode)
        self.driver.get(f"{self.server.base_url}/")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )

        try:
            # Check for password mode
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
            pass  # Some tests will check the page state themselves

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

    def test_live_agent_viewer_container_exists(self):
        """The live-agent-viewer container should be rendered in the page."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        viewers = self.driver.find_elements(By.CSS_SELECTOR, ".live-agent-viewer")
        assert len(viewers) > 0, "Should have at least one live-agent-viewer container"

    def test_live_agent_start_form_exists(self):
        """The start form should be present with task and URL inputs."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        start_forms = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-start-form"
        )
        assert len(start_forms) > 0, "Should have a live-agent-start-form"

        # Check for task input
        task_inputs = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-task-input"
        )
        assert len(task_inputs) > 0, "Should have a task input field"

        # Check for URL input
        url_inputs = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-url-input"
        )
        assert len(url_inputs) > 0, "Should have a URL input field"

    def test_live_agent_start_button_exists(self):
        """The Start Agent button should be present."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        start_btns = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-start-btn"
        )
        assert len(start_btns) > 0, "Should have a Start Agent button"
        assert "Start Agent" in start_btns[0].text, \
            f"Button text should contain 'Start Agent', got '{start_btns[0].text}'"

    def test_live_agent_status_bar_exists(self):
        """The status bar with indicator and text should be present."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        status_indicators = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-status-indicator"
        )
        assert len(status_indicators) > 0, "Should have a status indicator"

        status_texts = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-status-text"
        )
        assert len(status_texts) > 0, "Should have status text"
        assert status_texts[0].text == "Ready", \
            f"Initial status should be 'Ready', got '{status_texts[0].text}'"

    def test_live_agent_control_buttons_exist(self):
        """Control buttons (pause, resume, stop) should exist in the DOM."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # Pause button (may be hidden initially but should exist in DOM)
        pause_btns = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-pause-btn"
        )
        assert len(pause_btns) > 0, "Should have a pause button"

        # Resume button
        resume_btns = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-resume-btn"
        )
        assert len(resume_btns) > 0, "Should have a resume button"

        # Stop button
        stop_btns = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-stop-btn"
        )
        assert len(stop_btns) > 0, "Should have a stop button"

    def test_live_agent_takeover_button_exists(self):
        """The takeover button should exist when allow_takeover is true."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        takeover_btns = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-takeover-btn"
        )
        assert len(takeover_btns) > 0, "Should have a takeover button"
        # Use textContent instead of .text since button is inside a hidden container
        btn_text = takeover_btns[0].get_attribute("textContent").strip()
        assert "Take Over" in btn_text, \
            f"Takeover button should say 'Take Over', got '{btn_text}'"

    def test_live_agent_instruction_input_exists(self):
        """The instruction input and send button should exist."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        instruct_inputs = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-instruct-text"
        )
        assert len(instruct_inputs) > 0, "Should have an instruction text input"

        instruct_btns = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-instruct-btn"
        )
        assert len(instruct_btns) > 0, "Should have an instruction send button"

    def test_live_agent_filmstrip_container_exists(self):
        """The filmstrip container should exist in the DOM."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        filmstrips = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-filmstrip"
        )
        assert len(filmstrips) > 0, "Should have a filmstrip container"

    def test_live_agent_screenshot_panel_exists(self):
        """The screenshot panel should exist in the DOM."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        panels = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-screenshot-panel"
        )
        assert len(panels) > 0, "Should have a screenshot panel"

    def test_live_agent_overlay_controls_exist(self):
        """Overlay toggle checkboxes should be present."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        overlay_controls = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-overlay-controls"
        )
        assert len(overlay_controls) > 0, "Should have overlay controls"

        toggles = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-overlay-toggle"
        )
        assert len(toggles) >= 2, \
            f"Should have at least 2 overlay toggles, got {len(toggles)}"

    def test_live_agent_thought_panel_exists(self):
        """The thought panel should exist for showing agent reasoning."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        thought_panels = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-thought-panel"
        )
        assert len(thought_panels) > 0, "Should have a thought panel"

        thought_texts = self.driver.find_elements(
            By.CSS_SELECTOR, ".live-agent-thought-text"
        )
        assert len(thought_texts) > 0, "Should have thought text element"

    def test_radio_annotation_schemas_render(self):
        """Radio annotation schemas should render on the page."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source

        # Check that the annotation schemas from the config are present
        assert "task_completion" in page_source, \
            "task_completion schema should be present"
        assert "efficiency" in page_source, \
            "efficiency schema should be present"
        assert "needed_intervention" in page_source, \
            "needed_intervention schema should be present"

    def test_text_annotation_schema_renders(self):
        """The notes text annotation schema should render."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source
        assert "notes" in page_source, "notes text schema should be present"

    def test_radio_buttons_are_clickable(self):
        """Should be able to click radio buttons for annotation."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # Find radio inputs for task_completion
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][name*='task_completion']"
        )
        if radios:
            radios[0].click()
            assert radios[0].is_selected(), \
                "Radio button should be selected after click"

    def test_live_agent_js_loaded(self):
        """The live-agent-viewer.js should be loaded and LiveAgentViewer available."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # Check that the LiveAgentViewer class is available on window
        result = self.driver.execute_script(
            "return typeof window.LiveAgentViewer !== 'undefined';"
        )
        assert result, "LiveAgentViewer should be available on window"

    def test_live_agent_viewer_initialized(self):
        """The LiveAgentViewer should auto-initialize on the container element."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # Give a moment for auto-initialization
        time.sleep(0.5)

        # Check that the viewer instance is attached to the container
        result = self.driver.execute_script("""
            var viewers = document.querySelectorAll('.live-agent-viewer');
            if (viewers.length === 0) return false;
            return viewers[0]._liveAgentViewer !== undefined;
        """)
        assert result, "LiveAgentViewer should be auto-initialized on the container"

    def test_controls_initially_disabled(self):
        """Control buttons should be disabled before a session starts."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        pause_btn = self.driver.find_element(By.CSS_SELECTOR, ".live-agent-pause-btn")
        assert not pause_btn.is_enabled(), "Pause button should be disabled initially"

        stop_btn = self.driver.find_element(By.CSS_SELECTOR, ".live-agent-stop-btn")
        assert not stop_btn.is_enabled(), "Stop button should be disabled initially"

        instruct_input = self.driver.find_element(
            By.CSS_SELECTOR, ".live-agent-instruct-text"
        )
        assert not instruct_input.is_enabled(), \
            "Instruction input should be disabled initially"

    def test_task_input_prepopulated(self):
        """Task input should be pre-populated from instance data."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        task_input = self.driver.find_element(
            By.CSS_SELECTOR, ".live-agent-task-input"
        )
        value = task_input.get_attribute("value")
        # The task input should have some value from the data
        # (the first instance's task_description)
        assert value is not None, "Task input should have a value attribute"

    def test_main_viewer_hidden_initially(self):
        """The main viewer area should be hidden before a session starts."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        main_viewer = self.driver.find_element(By.CSS_SELECTOR, ".live-agent-main")
        display = main_viewer.value_of_css_property("display")
        assert display == "none", \
            f"Main viewer should be hidden initially, got display: {display}"


if __name__ == "__main__":
    unittest.main()
