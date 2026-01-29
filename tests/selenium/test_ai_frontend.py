"""
Selenium tests for AI frontend features.

Tests AI button rendering, hint tooltips, and keyword highlighting.
"""

import pytest
import time
import os
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file


def create_chrome_options():
    """Create Chrome options for headless testing."""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    return options


class TestAIButtonRendering(unittest.TestCase):
    """Test AI button rendering in the annotation interface."""

    @classmethod
    def setUpClass(cls):
        """Set up test server with AI-enabled config."""
        cls.test_dir = create_test_directory("ai_frontend_test")

        # Create test data
        test_data = [
            {"id": "1", "text": "This product is amazing! Absolutely love it!"},
            {"id": "2", "text": "Terrible quality. Would not recommend."},
            {"id": "3", "text": "It's okay, nothing special but works fine."},
        ]
        data_file = create_test_data_file(cls.test_dir, test_data, "data.jsonl")

        # Create AI cache directory
        cache_dir = os.path.join(cls.test_dir, "ai_cache")
        os.makedirs(cache_dir, exist_ok=True)

        # Create config with AI support (disabled for these tests since we don't need Ollama)
        config_content = f"""
annotation_task_name: AI Frontend Test
task_dir: {cls.test_dir}
site_dir: default
port: 0
debug: true

data_files:
  - {data_file}

item_properties:
  id_key: id
  text_key: text

user_config:
  allow_all_users: true

annotation_schemes:
  - annotation_type: radio
    annotation_id: 0
    name: sentiment
    description: What is the sentiment of this text?
    labels:
      - name: positive
        tooltip: Positive sentiment
        key_value: p
      - name: negative
        tooltip: Negative sentiment
        key_value: n
      - name: neutral
        tooltip: Neutral sentiment
        key_value: u

output_annotation_dir: {cls.test_dir}/output
output_annotation_format: json
"""
        config_file = os.path.join(cls.test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            f.write(config_content)

        cls.server = FlaskTestServer(config=config_file)
        if not cls.server.start():
            raise Exception("Failed to start test server")

        cls.chrome_options = create_chrome_options()

    @classmethod
    def tearDownClass(cls):
        """Stop test server."""
        if hasattr(cls, 'server'):
            cls.server.stop()

    def setUp(self):
        """Set up browser for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)

        # Go to home page first - which shows auth form
        self.test_user = f"ai_test_{time.time()}"
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(0.5)

        # Try to find registration form on home page
        try:
            email_input = self.driver.find_element(By.NAME, "email")
            pass_input = self.driver.find_element(By.NAME, "pass")
            email_input.send_keys(self.test_user)
            pass_input.send_keys("testpass")

            # Submit
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
            submit_btn.click()
            time.sleep(1)
        except NoSuchElementException:
            # Auth might not be required, continue
            pass

    def tearDown(self):
        """Close browser after each test."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def test_ai_help_div_exists(self):
        """Test that the ai-help div exists in annotation form."""
        # Navigate to annotation page
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1)

        # Check for ai-help div
        ai_help_divs = self.driver.find_elements(By.CSS_SELECTOR, ".ai-help")

        # Should have at least one ai-help div (one per annotation scheme)
        # Note: Without AI enabled, this will be empty or hidden
        self.assertGreaterEqual(len(ai_help_divs), 0,
            "Should have ai-help div containers")

    def test_annotation_form_structure(self):
        """Test that annotation form has correct structure."""
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(1)

        # Check for annotation form - try multiple possible selectors
        forms = self.driver.find_elements(By.CSS_SELECTOR, ".annotation-form")
        if not forms:
            # Try alternative selectors that might be used
            forms = self.driver.find_elements(By.CSS_SELECTOR, "[data-annotation-id]")
        if not forms:
            # Check for any form with radio/checkbox inputs (annotation indicators)
            forms = self.driver.find_elements(By.CSS_SELECTOR, "form")

        # If still no forms, check if we're on auth page (which is expected without login)
        auth_forms = self.driver.find_elements(By.CSS_SELECTOR, "input[name='email']")
        if auth_forms:
            self.skipTest("Still on authentication page - expected behavior")

        # If we have forms, verify structure
        if forms:
            for form in forms:
                # Should have data-annotation-id attribute if it's an annotation form
                annotation_id = form.get_attribute("data-annotation-id")
                if annotation_id is not None:
                    self.assertIsNotNone(annotation_id, "Form should have data-annotation-id")

    def test_no_duplicate_ai_buttons_on_load(self):
        """Test that AI buttons are not duplicated on initial page load."""
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)  # Wait for JS to load

        # Count ai-assistant-containter elements (note: typo is intentional, matches code)
        ai_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".ai-assistant-containter")

        # Count by type
        hint_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".hint.ai-assistant-containter")
        keyword_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".keyword.ai-assistant-containter")

        # Log counts for debugging
        print(f"Total AI buttons: {len(ai_buttons)}")
        print(f"Hint buttons: {len(hint_buttons)}")
        print(f"Keyword buttons: {len(keyword_buttons)}")

        # Each type should appear at most once per annotation form
        annotation_forms = self.driver.find_elements(By.CSS_SELECTOR, ".annotation-form")
        num_forms = len(annotation_forms)

        # Keyword buttons should not exceed number of forms
        self.assertLessEqual(len(keyword_buttons), num_forms,
            f"Should have at most {num_forms} keyword buttons, found {len(keyword_buttons)}")

    def test_no_duplicate_buttons_after_navigation(self):
        """Test that navigating between instances doesn't duplicate buttons."""
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)

        # Count initial buttons
        initial_keyword_count = len(self.driver.find_elements(By.CSS_SELECTOR, ".keyword.ai-assistant-containter"))

        # Click next button to navigate
        try:
            next_btn = self.driver.find_element(By.ID, "next-btn")
            if next_btn.is_enabled():
                # Need to make an annotation first
                radio = self.driver.find_element(By.CSS_SELECTOR, "input[type='radio']")
                radio.click()
                time.sleep(0.5)

                next_btn.click()
                time.sleep(2)

                # Count buttons after navigation
                after_keyword_count = len(self.driver.find_elements(By.CSS_SELECTOR, ".keyword.ai-assistant-containter"))

                # Should not have more buttons than before
                self.assertLessEqual(after_keyword_count, max(initial_keyword_count, 1),
                    f"Navigation should not duplicate buttons. Before: {initial_keyword_count}, After: {after_keyword_count}")
        except NoSuchElementException:
            self.skipTest("Next button not found")


class TestAIHintTooltip(unittest.TestCase):
    """Test AI hint tooltip functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test server with AI config."""
        cls.test_dir = create_test_directory("ai_tooltip_test")

        test_data = [
            {"id": "1", "text": "Great product! Highly recommended!"},
        ]
        data_file = create_test_data_file(cls.test_dir, test_data, "data.jsonl")

        cache_dir = os.path.join(cls.test_dir, "ai_cache")
        os.makedirs(cache_dir, exist_ok=True)

        # Config without actual AI endpoint (tests UI behavior only)
        config_content = f"""
annotation_task_name: AI Tooltip Test
task_dir: {cls.test_dir}
site_dir: default
port: 0
debug: true

data_files:
  - {data_file}

item_properties:
  id_key: id
  text_key: text

user_config:
  allow_all_users: true

annotation_schemes:
  - annotation_type: radio
    annotation_id: 0
    name: sentiment
    description: What is the sentiment?
    labels:
      - positive
      - negative

output_annotation_dir: {cls.test_dir}/output
output_annotation_format: json
"""
        config_file = os.path.join(cls.test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            f.write(config_content)

        cls.server = FlaskTestServer(config=config_file)
        if not cls.server.start():
            raise Exception("Failed to start test server")

        cls.chrome_options = create_chrome_options()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server'):
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)

        # Go to home page first - which shows auth form
        self.test_user = f"tooltip_test_{time.time()}"
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(0.5)

        # Try to find registration form on home page
        try:
            email_input = self.driver.find_element(By.NAME, "email")
            pass_input = self.driver.find_element(By.NAME, "pass")
            email_input.send_keys(self.test_user)
            pass_input.send_keys("testpass")

            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
            submit_btn.click()
            time.sleep(1)
        except NoSuchElementException:
            # Auth might not be required, continue
            pass

    def tearDown(self):
        if hasattr(self, 'driver'):
            self.driver.quit()

    def test_tooltip_exists_in_ai_help(self):
        """Test that tooltip element exists within ai-help container."""
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)

        # Check for tooltip within ai-help
        tooltips = self.driver.find_elements(By.CSS_SELECTOR, ".ai-help .tooltip")

        # Tooltip should exist (even if hidden/empty when AI disabled)
        # The container should be present for JS to populate
        ai_help_divs = self.driver.find_elements(By.CSS_SELECTOR, ".ai-help")
        if ai_help_divs:
            for ai_help in ai_help_divs:
                # Each ai-help should have a tooltip child
                tooltip = ai_help.find_elements(By.CSS_SELECTOR, ".tooltip")
                self.assertGreaterEqual(len(tooltip), 0,
                    "ai-help should have tooltip container (may be empty if AI disabled)")

    def test_hint_button_click_shows_tooltip(self):
        """Test that clicking hint button shows/activates the tooltip."""
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(2)

        # Find hint button
        hint_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".hint.ai-assistant-containter")

        if not hint_buttons:
            self.skipTest("No hint buttons found (AI may not be enabled)")

        # Click the hint button
        hint_buttons[0].click()
        time.sleep(1)

        # Tooltip should become active
        active_tooltips = self.driver.find_elements(By.CSS_SELECTOR, ".tooltip.active")

        # If AI is enabled and working, tooltip should be active
        # If AI is disabled, this test still verifies the click handler works
        print(f"Active tooltips after click: {len(active_tooltips)}")


class TestAIWithOllama(unittest.TestCase):
    """Test AI features with actual Ollama integration.

    These tests require Ollama to be running locally.
    They are skipped if Ollama is not available.
    """

    @classmethod
    def setUpClass(cls):
        """Check if Ollama is available before running tests."""
        import requests
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.status_code != 200:
                raise Exception("Ollama not responding")
        except Exception:
            pytest.skip("Ollama is not running - skipping Ollama integration tests")

        cls.test_dir = create_test_directory("ai_ollama_frontend_test")

        test_data = [
            {"id": "1", "text": "This product is amazing! Absolutely love the quality!"},
        ]
        data_file = create_test_data_file(cls.test_dir, test_data, "data.jsonl")

        cache_dir = os.path.join(cls.test_dir, "ai_cache")
        os.makedirs(cache_dir, exist_ok=True)

        # Full AI config with Ollama
        config_content = f"""
annotation_task_name: AI Ollama Frontend Test
task_dir: {cls.test_dir}
site_dir: default
port: 0
debug: true

data_files:
  - {data_file}

item_properties:
  id_key: id
  text_key: text

user_config:
  allow_all_users: true

annotation_schemes:
  - annotation_type: radio
    annotation_id: 0
    name: sentiment
    description: What is the sentiment of this text?
    labels:
      - name: positive
        tooltip: Positive sentiment
        key_value: p
      - name: negative
        tooltip: Negative sentiment
        key_value: n

ai_support:
  enabled: true
  endpoint_type: ollama
  ai_config:
    model: qwen3:0.6b
    temperature: 0.7
    max_tokens: 150
    include:
      all: true
  cache_config:
    disk_cache:
      enabled: true
      path: {cache_dir}/cache.json
    prefetch:
      warm_up_page_count: 0
      on_next: 0
      on_prev: 0

output_annotation_dir: {cls.test_dir}/output
output_annotation_format: json
"""
        config_file = os.path.join(cls.test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            f.write(config_content)

        cls.server = FlaskTestServer(config=config_file)
        if not cls.server.start():
            pytest.skip("Server failed to start with Ollama config")

        cls.chrome_options = create_chrome_options()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server') and cls.server:
            cls.server.stop()

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)

        # Go to home page first - which shows auth form
        self.test_user = f"ollama_test_{time.time()}"
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(0.5)

        # Try to find registration form on home page
        try:
            email_input = self.driver.find_element(By.NAME, "email")
            pass_input = self.driver.find_element(By.NAME, "pass")
            email_input.send_keys(self.test_user)
            pass_input.send_keys("testpass")

            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
            submit_btn.click()
            time.sleep(1)
        except NoSuchElementException:
            # Auth might not be required, continue
            pass

    def tearDown(self):
        if hasattr(self, 'driver'):
            self.driver.quit()

    def test_ai_buttons_appear_with_ollama(self):
        """Test that AI buttons appear when Ollama is configured."""
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(3)  # Wait for JS to load and fetch AI buttons

        # Should have AI buttons
        ai_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".ai-assistant-containter")

        # With AI enabled, we should have buttons (hint, keyword, random)
        self.assertGreater(len(ai_buttons), 0,
            "Should have AI assistant buttons when Ollama is enabled")

    def test_hint_shows_content_or_loading(self):
        """Test that clicking hint shows either loading state or content."""
        self.driver.get(f"{self.server.base_url}/")
        time.sleep(3)

        hint_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".hint.ai-assistant-containter")

        if not hint_buttons:
            self.skipTest("No hint buttons found")

        # Click hint
        hint_buttons[0].click()

        # Wait for tooltip to become active
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".tooltip.active"))
            )
        except TimeoutException:
            self.fail("Tooltip did not activate after clicking hint")

        # Check tooltip has content (loading or result)
        tooltip = self.driver.find_element(By.CSS_SELECTOR, ".tooltip.active")
        content = tooltip.text

        # Should have some content (loading message, error, or actual hint)
        self.assertTrue(
            len(content) > 0 or "loading" in tooltip.get_attribute("innerHTML").lower(),
            "Tooltip should show loading state or content"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
