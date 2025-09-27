"""
Hugging Face AI endpoint implementation.

This module provides integration with Hugging Face's Inference API for LLM inference.
"""

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

        self.client = InferenceClient(
            model=self.model,
            token=api_key
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
            return response.choices[0].message.content
        except Exception as e:
            raise AIEndpointRequestError(f"Hugging Face request failed: {e}")
