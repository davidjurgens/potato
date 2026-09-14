"""
Hugging Face AI endpoint implementation.

Integration with Hugging Face's Inference API for LLM inference.
"""

from typing import Dict, List

from huggingface_hub import InferenceClient
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError

DEFAULT_MODEL = "meta-llama/Llama-3.2-3B-Instruct"

class HuggingfaceEndpoint(BaseAIEndpoint):
    """Hugging Face endpoint for cloud-based LLM inference."""

    def _initialize_client(self) -> None:
        """Initialize the Hugging Face client."""
        api_key = self.ai_config.get("api_key", "")
        if not api_key:
            raise AIEndpointRequestError("Hugging Face API key is required")

        # Default timeout of 30 seconds, configurable via ai_config
        timeout = self.ai_config.get("timeout", 30)
        self.client = InferenceClient(
            model=self.model,
            token=api_key,
            timeout=timeout
        )

    def _get_default_model(self) -> str:
        """Get the default Hugging Face model."""
        return DEFAULT_MODEL

    def query(self, prompt: str, output_format: dict) -> str:
        """
        Send a query to Hugging Face and return the response.

        Args:
            prompt: The prompt to send to the model

        Returns:
            The model's response as a string

        Raises:
            AIEndpointRequestError: If the request fails
        """
        try:
            response = self.client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format= {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "output_format",
                        "schema": output_format.model_json_schema(),
                        "strict": True,
                    }
                }
            )
            self._warn_if_truncated(
                self._stop_reason(response.choices[0], "finish_reason"))
            return response.choices[0].message.content
        except Exception as e:
            raise AIEndpointRequestError(f"Hugging Face request failed: {e}")

    def chat_query(self, messages: List[Dict[str, str]]) -> str:
        """Send a multi-turn chat to Hugging Face using the chat-completion API.

        The base class flattens the chat and calls query(prompt), which this
        class cannot answer without an output_format, so every chat message
        failed before a request was sent.
        """
        try:
            response = self.client.chat_completion(
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            self._warn_if_truncated(
                self._stop_reason(response.choices[0], "finish_reason"),
                where="chat reply")
            return response.choices[0].message.content or ""
        except Exception as e:
            raise AIEndpointRequestError(f"Hugging Face chat request failed: {e}")
