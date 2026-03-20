"""
Integration tests for Chat Support with a real Ollama LLM (llama3.2:1b).

These tests verify that the chat pipeline works end-to-end with an actual
language model. They require a running Ollama server with llama3.2:1b pulled.

Skip automatically if Ollama is not reachable.
"""

import json
import os
import time

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434"
MODEL = "llama3.2:1b"


def ollama_available():
    """Check if Ollama is reachable and the model is pulled."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if resp.status_code != 200:
            return False
        models = [m["name"] for m in resp.json().get("models", [])]
        return MODEL in models
    except Exception:
        return False


skip_no_ollama = pytest.mark.skipif(
    not ollama_available(),
    reason=f"Ollama not available or {MODEL} not pulled",
)


def _make_chat_config(test_dir, data_file, **overrides):
    """Create a config with chat_support pointing at the real Ollama."""
    annotation_schemes = [
        {
            "name": "sentiment",
            "annotation_type": "radio",
            "labels": ["positive", "negative", "neutral", "mixed"],
            "description": "Classify the overall sentiment of the text.",
        }
    ]

    config_path = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        annotation_task_name="Sentiment with Chat",
        annotation_task_description="Classify text sentiment as positive, negative, neutral, or mixed.",
    )

    # Inject chat_support into the generated config
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    cfg["chat_support"] = {
        "enabled": True,
        "endpoint_type": "ollama",
        "ai_config": {
            "model": MODEL,
            "temperature": 0.3,
            "max_tokens": 150,
            "base_url": OLLAMA_URL,
            "timeout": 30,
        },
    }
    cfg.update(overrides)

    with open(config_path, "w") as f:
        yaml.dump(cfg, f)

    return config_path


def _login(session, base_url, username="testuser"):
    session.post(f"{base_url}/register", data={"email": username, "pass": "pass"})
    session.post(f"{base_url}/auth", data={"email": username, "pass": "pass"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@skip_no_ollama
class TestChatOllamaIntegration:
    """End-to-end tests with a real Ollama model."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self):
        test_dir = create_test_directory("chat_ollama_integration")
        data = [
            {
                "id": "pos_1",
                "text": "I absolutely love this product! Best purchase I've made all year.",
            },
            {
                "id": "neg_1",
                "text": "Terrible experience. The service was awful and the food was cold.",
            },
            {
                "id": "mixed_1",
                "text": "The design is beautiful but the battery barely lasts two hours.",
            },
        ]
        data_file = create_test_data_file(test_dir, data)
        config_path = _make_chat_config(test_dir, data_file)

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        yield server
        server.stop()

    # ------------------------------------------------------------------
    # Basic send / receive
    # ------------------------------------------------------------------

    def test_send_receives_nonempty_response(self, flask_server):
        """The LLM should return a non-empty string for a simple question."""
        s = requests.Session()
        _login(s, flask_server.base_url, "ollama_user1")
        s.get(f"{flask_server.base_url}/annotate")

        resp = s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={
                "message": "What is the sentiment of this text?",
                "instance_id": "pos_1",
            },
            timeout=30,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["content"]) > 0, "LLM response should be non-empty"
        assert data["response_time_ms"] > 0, "Should report response time"

    # ------------------------------------------------------------------
    # Context awareness
    # ------------------------------------------------------------------

    def test_response_reflects_instance_context(self, flask_server):
        """The LLM should reference content from the system prompt / instance text."""
        s = requests.Session()
        _login(s, flask_server.base_url, "ollama_user2")
        s.get(f"{flask_server.base_url}/annotate")

        resp = s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={
                "message": "Summarize the text I'm annotating in one sentence.",
                "instance_id": "neg_1",
            },
            timeout=30,
        )
        assert resp.status_code == 200
        content = resp.json()["content"].lower()
        # The model should reference something about the negative text
        # (service, food, terrible, awful, etc.)
        negative_keywords = ["service", "food", "terrible", "awful", "bad", "negative", "cold", "experience"]
        assert any(kw in content for kw in negative_keywords), (
            f"Response should reference the negative instance text. Got: {content[:300]}"
        )

    # ------------------------------------------------------------------
    # Multi-turn conversation
    # ------------------------------------------------------------------

    def test_multi_turn_conversation(self, flask_server):
        """Send two messages and verify the LLM receives conversation history."""
        s = requests.Session()
        _login(s, flask_server.base_url, "ollama_user3")
        s.get(f"{flask_server.base_url}/annotate")

        # First message
        resp1 = s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={
                "message": "The text I'm looking at mentions a product. Is the tone positive or negative?",
                "instance_id": "pos_1",
            },
            timeout=30,
        )
        assert resp1.status_code == 200
        first_reply = resp1.json()["content"]
        assert len(first_reply) > 0

        # Second message (follow-up)
        resp2 = s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={
                "message": "Can you explain why you think that?",
                "instance_id": "pos_1",
            },
            timeout=30,
        )
        assert resp2.status_code == 200
        second_reply = resp2.json()["content"]
        assert len(second_reply) > 0

        # Verify history has 4 messages (user, assistant, user, assistant)
        hist = s.get(
            f"{flask_server.base_url}/api/chat/history",
            params={"instance_id": "pos_1"},
        ).json()
        messages = hist["messages"]
        assert len(messages) == 4
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"
        assert messages[3]["role"] == "assistant"

    # ------------------------------------------------------------------
    # History isolation across instances
    # ------------------------------------------------------------------

    def test_chat_history_isolated_per_instance(self, flask_server):
        """Chat on instance A should not bleed into instance B's history."""
        s = requests.Session()
        _login(s, flask_server.base_url, "ollama_user4")
        s.get(f"{flask_server.base_url}/annotate")

        # Chat on instance pos_1
        s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={"message": "Hello for pos_1", "instance_id": "pos_1"},
            timeout=30,
        )

        # Chat on instance neg_1
        s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={"message": "Hello for neg_1", "instance_id": "neg_1"},
            timeout=30,
        )

        # Check histories are separate
        hist_pos = s.get(
            f"{flask_server.base_url}/api/chat/history",
            params={"instance_id": "pos_1"},
        ).json()["messages"]

        hist_neg = s.get(
            f"{flask_server.base_url}/api/chat/history",
            params={"instance_id": "neg_1"},
        ).json()["messages"]

        assert len(hist_pos) == 2  # user + assistant
        assert len(hist_neg) == 2
        assert hist_pos[0]["content"] == "Hello for pos_1"
        assert hist_neg[0]["content"] == "Hello for neg_1"

    # ------------------------------------------------------------------
    # Behavioral data tracking
    # ------------------------------------------------------------------

    def test_chat_interaction_logged_in_behavioral_data(self, flask_server):
        """Chat messages should appear in behavioral_data for the instance."""
        s = requests.Session()
        _login(s, flask_server.base_url, "ollama_user5")
        s.get(f"{flask_server.base_url}/annotate")

        s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={"message": "Test behavioral logging", "instance_id": "mixed_1"},
            timeout=30,
        )

        # Fetch behavioral data
        resp = s.get(
            f"{flask_server.base_url}/api/behavioral_data/mixed_1",
        )
        assert resp.status_code == 200
        bd = resp.json()

        # Check chat_history
        chat_history = bd.get("chat_history", [])
        assert len(chat_history) >= 2
        assert chat_history[0]["role"] == "user"
        assert chat_history[0]["content"] == "Test behavioral logging"
        assert chat_history[1]["role"] == "assistant"
        assert chat_history[1]["response_time_ms"] is not None
        assert chat_history[1]["response_time_ms"] > 0

        # Check interaction events
        interactions = bd.get("interactions", [])
        chat_events = [e for e in interactions if e["event_type"] == "chat_message_sent"]
        assert len(chat_events) >= 1
        meta = chat_events[0]["metadata"]
        assert "message_length" in meta
        assert "response_length" in meta
        assert "response_time_ms" in meta
        assert meta["response_time_ms"] > 0

    # ------------------------------------------------------------------
    # Config endpoint
    # ------------------------------------------------------------------

    def test_config_returns_correct_settings(self, flask_server):
        s = requests.Session()
        _login(s, flask_server.base_url, "ollama_user6")

        resp = s.get(f"{flask_server.base_url}/api/chat/config")
        assert resp.status_code == 200
        cfg = resp.json()
        assert cfg["enabled"] is True
        assert cfg["title"] == "Ask AI"
        assert cfg["sidebar_width"] == 380
        assert isinstance(cfg["max_history_per_instance"], int)

    # ------------------------------------------------------------------
    # Different instance contexts produce different responses
    # ------------------------------------------------------------------

    def test_different_instances_get_different_context(self, flask_server):
        """Asking the same question on different instances should yield
        responses referencing different texts."""
        s = requests.Session()
        _login(s, flask_server.base_url, "ollama_user7")
        s.get(f"{flask_server.base_url}/annotate")

        resp_pos = s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={
                "message": "What words in the text suggest its sentiment?",
                "instance_id": "pos_1",
            },
            timeout=30,
        ).json()

        resp_neg = s.post(
            f"{flask_server.base_url}/api/chat/send",
            json={
                "message": "What words in the text suggest its sentiment?",
                "instance_id": "neg_1",
            },
            timeout=30,
        ).json()

        # Both should be non-empty
        assert len(resp_pos["content"]) > 10
        assert len(resp_neg["content"]) > 10

        # Responses should differ since the instance text is different
        assert resp_pos["content"] != resp_neg["content"], (
            "Responses for different instances should not be identical"
        )
