"""
Unit tests for the agent proxy module.

Tests cover:
- EchoProxy send/receive cycle
- GenericHTTPProxy with mocked requests
- AgentProxyFactory registration and creation
- SafetySandbox limits
- AgentSessionManager lifecycle
- InteractiveChatDisplay rendering
"""

import time
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from potato.agent_proxy.base import (
    AgentMessage, AgentResponse, BaseAgentProxy, AgentProxyFactory,
)
from potato.agent_proxy.echo_proxy import EchoProxy
from potato.agent_proxy.sandbox import SafetySandbox, SandboxViolation
from potato.agent_proxy.session import (
    AgentSession, AgentSessionManager,
    init_agent_session_manager, get_agent_session_manager,
    clear_agent_session_manager,
)


class TestAgentMessage:
    """Test AgentMessage dataclass."""

    def test_defaults(self):
        msg = AgentMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert isinstance(msg.timestamp, float)
        assert msg.metadata == {}

    def test_custom_fields(self):
        msg = AgentMessage(
            role="agent", content="hi", timestamp=100.0,
            metadata={"key": "value"},
        )
        assert msg.timestamp == 100.0
        assert msg.metadata["key"] == "value"


class TestAgentResponse:
    """Test AgentResponse dataclass."""

    def test_defaults(self):
        msg = AgentMessage(role="agent", content="ok")
        resp = AgentResponse(message=msg)
        assert resp.done is False
        assert resp.error is None

    def test_with_error(self):
        msg = AgentMessage(role="error", content="fail")
        resp = AgentResponse(message=msg, error="timeout")
        assert resp.error == "timeout"


class TestEchoProxy:
    """Test the echo proxy implementation."""

    def test_default_responses(self):
        proxy = EchoProxy({"type": "echo"})
        ctx = proxy.start_session("test task")
        resp = proxy.send_message("hello", ctx)
        assert resp.message.role == "agent"
        assert resp.message.content == "I understand."

    def test_custom_responses(self):
        proxy = EchoProxy({"type": "echo", "responses": ["A", "B", "C"]})
        ctx = proxy.start_session("task")
        r1 = proxy.send_message("msg1", ctx)
        r2 = proxy.send_message("msg2", ctx)
        r3 = proxy.send_message("msg3", ctx)
        assert r1.message.content == "A"
        assert r2.message.content == "B"
        assert r3.message.content == "C"

    def test_wraps_around(self):
        proxy = EchoProxy({"type": "echo", "responses": ["X"]})
        ctx = proxy.start_session("task")
        r1 = proxy.send_message("a", ctx)
        r2 = proxy.send_message("b", ctx)
        assert r1.message.content == "X"
        assert r2.message.content == "X"

    def test_end_session(self):
        proxy = EchoProxy({"type": "echo"})
        ctx = proxy.start_session("task")
        proxy.end_session(ctx)  # Should not raise

    def test_session_context_has_task(self):
        proxy = EchoProxy({"type": "echo"})
        ctx = proxy.start_session("Book a flight")
        assert ctx["task_description"] == "Book a flight"


class TestGenericHTTPProxy:
    """Test the HTTP proxy with mocked requests."""

    def test_send_message_success(self):
        from potato.agent_proxy.http_proxy import GenericHTTPProxy

        proxy = GenericHTTPProxy({
            "type": "http",
            "url": "http://fake-agent/chat",
        })

        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Agent says hello"}
        mock_response.raise_for_status = MagicMock()

        ctx = proxy.start_session("test task")

        with patch("potato.agent_proxy.http_proxy.requests.post", return_value=mock_response) as mock_post:
            resp = proxy.send_message("hello", ctx)

        assert resp.message.content == "Agent says hello"
        assert resp.message.role == "agent"
        mock_post.assert_called_once()

    def test_send_message_custom_keys(self):
        from potato.agent_proxy.http_proxy import GenericHTTPProxy

        proxy = GenericHTTPProxy({
            "type": "http",
            "url": "http://fake-agent/chat",
            "message_key": "input",
            "response_key": "output",
        })

        mock_response = MagicMock()
        mock_response.json.return_value = {"output": "Custom response"}
        mock_response.raise_for_status = MagicMock()

        ctx = proxy.start_session("task")

        with patch("potato.agent_proxy.http_proxy.requests.post", return_value=mock_response) as mock_post:
            resp = proxy.send_message("test", ctx)

        assert resp.message.content == "Custom response"
        # Check the payload used the custom key
        call_kwargs = mock_post.call_args
        assert "input" in call_kwargs.kwargs["json"]

    def test_send_with_history(self):
        from potato.agent_proxy.http_proxy import GenericHTTPProxy

        proxy = GenericHTTPProxy({
            "type": "http",
            "url": "http://fake-agent/chat",
            "send_history": True,
        })

        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Got it"}
        mock_response.raise_for_status = MagicMock()

        ctx = proxy.start_session("task")

        with patch("potato.agent_proxy.http_proxy.requests.post", return_value=mock_response):
            proxy.send_message("first", ctx)

        # History should now have 2 entries (user + agent)
        assert len(ctx["history"]) == 2
        assert ctx["history"][0]["role"] == "user"
        assert ctx["history"][1]["role"] == "agent"

    def test_send_message_timeout(self):
        import requests as req_lib
        from potato.agent_proxy.http_proxy import GenericHTTPProxy

        proxy = GenericHTTPProxy({
            "type": "http",
            "url": "http://fake-agent/chat",
        })

        ctx = proxy.start_session("task")

        with patch("potato.agent_proxy.http_proxy.requests.post", side_effect=req_lib.Timeout()):
            resp = proxy.send_message("hello", ctx)

        assert resp.error == "timeout"
        assert resp.message.role == "error"

    def test_missing_url_raises(self):
        from potato.agent_proxy.http_proxy import GenericHTTPProxy

        with pytest.raises(ValueError, match="requires 'url'"):
            GenericHTTPProxy({"type": "http"})


class TestAgentProxyFactory:
    """Test the factory registry."""

    def test_echo_registered(self):
        assert "echo" in AgentProxyFactory.get_supported_types()

    def test_http_registered(self):
        assert "http" in AgentProxyFactory.get_supported_types()

    def test_openai_registered(self):
        assert "openai" in AgentProxyFactory.get_supported_types()

    def test_create_echo(self):
        proxy = AgentProxyFactory.create({"agent_proxy": {"type": "echo"}})
        assert isinstance(proxy, EchoProxy)

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown agent proxy type"):
            AgentProxyFactory.create({"agent_proxy": {"type": "nonexistent"}})

    def test_create_missing_type_raises(self):
        with pytest.raises(ValueError, match="agent_proxy.type is required"):
            AgentProxyFactory.create({"agent_proxy": {}})


class TestSafetySandbox:
    """Test sandbox safety limits."""

    def test_step_limit_ok(self):
        sandbox = SafetySandbox({"sandbox": {"max_steps": 5}})
        sandbox.check_step_limit(4)  # Should not raise

    def test_step_limit_exceeded(self):
        sandbox = SafetySandbox({"sandbox": {"max_steps": 5}})
        with pytest.raises(SandboxViolation, match="Step limit"):
            sandbox.check_step_limit(5)

    def test_session_timeout_ok(self):
        sandbox = SafetySandbox({"sandbox": {"max_session_seconds": 600}})
        sandbox.check_session_timeout(time.time() - 10)  # Should not raise

    def test_session_timeout_exceeded(self):
        sandbox = SafetySandbox({"sandbox": {"max_session_seconds": 1}})
        with pytest.raises(SandboxViolation, match="Session timeout"):
            sandbox.check_session_timeout(time.time() - 10)

    def test_rate_limit_ok(self):
        sandbox = SafetySandbox({"sandbox": {"rate_limit_per_minute": 5}})
        for _ in range(5):
            sandbox.check_rate_limit("user1")  # Should not raise on last one
        # But 6th should fail
        with pytest.raises(SandboxViolation, match="Rate limit"):
            sandbox.check_rate_limit("user1")

    def test_rate_limit_per_user(self):
        sandbox = SafetySandbox({"sandbox": {"rate_limit_per_minute": 2}})
        sandbox.check_rate_limit("user1")
        sandbox.check_rate_limit("user1")
        # user2 is separate
        sandbox.check_rate_limit("user2")  # Should not raise

    def test_default_values(self):
        sandbox = SafetySandbox({})
        assert sandbox.max_steps == 20
        assert sandbox.max_session_seconds == 600
        assert sandbox.rate_limit_per_minute == 10
        assert sandbox.request_timeout == 60

    def test_request_timeout(self):
        sandbox = SafetySandbox({"sandbox": {"request_timeout_seconds": 30}})
        assert sandbox.get_request_timeout() == 30


class TestAgentSessionManager:
    """Test the session manager lifecycle."""

    def setup_method(self):
        clear_agent_session_manager()

    def teardown_method(self):
        clear_agent_session_manager()

    def test_singleton_init_and_get(self):
        mgr = init_agent_session_manager({"agent_proxy": {"type": "echo"}})
        assert mgr is get_agent_session_manager()

    def test_get_before_init_raises(self):
        with pytest.raises(ValueError, match="not been initialized"):
            get_agent_session_manager()

    def test_create_and_get_session(self):
        mgr = init_agent_session_manager({})
        proxy = EchoProxy({"type": "echo"})
        session = mgr.create_session("user1", "item1", proxy, "test task")
        assert session.user_id == "user1"
        assert session.instance_id == "item1"
        assert session.step_count == 0
        assert session.finished is False

        retrieved = mgr.get_session("user1", "item1")
        assert retrieved is session

    def test_get_nonexistent_returns_none(self):
        mgr = init_agent_session_manager({})
        assert mgr.get_session("nobody", "nothing") is None

    def test_create_duplicate_returns_existing(self):
        mgr = init_agent_session_manager({})
        proxy = EchoProxy({"type": "echo"})
        s1 = mgr.create_session("user1", "item1", proxy, "task")
        s2 = mgr.create_session("user1", "item1", proxy, "task")
        assert s1 is s2

    def test_remove_session(self):
        mgr = init_agent_session_manager({})
        proxy = EchoProxy({"type": "echo"})
        mgr.create_session("user1", "item1", proxy, "task")
        mgr.remove_session("user1", "item1")
        assert mgr.get_session("user1", "item1") is None

    def test_remove_nonexistent_is_safe(self):
        mgr = init_agent_session_manager({})
        mgr.remove_session("nobody", "nothing")  # Should not raise


class TestInteractiveChatDisplay:
    """Test the interactive chat display rendering."""

    def test_render_empty_data_shows_chat_panel(self):
        from potato.server_utils.displays.interactive_chat_display import InteractiveChatDisplay
        display = InteractiveChatDisplay()
        html = display.render({"key": "conversation"}, None)
        assert "agent-chat-panel" in html
        assert "agent-chat-messages" in html
        assert "agent-chat-input" in html
        assert "agent-chat-send-btn" in html
        assert "agent-chat-finish-btn" in html

    def test_render_empty_list_shows_chat_panel(self):
        from potato.server_utils.displays.interactive_chat_display import InteractiveChatDisplay
        display = InteractiveChatDisplay()
        html = display.render({"key": "conversation"}, [])
        assert "agent-chat-panel" in html

    def test_render_populated_data_shows_dialogue(self):
        from potato.server_utils.displays.interactive_chat_display import InteractiveChatDisplay
        display = InteractiveChatDisplay()
        conversation = [
            {"speaker": "User", "text": "Hello"},
            {"speaker": "Agent", "text": "Hi there"},
        ]
        html = display.render({"key": "conversation"}, conversation)
        # Should render as dialogue, not chat panel
        assert "agent-chat-panel" not in html
        assert "dialogue" in html
        assert "Hello" in html
        assert "Hi there" in html

    def test_chat_active_data_attribute(self):
        from potato.server_utils.displays.interactive_chat_display import InteractiveChatDisplay
        display = InteractiveChatDisplay()

        # Empty data -> chat-active = true
        attrs = display.get_data_attributes({"key": "conv"}, None)
        assert attrs["chat-active"] == "true"

        # Populated data -> chat-active = false
        attrs = display.get_data_attributes({"key": "conv"}, [{"speaker": "User", "text": "hi"}])
        assert attrs["chat-active"] == "false"

    def test_custom_placeholder(self):
        from potato.server_utils.displays.interactive_chat_display import InteractiveChatDisplay
        display = InteractiveChatDisplay()
        html = display.render(
            {"key": "conv", "display_options": {"placeholder_text": "Custom placeholder"}},
            None,
        )
        assert "Custom placeholder" in html

    def test_supports_span_target(self):
        from potato.server_utils.displays.interactive_chat_display import InteractiveChatDisplay
        display = InteractiveChatDisplay()
        assert display.supports_span_target is True


class TestDisplayRegistryIntegration:
    """Test that interactive_chat is properly registered."""

    def test_interactive_chat_in_registry(self):
        from potato.server_utils.displays.registry import display_registry
        assert display_registry.is_registered("interactive_chat")

    def test_interactive_chat_in_supported_types(self):
        from potato.server_utils.displays.registry import display_registry
        assert "interactive_chat" in display_registry.get_supported_types()

    def test_interactive_chat_supports_span(self):
        from potato.server_utils.displays.registry import display_registry
        assert display_registry.supports_span_target("interactive_chat") is True
