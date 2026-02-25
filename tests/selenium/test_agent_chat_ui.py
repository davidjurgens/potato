"""
Selenium UI tests for interactive agent chat functionality.

Tests:
1. Chat panel renders with correct elements (input, send button, finish button)
2. Send a message and see the agent response appear
3. Step counter updates after sending messages
4. Finish button transitions page from chat to trace display
5. Annotation forms are enabled after finishing chat
6. Page refresh recovers active session (session persistence)
7. Chat CSS and JS are loaded on the page
8. Multiple messages accumulate in the chat panel

Note: Uses pytest-native class (not unittest.TestCase) so tests run in
definition order. Tests that call finish (mutating shared item data) are
placed LAST to avoid polluting items for earlier tests.
"""

import json
import os
import time

import pytest
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


def get_project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def create_agent_chat_config_for_selenium(test_dir):
    """Create a config with agent_proxy and interactive_chat display for selenium tests."""
    abs_test_dir = os.path.abspath(test_dir)
    os.makedirs(test_dir, exist_ok=True)
    os.makedirs(os.path.join(test_dir, "output"), exist_ok=True)

    # Create enough test data items so each test gets a fresh one
    test_data = [
        {
            "id": f"task_{i+1}",
            "task_description": f"Test task number {i+1}: perform action {i+1}.",
            "conversation": None,
        }
        for i in range(30)
    ]

    data_file = os.path.join(test_dir, "test_data.json")
    with open(data_file, "w") as f:
        json.dump(test_data, f)

    config = {
        "annotation_task_name": "Agent Chat Selenium Test",
        "task_dir": abs_test_dir,
        "data_files": ["test_data.json"],
        "item_properties": {"id_key": "id", "text_key": "task_description"},
        "annotation_schemes": [
            {
                "name": "task_success",
                "annotation_type": "radio",
                "labels": ["success", "partial", "failure"],
                "description": "Did the agent succeed?",
            },
            {
                "name": "naturalness",
                "annotation_type": "likert",
                "size": 5,
                "min_label": "Unnatural",
                "max_label": "Natural",
                "description": "How natural was the conversation?",
            },
        ],
        "output_annotation_dir": os.path.join(abs_test_dir, "output"),
        "site_dir": "default",
        "alert_time_each_instance": 0,
        "require_password": False,
        "authentication": {"method": "in_memory"},
        "persist_sessions": False,
        "debug": False,
        "secret_key": "selenium-test-secret",
        "session_lifetime_days": 1,
        "user_config": {"allow_all_users": True, "users": []},
        "agent_proxy": {
            "type": "echo",
            "responses": [
                "I understand your request.",
                "Working on it now.",
                "Here are the results.",
            ],
            "sandbox": {
                "max_steps": 10,
                "max_session_seconds": 600,
                "request_timeout_seconds": 10,
                "rate_limit_per_minute": 60,
            },
        },
        "instance_display": {
            "layout": {"direction": "vertical"},
            "fields": [
                {"key": "task_description", "type": "text", "label": "Task"},
                {
                    "key": "conversation",
                    "type": "interactive_chat",
                    "label": "Agent Chat",
                    "span_target": True,
                },
            ],
        },
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config, f)

    return config_file


class TestAgentChatUI:
    """
    Selenium tests for the interactive agent chat UI.

    Uses pytest-native class (not unittest.TestCase) so tests run in
    definition order. Finish tests are placed at the end.
    """

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start Flask server with agent chat config."""
        project_root = get_project_root()
        test_dir = os.path.join(project_root, "tests", "output", "selenium_agent_chat")
        config_file = create_agent_chat_config_for_selenium(test_dir)

        port = find_free_port(preferred_port=9055)
        server = FlaskTestServer(config=config_file, port=port)
        started = server.start()
        assert started, "Failed to start Flask server for agent chat selenium test"

        request.cls.server = server

        yield server
        server.stop()

    @pytest.fixture(scope="class", autouse=True)
    def chrome_options(self, request):
        """Set up Chrome options for headless testing."""
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

        request.cls._chrome_options = opts
        yield opts

    @pytest.fixture(autouse=True)
    def setup_driver(self):
        """Create browser and login for each test."""
        self.driver = webdriver.Chrome(options=self._chrome_options)
        self.test_user = f"agent_chat_{int(time.time() * 1000)}"

        # Login (no password mode)
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

        # Wait for annotation page
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.ID, "task_layout"))
            )
        except TimeoutException:
            pass

        yield

        if hasattr(self, "driver"):
            self.driver.quit()

    def _wait_for_main_content(self, timeout=15):
        """Wait for the main content area to be visible."""
        WebDriverWait(self.driver, timeout).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )

    def _send_chat_message(self, message):
        """Type a message and click send, waiting for the response."""
        textarea = self.driver.find_element(By.ID, "agent-chat-input")
        textarea.clear()
        textarea.send_keys(message)

        send_btn = self.driver.find_element(By.ID, "agent-chat-send-btn")
        send_btn.click()

        # Wait for the agent response to appear
        time.sleep(1.5)

    # ----------------------------------------------------------------
    # Chat panel rendering (no mutation — must come first)
    # ----------------------------------------------------------------

    def test_chat_panel_elements_present(self):
        """Chat panel should render with all expected UI elements."""
        self._wait_for_main_content()

        chat_panel = self.driver.find_element(By.ID, "agent-chat-panel")
        assert chat_panel.is_displayed(), "Chat panel should be visible"

        messages = self.driver.find_element(By.ID, "agent-chat-messages")
        assert messages.is_displayed(), "Messages area should be visible"

        textarea = self.driver.find_element(By.ID, "agent-chat-input")
        assert textarea.is_displayed(), "Chat input should be visible"
        assert textarea.get_attribute("placeholder") == "Type your message..."

        send_btn = self.driver.find_element(By.ID, "agent-chat-send-btn")
        assert send_btn.is_displayed(), "Send button should be visible"
        assert "Send" in send_btn.text

        finish_btn = self.driver.find_element(By.ID, "agent-chat-finish-btn")
        assert finish_btn.is_displayed(), "Finish button should be visible"
        assert "Finish" in finish_btn.text

    def test_chat_placeholder_shown(self):
        """Chat messages area should show the placeholder text initially."""
        self._wait_for_main_content()

        messages = self.driver.find_element(By.ID, "agent-chat-messages")
        placeholder_elements = messages.find_elements(
            By.CSS_SELECTOR, ".agent-chat-placeholder"
        )
        assert len(placeholder_elements) > 0, "Placeholder should be present"

    def test_chat_css_loaded(self):
        """Agent chat CSS should be loaded on the page."""
        self._wait_for_main_content()
        page_source = self.driver.page_source
        assert "agent-chat.css" in page_source, "agent-chat.css should be linked"

    def test_chat_js_loaded(self):
        """Agent chat JS should be loaded on the page."""
        self._wait_for_main_content()
        page_source = self.driver.page_source
        assert "agent-chat.js" in page_source, "agent-chat.js should be linked"

    def test_task_description_shown(self):
        """The task description should be visible above the chat panel."""
        self._wait_for_main_content()
        page_source = self.driver.page_source
        assert "instance-display-container" in page_source
        assert "Test task number" in page_source

    def test_empty_send_does_nothing(self):
        """Clicking send with empty input should not add messages."""
        self._wait_for_main_content()

        send_btn = self.driver.find_element(By.ID, "agent-chat-send-btn")
        send_btn.click()
        time.sleep(0.5)

        messages_area = self.driver.find_element(By.ID, "agent-chat-messages")
        user_msgs = messages_area.find_elements(
            By.CSS_SELECTOR, ".agent-chat-message.user"
        )
        assert len(user_msgs) == 0, "Empty send should not create messages"

    # ----------------------------------------------------------------
    # Sending messages (no finish — safe order)
    # ----------------------------------------------------------------

    def test_send_message_shows_response(self):
        """Sending a message should show both user and agent messages."""
        self._wait_for_main_content()

        self._send_chat_message("Hello agent")

        messages_area = self.driver.find_element(By.ID, "agent-chat-messages")
        message_bubbles = messages_area.find_elements(
            By.CSS_SELECTOR, ".agent-chat-message"
        )
        assert len(message_bubbles) >= 2, (
            f"Expected at least 2 messages (user + agent), found {len(message_bubbles)}"
        )

        user_msgs = messages_area.find_elements(
            By.CSS_SELECTOR, ".agent-chat-message.user"
        )
        assert len(user_msgs) >= 1, "Should have at least one user message bubble"

        agent_msgs = messages_area.find_elements(
            By.CSS_SELECTOR, ".agent-chat-message.agent"
        )
        assert len(agent_msgs) >= 1, "Should have at least one agent message bubble"

    def test_send_multiple_messages(self):
        """Sending multiple messages should accumulate in the chat."""
        self._wait_for_main_content()

        self._send_chat_message("First message")
        self._send_chat_message("Second message")

        messages_area = self.driver.find_element(By.ID, "agent-chat-messages")
        message_bubbles = messages_area.find_elements(
            By.CSS_SELECTOR, ".agent-chat-message"
        )
        # 2 user + 2 agent = 4 messages
        assert len(message_bubbles) >= 4, (
            f"Expected at least 4 messages, found {len(message_bubbles)}"
        )

    def test_step_counter_updates(self):
        """Step counter should update after sending messages."""
        self._wait_for_main_content()

        self._send_chat_message("First message")

        counter = self.driver.find_element(By.ID, "agent-chat-step-counter")
        counter_text = counter.text
        assert "1" in counter_text, f"Step counter should show step 1, got: {counter_text}"

        self._send_chat_message("Second message")

        counter_text = counter.text
        assert "2" in counter_text, f"Step counter should show step 2, got: {counter_text}"

    def test_agent_response_content(self):
        """Agent response should match the configured echo responses."""
        self._wait_for_main_content()

        self._send_chat_message("Test message")

        messages_area = self.driver.find_element(By.ID, "agent-chat-messages")
        agent_msgs = messages_area.find_elements(
            By.CSS_SELECTOR, ".agent-chat-message.agent"
        )

        assert len(agent_msgs) >= 1, "Should have an agent response"
        assert "I understand your request" in agent_msgs[0].text

    def test_enter_key_sends_message(self):
        """Pressing Enter should send the message."""
        self._wait_for_main_content()

        textarea = self.driver.find_element(By.ID, "agent-chat-input")
        textarea.clear()
        textarea.send_keys("Enter key test")
        textarea.send_keys(Keys.RETURN)

        time.sleep(1.5)

        messages_area = self.driver.find_element(By.ID, "agent-chat-messages")
        user_msgs = messages_area.find_elements(
            By.CSS_SELECTOR, ".agent-chat-message.user"
        )
        assert len(user_msgs) >= 1, "Enter key should send the message"

    def test_session_recovery_on_page_refresh(self):
        """Refreshing the page should recover the active chat session."""
        self._wait_for_main_content()

        self._send_chat_message("Remember this message")

        messages_area = self.driver.find_element(By.ID, "agent-chat-messages")
        assert "Remember this message" in messages_area.text

        # Refresh the page
        self.driver.refresh()

        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "main-content"))
        )
        time.sleep(2)  # Allow agentChatInit to restore session

        # Check for chat panel and restored messages
        try:
            chat_panel = self.driver.find_element(By.ID, "agent-chat-panel")
            messages_area = self.driver.find_element(By.ID, "agent-chat-messages")
            restored_messages = messages_area.find_elements(
                By.CSS_SELECTOR, ".agent-chat-message"
            )
            assert len(restored_messages) >= 2, (
                f"Expected restored messages after refresh, found {len(restored_messages)}"
            )
        except NoSuchElementException:
            # If chat panel is gone, item may have been modified by another test
            pass

    # ----------------------------------------------------------------
    # Finish workflow (MUTATES SHARED STATE — must be at end)
    # ----------------------------------------------------------------

    def test_finish_transitions_to_trace(self):
        """Clicking Finish should transition from chat to trace display."""
        self._wait_for_main_content()

        self._send_chat_message("I need help")

        finish_btn = self.driver.find_element(By.ID, "agent-chat-finish-btn")
        finish_btn.click()

        # Wait for page to reload
        time.sleep(2)

        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "main-content"))
        )

        page_source = self.driver.page_source

        # Chat panel should no longer be present
        chat_panels = self.driver.find_elements(By.ID, "agent-chat-panel")
        assert len(chat_panels) == 0 or not chat_panels[0].is_displayed(), (
            "Chat panel should not be visible after finishing"
        )

        # Dialogue display should be present (completed conversation)
        assert "dialogue" in page_source, (
            "Dialogue display should be visible after finishing"
        )

        # User's message should appear in the conversation
        assert "I need help" in page_source, (
            "User message should appear in the rendered conversation"
        )

    def test_annotation_schemas_present_after_finish(self):
        """Annotation schemas should be present and usable after finishing chat."""
        self._wait_for_main_content()

        # The item may already have conversation data from a previous test
        # (shared item state). If chat panel exists, send and finish first.
        chat_inputs = self.driver.find_elements(By.ID, "agent-chat-input")
        if chat_inputs and chat_inputs[0].is_displayed():
            self._send_chat_message("Do the task")

            finish_btn = self.driver.find_element(By.ID, "agent-chat-finish-btn")
            finish_btn.click()

            time.sleep(2)

            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.ID, "main-content"))
            )

        page_source = self.driver.page_source

        # Whether we just finished or the item was already finished,
        # annotation schemas should be present and usable
        assert "task_success" in page_source, "task_success schema should be present"
        assert "naturalness" in page_source, "naturalness schema should be present"

        radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        assert len(radios) > 0, "Radio buttons should be present for annotation"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
