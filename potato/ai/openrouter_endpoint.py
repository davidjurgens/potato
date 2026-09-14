"""
OpenRouter endpoint implementation.
integration with OpenRouter's API for LLM inference.
"""
from typing import Any, Dict, List

import requests
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError

DEFAULT_MODEL = "openai/gpt-4o-mini"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

class OpenRouterEndpoint(BaseAIEndpoint):
    """OpenRouter endpoint for cloud-based LLM inference."""

    # Models that support structured output
    STRUCTURED_OUTPUT_MODELS = {
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "openai/gpt-4-turbo",
        "anthropic/claude-3-5-sonnet",
        "deepseek/deepseek-r1:free"
    }

    def _initialize_client(self) -> None:
        """Initialize the OpenAI client."""
        api_key = self.ai_config.get("api_key", "")
        if not api_key:
            raise AIEndpointRequestError("OpenRouter API key is required")
        # Default timeout of 30 seconds, configurable via ai_config, as on
        # every other endpoint. Without one, requests.post waits forever and
        # a stalled provider hangs the annotator's request with it.
        self.timeout = self.ai_config.get("timeout", 30)

    def _get_default_model(self) -> str:
        """Get the default OpenAI model."""
        return DEFAULT_MODEL

    def supports_structured_output(self) -> bool:
        """Check if the current model supports structured output."""
        model = self.model or DEFAULT_MODEL
        return any(model.startswith(prefix.split('/')[0]) or model in self.STRUCTURED_OUTPUT_MODELS
                   for prefix in self.STRUCTURED_OUTPUT_MODELS)

    def _post(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """POST one chat-completion request and return the decoded reply."""
        headers = {
            "Authorization": f"Bearer {self.ai_config.get('api_key')}",
            "Content-Type": "application/json"
        }
        r = requests.post(API_URL, headers=headers, json=body,
                          timeout=getattr(self, "timeout", 30))
        if r.status_code >= 400:
            raise AIEndpointRequestError(f"OpenRouter error {r.status_code}: {r.text}")
        return r.json()

    def query(self, prompt: str, output_format: dict) -> str:
        """
        Send a query to OpenRouter and return the response.

        Args:
            prompt: The prompt to send to the model (as messages list or string)
            output_format: Pydantic model for structured output

        Returns:
            The model's response as a string

        Raises:
            AIEndpointRequestError: If the request fails
        """
        try:
            messages = [{"role": "user", "content": prompt}]
            schema = output_format.model_json_schema()

            body = {
                "model": self.model or DEFAULT_MODEL,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "messages": messages,
            }

            # Handle structured output based on model support. A model that
            # does not support it gets the raw prompt.
            if self.supports_structured_output():
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "response",
                        "schema": schema,
                        "strict": True
                    }
                }

            data = self._post(body)
            self._warn_if_truncated(data["choices"][0].get("finish_reason"))
            if self.supports_structured_output():
                return self.parseStringToJson(data["choices"][0]["message"]["content"])
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            raise AIEndpointRequestError(f"OpenRouter request failed: {e}")

    def chat_query(self, messages: List[Dict[str, str]]) -> str:
        """Send a multi-turn chat to OpenRouter as free text.

        The base class flattens the chat and calls query(prompt), which this
        class cannot answer without an output_format, so every chat message
        failed before a request was sent.
        """
        try:
            data = self._post({
                "model": self.model or DEFAULT_MODEL,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "messages": messages,
            })
            self._warn_if_truncated(data["choices"][0].get("finish_reason"),
                                    where="chat reply")
            return data["choices"][0]["message"].get("content") or ""
        except Exception as e:
            raise AIEndpointRequestError(f"OpenRouter chat request failed: {e}")
