"""
Unit tests for ChatManager and ChatMessage.
"""

import pytest
import time
from unittest.mock import patch, MagicMock

from potato.interaction_tracking import ChatMessage, BehavioralData


class TestChatMessage:
    """Test ChatMessage dataclass serialization."""

    def test_to_dict(self):
        msg = ChatMessage(
            role="user",
            content="What does this mean?",
            timestamp=1700000000.0,
            instance_id="inst_1",
        )
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "What does this mean?"
        assert d["timestamp"] == 1700000000.0
        assert d["instance_id"] == "inst_1"
        assert d["response_time_ms"] is None

    def test_to_dict_with_response_time(self):
        msg = ChatMessage(
            role="assistant",
            content="This text discusses...",
            timestamp=1700000002.5,
            instance_id="inst_1",
            response_time_ms=2500,
        )
        d = msg.to_dict()
        assert d["role"] == "assistant"
        assert d["response_time_ms"] == 2500

    def test_from_dict(self):
        data = {
            "role": "user",
            "content": "Hello",
            "timestamp": 1700000000.0,
            "instance_id": "inst_1",
            "response_time_ms": None,
        }
        msg = ChatMessage.from_dict(data)
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.instance_id == "inst_1"

    def test_from_dict_missing_fields(self):
        """Should use defaults for missing fields."""
        msg = ChatMessage.from_dict({})
        assert msg.role == ""
        assert msg.content == ""
        assert msg.timestamp == 0
        assert msg.instance_id == ""
        assert msg.response_time_ms is None

    def test_round_trip(self):
        """Serialize then deserialize should produce equal data."""
        original = ChatMessage(
            role="assistant",
            content="Here's what I think...",
            timestamp=1700000001.0,
            instance_id="inst_42",
            response_time_ms=1234,
        )
        restored = ChatMessage.from_dict(original.to_dict())
        assert restored.role == original.role
        assert restored.content == original.content
        assert restored.timestamp == original.timestamp
        assert restored.instance_id == original.instance_id
        assert restored.response_time_ms == original.response_time_ms


class TestBehavioralDataChatHistory:
    """Test chat_history integration in BehavioralData."""

    def test_chat_history_default_empty(self):
        bd = BehavioralData(instance_id="test")
        assert bd.chat_history == []

    def test_chat_history_to_dict(self):
        bd = BehavioralData(instance_id="test")
        bd.chat_history.append(ChatMessage(
            role="user", content="Hi", timestamp=1.0, instance_id="test",
        ))
        bd.chat_history.append(ChatMessage(
            role="assistant", content="Hello!", timestamp=2.0,
            instance_id="test", response_time_ms=500,
        ))

        d = bd.to_dict()
        assert len(d["chat_history"]) == 2
        assert d["chat_history"][0]["role"] == "user"
        assert d["chat_history"][1]["response_time_ms"] == 500

    def test_chat_history_from_dict(self):
        data = {
            "instance_id": "test",
            "chat_history": [
                {"role": "user", "content": "Q", "timestamp": 1.0, "instance_id": "test"},
                {"role": "assistant", "content": "A", "timestamp": 2.0, "instance_id": "test", "response_time_ms": 100},
            ],
        }
        bd = BehavioralData.from_dict(data)
        assert len(bd.chat_history) == 2
        assert isinstance(bd.chat_history[0], ChatMessage)
        assert bd.chat_history[0].content == "Q"
        assert bd.chat_history[1].response_time_ms == 100

    def test_backward_compat_no_chat_history(self):
        """Old data without chat_history should deserialize fine."""
        data = {
            "instance_id": "old_inst",
            "session_start": 1.0,
            "interactions": [],
        }
        bd = BehavioralData.from_dict(data)
        assert bd.chat_history == []

    def test_chat_history_round_trip(self):
        bd = BehavioralData(instance_id="round_trip")
        bd.chat_history.append(ChatMessage(
            role="user", content="test msg", timestamp=time.time(), instance_id="round_trip",
        ))
        restored = BehavioralData.from_dict(bd.to_dict())
        assert len(restored.chat_history) == 1
        assert restored.chat_history[0].content == "test msg"


class TestChatManagerUnit:
    """Test ChatManager initialization and methods with mocked endpoints."""

    def test_init_disabled(self):
        from potato.chat_manager import ChatManager
        mgr = ChatManager({"chat_support": {"enabled": False}})
        assert mgr.enabled is False
        assert mgr.endpoint is None

    def test_init_no_config(self):
        from potato.chat_manager import ChatManager
        mgr = ChatManager({})
        assert mgr.enabled is False

    def test_ui_config_defaults(self):
        from potato.chat_manager import ChatManager
        mgr = ChatManager({})
        cfg = mgr.get_ui_config()
        assert cfg["enabled"] is False
        assert cfg["title"] == "Ask AI"
        assert cfg["placeholder"] == "Ask about this annotation..."
        assert cfg["sidebar_width"] == 380
        assert cfg["max_history_per_instance"] == 50

    def test_ui_config_custom(self):
        from potato.chat_manager import ChatManager
        mgr = ChatManager({
            "chat_support": {
                "enabled": False,
                "ui": {
                    "title": "Help",
                    "placeholder": "Type here...",
                    "sidebar_width": 400,
                    "max_history_per_instance": 20,
                },
            },
        })
        cfg = mgr.get_ui_config()
        assert cfg["title"] == "Help"
        assert cfg["sidebar_width"] == 400
        assert cfg["max_history_per_instance"] == 20

    def test_build_system_prompt(self):
        from potato.chat_manager import ChatManager
        mgr = ChatManager({
            "annotation_task_name": "Sentiment",
            "annotation_task_description": "Classify sentiment",
            "annotation_schemes": [
                {"name": "sent", "labels": ["pos", "neg"]},
            ],
        })
        prompt = mgr.build_system_prompt("Hello world", "inst_1")
        assert "Sentiment" in prompt
        assert "Classify sentiment" in prompt
        assert "pos, neg" in prompt
        assert "Hello world" in prompt

    def test_build_system_prompt_custom_template(self):
        from potato.chat_manager import ChatManager
        mgr = ChatManager({
            "annotation_task_name": "Test",
            "chat_support": {
                "system_prompt": {
                    "template": "Task: {task_name}, Text: {instance_text}",
                },
            },
        })
        prompt = mgr.build_system_prompt("some text", "id1")
        assert prompt == "Task: Test, Text: some text"

    def test_send_message_no_endpoint(self):
        from potato.chat_manager import ChatManager
        mgr = ChatManager({})
        result = mgr.send_message("hello", "text", "id1", [])
        assert "not configured" in result["content"]
        assert result["response_time_ms"] == 0

    def test_send_message_with_mocked_endpoint(self):
        from potato.chat_manager import ChatManager
        mgr = ChatManager({})
        mgr.enabled = True
        mock_endpoint = MagicMock()
        mock_endpoint.chat_query.return_value = "I can help with that!"
        mgr.endpoint = mock_endpoint

        result = mgr.send_message("What is this?", "Test text", "inst_1", [])
        assert result["content"] == "I can help with that!"
        assert result["response_time_ms"] >= 0
        mock_endpoint.chat_query.assert_called_once()

        # Verify the messages passed to chat_query
        call_args = mock_endpoint.chat_query.call_args[0][0]
        assert call_args[0]["role"] == "system"
        assert call_args[-1]["role"] == "user"
        assert call_args[-1]["content"] == "What is this?"

    def test_send_message_with_history(self):
        from potato.chat_manager import ChatManager
        mgr = ChatManager({})
        mgr.enabled = True
        mock_endpoint = MagicMock()
        mock_endpoint.chat_query.return_value = "Follow-up answer"
        mgr.endpoint = mock_endpoint

        history = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
        ]
        result = mgr.send_message("Second question", "txt", "id", history)

        call_args = mock_endpoint.chat_query.call_args[0][0]
        # system + 2 history + 1 new user message = 4
        assert len(call_args) == 4
        assert call_args[1]["content"] == "First question"
        assert call_args[2]["content"] == "First answer"
        assert call_args[3]["content"] == "Second question"

    def test_send_message_endpoint_error(self):
        from potato.chat_manager import ChatManager
        mgr = ChatManager({})
        mgr.enabled = True
        mock_endpoint = MagicMock()
        mock_endpoint.chat_query.side_effect = Exception("Connection refused")
        mgr.endpoint = mock_endpoint

        result = mgr.send_message("test", "text", "id", [])
        assert "error" in result["content"].lower()


class TestChatManagerSingleton:
    """Test singleton init/get/clear pattern."""

    def test_init_get_clear(self):
        from potato.chat_manager import (
            init_chat_manager, get_chat_manager, clear_chat_manager,
        )
        clear_chat_manager()
        assert get_chat_manager() is None

        mgr = init_chat_manager({})
        assert get_chat_manager() is mgr

        clear_chat_manager()
        assert get_chat_manager() is None
