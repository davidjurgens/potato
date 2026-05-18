"""
OpenAI AI endpoint implementation.

This module provides integration with OpenAI's API for LLM inference.
"""

import os
from typing import Dict, List
from openai import OpenAI
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError, ModelCapabilities

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIEndpoint(BaseAIEndpoint):
    """OpenAI endpoint for cloud-based LLM inference."""

    # Capabilities declaration for text-based OpenAI models
    CAPABILITIES = ModelCapabilities(
        text_generation=True,
        vision_input=False,
        bounding_box_output=False,
        text_classification=True,
        image_classification=False,
        rationale_generation=True,
        keyword_extraction=True,
    )

    def _initialize_client(self) -> None:
        """Initialize the OpenAI client."""
        # OpenAI-compatible servers (vLLM, llama.cpp, etc.) ignore the key
        # but the SDK rejects an empty string, so accept a placeholder.
        api_key = self.ai_config.get("api_key") or os.environ.get(
            "OPENAI_API_KEY", ""
        )
        base_url = self.ai_config.get("base_url")
        if not api_key:
            if base_url:
                api_key = "EMPTY"  # non-empty placeholder for local servers
            else:
                raise AIEndpointRequestError("OpenAI API key is required")

        # Default timeout of 30 seconds, configurable via ai_config
        timeout = self.ai_config.get("timeout", 30)
        client_kwargs = {"api_key": api_key, "timeout": timeout}
        # Honor a custom base_url so this endpoint can target any
        # OpenAI-compatible server (previously ignored -> always hit
        # api.openai.com even when a local base_url was configured).
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = OpenAI(**client_kwargs)

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

    def chat_query(self, messages: List[Dict[str, str]]) -> str:
        """Send a multi-turn chat to OpenAI using native messages API."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            return response.choices[0].message.content
        except Exception as e:
            raise AIEndpointRequestError(f"OpenAI chat request failed: {e}")

