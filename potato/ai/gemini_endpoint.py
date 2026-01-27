"""
Google Gemini AI endpoint implementation.

This module provides integration with Google's Gemini API for LLM inference.
"""

from google import genai
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError

DEFAULT_MODEL = "gemini-2.0-flash-exp"


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
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                generation_config={
                    'max_output_tokens': self.max_tokens,
                    'temperature': self.temperature,
                    'response_schema': prompt_format.model_json_schema(),
                }
            )
            return response.text
        except Exception as e:
            raise AIEndpointRequestError(f"Gemini request failed: {e}")
