"""
OpenAI Chat Completions Agent Proxy

Uses the OpenAI SDK to communicate with chat completion models.
Maintains conversation history in session context for multi-turn dialogue.

Configuration:
    agent_proxy:
      type: openai
      api_key: "${OPENAI_API_KEY}"   # or set OPENAI_API_KEY env var
      model: "gpt-4o"
      system_prompt: "You are a helpful travel agent."
      temperature: 0.7
      max_tokens: 1024
"""

import logging
import os

from .base import BaseAgentProxy, AgentMessage, AgentResponse, AgentProxyFactory

logger = logging.getLogger(__name__)


class OpenAIChatProxy(BaseAgentProxy):
    """OpenAI Chat Completions proxy."""

    proxy_type = "openai"

    def _initialize(self):
        api_key = self.config.get("api_key", "")
        # Support environment variable references like ${OPENAI_API_KEY}
        if api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            api_key = os.environ.get(env_var, "")

        if not api_key:
            api_key = os.environ.get("OPENAI_API_KEY", "")

        if not api_key:
            raise ValueError(
                "OpenAI proxy requires api_key in config or OPENAI_API_KEY env var"
            )

        try:
            import openai
            self.client = openai.OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError(
                "openai package is required for the OpenAI proxy. "
                "Install with: pip install openai"
            )

        self.model = self.config.get("model", "gpt-4o")
        self.system_prompt = self.config.get("system_prompt", "")
        self.temperature = self.config.get("temperature", 0.7)
        self.max_tokens = self.config.get("max_tokens", 1024)
        self.timeout = self.config.get("sandbox", {}).get(
            "request_timeout_seconds", 60
        )

    def start_session(self, task_description: str) -> dict:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        # Include task description as system context
        messages.append({
            "role": "system",
            "content": f"The user's task: {task_description}",
        })
        return {"messages": messages}

    def send_message(self, message: str, session_context: dict) -> AgentResponse:
        messages = session_context.get("messages", [])
        messages.append({"role": "user", "content": message})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=self.timeout,
            )

            content = response.choices[0].message.content or ""
            messages.append({"role": "assistant", "content": content})
            session_context["messages"] = messages

            return AgentResponse(
                message=AgentMessage(role="agent", content=content)
            )

        except Exception as e:
            logger.error(f"OpenAI proxy error: {e}")
            return AgentResponse(
                message=AgentMessage(
                    role="error", content=f"Agent error: {e}"
                ),
                error=str(e),
            )


# Register with factory
AgentProxyFactory.register("openai", OpenAIChatProxy)
