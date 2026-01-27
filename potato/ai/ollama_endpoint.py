"""
Ollama AI endpoint implementation.

This module provides integration with Ollama for local LLM inference.
"""

import json
from typing import Type
import ollama
from pydantic import BaseModel
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError
import re


DEFAULT_MODEL = "llama3.2"

class OllamaEndpoint(BaseAIEndpoint):
    """Ollama endpoint for local LLM inference."""

    def _initialize_client(self) -> None:
        """Initialize the Ollama client."""
        # Default timeout of 60 seconds for local inference (can be slower)
        timeout = self.ai_config.get("timeout", 60)
        host = self.ai_config.get("base_url", "http://localhost:11434")

        # Create client with timeout
        self.client = ollama.Client(host=host, timeout=timeout)

        # Check if Ollama is available
        try:
            self.client.list()
        except Exception as e:
            raise AIEndpointRequestError(f"Failed to connect to Ollama: {e}")

    def _get_default_model(self) -> str:
        """Get the default Ollama model."""
        return DEFAULT_MODEL

    def query(self, prompt: str, output_format: Type[BaseModel]) -> str:
        """
        Send a query to Ollama and return the response.

        Args:
            prompt: The prompt to send to the model

        Returns:
            The model's response as a string

        Raises:
            AIEndpointRequestError: If the request fails
        """
        try:
            response = self.client.chat(
                model=self.model,
                messages=[{'role': 'user', 'content': prompt}],
                options={
                    'temperature': self.temperature,
                    'num_predict': self.max_tokens
                }, 
                format=output_format.model_json_schema(),
                think= False,
            )
            return self.parseStringToJson(response['message']['content'])
        except Exception as e:
            raise AIEndpointRequestError(f"Ollama request failed: {e}")
        
  

