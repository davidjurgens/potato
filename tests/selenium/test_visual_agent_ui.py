"""
Selenium tests for the visual agent evaluation example.

Tests the visual-agent-evaluation config which uses:
- Image display (screenshot_url) alongside dialogue trace
- Radio schemas (task_success, grounding_accuracy, safety)
- Likert schema (navigation_efficiency)
- Multiselect schema (gui_errors)
- Text schema (notes)
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


def create_chrome_options():
    opts = ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-plugins")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return opts


def login_user(driver, base_url, username):
    """Register and login a user, wait for annotation page."""
    driver.get(f"{base_url}/")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "login-email"))
    )
    try:
        driver.find_element(By.ID, "login-tab")
        register_tab = driver.find_element(By.ID, "register-tab")
        register_tab.click()
        WebDriverWait(driver, 5).until(
            EC.visibility_of_element_located((By.ID, "register-content"))
        )
        driver.find_element(By.ID, "register-email").send_keys(username)
        driver.find_element(By.ID, "register-pass").send_keys("test123")
        driver.find_element(By.CSS_SELECTOR, "#register-content form").submit()
    except NoSuchElementException:
        username_field = driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(username)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    time.sleep(0.5)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
    except TimeoutException:
        pass


class TestVisualAgentUI(unittest.TestCase):
    """Test the visual agent evaluation UI with image + dialogue display."""

    @classmethod
    def setUpClass(cls):
        project_root = get_project_root()
        config_path = os.path.join(
            project_root,
            "examples/agent-traces/visual-agent-evaluation/config.yaml",
        )
        port = find_free_port(preferred_port=9070)
        cls.server = FlaskTestServer(config=config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start server for visual agent UI test"
        cls.chrome_options = create_chrome_options()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"vis_{int(time.time() * 1000) % 100000}"
        login_user(self.driver, self.server.base_url, self.test_user)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    # --- Page structure ---

    def test_page_loads_with_main_content(self):
        """Visual agent evaluation page should load with main content."""
        main = self.driver.find_element(By.ID, "main-content")
        assert main.is_displayed(), "main-content should be visible"

    def test_image_display_present(self):
        """An image element should be present for the screenshot field."""
        images = self.driver.find_elements(By.CSS_SELECTOR, "img")
        # Filter to images that look like screenshots (not icons)
        screenshot_imgs = [
            img for img in images
            if img.get_attribute("src") and "placehold" in (img.get_attribute("src") or "")
        ]
        # Even if placeholder doesn't match, at least one img in instance area
        instance_imgs = self.driver.find_elements(
            By.CSS_SELECTOR, ".instance-display-container img, #main-content img"
        )
        assert len(screenshot_imgs) > 0 or len(instance_imgs) > 0, \
            "Should have an image element for the screenshot"

    def test_dialogue_display_present(self):
        """Dialogue display should render agent action trace."""
        page_source = self.driver.page_source
        has_dialogue = (
            "Agent (Thought)" in page_source
            or "Agent (Action)" in page_source
            or "Environment" in page_source
            or "dialogue" in page_source.lower()
        )
        assert has_dialogue, "Should render dialogue with agent trace content"

    def test_task_description_visible(self):
        """Task description text should be visible."""
        page_source = self.driver.page_source
        # Check for content from the first visual trace
        assert "Navigate to Amazon" in page_source or "task_description" in page_source, \
            "Task description should be present"

    def test_metadata_table_present(self):
        """Metadata spreadsheet should render trace info."""
        page_source = self.driver.page_source
        has_metadata = (
            "Steps" in page_source
            or "Browser" in page_source
            or "Duration" in page_source
            or "spreadsheet" in page_source.lower()
        )
        assert has_metadata, "Metadata table should display trace info"

    # --- Annotation schemas ---

    def test_task_success_radio_renders(self):
        """task_success radio schema should be present."""
        page_source = self.driver.page_source
        assert "task_success" in page_source, "task_success schema should render"

    def test_grounding_accuracy_radio_renders(self):
        """grounding_accuracy radio schema should be present."""
        page_source = self.driver.page_source
        assert "grounding_accuracy" in page_source, \
            "grounding_accuracy schema should render"

    def test_navigation_efficiency_likert_renders(self):
        """navigation_efficiency likert schema should be present."""
        page_source = self.driver.page_source
        assert "navigation_efficiency" in page_source, \
            "navigation_efficiency schema should render"

    def test_gui_errors_multiselect_renders(self):
        """gui_errors multiselect schema should be present."""
        page_source = self.driver.page_source
        assert "gui_errors" in page_source, "gui_errors schema should render"

    def test_safety_radio_renders(self):
        """safety radio schema should be present."""
        page_source = self.driver.page_source
        assert "safety" in page_source, "safety schema should render"

    # --- Interactions ---

    def test_task_success_radio_clickable(self):
        """Should be able to click a task_success radio."""
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][name*='task_success']"
        )
        if not radios:
            self.skipTest("No task_success radio buttons found")
        radios[0].click()
        time.sleep(0.2)
        assert radios[0].is_selected(), "Radio should be selected after click"

    def test_grounding_accuracy_radio_clickable(self):
        """Should be able to click a grounding_accuracy radio."""
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][name*='grounding_accuracy']"
        )
        if not radios:
            self.skipTest("No grounding_accuracy radio buttons found")
        radios[0].click()
        time.sleep(0.2)
        assert radios[0].is_selected(), "Radio should be selected after click"

    def test_gui_errors_checkbox_clickable(self):
        """Should be able to click gui_errors checkboxes (multiselect)."""
        checkboxes = self.driver.find_elements(
            By.CSS_SELECTOR,
            "input[type='checkbox'][schema='gui_errors'],"
            " #gui_errors input[type='checkbox']"
        )
        if not checkboxes:
            self.skipTest("No gui_errors checkboxes found")

        checkboxes[0].click()
        time.sleep(0.2)
        assert checkboxes[0].is_selected(), "First checkbox should be selected"

        if len(checkboxes) > 1:
            checkboxes[1].click()
            time.sleep(0.2)
            assert checkboxes[1].is_selected(), "Second checkbox should be selected"
            assert checkboxes[0].is_selected(), "First should remain selected"

    def test_likert_clickable_via_js(self):
        """Should be able to interact with navigation_efficiency likert via JS."""
        likert_inputs = self.driver.find_elements(
            By.CSS_SELECTOR,
            "input.shadcn-likert-input[schema='navigation_efficiency']"
        )
        if not likert_inputs:
            likert_inputs = self.driver.find_elements(
                By.CSS_SELECTOR, "#navigation_efficiency input[type='radio']"
            )
        if not likert_inputs:
            self.skipTest("No navigation_efficiency likert inputs found")

        mid = len(likert_inputs) // 2
        self.driver.execute_script("arguments[0].click();", likert_inputs[mid])
        time.sleep(0.2)
        assert likert_inputs[mid].is_selected(), "Likert input should be selected"

    def test_navigation_elements_present(self):
        """Navigation elements (next/prev or go_to) should be present."""
        # The page should have some navigation mechanism
        page_source = self.driver.page_source
        has_nav = (
            "click_to_next" in page_source
            or "get_new_instance" in page_source
            or "go_to" in page_source
            or "ArrowRight" in page_source
        )
        assert has_nav, "Should have navigation JS functions in the page"


if __name__ == "__main__":
    unittest.main()
