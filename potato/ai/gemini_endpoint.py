"""
Google Gemini AI endpoint implementation.

Integration with Google's Gemini API for LLM inference.
"""

from typing import Dict, List

from google import genai
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError

# Was gemini-2.0-flash-exp: an experimental preview, and unpriced, so a
# study that never set a model ran uncapped. See the note in
# anthropic_endpoint.
DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiEndpoint(BaseAIEndpoint):
    """Google Gemini endpoint for cloud-based LLM inference."""

    def _initialize_client(self) -> None:
        """Initialize the Gemini client."""
        api_key = self.ai_config.get("api_key", "")
        if not api_key:
            raise AIEndpointRequestError("Gemini API key is required")

        # Default timeout of 30 seconds, configurable via ai_config
        timeout = self.ai_config.get("timeout", 30)
        self.client = genai.Client(
            api_key=api_key,
            http_options={'timeout': timeout}
        )

    def _get_default_model(self) -> str:
        """Get the default Gemini model."""
        return DEFAULT_MODEL

    def query(self, prompt: str, prompt_format: dict) -> str:
        """
        Send a query to Gemini and return the response.

        Args:
            prompt: The prompt to send to the model

        Returns:
            The model's response as a string

        Raises:
            AIEndpointRequestError: If the request fails
        """
        try:
            # `config=`, not `generation_config=`: google-genai's
            # generate_content has no generation_config parameter, so every
            # call raised TypeError before a request was sent. A raw JSON
            # schema goes in response_json_schema, which needs the JSON mime
            # type alongside it.
            config = {
                'max_output_tokens': self.max_tokens,
                'temperature': self.temperature,
            }
            if prompt_format is not None and hasattr(prompt_format, "model_json_schema"):
                config['response_mime_type'] = 'application/json'
                config['response_json_schema'] = prompt_format.model_json_schema()
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                self._warn_if_truncated(
                    self._stop_reason(candidates[0], "finish_reason", "finishReason"))
            return response.text
        except Exception as e:
            raise AIEndpointRequestError(f"Gemini request failed: {e}")

    def chat_query(self, messages: List[Dict[str, str]]) -> str:
        """Send a multi-turn chat to Gemini as free text.

        Gemini calls the assistant role "model" and takes the system prompt as
        a config field rather than a turn. The base class's fallback called
        query(prompt) without a prompt_format and failed on every message.
        """
        try:
            system_parts = []
            contents = []
            for msg in messages:
                if msg["role"] == "system":
                    system_parts.append(msg["content"])
                    continue
                role = "model" if msg["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

            config = {
                'max_output_tokens': self.max_tokens,
                'temperature': self.temperature,
            }
            if system_parts:
                config['system_instruction'] = "\n\n".join(system_parts)

            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                self._warn_if_truncated(
                    self._stop_reason(candidates[0], "finish_reason", "finishReason"),
                    where="chat reply")
            return response.text or ""
        except Exception as e:
            raise AIEndpointRequestError(f"Gemini chat request failed: {e}")
