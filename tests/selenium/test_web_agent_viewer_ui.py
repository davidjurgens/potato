"""
Selenium UI tests for the Web Agent Trace Viewer.

Tests the interactive step-by-step viewer including:
- Viewer container rendering
- Screenshot and SVG overlay display
- Step navigation (buttons, filmstrip, keyboard)
- Overlay visibility controls
- Step details panel content

Uses the examples/agent-traces/web-agent-review/config.yaml example project.
"""

import os
import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


def get_project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


class TestWebAgentViewerUI(unittest.TestCase):
    """Selenium tests for the web agent trace viewer display."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server with web-agent-review example config."""
        project_root = get_project_root()
        config_path = os.path.join(
            project_root, "examples/agent-traces/web-agent-review/config.yaml"
        )

        port = find_free_port(preferred_port=9060)
        cls.server = FlaskTestServer(config=config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start Flask server for web agent viewer test"

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
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"test_wav_{int(time.time())}"
        self._login()

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        """Login with simple (no-password) mode."""
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
            field = self.driver.find_element(By.ID, "login-email")
            field.clear()
            field.send_keys(self.test_user)
            self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit']"
            ).click()

        time.sleep(0.5)
        try:
            WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.ID, "main-content"))
            )
        except TimeoutException:
            pass

    def _wait_for_viewer(self, timeout=10):
        """Wait for the web agent viewer to be present."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".web-agent-viewer"))
        )

    # --- Rendering tests ---

    def test_viewer_container_renders(self):
        """Web agent viewer container should be present and visible."""
        viewer = self._wait_for_viewer()
        self.assertTrue(viewer.is_displayed())
        self.assertTrue(viewer.get_attribute("data-steps"))

    def test_screenshot_displays(self):
        """Screenshot image should load with valid src."""
        self._wait_for_viewer()
        img = self.driver.find_element(By.CSS_SELECTOR, ".step-screenshot")
        self.assertTrue(img.is_displayed())
        src = img.get_attribute("src")
        self.assertTrue(src and len(src) > 0)

    def test_svg_overlay_layer_exists(self):
        """SVG overlay layer should be present in the screenshot container."""
        self._wait_for_viewer()
        svg = self.driver.find_element(By.CSS_SELECTOR, ".overlay-layer")
        self.assertIsNotNone(svg)

    def test_step_details_panel_renders(self):
        """Step details panel should show action badge and content."""
        self._wait_for_viewer()
        panel = self.driver.find_element(By.CSS_SELECTOR, ".step-details-panel")
        self.assertTrue(panel.is_displayed())
        badge = panel.find_element(By.CSS_SELECTOR, ".action-badge")
        self.assertTrue(badge.is_displayed())
        self.assertTrue(len(badge.text) > 0)

    def test_filmstrip_renders(self):
        """Filmstrip should contain correct number of thumbnails."""
        self._wait_for_viewer()
        filmstrip = self.driver.find_element(By.CSS_SELECTOR, ".filmstrip")
        self.assertTrue(filmstrip.is_displayed())
        thumbs = filmstrip.find_elements(By.CSS_SELECTOR, ".filmstrip-thumb")
        self.assertGreater(len(thumbs), 0)

    def test_step_counter_displays(self):
        """Step counter should show 'Step 1 of N' format."""
        self._wait_for_viewer()
        counter = self.driver.find_element(By.CSS_SELECTOR, ".step-counter")
        text = counter.text
        self.assertRegex(text, r"Step \d+ of \d+")

    # --- Navigation tests ---

    def test_next_step_button(self):
        """Clicking next should advance step counter and update content."""
        self._wait_for_viewer()
        counter = self.driver.find_element(By.CSS_SELECTOR, ".step-counter")
        initial_text = counter.text

        next_btn = self.driver.find_element(By.CSS_SELECTOR, ".step-next")
        if not next_btn.get_attribute("disabled"):
            next_btn.click()
            time.sleep(0.3)
            new_text = self.driver.find_element(By.CSS_SELECTOR, ".step-counter").text
            self.assertNotEqual(initial_text, new_text)
            self.assertIn("Step 2", new_text)

    def test_prev_step_button(self):
        """After navigating forward, prev should go back."""
        self._wait_for_viewer()
        next_btn = self.driver.find_element(By.CSS_SELECTOR, ".step-next")
        if not next_btn.get_attribute("disabled"):
            next_btn.click()
            time.sleep(0.3)

            prev_btn = self.driver.find_element(By.CSS_SELECTOR, ".step-prev")
            prev_btn.click()
            time.sleep(0.3)

            counter = self.driver.find_element(By.CSS_SELECTOR, ".step-counter")
            self.assertIn("Step 1", counter.text)

    def test_filmstrip_click_navigation(self):
        """Clicking a filmstrip thumbnail should jump to that step."""
        self._wait_for_viewer()
        thumbs = self.driver.find_elements(By.CSS_SELECTOR, ".filmstrip-thumb")
        if len(thumbs) >= 3:
            thumbs[2].click()
            time.sleep(0.3)
            counter = self.driver.find_element(By.CSS_SELECTOR, ".step-counter")
            self.assertIn("Step 3", counter.text)

    def test_filmstrip_active_highlight(self):
        """Active step thumbnail should have filmstrip-active CSS class."""
        self._wait_for_viewer()
        active = self.driver.find_elements(By.CSS_SELECTOR, ".filmstrip-thumb.filmstrip-active")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].get_attribute("data-step"), "0")

    def test_keyboard_arrow_navigation(self):
        """Arrow keys should navigate steps when viewer is focused."""
        viewer = self._wait_for_viewer()
        viewer.click()  # Focus the viewer
        time.sleep(0.2)

        viewer.send_keys(Keys.ARROW_RIGHT)
        time.sleep(0.3)
        counter = self.driver.find_element(By.CSS_SELECTOR, ".step-counter")
        self.assertIn("Step 2", counter.text)

    def test_step_boundary_disabled(self):
        """At first step, prev button should be disabled."""
        self._wait_for_viewer()
        prev_btn = self.driver.find_element(By.CSS_SELECTOR, ".step-prev")
        self.assertTrue(prev_btn.get_attribute("disabled"))

    # --- Overlay tests ---

    def test_click_marker_overlay_visible(self):
        """On a click step, SVG should contain circle elements."""
        self._wait_for_viewer()
        # First step is a click action - overlays should render
        time.sleep(0.5)
        svg = self.driver.find_element(By.CSS_SELECTOR, ".overlay-layer")
        circles = svg.find_elements(By.CSS_SELECTOR, "circle")
        # Should have click marker circles
        self.assertGreater(len(circles), 0)

    def test_bounding_box_overlay_visible(self):
        """On a step with element bbox, rect with dashed stroke should exist."""
        self._wait_for_viewer()
        time.sleep(0.5)
        svg = self.driver.find_element(By.CSS_SELECTOR, ".overlay-layer")
        rects = svg.find_elements(By.CSS_SELECTOR, "rect")
        # First step has bbox data - should have bounding box rect
        self.assertGreater(len(rects), 0)

    def test_mouse_path_overlay_visible(self):
        """On a step with mouse_path data, path element should exist."""
        self._wait_for_viewer()
        time.sleep(0.5)
        svg = self.driver.find_element(By.CSS_SELECTOR, ".overlay-layer")
        paths = svg.find_elements(By.CSS_SELECTOR, "path")
        # First step has mouse_path data
        self.assertGreater(len(paths), 0)

    def test_overlay_toggle_keyboard(self):
        """Pressing '1' should toggle click marker visibility."""
        viewer = self._wait_for_viewer()
        viewer.click()
        time.sleep(0.3)

        # Toggle click markers off
        viewer.send_keys("1")
        time.sleep(0.3)

        # Check that the overlay-toggle checkbox for click is unchecked
        cb = self.driver.find_element(
            By.CSS_SELECTOR, '.overlay-toggle[data-overlay="click"]'
        )
        self.assertFalse(cb.is_selected())

    def test_overlay_show_all(self):
        """Pressing 'A' should show all overlay types."""
        viewer = self._wait_for_viewer()
        viewer.click()
        time.sleep(0.2)

        # First hide one
        viewer.send_keys("1")
        time.sleep(0.2)

        # Then show all
        viewer.send_keys("a")
        time.sleep(0.3)

        toggles = self.driver.find_elements(By.CSS_SELECTOR, ".overlay-toggle")
        for toggle in toggles:
            self.assertTrue(toggle.is_selected())

    def test_overlay_hide_all(self):
        """Pressing 'N' should hide all overlay types."""
        viewer = self._wait_for_viewer()
        viewer.click()
        time.sleep(0.2)

        viewer.send_keys("n")
        time.sleep(0.3)

        toggles = self.driver.find_elements(By.CSS_SELECTOR, ".overlay-toggle")
        for toggle in toggles:
            self.assertFalse(toggle.is_selected())


if __name__ == "__main__":
    unittest.main()
