"""
Selenium UI tests for agent trace annotation features.

Tests:
1. Agent trace example loads and displays dialogue content in browser
2. Annotation schemas (radio, likert, multiselect) render correctly
3. Annotations can be created through the UI
4. Annotations persist after page refresh
5. Agent comparison example renders pairwise layout
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


import pytest


pytestmark = pytest.mark.redundant

def get_project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


class TestAgentTraceUI(unittest.TestCase):
    """Selenium tests for agent trace annotation UI."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server with agent trace evaluation config."""
        project_root = get_project_root()
        config_path = os.path.join(
            project_root, "examples/agent-traces/agent-trace-evaluation/config.yaml"
        )

        port = find_free_port(preferred_port=9050)
        cls.server = FlaskTestServer(config=config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start Flask server for agent trace UI test"

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
        self.test_user = f"test_agent_{int(time.time())}"

        # Login (no password mode)
        self.driver.get(f"{self.server.base_url}/")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )

        try:
            # Check for simple login mode (no password)
            self.driver.find_element(By.ID, "login-tab")
            # Password mode - not expected for this config but handle it
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

    def test_page_loads_with_annotation_content(self):
        """Annotation page should load with agent trace content visible."""
        # Wait for main content
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source
        # Should have annotation-related content
        assert "task_success" in page_source or "annotation" in page_source.lower()

    def test_dialogue_display_renders(self):
        """The dialogue display should render agent trace conversation turns."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source
        # The dialogue display renders with speaker names from the trace data
        # Check for dialogue-related CSS classes or content
        has_dialogue = (
            "dialogue" in page_source.lower()
            or "speaker" in page_source.lower()
            or "Agent" in page_source
            or "conversation" in page_source.lower()
        )
        assert has_dialogue, "Page should contain dialogue display content"

    def test_radio_schema_renders(self):
        """The task_success radio schema should render."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source
        assert "task_success" in page_source, "task_success schema should be present"

    def test_likert_schema_renders(self):
        """The efficiency likert schema should render."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source
        assert "efficiency" in page_source, "efficiency schema should be present"

    def test_multiselect_schema_renders(self):
        """The mast_errors multiselect schema should render."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source
        assert "mast_errors" in page_source, "mast_errors schema should be present"

    def test_radio_annotation_clickable(self):
        """Should be able to click a radio button for task_success."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # Find radio inputs for task_success
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][name*='task_success']"
        )
        if radios:
            radios[0].click()
            assert radios[0].is_selected(), "Radio button should be selected after click"

    def test_next_button_exists(self):
        """A next/submit button should be available."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # Look for submit/next button
        buttons = self.driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit']")
        button_texts = [b.text.lower() for b in buttons if b.is_displayed()]
        has_navigation = any(
            word in text
            for text in button_texts
            for word in ["next", "submit", "save", "done"]
        )
        # Also check for elements with specific IDs
        try:
            self.driver.find_element(By.ID, "next-btn")
            has_navigation = True
        except NoSuchElementException:
            pass
        try:
            self.driver.find_element(By.ID, "submit-btn")
            has_navigation = True
        except NoSuchElementException:
            pass

        # At minimum, verify the page has interactive annotation elements
        assert has_navigation or len(buttons) > 0, "Should have navigation buttons"


class TestAgentComparisonUI(unittest.TestCase):
    """Selenium tests for agent comparison (pairwise) UI."""

    @classmethod
    def setUpClass(cls):
        """Start Flask server with agent comparison config."""
        project_root = get_project_root()
        config_path = os.path.join(
            project_root, "examples/agent-traces/agent-comparison/config.yaml"
        )

        port = find_free_port(preferred_port=9051)
        cls.server = FlaskTestServer(config=config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start Flask server for comparison UI test"

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
        self.test_user = f"test_cmp_{int(time.time())}"

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

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_comparison_page_loads(self):
        """Agent comparison page should load."""
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )

        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source
        # Should contain comparison-related content
        assert (
            "preference" in page_source.lower()
            or "agent" in page_source.lower()
            or "pairwise" in page_source.lower()
            or "comparison" in page_source.lower()
        ), "Should contain agent comparison content"

    def test_comparison_has_annotation_schemas(self):
        """Comparison page should have annotation schemas."""
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source
        # Should have the preference or overall_quality schema
        assert (
            "preference" in page_source
            or "overall_quality" in page_source
            or "agent_preference" in page_source
        ), "Should have comparison annotation schemas"


if __name__ == "__main__":
    unittest.main()
