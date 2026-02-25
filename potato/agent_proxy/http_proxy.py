"""
Generic HTTP Agent Proxy

POSTs to any REST endpoint with configurable field mapping.
Supports sending full conversation history and custom headers.

Configuration:
    agent_proxy:
      type: http
      url: "http://localhost:8080/chat"
      headers:
        Authorization: "Bearer YOUR_KEY"
      message_key: "message"        # key in request body for user message
      response_key: "response"      # key in response JSON for agent reply
      session_id_key: "session_id"  # key in request/response for session tracking
      send_history: false           # whether to send full conversation history
      history_key: "messages"       # key for history array in request body
"""

import logging
import uuid

import requests

from .base import BaseAgentProxy, AgentMessage, AgentResponse, AgentProxyFactory

logger = logging.getLogger(__name__)


class GenericHTTPProxy(BaseAgentProxy):
    """Generic REST API proxy with configurable field mapping."""

    proxy_type = "http"

    def _initialize(self):
        self.url = self.config.get("url")
        if not self.url:
            raise ValueError("http proxy requires 'url' in agent_proxy config")

        self.headers = self.config.get("headers", {})
        self.message_key = self.config.get("message_key", "message")
        self.response_key = self.config.get("response_key", "response")
        self.session_id_key = self.config.get("session_id_key", "session_id")
        self.send_history = self.config.get("send_history", False)
        self.history_key = self.config.get("history_key", "messages")
        self.timeout = self.config.get("sandbox", {}).get(
            "request_timeout_seconds", 60
        )

    def start_session(self, task_description: str) -> dict:
        return {
            "session_id": str(uuid.uuid4()),
            "task_description": task_description,
            "history": [],
        }

    def send_message(self, message: str, session_context: dict) -> AgentResponse:
        payload = {
            self.message_key: message,
            self.session_id_key: session_context["session_id"],
        }

        if self.send_history:
            payload[self.history_key] = session_context.get("history", [])

        try:
            resp = requests.post(
                self.url,
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            response_text = data.get(self.response_key, "")
            if not response_text and isinstance(data, str):
                response_text = data

            # Update history
            session_context.setdefault("history", []).append(
                {"role": "user", "content": message}
            )
            session_context["history"].append(
                {"role": "agent", "content": response_text}
            )

            return AgentResponse(
                message=AgentMessage(role="agent", content=str(response_text))
            )

        except requests.Timeout:
            return AgentResponse(
                message=AgentMessage(role="error", content="Agent request timed out."),
                error="timeout",
            )
        except requests.RequestException as e:
            logger.error(f"HTTP proxy request failed: {e}")
            return AgentResponse(
                message=AgentMessage(
                    role="error", content=f"Agent communication error: {e}"
                ),
                error=str(e),
            )


# Register with factory
AgentProxyFactory.register("http", GenericHTTPProxy)
