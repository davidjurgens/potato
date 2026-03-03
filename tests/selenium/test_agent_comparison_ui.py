"""
Selenium tests for agent comparison (pairwise A/B) UI.

Tests the agent-comparison config which uses:
- Dialogue display for both agent traces (A then B)
- 5 radio schemas for pairwise preferences
- Multirate schema for per-dimension ratings
- Text schema for preference reasoning
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


class TestAgentComparisonInteraction(unittest.TestCase):
    """Test deeper interactions with the agent comparison (pairwise) UI."""

    @classmethod
    def setUpClass(cls):
        project_root = get_project_root()
        config_path = os.path.join(
            project_root,
            "examples/agent-traces/agent-comparison/config.yaml",
        )
        port = find_free_port(preferred_port=9071)
        cls.server = FlaskTestServer(config=config_path, port=port)
        started = cls.server.start()
        assert started, "Failed to start server for agent comparison test"
        cls.chrome_options = create_chrome_options()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"cmp_{int(time.time() * 1000) % 100000}"
        login_user(self.driver, self.server.base_url, self.test_user)

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    # --- Pairwise radio schemas ---

    def test_overall_preference_radio_present(self):
        """overall_preference radio schema should render with 5 options."""
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][name*='overall_preference']"
        )
        assert len(radios) >= 5, \
            f"overall_preference should have at least 5 options, got {len(radios)}"

    def test_overall_preference_radio_clickable(self):
        """Should be able to click overall_preference radio buttons."""
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][name*='overall_preference']"
        )
        if not radios:
            self.skipTest("No overall_preference radios found")
        radios[0].click()
        time.sleep(0.2)
        assert radios[0].is_selected(), "Radio should be selected after click"

    def test_completeness_radio_present(self):
        """completeness comparison radio should be present."""
        page_source = self.driver.page_source
        assert "completeness" in page_source, \
            "completeness schema should be present"

    def test_efficiency_radio_present(self):
        """efficiency comparison radio should be present."""
        page_source = self.driver.page_source
        assert "efficiency" in page_source, "efficiency schema should be present"

    def test_accuracy_radio_present(self):
        """accuracy comparison radio should be present."""
        page_source = self.driver.page_source
        assert "accuracy" in page_source, "accuracy schema should be present"

    def test_helpfulness_radio_present(self):
        """helpfulness comparison radio should be present."""
        page_source = self.driver.page_source
        assert "helpfulness" in page_source, "helpfulness schema should be present"

    def test_all_comparison_radios_have_three_options(self):
        """Each comparison schema (completeness, efficiency, accuracy, helpfulness)
        should have agent_a/tie/agent_b options."""
        for schema_name in ["completeness", "efficiency", "accuracy", "helpfulness"]:
            radios = self.driver.find_elements(
                By.CSS_SELECTOR,
                f"input[type='radio'][name*='{schema_name}']"
            )
            assert len(radios) >= 3, \
                f"{schema_name} should have at least 3 options, got {len(radios)}"

    def test_radio_mutual_exclusion(self):
        """Clicking a different radio in the same group should deselect the first."""
        radios = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio'][name*='overall_preference']"
        )
        if len(radios) < 2:
            self.skipTest("Need at least 2 radios for mutual exclusion test")

        radios[0].click()
        time.sleep(0.2)
        assert radios[0].is_selected()

        radios[1].click()
        time.sleep(0.2)
        assert radios[1].is_selected()
        assert not radios[0].is_selected(), \
            "First radio should be deselected after clicking second"

    # --- Multirate schema ---

    def test_multirate_table_renders(self):
        """dimension_ratings multirate schema should render as a table."""
        page_source = self.driver.page_source
        assert "dimension_ratings" in page_source, \
            "dimension_ratings schema should be present"

        tables = self.driver.find_elements(
            By.CSS_SELECTOR, ".shadcn-multirate-table"
        )
        assert len(tables) > 0, "Should have a multirate table"

    def test_multirate_has_agent_labels(self):
        """Multirate table should contain Agent A and Agent B labels."""
        page_source = self.driver.page_source
        assert "Agent A" in page_source, "Should have Agent A labels"
        assert "Agent B" in page_source, "Should have Agent B labels"

    def test_multirate_radio_clickable(self):
        """Should be able to click multirate radio buttons."""
        multirate_radios = self.driver.find_elements(
            By.CSS_SELECTOR, ".shadcn-multirate-radio"
        )
        if not multirate_radios:
            self.skipTest("No multirate radio buttons found")

        multirate_radios[0].click()
        time.sleep(0.2)
        assert multirate_radios[0].is_selected(), \
            "Multirate radio should be selected after click"

    def test_multirate_has_rating_columns(self):
        """Multirate table should have rating columns 1-5."""
        page_source = self.driver.page_source
        # The config defines labels "1" through "5"
        for rating in ["1", "2", "3", "4", "5"]:
            assert f'value="{rating}"' in page_source or \
                   f"value='{rating}'" in page_source, \
                f"Multirate should have rating value {rating}"

    # --- Text input ---

    def test_text_input_present(self):
        """preference_reason text input should be present."""
        page_source = self.driver.page_source
        assert "preference_reason" in page_source, \
            "preference_reason text schema should be present"

    def test_text_input_editable(self):
        """Should be able to type in the preference_reason text area."""
        text_inputs = self.driver.find_elements(
            By.CSS_SELECTOR,
            "textarea[schema='preference_reason'],"
            " #preference_reason textarea,"
            " input[schema='preference_reason']"
        )
        if not text_inputs:
            # Try broader search
            text_inputs = self.driver.find_elements(
                By.CSS_SELECTOR, "textarea.annotation-input"
            )
        if not text_inputs:
            self.skipTest("No text input found for preference_reason")

        text_inputs[0].send_keys("Agent A was more thorough")
        time.sleep(0.2)
        value = text_inputs[0].get_attribute("value")
        assert "thorough" in value, "Text input should contain typed text"

    # --- Dialogue content ---

    def test_dialogue_contains_agent_traces(self):
        """Dialogue should display agent trace content."""
        page_source = self.driver.page_source
        has_traces = (
            "Agent (Thought)" in page_source
            or "Agent (Action)" in page_source
            or "Environment" in page_source
        )
        assert has_traces, "Dialogue should contain agent trace speaker names"

    def test_task_description_visible(self):
        """Task description should be visible on the page."""
        page_source = self.driver.page_source
        # Content from agent-comparisons.json
        has_task = (
            "task_description" in page_source
            or "Task" in page_source
        )
        assert has_task, "Task description should be present"


if __name__ == "__main__":
    unittest.main()
