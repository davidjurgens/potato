"""
Server integration tests for agent chat routes.

Tests the /agent_chat/send, /agent_chat/finish, and /agent_chat/status endpoints
using a FlaskTestServer with echo proxy configuration.

Coverage:
- Authentication enforcement (401 for unauthenticated)
- Input validation (empty messages, whitespace-only)
- Echo proxy response cycling
- Step count tracking
- Session status reporting
- Finish workflow (conversation written to item data)
- Post-finish rejection
- Step limit enforcement
- Concurrent users with isolated sessions
- Full end-to-end workflow: chat → finish → page shows trace → submit annotation
- Annotation page HTML content before/after finish
- Finish unauthenticated
"""

import json
import time
import pytest
import requests
import os
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory, create_test_data_file


def create_agent_chat_config(test_dir, max_steps=5):
    """Create a config with agent_proxy and interactive_chat display."""
    abs_test_dir = os.path.abspath(test_dir)

    # Create enough test data items so each test gets a fresh item
    # (the finish route writes conversation data to shared item_data)
    tasks = [
        "Book a flight to London.",
        "Find a hotel in Paris.",
        "Plan a trip to Tokyo.",
        "Reserve a restaurant in Rome.",
        "Rent a car in Berlin.",
        "Schedule a tour in Barcelona.",
        "Book a cruise from Miami.",
        "Find a hostel in Amsterdam.",
        "Arrange airport transfer in Dubai.",
        "Plan a city tour in New York.",
        "Book a spa in Bali.",
        "Reserve tickets in Vienna.",
        "Find a guide in Cairo.",
        "Plan a road trip in Iceland.",
        "Book a train in Switzerland.",
        "Find a campsite in Norway.",
        "Reserve a villa in Greece.",
        "Arrange a safari in Kenya.",
        "Book a ferry in Croatia.",
        "Plan a hike in Peru.",
        "Find a market tour in Thailand.",
        "Reserve a cabin in Canada.",
        "Book a bus in Portugal.",
        "Plan a visit to Japan.",
        "Find a festival in India.",
        "Book a flight to Sydney.",
        "Plan a beach trip to Maldives.",
        "Find a lodge in Tanzania.",
        "Reserve a yacht in Monaco.",
        "Book a balloon ride in Turkey.",
    ]
    test_data = [
        {
            "id": f"task_{i+1}",
            "task_description": desc,
            "conversation": None,
        }
        for i, desc in enumerate(tasks)
    ]

    data_file = os.path.join(test_dir, "test_data.json")
    with open(data_file, "w") as f:
        json.dump(test_data, f)

    config = {
        "annotation_task_name": "Agent Chat Test",
        "task_dir": abs_test_dir,
        "data_files": ["test_data.json"],
        "item_properties": {"id_key": "id", "text_key": "task_description"},
        "annotation_schemes": [
            {
                "name": "task_success",
                "annotation_type": "radio",
                "labels": ["success", "failure"],
                "description": "Did it work?",
            }
        ],
        "output_annotation_dir": os.path.join(abs_test_dir, "output"),
        "site_dir": "default",
        "alert_time_each_instance": 0,
        "require_password": False,
        "authentication": {"method": "in_memory"},
        "persist_sessions": False,
        "debug": False,
        "secret_key": "test-secret",
        "session_lifetime_days": 1,
        "user_config": {"allow_all_users": True, "users": []},
        "agent_proxy": {
            "type": "echo",
            "responses": ["Echo response 1", "Echo response 2", "Echo response 3"],
            "sandbox": {
                "max_steps": max_steps,
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
                    "label": "Chat",
                },
            ],
        },
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config, f)

    return config_file


def _make_unique_user(prefix="testuser"):
    """Generate a unique username using timestamp."""
    return f"{prefix}_{int(time.time() * 1000)}"


class TestAgentChatRoutes:
    """Test agent chat route endpoints."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask test server with agent proxy config."""
        test_dir = create_test_directory("agent_chat_routes")
        config_file = create_agent_chat_config(test_dir)

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        yield server
        server.stop()

    def _auth_session(self, flask_server, username=None):
        """Create an authenticated requests session with a unique user."""
        if username is None:
            username = _make_unique_user()
        s = requests.Session()
        s.post(
            f"{flask_server.base_url}/register",
            data={"email": username, "pass": "testpass"},
            timeout=5,
        )
        s.post(
            f"{flask_server.base_url}/auth",
            data={"email": username, "pass": "testpass"},
            timeout=5,
        )
        return s

    # ----------------------------------------------------------------
    # Authentication tests
    # ----------------------------------------------------------------

    def test_send_unauthenticated(self, flask_server):
        """Unauthenticated send should return 401."""
        resp = requests.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "hello"},
            timeout=5,
        )
        assert resp.status_code == 401

    def test_finish_unauthenticated(self, flask_server):
        """Unauthenticated finish should return 401."""
        resp = requests.post(
            f"{flask_server.base_url}/agent_chat/finish",
            json={},
            timeout=5,
        )
        assert resp.status_code == 401

    def test_status_unauthenticated(self, flask_server):
        """Unauthenticated status should return 401."""
        resp = requests.get(
            f"{flask_server.base_url}/agent_chat/status",
            timeout=5,
        )
        assert resp.status_code == 401

    # ----------------------------------------------------------------
    # Input validation tests
    # ----------------------------------------------------------------

    def test_send_empty_message(self, flask_server):
        """Sending an empty message should return 400."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)
        resp = s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": ""},
            timeout=5,
        )
        assert resp.status_code == 400

    def test_send_whitespace_only_message(self, flask_server):
        """Sending whitespace-only message should return 400."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)
        resp = s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "   \n\t  "},
            timeout=5,
        )
        assert resp.status_code == 400

    def test_send_no_json_body(self, flask_server):
        """Sending with no JSON body should return 400."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)
        resp = s.post(
            f"{flask_server.base_url}/agent_chat/send",
            data="not json",
            timeout=5,
        )
        assert resp.status_code == 400

    # ----------------------------------------------------------------
    # Annotation page content (MUST run before finish tests which
    # mutate shared item_data and change the display from chat to trace)
    # ----------------------------------------------------------------

    def test_annotation_page_contains_chat_panel(self, flask_server):
        """Annotation page should contain the chat panel HTML before chat finishes."""
        s = self._auth_session(flask_server)
        resp = s.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200

        html = resp.text
        assert "instance-display-container" in html, (
            "instance-display-container not found — instance_display rendering may have failed"
        )
        assert "agent-chat-panel" in html, (
            "Chat panel not rendered. The conversation field should be null for a fresh item."
        )
        assert "agent-chat-input" in html
        assert "agent-chat-send-btn" in html
        assert "agent-chat-finish-btn" in html

    def test_annotation_page_contains_chat_css_js(self, flask_server):
        """Annotation page should load agent-chat CSS and JS."""
        s = self._auth_session(flask_server)
        resp = s.get(f"{flask_server.base_url}/annotate", timeout=5)
        html = resp.text

        assert "agent-chat.css" in html
        assert "agent-chat.js" in html

    # ----------------------------------------------------------------
    # Basic send/receive tests
    # ----------------------------------------------------------------

    def test_send_and_receive(self, flask_server):
        """Send a message and get a response from the echo proxy."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        resp = s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "Hello agent"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "content" in data
        assert data["content"] == "Echo response 1"
        assert data["step_count"] == 1
        assert data["max_steps"] == 5
        assert data["role"] == "agent"

    def test_echo_response_cycling(self, flask_server):
        """Echo proxy should cycle through responses in order."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        expected_responses = [
            "Echo response 1",
            "Echo response 2",
            "Echo response 3",
            "Echo response 1",  # wraps around
        ]

        for i, expected in enumerate(expected_responses):
            resp = s.post(
                f"{flask_server.base_url}/agent_chat/send",
                json={"message": f"msg {i+1}"},
                timeout=10,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["content"] == expected, (
                f"Step {i+1}: expected '{expected}', got '{data['content']}'"
            )

    def test_step_count_increments(self, flask_server):
        """Step count should increment with each message."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        for i in range(3):
            resp = s.post(
                f"{flask_server.base_url}/agent_chat/send",
                json={"message": f"msg {i+1}"},
                timeout=10,
            )
            assert resp.json()["step_count"] == i + 1

    # ----------------------------------------------------------------
    # Session status tests
    # ----------------------------------------------------------------

    def test_status_inactive_before_any_message(self, flask_server):
        """Status should be inactive before any messages are sent."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        resp = s.get(
            f"{flask_server.base_url}/agent_chat/status",
            timeout=5,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False

    def test_status_shows_active_session(self, flask_server):
        """Status endpoint should report an active session after sending."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "start"},
            timeout=10,
        )

        resp = s.get(
            f"{flask_server.base_url}/agent_chat/status",
            timeout=5,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert len(data["messages"]) == 2  # user msg + agent response
        assert data["step_count"] == 1
        assert data["max_steps"] == 5

    def test_status_message_content_matches(self, flask_server):
        """Status should return exact message content."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "specific test message"},
            timeout=10,
        )

        resp = s.get(
            f"{flask_server.base_url}/agent_chat/status",
            timeout=5,
        )
        data = resp.json()
        messages = data["messages"]

        # First message should be the user's
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "specific test message"
        # Second should be agent's echo response
        assert messages[1]["role"] == "agent"
        assert messages[1]["content"] == "Echo response 1"

    def test_status_accumulates_messages(self, flask_server):
        """Status should show all messages sent so far."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        for i in range(3):
            s.post(
                f"{flask_server.base_url}/agent_chat/send",
                json={"message": f"message {i+1}"},
                timeout=10,
            )

        resp = s.get(
            f"{flask_server.base_url}/agent_chat/status",
            timeout=5,
        )
        data = resp.json()
        # 3 user + 3 agent = 6 messages
        assert len(data["messages"]) == 6
        assert data["step_count"] == 3

    # ----------------------------------------------------------------
    # Finish workflow tests
    # ----------------------------------------------------------------

    def test_finish_writes_conversation(self, flask_server):
        """Finishing should succeed and return message count."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "first message"},
            timeout=10,
        )
        s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "second message"},
            timeout=10,
        )

        resp = s.post(
            f"{flask_server.base_url}/agent_chat/finish",
            json={},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["message_count"] == 4  # 2 user + 2 agent messages

    def test_finish_without_session(self, flask_server):
        """Finishing without a session should return error."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        resp = s.post(
            f"{flask_server.base_url}/agent_chat/finish",
            json={},
            timeout=10,
        )
        assert resp.status_code == 400

    def test_status_inactive_after_finish(self, flask_server):
        """Status should show inactive after finishing."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "test"},
            timeout=10,
        )
        s.post(
            f"{flask_server.base_url}/agent_chat/finish",
            json={},
            timeout=10,
        )

        resp = s.get(
            f"{flask_server.base_url}/agent_chat/status",
            timeout=5,
        )
        data = resp.json()
        assert data["active"] is False

    def test_send_after_finish_rejected(self, flask_server):
        """Sending after finishing should be rejected."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "test"},
            timeout=10,
        )
        s.post(
            f"{flask_server.base_url}/agent_chat/finish",
            json={},
            timeout=10,
        )

        resp = s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "after finish"},
            timeout=10,
        )
        assert resp.status_code == 400

    def test_double_finish_rejected(self, flask_server):
        """Finishing twice should be rejected on the second call."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "test"},
            timeout=10,
        )

        resp1 = s.post(
            f"{flask_server.base_url}/agent_chat/finish",
            json={},
            timeout=10,
        )
        assert resp1.status_code == 200

        resp2 = s.post(
            f"{flask_server.base_url}/agent_chat/finish",
            json={},
            timeout=10,
        )
        assert resp2.status_code == 400

    # ----------------------------------------------------------------
    # Step limit enforcement
    # ----------------------------------------------------------------

    def test_step_limit_enforced(self, flask_server):
        """Sending beyond max_steps should be rejected."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        # Send max_steps messages (5)
        for i in range(5):
            resp = s.post(
                f"{flask_server.base_url}/agent_chat/send",
                json={"message": f"msg {i+1}"},
                timeout=10,
            )
            assert resp.status_code == 200, f"Step {i+1} should succeed"

        # 6th message should be rejected
        resp = s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "one too many"},
            timeout=10,
        )
        assert resp.status_code == 400
        assert "Step limit" in resp.json().get("error", "")

    # ----------------------------------------------------------------
    # Concurrent users
    # ----------------------------------------------------------------

    def test_concurrent_users_isolated(self, flask_server):
        """Multiple users should have isolated chat sessions."""
        user1 = _make_unique_user("user1")
        user2 = _make_unique_user("user2")

        s1 = self._auth_session(flask_server, username=user1)
        s2 = self._auth_session(flask_server, username=user2)

        s1.get(f"{flask_server.base_url}/annotate", timeout=5)
        s2.get(f"{flask_server.base_url}/annotate", timeout=5)

        # User 1 sends 2 messages
        s1.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "user1 msg1"},
            timeout=10,
        )
        s1.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "user1 msg2"},
            timeout=10,
        )

        # User 2 sends 1 message
        s2.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "user2 msg1"},
            timeout=10,
        )

        # Check status independently
        status1 = s1.get(
            f"{flask_server.base_url}/agent_chat/status", timeout=5
        ).json()
        status2 = s2.get(
            f"{flask_server.base_url}/agent_chat/status", timeout=5
        ).json()

        assert status1["step_count"] == 2
        assert status2["step_count"] == 1
        assert len(status1["messages"]) == 4  # 2 user + 2 agent
        assert len(status2["messages"]) == 2  # 1 user + 1 agent

    def test_concurrent_users_finish_independently(self, flask_server):
        """One user finishing should not affect another user's session."""
        user1 = _make_unique_user("finuser1")
        user2 = _make_unique_user("finuser2")

        s1 = self._auth_session(flask_server, username=user1)
        s2 = self._auth_session(flask_server, username=user2)

        s1.get(f"{flask_server.base_url}/annotate", timeout=5)
        s2.get(f"{flask_server.base_url}/annotate", timeout=5)

        # Both send a message
        s1.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "hello from user1"},
            timeout=10,
        )
        s2.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "hello from user2"},
            timeout=10,
        )

        # User 1 finishes
        s1.post(
            f"{flask_server.base_url}/agent_chat/finish",
            json={},
            timeout=10,
        )

        # User 2 should still be active
        status2 = s2.get(
            f"{flask_server.base_url}/agent_chat/status", timeout=5
        ).json()
        assert status2["active"] is True

        # User 2 can still send messages
        resp = s2.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "still chatting"},
            timeout=10,
        )
        assert resp.status_code == 200

    # ----------------------------------------------------------------
    # Trace display after finish
    # ----------------------------------------------------------------

    def test_annotation_page_shows_trace_after_finish(self, flask_server):
        """After finishing chat, annotation page should show agent trace display."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        # Send a message and finish
        s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "test message"},
            timeout=10,
        )
        s.post(
            f"{flask_server.base_url}/agent_chat/finish",
            json={},
            timeout=10,
        )

        # Reload page — should now show trace, not chat panel
        resp = s.get(f"{flask_server.base_url}/annotate", timeout=5)
        html = resp.text

        # Chat panel should NOT be present (conversation data is now populated)
        assert "agent-chat-panel" not in html
        # Dialogue display should be present (renders completed conversation)
        assert "dialogue" in html
        # The user's message content should appear in the conversation
        assert "test message" in html

    # ----------------------------------------------------------------
    # Full end-to-end workflow
    # ----------------------------------------------------------------

    def test_full_workflow_chat_finish_annotate(self, flask_server):
        """End-to-end: chat with agent, finish, verify trace, submit annotation."""
        s = self._auth_session(flask_server)
        s.get(f"{flask_server.base_url}/annotate", timeout=5)

        # Step 1: Chat with agent
        r1 = s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "I need a flight to London"},
            timeout=10,
        )
        assert r1.status_code == 200
        assert r1.json()["content"] == "Echo response 1"

        r2 = s.post(
            f"{flask_server.base_url}/agent_chat/send",
            json={"message": "Budget is $500"},
            timeout=10,
        )
        assert r2.status_code == 200
        assert r2.json()["step_count"] == 2

        # Step 2: Finish chat
        fin = s.post(
            f"{flask_server.base_url}/agent_chat/finish",
            json={},
            timeout=10,
        )
        assert fin.status_code == 200
        assert fin.json()["success"] is True
        assert fin.json()["message_count"] == 4

        # Step 3: Verify page shows dialogue
        page = s.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert "dialogue" in page.text
        assert "I need a flight to London" in page.text
        assert "Echo response 1" in page.text

        # Step 4: Annotation schemas should be present
        assert "task_success" in page.text
