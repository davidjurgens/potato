"""
Selenium tests for the LLM Chat Sidebar UI.

Tests the chat sidebar toggle, message sending/receiving, typing indicator,
history persistence across navigation, and keyboard isolation.

Requires a running Ollama server with llama3.2:1b.
"""

import json
import os
import time
import unittest

import pytest
import requests
import yaml
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_data_file,
    create_test_directory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434"
MODEL = "llama3.2:1b"


def ollama_available():
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if resp.status_code != 200:
            return False
        models = [m["name"] for m in resp.json().get("models", [])]
        return MODEL in models
    except Exception:
        return False


def _create_chat_config(test_dir, port):
    """Build a YAML config with chat_support enabled."""
    data = [
        {"id": "item_1", "text": "I absolutely love this product! Highly recommended."},
        {"id": "item_2", "text": "Terrible experience. Would not recommend to anyone."},
        {"id": "item_3", "text": "It works fine. Nothing special but gets the job done."},
    ]
    data_file = create_test_data_file(test_dir, data)

    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    config = {
        "annotation_task_name": f"Chat Sidebar UI Test {port}",
        "annotation_task_description": "Classify text sentiment.",
        "authentication": {"method": "in_memory"},
        "require_password": False,
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "Classify the overall sentiment of the text.",
            }
        ],
        "chat_support": {
            "enabled": True,
            "endpoint_type": "ollama",
            "ai_config": {
                "model": MODEL,
                "temperature": 0.3,
                "max_tokens": 100,
                "base_url": OLLAMA_URL,
                "timeout": 30,
            },
            "ui": {
                "title": "Ask AI",
                "placeholder": "Ask about this annotation...",
                "sidebar_width": 380,
            },
        },
        "task_dir": test_dir,
        "output_annotation_dir": output_dir,
        "port": port,
        "host": "0.0.0.0",
        "persist_sessions": False,
        "secret_key": "test-secret-key",
        "session_lifetime_days": 1,
        "user_config": {"allow_all_users": True, "users": []},
        "alert_time_each_instance": 10000000,
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config, f)
    return config_file


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not ollama_available(), reason=f"Ollama not available or {MODEL} not pulled")
class TestChatSidebarUI(unittest.TestCase):
    """Selenium tests for the LLM chat sidebar."""

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        cls.test_dir = os.path.join(
            tests_dir, "output", f"chat_sidebar_ui_{int(time.time())}"
        )
        os.makedirs(cls.test_dir, exist_ok=True)

        cls.port = find_free_port()
        cls.config_file = _create_chat_config(cls.test_dir, cls.port)

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
        self.test_user = f"chat_ui_{int(time.time() * 1000)}"
        self._login()

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    # ------------------------------------------------------------------
    # Auth helper
    # ------------------------------------------------------------------

    def _login(self):
        self.driver.get(f"{self.server.base_url}/")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "login-email"))
        )
        field = self.driver.find_element(By.ID, "login-email")
        field.clear()
        field.send_keys(self.test_user)
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        # Wait for annotation page
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "task_layout"))
        )
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

    def _wait(self, by, value, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def _wait_visible(self, by, value, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((by, value))
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_toggle_button_present_in_navbar(self):
        """The chat toggle button should appear in the navbar."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait(By.ID, "main-content")

        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        self.assertTrue(toggle.is_displayed())
        self.assertIn("Ask AI", toggle.text)

    def test_sidebar_opens_and_closes(self):
        """Clicking the toggle should open/close the sidebar."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait(By.ID, "main-content")

        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        sidebar = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-sidebar")

        # Initially closed (not visible — transform hides it)
        self.assertNotIn("open", sidebar.get_attribute("class"))

        # Click to open
        toggle.click()
        time.sleep(0.4)  # wait for animation
        self.assertIn("open", sidebar.get_attribute("class"))
        self.assertIn("active", toggle.get_attribute("class"))

        # Click to close
        toggle.click()
        time.sleep(0.4)
        self.assertNotIn("open", sidebar.get_attribute("class"))
        self.assertNotIn("active", toggle.get_attribute("class"))

    def test_close_button_closes_sidebar(self):
        """The X button inside the sidebar should close it."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait(By.ID, "main-content")

        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        toggle.click()
        time.sleep(0.4)

        close_btn = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-close-btn")
        close_btn.click()
        time.sleep(0.4)

        sidebar = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-sidebar")
        self.assertNotIn("open", sidebar.get_attribute("class"))

    def test_sidebar_has_input_and_send_button(self):
        """The sidebar should contain a textarea and send button."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait(By.ID, "main-content")

        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        toggle.click()
        time.sleep(0.4)

        textarea = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-input")
        self.assertTrue(textarea.is_displayed())
        self.assertEqual(textarea.get_attribute("placeholder"), "Ask about this annotation...")

        send_btn = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-send-btn")
        self.assertTrue(send_btn.is_displayed())
        self.assertEqual(send_btn.text, "Send")

    def test_send_message_and_receive_response(self):
        """Type a message, send it, and verify both user + assistant bubbles appear."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait(By.ID, "main-content")

        # Open sidebar
        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        toggle.click()
        time.sleep(0.4)

        # Type a message
        textarea = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-input")
        textarea.send_keys("Is this text positive or negative?")

        # Send
        send_btn = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-send-btn")
        send_btn.click()

        # User message should appear immediately
        WebDriverWait(self.driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".llm-chat-message.user"))
        )
        user_msg = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-message.user")
        self.assertEqual(user_msg.text, "Is this text positive or negative?")

        # Typing indicator should show
        typing = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-typing")
        # It may flash quickly, so just check it exists

        # Wait for assistant response (up to 30s for Ollama)
        WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".llm-chat-message.assistant")
            )
        )
        assistant_msg = self.driver.find_element(
            By.CSS_SELECTOR, ".llm-chat-message.assistant"
        )
        self.assertTrue(len(assistant_msg.text) > 0, "Assistant response should be non-empty")

    def test_enter_sends_message(self):
        """Pressing Enter (without Shift) should send the message."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait(By.ID, "main-content")

        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        toggle.click()
        time.sleep(0.4)

        textarea = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-input")
        textarea.send_keys("Hello")
        textarea.send_keys(Keys.RETURN)

        # User message should appear
        WebDriverWait(self.driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".llm-chat-message.user"))
        )
        user_msg = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-message.user")
        self.assertEqual(user_msg.text, "Hello")

    def test_keyboard_isolation(self):
        """Typing in the chat input should NOT trigger annotation keyboard shortcuts."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait(By.ID, "main-content")

        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        toggle.click()
        time.sleep(0.4)

        textarea = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-input")
        # Type keys that are often used as keyboard shortcuts (1, 2, n, p)
        textarea.send_keys("1 2 n p test message")

        # The textarea should contain all the typed text (not intercepted)
        self.assertEqual(textarea.get_attribute("value"), "1 2 n p test message")

    def test_empty_state_shown_initially(self):
        """Before any messages, the sidebar should show an empty state message."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait(By.ID, "main-content")

        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        toggle.click()
        time.sleep(0.4)

        empty = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-empty")
        self.assertTrue(empty.is_displayed())
        self.assertIn("Ask a question", empty.text)

    def test_chat_history_persists_after_navigation(self):
        """Send a message, navigate Next then Previous, and verify the chat reloads."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait(By.ID, "main-content")

        # Open sidebar and send a message
        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        toggle.click()
        time.sleep(0.4)

        textarea = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-input")
        textarea.send_keys("History persistence test")
        self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-send-btn").click()

        # Wait for assistant response
        WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".llm-chat-message.assistant")
            )
        )

        # Close sidebar before navigating (avoids click interception)
        toggle.click()
        time.sleep(0.4)

        # Navigate to next instance (use JS click as fallback for safety)
        next_btn = self.driver.find_element(By.ID, "next-btn")
        self.driver.execute_script("arguments[0].click();", next_btn)
        time.sleep(1.5)

        # Navigate back to previous instance
        prev_btn = self.driver.find_element(By.ID, "prev-btn")
        self.driver.execute_script("arguments[0].click();", prev_btn)
        time.sleep(1.5)

        # Re-open sidebar
        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        toggle.click()
        time.sleep(1.5)  # wait for history to load via API

        # Verify chat messages are restored
        user_msgs = self.driver.find_elements(By.CSS_SELECTOR, ".llm-chat-message.user")
        assistant_msgs = self.driver.find_elements(
            By.CSS_SELECTOR, ".llm-chat-message.assistant"
        )
        self.assertGreaterEqual(len(user_msgs), 1, "User message should be restored")
        self.assertGreaterEqual(
            len(assistant_msgs), 1, "Assistant message should be restored"
        )
        self.assertEqual(user_msgs[0].text, "History persistence test")

    def test_chat_clears_on_new_instance(self):
        """Navigating to a different instance should clear the chat (no history there)."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait(By.ID, "main-content")

        # Open sidebar and send a message
        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        toggle.click()
        time.sleep(0.4)

        textarea = self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-input")
        textarea.send_keys("Message on instance 1")
        self.driver.find_element(By.CSS_SELECTOR, ".llm-chat-send-btn").click()

        # Wait for response
        WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".llm-chat-message.assistant")
            )
        )

        # Close sidebar before navigating (avoids click interception)
        toggle.click()
        time.sleep(0.4)

        # Navigate to next instance (use JS click for safety)
        next_btn = self.driver.find_element(By.ID, "next-btn")
        self.driver.execute_script("arguments[0].click();", next_btn)
        time.sleep(1.5)

        # Re-open sidebar on the new instance
        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)
        toggle.click()
        time.sleep(1.5)

        # On the new instance, chat should show empty state or no messages from instance 1
        msgs = self.driver.find_elements(By.CSS_SELECTOR, ".llm-chat-message")
        for msg in msgs:
            self.assertNotIn(
                "Message on instance 1",
                msg.text,
                "Previous instance's messages should not appear",
            )

    def test_body_class_added_when_open(self):
        """Opening the sidebar should add llm-chat-open class to body."""
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait(By.ID, "main-content")

        toggle = self._wait(By.CSS_SELECTOR, ".llm-chat-toggle-btn", timeout=5)

        # Not open initially
        body_classes = self.driver.find_element(By.TAG_NAME, "body").get_attribute("class")
        self.assertNotIn("llm-chat-open", body_classes)

        # Open
        toggle.click()
        time.sleep(0.4)
        body_classes = self.driver.find_element(By.TAG_NAME, "body").get_attribute("class")
        self.assertIn("llm-chat-open", body_classes)

        # Close
        toggle.click()
        time.sleep(0.4)
        body_classes = self.driver.find_element(By.TAG_NAME, "body").get_attribute("class")
        self.assertNotIn("llm-chat-open", body_classes)


if __name__ == "__main__":
    unittest.main()
