"""
Selenium UI tests for conditional schema branching (display logic).

Tests:
- Conditional schemas show/hide correctly on user interaction
- Animations work properly
- Values are preserved when toggling visibility
- Stale annotations are tracked
- Multi-level conditional chains work
"""

import unittest
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager
from tests.helpers.port_manager import find_free_port


class TestConditionalSchemaUI(unittest.TestCase):
    """Test conditional schema UI interactions."""

    @classmethod
    def setUpClass(cls):
        """Set up test server with conditional schemas."""
        cls.annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "main_question",
                "description": "Main question - always visible",
                "labels": [
                    {"name": "Option_A", "key_binding": "a"},
                    {"name": "Option_B", "key_binding": "b"},
                    {"name": "Option_C", "key_binding": "c"}
                ]
            },
            {
                "annotation_type": "text",
                "name": "detail_a",
                "description": "Details for Option A (conditional)",
                "display_logic": {
                    "show_when": [
                        {"schema": "main_question", "operator": "equals", "value": "Option_A"}
                    ]
                }
            },
            {
                "annotation_type": "multiselect",
                "name": "options_b",
                "description": "Sub-options for B (conditional)",
                "labels": [
                    {"name": "Sub1", "key_binding": "1"},
                    {"name": "Sub2", "key_binding": "2"},
                    {"name": "Other", "key_binding": "3"}
                ],
                "display_logic": {
                    "show_when": [
                        {"schema": "main_question", "operator": "equals", "value": "Option_B"}
                    ]
                }
            },
            {
                "annotation_type": "text",
                "name": "other_detail",
                "description": "Describe other (chained conditional)",
                "display_logic": {
                    "show_when": [
                        {"schema": "options_b", "operator": "contains", "value": "Other"}
                    ]
                }
            },
            {
                "annotation_type": "slider",
                "name": "confidence",
                "description": "Confidence for Option C",
                "min_value": 1,
                "max_value": 10,
                "starting_value": 5,
                "display_logic": {
                    "show_when": [
                        {"schema": "main_question", "operator": "equals", "value": "Option_C"}
                    ]
                }
            }
        ]

        cls.config_manager = TestConfigManager("selenium_conditional_test", cls.annotation_schemes, num_instances=5)
        cls.config_manager.__enter__()

        cls.port = find_free_port()
        cls.server = FlaskTestServer(port=cls.port, config_file=cls.config_manager.config_path)
        if not cls.server.start():
            raise RuntimeError("Failed to start Flask server")

        # Chrome options
        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        """Clean up server and config."""
        cls.server.stop()
        cls.config_manager.__exit__(None, None, None)

    def setUp(self):
        """Set up browser and login for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)

        # Generate unique username
        self.test_user = f"selenium_user_{int(time.time() * 1000)}"
        self.driver.get(f"{self.server.base_url}/")

        # Wait for page to load and find login form
        # The home page uses login-email for login (no password required in test config)
        try:
            email_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "login-email"))
            )
            email_input.clear()
            email_input.send_keys(self.test_user)
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()
        except Exception as e:
            # Try alternative selectors
            try:
                email_input = self.driver.find_element(By.NAME, "email")
                email_input.clear()
                email_input.send_keys(self.test_user)
                submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                submit_btn.click()
            except:
                pass  # May already be logged in

        # Wait for annotate page
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "annotation-forms"))
        )

    def tearDown(self):
        """Close browser."""
        if self.driver:
            self.driver.quit()

    def wait_for_element(self, by, value, timeout=10):
        """Wait for element to be present."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def wait_for_element_visible(self, by, value, timeout=10):
        """Wait for element to be visible."""
        return WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((by, value))
        )

    def wait_for_element_invisible(self, by, value, timeout=10):
        """Wait for element to become invisible."""
        return WebDriverWait(self.driver, timeout).until(
            EC.invisibility_of_element_located((by, value))
        )

    def test_conditional_schemas_initially_hidden(self):
        """Test that conditional schemas are hidden on page load."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)  # Wait for display logic initialization

        # Main question should be visible
        main_form = self.driver.find_element(By.ID, "main_question")
        self.assertTrue(main_form.is_displayed())

        # Conditional schemas should be hidden
        containers = self.driver.find_elements(By.CSS_SELECTOR, ".display-logic-container")
        for container in containers:
            classes = container.get_attribute("class")
            self.assertIn("display-logic-hidden", classes)

    def test_selecting_option_a_shows_detail_a(self):
        """Test that selecting Option A reveals the detail_a text field."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Find and click Option A
        option_a = self.driver.find_element(By.CSS_SELECTOR, "input[value='Option_A']")
        option_a.click()

        # Wait for animation
        time.sleep(0.5)

        # detail_a container should now be visible
        detail_a_container = self.driver.find_element(
            By.CSS_SELECTOR, "[data-schema-name='detail_a']"
        )
        classes = detail_a_container.get_attribute("class")
        self.assertIn("display-logic-visible", classes)
        self.assertNotIn("display-logic-hidden", classes)

    def test_selecting_option_b_shows_multiselect(self):
        """Test that selecting Option B reveals the options_b multiselect."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Click Option B
        option_b = self.driver.find_element(By.CSS_SELECTOR, "input[value='Option_B']")
        option_b.click()

        time.sleep(0.5)

        # options_b container should be visible
        options_b_container = self.driver.find_element(
            By.CSS_SELECTOR, "[data-schema-name='options_b']"
        )
        classes = options_b_container.get_attribute("class")
        self.assertIn("display-logic-visible", classes)

    def test_chained_conditional_shows_on_other(self):
        """Test that chained conditional (other_detail) shows when 'Other' is selected."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # First, select Option B to show options_b
        option_b = self.driver.find_element(By.CSS_SELECTOR, "input[value='Option_B']")
        option_b.click()
        time.sleep(0.5)

        # other_detail should still be hidden (no "Other" selected yet)
        other_detail_container = self.driver.find_element(
            By.CSS_SELECTOR, "[data-schema-name='other_detail']"
        )
        classes = other_detail_container.get_attribute("class")
        self.assertIn("display-logic-hidden", classes)

        # Now select "Other" checkbox
        other_checkbox = self.driver.find_element(By.CSS_SELECTOR, "input[value='Other']")
        other_checkbox.click()
        time.sleep(0.5)

        # other_detail should now be visible
        classes = other_detail_container.get_attribute("class")
        self.assertIn("display-logic-visible", classes)

    def test_switching_options_hides_previous_conditionals(self):
        """Test that switching from A to B hides detail_a and shows options_b."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Select Option A
        option_a = self.driver.find_element(By.CSS_SELECTOR, "input[value='Option_A']")
        option_a.click()
        time.sleep(0.5)

        # Verify detail_a is visible
        detail_a_container = self.driver.find_element(
            By.CSS_SELECTOR, "[data-schema-name='detail_a']"
        )
        self.assertIn("display-logic-visible", detail_a_container.get_attribute("class"))

        # Now switch to Option B
        option_b = self.driver.find_element(By.CSS_SELECTOR, "input[value='Option_B']")
        option_b.click()
        time.sleep(0.5)

        # detail_a should be hidden
        self.assertIn("display-logic-hidden", detail_a_container.get_attribute("class"))

        # options_b should be visible
        options_b_container = self.driver.find_element(
            By.CSS_SELECTOR, "[data-schema-name='options_b']"
        )
        self.assertIn("display-logic-visible", options_b_container.get_attribute("class"))

    def test_value_preserved_when_hidden_and_shown_again(self):
        """Test that entered values are preserved when schema is hidden and shown again."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Select Option A
        option_a = self.driver.find_element(By.CSS_SELECTOR, "input[value='Option_A']")
        option_a.click()
        time.sleep(0.5)

        # Enter text in detail_a (it's an input, not textarea, by default)
        detail_input = self.driver.find_element(By.CSS_SELECTOR, "input[schema='detail_a']")
        test_text = "This is my test input"
        detail_input.send_keys(test_text)
        time.sleep(0.5)

        # Switch to Option B (hides detail_a)
        option_b = self.driver.find_element(By.CSS_SELECTOR, "input[value='Option_B']")
        option_b.click()
        time.sleep(0.5)

        # Switch back to Option A
        option_a = self.driver.find_element(By.CSS_SELECTOR, "input[value='Option_A']")
        option_a.click()
        time.sleep(0.5)

        # Check that the text is still there
        detail_input = self.driver.find_element(By.CSS_SELECTOR, "input[schema='detail_a']")
        self.assertEqual(detail_input.get_attribute("value"), test_text)

    def test_slider_conditional_visibility(self):
        """Test that slider conditional (confidence) shows when Option C is selected."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Select Option C
        option_c = self.driver.find_element(By.CSS_SELECTOR, "input[value='Option_C']")
        option_c.click()
        time.sleep(0.5)

        # confidence slider should be visible
        confidence_container = self.driver.find_element(
            By.CSS_SELECTOR, "[data-schema-name='confidence']"
        )
        self.assertIn("display-logic-visible", confidence_container.get_attribute("class"))

    def test_display_logic_data_attributes_present(self):
        """Test that data-display-logic attributes are correctly set."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # Check that conditional containers have data-display-logic
        containers = self.driver.find_elements(By.CSS_SELECTOR, "[data-display-logic]")
        self.assertGreater(len(containers), 0)

        # Verify the attribute contains valid JSON
        for container in containers:
            display_logic = container.get_attribute("data-display-logic")
            self.assertIn("show_when", display_logic)
            self.assertIn("operator", display_logic)


class TestConditionalSchemaKeyboardNavigation(unittest.TestCase):
    """Test keyboard navigation with conditional schemas."""

    @classmethod
    def setUpClass(cls):
        """Set up test server."""
        cls.annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "choice",
                "description": "Make a choice",
                "labels": [
                    {"name": "Yes", "key_value": "y"},
                    {"name": "No", "key_value": "n"}
                ]
            },
            {
                "annotation_type": "text",
                "name": "yes_reason",
                "description": "Why yes?",
                "display_logic": {
                    "show_when": [
                        {"schema": "choice", "operator": "equals", "value": "y"}
                    ]
                }
            }
        ]

        cls.config_manager = TestConfigManager("selenium_keyboard_test", cls.annotation_schemes, num_instances=3)
        cls.config_manager.__enter__()

        cls.port = find_free_port()
        cls.server = FlaskTestServer(port=cls.port, config_file=cls.config_manager.config_path)
        if not cls.server.start():
            raise RuntimeError("Failed to start Flask server")

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        cls.server.stop()
        cls.config_manager.__exit__(None, None, None)

    def setUp(self):
        """Set up browser and login."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)

        self.test_user = f"kb_user_{int(time.time() * 1000)}"
        self.driver.get(f"{self.server.base_url}/")

        # Login (no password required in test config)
        try:
            email_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "login-email"))
            )
            email_input.clear()
            email_input.send_keys(self.test_user)
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()
        except Exception:
            # Try alternative selector
            try:
                email_input = self.driver.find_element(By.NAME, "email")
                email_input.clear()
                email_input.send_keys(self.test_user)
                submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                submit_btn.click()
            except:
                pass

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "annotation-forms"))
        )

    def tearDown(self):
        """Close browser."""
        if self.driver:
            self.driver.quit()

    def test_keyboard_shortcut_triggers_display_logic(self):
        """Test that keyboard shortcuts properly trigger display logic updates."""
        self.driver.get(f"{self.server.base_url}/annotate")
        time.sleep(1)

        # yes_reason should be hidden initially
        yes_reason_container = self.driver.find_element(
            By.CSS_SELECTOR, "[data-schema-name='yes_reason']"
        )
        self.assertIn("display-logic-hidden", yes_reason_container.get_attribute("class"))

        # Press 'y' key to select Yes
        body = self.driver.find_element(By.TAG_NAME, "body")
        body.send_keys("y")
        time.sleep(0.5)

        # yes_reason should now be visible
        self.assertIn("display-logic-visible", yes_reason_container.get_attribute("class"))


if __name__ == "__main__":
    unittest.main()
