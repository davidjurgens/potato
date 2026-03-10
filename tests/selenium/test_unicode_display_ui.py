"""
Selenium test for issue #114: Unicode characters in annotation text should
display correctly in the browser UI.

Verifies that German umlauts, French accents, Chinese characters, and other
non-ASCII text are preserved when rendered in the annotation interface.
"""

import json
import os
import time
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


class TestUnicodeDisplayUI(unittest.TestCase):
    """
    Issue #114: Unicode characters must be preserved in the annotation UI.

    The old regex `[^\\x20-\\x7E\\n]` stripped all non-ASCII characters.
    The fix only removes control characters, preserving Unicode text.
    """

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(tests_dir, "output",
                                     f"unicode_display_ui_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)

        # Create test data with various Unicode scripts
        test_data = [
            {
                "id": "de_1",
                "text": "Gute Frage. Aber bei den Grünen ist jeder so. Ausnahmslos jeder"
            },
            {
                "id": "fr_1",
                "text": "Le résumé du café est très naïve et intéressant"
            },
            {
                "id": "zh_1",
                "text": "这是一个关于人工智能的测试文本"
            },
            {
                "id": "mixed_1",
                "text": "Der König möchte über die Brücke gehen 👑"
            },
        ]
        data_file = create_test_data_file(cls.test_dir, test_data)

        annotation_schemes = [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "What is the sentiment?",
            }
        ]

        cls.config_file = create_test_config(
            cls.test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Unicode Display Test",
            require_password=False,
        )

        cls.port = find_free_port()
        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file
        )
        started = cls.server.start_server()
        assert started, "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=10)

        cls.chrome_options = ChromeOptions()
        cls.chrome_options.add_argument("--headless=new")
        cls.chrome_options.add_argument("--no-sandbox")
        cls.chrome_options.add_argument("--disable-dev-shm-usage")
        cls.chrome_options.add_argument("--disable-gpu")
        cls.chrome_options.add_argument("--window-size=1920,1080")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.test_user = f"unicode_user_{int(time.time() * 1000)}"
        self._login()

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _login(self):
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(self.test_user)
        self.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit']"
        ).click()
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

    def _get_displayed_text(self):
        """Get the text content currently shown in the annotation interface."""
        # Try multiple selectors — the text could be in different containers
        for selector in ["#instance-text", "#text-content", ".display-field",
                         ".text-display-content"]:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, selector)
                text = el.text.strip()
                if text:
                    return text
            except Exception:
                continue
        # Fallback: get all body text
        return self.driver.find_element(By.TAG_NAME, "body").text

    def _navigate_to_instance(self, instance_id):
        """Navigate to a specific instance by ID."""
        self.driver.get(
            f"{self.server.base_url}/annotate?instance_id={instance_id}"
        )
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
        time.sleep(0.3)

    def test_german_umlauts_displayed(self):
        """German umlauts (ü, ö, ä) should appear correctly in the UI."""
        self._navigate_to_instance("de_1")
        text = self._get_displayed_text()

        self.assertIn("Grünen", text,
                       "German umlaut ü was stripped from displayed text")

    def test_french_accents_displayed(self):
        """French accented characters should appear correctly."""
        self._navigate_to_instance("fr_1")
        text = self._get_displayed_text()

        self.assertIn("résumé", text,
                       "French accent é was stripped from displayed text")
        self.assertIn("café", text,
                       "French accent é in café was stripped")
        self.assertIn("naïve", text,
                       "French diaeresis ï was stripped from displayed text")

    def test_chinese_characters_displayed(self):
        """Chinese characters should appear correctly."""
        self._navigate_to_instance("zh_1")
        text = self._get_displayed_text()

        self.assertIn("人工智能", text,
                       "Chinese characters were stripped from displayed text")

    def test_mixed_unicode_with_emoji_displayed(self):
        """Mixed Unicode text with emoji should appear correctly."""
        self._navigate_to_instance("mixed_1")
        text = self._get_displayed_text()

        self.assertIn("König", text, "German ö was stripped")
        self.assertIn("möchte", text, "German ö was stripped")
        self.assertIn("Brücke", text, "German ü was stripped")


if __name__ == "__main__":
    unittest.main()
