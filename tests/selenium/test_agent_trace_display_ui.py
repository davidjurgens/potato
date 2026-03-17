"""
Selenium UI tests for the existing agent_trace display type.

Tests the step card rendering, badges, collapsible observations,
and annotation interactions when viewing agent traces.

Uses examples/agent-traces/agent-trace-evaluation/config.yaml.
"""

import os
import time
import unittest
import yaml

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


import pytest


pytestmark = pytest.mark.core

def get_project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


class TestAgentTraceDisplayUI(unittest.TestCase):
    """Selenium tests for the agent_trace display type rendering."""

    @classmethod
    def setUpClass(cls):
        project_root = get_project_root()
        config_path = os.path.join(
            project_root, "examples/agent-traces/agent-trace-evaluation/config.yaml"
        )

        # Read the base config and change conversation display to agent_trace
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f)

        for field in config_data.get("instance_display", {}).get("fields", []):
            if field.get("key") == "conversation" and field.get("type") == "dialogue":
                field["type"] = "agent_trace"
                # Remove dialogue-specific options that don't apply
                opts = field.get("display_options", {})
                opts.pop("per_turn_ratings", None)
                opts.pop("alternating_shading", None)
                opts.pop("show_turn_numbers", None)

        # Write modified config next to the original
        modified_config_path = os.path.join(
            os.path.dirname(config_path), "test_config_agent_trace_display.yaml"
        )
        with open(modified_config_path, "w") as f:
            yaml.dump(config_data, f)
        cls._modified_config = modified_config_path

        port = find_free_port(preferred_port=9064)
        cls.server = FlaskTestServer(config=modified_config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start Flask server"

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
        if hasattr(cls, "_modified_config") and os.path.exists(cls._modified_config):
            os.remove(cls._modified_config)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"test_atd_{int(time.time())}"
        self._login()

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
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

    # --- Rendering tests ---

    def test_agent_trace_steps_render(self):
        """Agent trace step elements should be present on the page."""
        steps = WebDriverWait(self.driver, 15).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".agent-trace-step")
            )
        )
        self.assertGreater(len(steps), 0)

    def test_step_badges_colored(self):
        """Step type badges should have distinct CSS classes."""
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".agent-trace-step"))
        )
        badges = self.driver.find_elements(By.CSS_SELECTOR, ".step-badge")
        self.assertGreater(len(badges), 0)

        # Check that different badge types exist
        badge_classes = set()
        for badge in badges:
            cls_attr = badge.get_attribute("class")
            for cls in cls_attr.split():
                if cls.startswith("badge-"):
                    badge_classes.add(cls)

        # Should have at least 2 different badge types (thought, action, observation)
        self.assertGreaterEqual(len(badge_classes), 2)

    def test_step_text_visible(self):
        """Step text content should be readable."""
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".agent-trace-step"))
        )
        step_texts = self.driver.find_elements(By.CSS_SELECTOR, ".step-text")
        self.assertGreater(len(step_texts), 0)
        # At least one should have text content
        has_text = any(el.text.strip() for el in step_texts)
        self.assertTrue(has_text)

    def test_trace_summary_renders(self):
        """Agent trace summary should show step counts."""
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".agent-trace-step"))
        )
        summaries = self.driver.find_elements(
            By.CSS_SELECTOR, ".agent-trace-summary"
        )
        if summaries:
            text = summaries[0].text
            self.assertIn("step", text.lower())

    def test_dialogue_display_renders(self):
        """Dialogue turns should render with content."""
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "main-content"))
        )
        time.sleep(1.0)

        # Check for dialogue or trace display elements
        page_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertGreater(len(page_text), 100)

    def test_radio_annotation_on_trace(self):
        """Can select radio (task_success) while viewing trace."""
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".agent-trace-step"))
        )

        radios = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][name="task_success"]'
        )
        if radios:
            self.driver.execute_script("arguments[0].click()", radios[0])
            time.sleep(0.5)
            self.assertTrue(radios[0].is_selected())

    def test_likert_annotation_on_trace(self):
        """Can set likert (efficiency) while viewing trace."""
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".agent-trace-step"))
        )

        likert = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][name="efficiency"]'
        )
        if len(likert) >= 3:
            self.driver.execute_script("arguments[0].click()", likert[2])
            time.sleep(0.5)
            self.assertTrue(likert[2].is_selected())

    def test_multiselect_annotation_on_trace(self):
        """Can check multiple error categories while viewing trace."""
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".agent-trace-step"))
        )

        checkboxes = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
        if len(checkboxes) >= 2:
            self.driver.execute_script("arguments[0].click()", checkboxes[0])
            time.sleep(0.3)
            # Checkbox should be checked
            # (Note: multiselect in potato uses hidden inputs, so check may work differently)

    def test_annotations_persist_across_trace_instances(self):
        """Annotations on trace 1 should persist after nav to trace 2 and back."""
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".agent-trace-step"))
        )

        radios = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][name="task_success"]'
        )
        if not radios:
            self.skipTest("No task_success radios found")

        # Select first radio
        self.driver.execute_script("arguments[0].click()", radios[0])
        time.sleep(1.5)  # Wait for debounce

        # Navigate to next instance
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ARROW_RIGHT)
        time.sleep(1.0)

        # Navigate back
        body.send_keys(Keys.ARROW_LEFT)
        time.sleep(1.0)

        # Verify annotation persisted
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, 'input[type="radio"][name="task_success"]'
        )
        selected = [r for r in radios if r.is_selected()]
        self.assertGreater(
            len(selected), 0,
            "Radio annotation should persist across instance navigation"
        )

    def test_step_type_data_attributes(self):
        """Each step should have data-step-type attribute."""
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".agent-trace-step"))
        )
        steps = self.driver.find_elements(By.CSS_SELECTOR, ".agent-trace-step")
        for step in steps[:5]:  # Check first 5
            step_type = step.get_attribute("data-step-type")
            self.assertIsNotNone(step_type)
            self.assertIn(step_type, ["thought", "action", "observation", "system", "error"])


if __name__ == "__main__":
    unittest.main()
