"""
OpenAI Chat Completions Agent Proxy

Uses the OpenAI SDK to communicate with chat completion models.
Maintains conversation history in session context for multi-turn dialogue.

Configuration:
    agent_proxy:
      type: openai
      api_key: "${OPENAI_API_KEY}"   # or set OPENAI_API_KEY env var
      model: "gpt-4o"
      base_url: "http://localhost:8001/v1"   # optional, any OpenAI-compatible server
      system_prompt: "You are a helpful travel agent."
      temperature: 0.7
      max_tokens: 1024
"""

import logging
import os
from urllib.parse import urlparse

from .base import BaseAgentProxy, AgentMessage, AgentResponse, AgentProxyFactory

logger = logging.getLogger(__name__)


def _normalize_base_url(raw: str) -> str:
    """The OpenAI SDK appends '/chat/completions' to base_url. For bare host
    URLs (vLLM/local servers) append the conventional '/v1'; URLs that
    already carry a path (e.g. Gemini's /v1beta/openai/) are left intact."""
    if not raw:
        return raw
    u = raw.rstrip("/")
    if not urlparse(u).path:
        u = u + "/v1"
    return u


class OpenAIChatProxy(BaseAgentProxy):
    """OpenAI Chat Completions proxy."""

    proxy_type = "openai"

    def _endpoint_setting(self, name: str, default=""):
        """A connection setting, from `agent_proxy` or its `ai_config` block.

        Every other model-backed block in Potato nests these under
        `ai_config` -- `ai_support`, `live_agent`, `judge_calibration` -- so
        that is what an author writes here by analogy. Only the flat form was
        read, so a `base_url` written the usual way was invisible and the
        proxy then refused to start for want of an api_key it did not need.
        The flat form wins where both are given.
        """
        if name in self.config:
            return self.config.get(name, default)
        nested = self.config.get("ai_config")
        if isinstance(nested, dict) and name in nested:
            return nested.get(name, default)
        return default

    def _initialize(self):
        api_key = self._endpoint_setting("api_key", "") or ""
        # Support environment variable references like ${OPENAI_API_KEY}
        if isinstance(api_key, str) and api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            api_key = os.environ.get(env_var, "")

        if not api_key:
            api_key = os.environ.get("OPENAI_API_KEY", "")

        base_url = _normalize_base_url(
            self._endpoint_setting("base_url", "") or "") or None

        if not api_key:
            if base_url:
                # Local/OpenAI-compatible servers (vLLM etc.) ignore the key,
                # but the SDK requires a non-empty value.
                api_key = "EMPTY"
            else:
                raise ValueError(
                    "agent_proxy type 'openai' needs either an `api_key` (in "
                    "the block, or OPENAI_API_KEY in the environment) or a "
                    "`base_url` pointing at an OpenAI-compatible server, which "
                    "does not need a key. Both may be written directly in the "
                    "`agent_proxy` block or under `ai_config` inside it."
                )

        try:
            import openai
            self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        except ImportError:
            raise ImportError(
                "openai package is required for the OpenAI proxy. "
                "Install with: pip install openai"
            )

        self.model = self._endpoint_setting("model", "gpt-4o")
        self.system_prompt = self._endpoint_setting("system_prompt", "")
        self.temperature = self._endpoint_setting("temperature", 0.7)
        self.max_tokens = self._endpoint_setting("max_tokens", 1024)
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
