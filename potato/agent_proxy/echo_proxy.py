"""
Echo Agent Proxy

A testing/demo proxy that returns responses from a configurable list.
Cycles through responses in order, wrapping around when exhausted.

Configuration:
    agent_proxy:
      type: echo
      responses:
        - "I understand your request."
        - "Working on it now."
        - "Here's what I found."
"""

import logging

from .base import BaseAgentProxy, AgentMessage, AgentResponse, AgentProxyFactory

logger = logging.getLogger(__name__)


class EchoProxy(BaseAgentProxy):
    """Test proxy that returns canned responses in order."""

    proxy_type = "echo"

    def _initialize(self):
        self.responses = self.config.get("responses", [
            "I understand.",
            "Working on it.",
            "Done!",
        ])

    def start_session(self, task_description: str) -> dict:
        return {"response_index": 0, "task_description": task_description}

    def send_message(self, message: str, session_context: dict) -> AgentResponse:
        idx = session_context.get("response_index", 0)
        response_text = self.responses[idx % len(self.responses)]
        session_context["response_index"] = idx + 1

        return AgentResponse(
            message=AgentMessage(
                role="agent",
                content=response_text,
            )
        )

    def end_session(self, session_context: dict):
        pass


# Register with factory
AgentProxyFactory.register("echo", EchoProxy)
