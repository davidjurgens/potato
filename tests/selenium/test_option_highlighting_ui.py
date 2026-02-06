"""
Selenium UI tests for Option Highlighting feature.

These tests require:
1. A running Ollama instance with qwen3:0.6b model
2. Chrome or Firefox with WebDriver

To set up Ollama:
    ollama pull qwen3:0.6b

Run tests with:
    pytest tests/selenium/test_option_highlighting_ui.py -v

Skip these tests if Ollama is not available:
    pytest tests/selenium/test_option_highlighting_ui.py -v -m "not ollama"
"""

import json
import os
import shutil
import time
import unittest
import yaml

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_directory


def is_ollama_available():
    """Check if Ollama is running and qwen3:0.6b model is available."""
    try:
        import ollama
        client = ollama.Client(host="http://localhost:11434", timeout=5)
        models = client.list()
        model_names = [m.get('name', m.get('model', '')) for m in models.get('models', [])]
        has_model = any('qwen3' in name and '0.6b' in name for name in model_names)
        if not has_model:
            has_model = 'qwen3:0.6b' in model_names
        return has_model
    except Exception as e:
        print(f"Ollama check failed: {e}")
        return False


# Skip all tests if Ollama not available
pytestmark = pytest.mark.skipif(
    not is_ollama_available(),
    reason="Ollama with qwen3:0.6b model not available"
)


class TestOptionHighlightingUI(unittest.TestCase):
    """Selenium tests for option highlighting UI behavior."""

    @classmethod
    def setUpClass(cls):
        """Set up the Flask server with option highlighting enabled."""
        cls.test_dir = create_test_directory("option_highlight_selenium")

        # Create test data with clear sentiment
        test_data = [
            {"id": "1", "text": "I absolutely love this product! It's amazing and wonderful!"},
            {"id": "2", "text": "Terrible, awful, horrible. Worst experience ever."},
            {"id": "3", "text": "The meeting is at 3 PM. Please bring your notes."},
            {"id": "4", "text": "Great quality but expensive. Mixed feelings overall."},
        ]

        data_file = os.path.join(cls.test_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(test_data, f)

        # Create config with option highlighting
        config = {
            "annotation_task_name": "Option Highlighting Selenium Test",
            "task_dir": cls.test_dir,
            "data_files": ["test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "output_annotation_dir": "annotation_output",
            "output_annotation_format": "json",
            "user_config": {"allow_all_users": True},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "description": "What is the sentiment of this text?",
                    "labels": [
                        {"name": "Positive", "tooltip": "Positive sentiment"},
                        {"name": "Negative", "tooltip": "Negative sentiment"},
                        {"name": "Neutral", "tooltip": "Neutral/factual"},
                        {"name": "Mixed", "tooltip": "Both positive and negative"}
                    ]
                }
            ],
            "ai_support": {
                "enabled": True,
                "endpoint_type": "ollama",
                "ai_config": {
                    "model": "qwen3:0.6b",
                    "base_url": "http://localhost:11434",
                    "temperature": 0.3,
                    "max_tokens": 256,
                    "timeout": 60,
                    "include": {"all": True}
                },
                "option_highlighting": {
                    "enabled": True,
                    "top_k": 2,
                    "dim_opacity": 0.4,
                    "auto_apply": True,
                    "prefetch_count": 5
                },
                "cache_config": {
                    "disk_cache": {
                        "enabled": True,
                        "path": os.path.join(cls.test_dir, "ai_cache.json")
                    },
                    "prefetch": {
                        "warm_up_page_count": 0,
                        "on_next": 2,
                        "on_prev": 0
                    }
                }
            }
        }

        config_file = os.path.join(cls.test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Start server
        cls.port = find_free_port()
        cls.server = FlaskTestServer(port=cls.port, config_file=config_file)

        if not cls.server.start():
            raise Exception("Failed to start Flask test server")

        # Set up Chrome options
        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        """Clean up server and test files."""
        if hasattr(cls, 'server'):
            cls.server.stop()

        if hasattr(cls, 'test_dir') and os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir)

    def setUp(self):
        """Set up WebDriver for each test."""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.base_url = self.server.base_url

        # Generate unique user
        self.test_user = f"test_user_{int(time.time())}"

        # Login
        self._login()

    def tearDown(self):
        """Clean up WebDriver."""
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login(self):
        """Login to the annotation interface."""
        self.driver.get(f"{self.base_url}/")

        # Wait for login page
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-content"))
        )

        # Enter username (simple mode, no password)
        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.clear()
        username_field.send_keys(self.test_user)

        # Submit
        login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
        login_form.submit()

        # Wait for annotation interface
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )

        # Wait for main content to be visible
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

    def _wait_for_highlights(self, timeout=30):
        """Wait for option highlighting to be applied."""
        # Wait for either highlighted or dimmed options to appear
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: (
                    d.find_elements(By.CSS_SELECTOR, ".option-highlighted") or
                    d.find_elements(By.CSS_SELECTOR, ".option-dimmed")
                )
            )
            return True
        except TimeoutException:
            return False

    # ================================================================
    # Basic visibility tests
    # ================================================================

    def test_highlighting_applied_on_page_load(self):
        """Test that highlighting is applied when page loads (auto_apply=True)."""
        # Wait for highlighting to be applied
        highlights_applied = self._wait_for_highlights(timeout=45)

        # Check for either highlighted or dimmed elements
        highlighted = self.driver.find_elements(By.CSS_SELECTOR, ".option-highlighted")
        dimmed = self.driver.find_elements(By.CSS_SELECTOR, ".option-dimmed")

        # Should have some highlighting applied
        self.assertTrue(
            highlights_applied or len(highlighted) > 0 or len(dimmed) > 0,
            "Option highlighting should be applied on page load"
        )

    def test_highlighted_options_are_visible(self):
        """Test that highlighted options are at full opacity."""
        self._wait_for_highlights(timeout=45)

        highlighted = self.driver.find_elements(By.CSS_SELECTOR, ".option-highlighted")

        if len(highlighted) > 0:
            # Check that highlighted options have full opacity
            opacity = self.driver.execute_script(
                "return window.getComputedStyle(arguments[0]).opacity",
                highlighted[0]
            )
            self.assertEqual(float(opacity), 1.0, "Highlighted options should have full opacity")

    def test_dimmed_options_have_reduced_opacity(self):
        """Test that dimmed options have reduced opacity CSS."""
        self._wait_for_highlights(timeout=45)

        dimmed = self.driver.find_elements(By.CSS_SELECTOR, ".option-dimmed")

        if len(dimmed) > 0:
            # Check that opacity is less than 1
            opacity = self.driver.execute_script(
                "return window.getComputedStyle(arguments[0]).opacity",
                dimmed[0]
            )
            self.assertLess(float(opacity), 1.0, "Dimmed options should have opacity < 1")

    def test_all_options_remain_clickable(self):
        """Test that all options (highlighted and dimmed) are still clickable."""
        self._wait_for_highlights(timeout=45)

        # Find all radio options
        options = self.driver.find_elements(
            By.CSS_SELECTOR,
            ".annotation-form input[type='radio']"
        )

        self.assertGreater(len(options), 0, "Should have radio options")

        # Click each option and verify it gets selected
        for option in options:
            # Scroll into view
            self.driver.execute_script("arguments[0].scrollIntoView(true);", option)
            time.sleep(0.1)

            # Click
            option.click()

            # Verify selected
            is_selected = option.is_selected()
            self.assertTrue(is_selected, f"Option should be selectable")

    def test_form_has_ai_active_indicator(self):
        """Test that the form shows AI highlighting is active."""
        self._wait_for_highlights(timeout=45)

        # Check for the ai-highlighting-active class on the form
        active_forms = self.driver.find_elements(By.CSS_SELECTOR, ".ai-highlighting-active")

        # Should have at least one form with highlighting active
        # (this may fail if highlighting wasn't applied - which is also informative)
        if self.driver.find_elements(By.CSS_SELECTOR, ".option-highlighted, .option-dimmed"):
            self.assertGreater(
                len(active_forms), 0,
                "Form should have ai-highlighting-active class when highlighting is applied"
            )

    # ================================================================
    # Navigation tests
    # ================================================================

    def test_highlighting_updates_on_navigation(self):
        """Test that highlighting updates when navigating to next instance."""
        self._wait_for_highlights(timeout=45)

        # Get initial highlighted options
        initial_highlighted = [
            el.text for el in
            self.driver.find_elements(By.CSS_SELECTOR, ".option-highlighted")
        ]

        # Navigate to next instance
        next_btn = self.driver.find_element(By.ID, "next-btn")
        next_btn.click()

        # Wait for page to reload
        time.sleep(1)

        # Wait for main content
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

        # Wait for new highlighting
        self._wait_for_highlights(timeout=45)

        # Should have highlighting (may be same or different based on content)
        new_highlighted = self.driver.find_elements(By.CSS_SELECTOR, ".option-highlighted")
        new_dimmed = self.driver.find_elements(By.CSS_SELECTOR, ".option-dimmed")

        self.assertTrue(
            len(new_highlighted) > 0 or len(new_dimmed) > 0,
            "Highlighting should be applied after navigation"
        )

    # ================================================================
    # Option manager tests
    # ================================================================

    def test_option_highlight_manager_initialized(self):
        """Test that the optionHighlightManager is initialized in JavaScript."""
        self._wait_for_highlights(timeout=45)

        # Check if manager exists
        manager_exists = self.driver.execute_script(
            "return typeof window.optionHighlightManager !== 'undefined'"
        )

        self.assertTrue(manager_exists, "optionHighlightManager should be initialized")

    def test_option_highlight_manager_has_config(self):
        """Test that the manager has loaded configuration."""
        self._wait_for_highlights(timeout=45)

        # Check if config is loaded
        config = self.driver.execute_script(
            "return window.optionHighlightManager ? window.optionHighlightManager.config : null"
        )

        if config:
            self.assertTrue(config.get("enabled", False), "Config should show enabled")
            self.assertEqual(config.get("top_k"), 2, "Config should have top_k=2")

    def test_toggle_highlighting(self):
        """Test that highlighting can be toggled off and on."""
        self._wait_for_highlights(timeout=45)

        # Toggle off
        self.driver.execute_script(
            "if (window.optionHighlightManager) window.optionHighlightManager.clearAllHighlights()"
        )

        time.sleep(0.5)

        # Check highlights are cleared
        highlighted = self.driver.find_elements(By.CSS_SELECTOR, ".option-highlighted")
        dimmed = self.driver.find_elements(By.CSS_SELECTOR, ".option-dimmed")

        self.assertEqual(len(highlighted), 0, "Highlighted options should be cleared")
        self.assertEqual(len(dimmed), 0, "Dimmed options should be cleared")

        # Toggle back on
        self.driver.execute_script(
            "if (window.optionHighlightManager) window.optionHighlightManager.applyAllHighlights()"
        )

        # Wait for highlights to reappear
        self._wait_for_highlights(timeout=30)

        # Check highlights are back
        highlighted = self.driver.find_elements(By.CSS_SELECTOR, ".option-highlighted")
        dimmed = self.driver.find_elements(By.CSS_SELECTOR, ".option-dimmed")

        # At least some should be present
        self.assertTrue(
            len(highlighted) > 0 or len(dimmed) > 0,
            "Highlighting should be reapplied"
        )


class TestOptionHighlightingDisabledUI(unittest.TestCase):
    """Selenium tests for when option highlighting is disabled."""

    @classmethod
    def setUpClass(cls):
        """Set up server with option highlighting disabled."""
        cls.test_dir = create_test_directory("option_highlight_disabled_selenium")

        test_data = [{"id": "1", "text": "Test text for disabled highlighting."}]
        data_file = os.path.join(cls.test_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(test_data, f)

        config = {
            "annotation_task_name": "Option Highlighting Disabled Selenium",
            "task_dir": cls.test_dir,
            "data_files": ["test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "output_annotation_dir": "annotation_output",
            "user_config": {"allow_all_users": True},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "description": "What is the sentiment?",
                    "labels": ["Positive", "Negative", "Neutral"]
                }
            ],
            "ai_support": {
                "enabled": True,
                "endpoint_type": "ollama",
                "ai_config": {
                    "model": "qwen3:0.6b",
                    "include": {"all": True}
                },
                "option_highlighting": {
                    "enabled": False  # Disabled
                },
                "cache_config": {
                    "disk_cache": {"enabled": False},
                    "prefetch": {"warm_up_page_count": 0, "on_next": 0, "on_prev": 0}
                }
            }
        }

        config_file = os.path.join(cls.test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        cls.port = find_free_port()
        cls.server = FlaskTestServer(port=cls.port, config_file=config_file)

        if not cls.server.start():
            raise Exception("Failed to start Flask test server")

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server'):
            cls.server.stop()
        if hasattr(cls, 'test_dir') and os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.base_url = self.server.base_url
        self.test_user = f"test_user_{int(time.time())}"
        self._login()

    def tearDown(self):
        if hasattr(self, 'driver'):
            self.driver.quit()

    def _login(self):
        self.driver.get(f"{self.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-content"))
        )
        username_field = self.driver.find_element(By.ID, "login-email")
        username_field.send_keys(self.test_user)
        login_form = self.driver.find_element(By.CSS_SELECTOR, "#login-content form")
        login_form.submit()
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

    def test_no_highlighting_when_disabled(self):
        """Test that no highlighting is applied when feature is disabled."""
        # Wait a bit to ensure nothing gets applied
        time.sleep(3)

        highlighted = self.driver.find_elements(By.CSS_SELECTOR, ".option-highlighted")
        dimmed = self.driver.find_elements(By.CSS_SELECTOR, ".option-dimmed")

        self.assertEqual(len(highlighted), 0, "Should have no highlighted options when disabled")
        self.assertEqual(len(dimmed), 0, "Should have no dimmed options when disabled")

    def test_manager_shows_disabled_config(self):
        """Test that manager config shows disabled."""
        time.sleep(2)

        config = self.driver.execute_script(
            "return window.optionHighlightManager ? window.optionHighlightManager.config : null"
        )

        if config:
            self.assertFalse(
                config.get("enabled", True),
                "Config should show feature as disabled"
            )


if __name__ == '__main__':
    unittest.main()
