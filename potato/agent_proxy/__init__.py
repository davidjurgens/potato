"""
Agent Proxy Package

Provides agent proxy implementations for live agent interaction during annotation.
Proxies communicate with AI agent backends (echo, HTTP, OpenAI) and return
responses to the annotation interface.

Usage:
    from potato.agent_proxy import AgentProxyFactory

    proxy = AgentProxyFactory.create(config)
    context = proxy.start_session("Book a flight to Paris")
    response = proxy.send_message("Hello", context)
"""

from .base import AgentMessage, AgentResponse, BaseAgentProxy, AgentProxyFactory
from .session import (
    AgentSession,
    AgentSessionManager,
    init_agent_session_manager,
    get_agent_session_manager,
    clear_agent_session_manager,
)
from .sandbox import SafetySandbox, SandboxViolation

# Import proxy implementations to trigger registration
from . import echo_proxy
from . import http_proxy
from . import openai_proxy

__all__ = [
    "AgentMessage",
    "AgentResponse",
    "BaseAgentProxy",
    "AgentProxyFactory",
    "AgentSession",
    "AgentSessionManager",
    "init_agent_session_manager",
    "get_agent_session_manager",
    "clear_agent_session_manager",
    "SafetySandbox",
    "SandboxViolation",
]
