"""
Server integration tests for the Chat Support API endpoints.
"""

import json
import pytest
import requests
from unittest.mock import patch, MagicMock
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory, create_test_config, create_test_data_file,
)


def _make_config(test_dir, data_file, chat_enabled=True):
    """Create a test config with chat support."""
    annotation_schemes = [{
        "name": "sentiment",
        "annotation_type": "radio",
        "labels": ["positive", "negative", "neutral"],
        "description": "Classify sentiment.",
    }]

    extra = {}
    if chat_enabled:
        extra["chat_support"] = {
            "enabled": True,
            "endpoint_type": "ollama",
            "ai_config": {
                "model": "llama3.2",
                "temperature": 0.7,
                "max_tokens": 200,
            },
        }

    # Write chat_support into config manually since create_test_config doesn't know about it
    config_path = create_test_config(
        test_dir, annotation_schemes, data_files=[data_file],
        annotation_task_name="Chat Test",
    )

    if chat_enabled:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        cfg["chat_support"] = extra["chat_support"]
        with open(config_path, 'w') as f:
            yaml.dump(cfg, f)

    return config_path


def _login(session, base_url, username="testuser", password="pass"):
    """Register and log in a user."""
    session.post(f"{base_url}/register", data={"email": username, "pass": password})
    session.post(f"{base_url}/auth", data={"email": username, "pass": password})


class TestChatConfigEndpoint:
    """Test /api/chat/config endpoint."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self):
        test_dir = create_test_directory("chat_config_test")
        data = [{"id": "1", "text": "Test item 1"}, {"id": "2", "text": "Test item 2"}]
        data_file = create_test_data_file(test_dir, data)

        # Start WITHOUT chat support to test the disabled case
        config_path = create_test_config(
            test_dir,
            [{"name": "test", "annotation_type": "radio", "labels": ["a", "b"], "description": "test"}],
            data_files=[data_file],
        )

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        yield server
        server.stop()

    def test_config_disabled(self, flask_server):
        """When chat_support is not configured, /api/chat/config returns enabled=false."""
        s = requests.Session()
        _login(s, flask_server.base_url)

        resp = s.get(f"{flask_server.base_url}/api/chat/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False


class TestChatApiEndpoints:
    """Test chat send/history endpoints with mocked LLM."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self):
        test_dir = create_test_directory("chat_api_test")
        data = [
            {"id": "chat_item_1", "text": "I love this product."},
            {"id": "chat_item_2", "text": "This is terrible."},
        ]
        data_file = create_test_data_file(test_dir, data)
        config_path = _make_config(test_dir, data_file, chat_enabled=True)

        # Patch Ollama client to avoid needing a running Ollama server
        mock_client = MagicMock()
        mock_client.list.return_value = {"models": []}
        mock_client.chat.return_value = {
            "message": {"content": "This text expresses positive sentiment."}
        }

        with patch("ollama.Client", return_value=mock_client):
            server = FlaskTestServer(config=config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            # Store mock for later assertion
            server._mock_client = mock_client
            yield server
            server.stop()

    def test_chat_config_enabled(self, flask_server):
        s = requests.Session()
        _login(s, flask_server.base_url)

        resp = s.get(f"{flask_server.base_url}/api/chat/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert "title" in data
        assert "sidebar_width" in data

    def test_chat_send_requires_auth(self, flask_server):
        """Unauthenticated request should get 401."""
        s = requests.Session()
        resp = s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={"message": "hello"},
        )
        assert resp.status_code == 401

    def test_chat_send_requires_message(self, flask_server):
        s = requests.Session()
        _login(s, flask_server.base_url)

        resp = s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={},
        )
        assert resp.status_code == 400

    def test_chat_send_and_receive(self, flask_server):
        s = requests.Session()
        _login(s, flask_server.base_url, username="chat_user1")

        # Navigate to annotation page to get an instance assigned
        s.get(f"{flask_server.base_url}/annotate")

        resp = s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={"message": "What sentiment is this?", "instance_id": "chat_item_1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "content" in data
        assert "response_time_ms" in data
        assert len(data["content"]) > 0

    def test_chat_history_empty(self, flask_server):
        s = requests.Session()
        _login(s, flask_server.base_url, username="chat_user2")

        resp = s.get(
            f"{flask_server.base_url}/api/chat/history",
            params={"instance_id": "chat_item_2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages"] == []

    def test_chat_history_persists(self, flask_server):
        """After sending a message, history should contain both user and assistant messages."""
        s = requests.Session()
        _login(s, flask_server.base_url, username="chat_user3")

        # Navigate to get instance
        s.get(f"{flask_server.base_url}/annotate")

        # Send a message
        s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={"message": "Help me", "instance_id": "chat_item_1"},
        )

        # Fetch history
        resp = s.get(
            f"{flask_server.base_url}/api/chat/history",
            params={"instance_id": "chat_item_1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        messages = data["messages"]
        assert len(messages) >= 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Help me"
        assert messages[1]["role"] == "assistant"

    def test_chat_history_requires_auth(self, flask_server):
        s = requests.Session()
        resp = s.get(
            f"{flask_server.base_url}/api/chat/history",
            params={"instance_id": "chat_item_1"},
        )
        assert resp.status_code == 401
