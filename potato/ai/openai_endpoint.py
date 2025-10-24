"""
OpenAI AI endpoint implementation.

This module provides integration with OpenAI's API for LLM inference.
"""

from openai import OpenAI
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError

DEFAULT_MODEL = "gpt-4o-mini"

class OpenAIEndpoint(BaseAIEndpoint):
    """OpenAI endpoint for cloud-based LLM inference."""

    def _initialize_client(self) -> None:
        """Initialize the OpenAI client."""
        api_key = self.ai_config.get("api_key", "")
        if not api_key:
            raise AIEndpointRequestError("OpenRouter API key is required")

        self.client = OpenAI(api_key=api_key)

    def _get_default_model(self) -> str:
        """Get the default OpenAI model."""
        return DEFAULT_MODEL

    def query(self, prompt: str, output_format: dict) -> str:
        """
        Send a query to OpenAI and return the response.

        Args:
            prompt: The prompt to send to the model

        Returns:
            The model's response as a string

        Raises:
            AIEndpointRequestError: If the request fails
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                text_format=output_format.model_json_schema(),
            )
            return response.choices[0].message.content
        except Exception as e:
            raise AIEndpointRequestError(f"OpenAI request failed: {e}")

