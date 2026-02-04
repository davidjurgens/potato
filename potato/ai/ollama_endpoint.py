"""
Ollama AI endpoint implementation.

This module provides integration with Ollama for local LLM inference.
"""

import json
from typing import Type
import ollama
from pydantic import BaseModel
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError, ModelCapabilities
import re


DEFAULT_MODEL = "llama3.2"


class OllamaEndpoint(BaseAIEndpoint):
    """Ollama endpoint for local LLM inference."""

    # Capabilities declaration for text-based Ollama models
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
        import logging
        logger = logging.getLogger(__name__)

        try:
            logger.debug(f"[Ollama] Querying model: {self.model}")
            logger.debug(f"[Ollama] Prompt (first 200 chars): {prompt[:200]}...")

            # Disable thinking mode for qwen3 models to get direct JSON output
            options = {
                'temperature': self.temperature,
                'num_predict': self.max_tokens
            }

            response = self.client.chat(
                model=self.model,
                messages=[{'role': 'user', 'content': prompt}],
                options=options,
                format=output_format.model_json_schema(),
                think=False,  # Disable thinking mode for direct output
            )

            # Log full response structure for debugging
            logger.debug(f"[Ollama] Response type: {type(response)}")
            logger.debug(f"[Ollama] Full response: {response}")

            # Get the message object - handle both dict and object access
            message = response.get('message') if hasattr(response, 'get') else getattr(response, 'message', None)
            if message is None:
                raise AIEndpointRequestError("No message in Ollama response")

            # Get content - handle both dict and object access
            content = message.get('content') if hasattr(message, 'get') else getattr(message, 'content', None)

            # Some models put response in 'thinking' field - check that too
            if not content and hasattr(message, 'thinking') and message.thinking:
                logger.warning("[Ollama] Content empty but thinking field has data - model may need think=False")
                # Try to extract JSON from thinking field as fallback
                thinking_text = message.thinking
                # Look for JSON in the thinking text
                import re
                json_match = re.search(r'\{[^{}]*\}', thinking_text)
                if json_match:
                    content = json_match.group(0)
                    logger.debug(f"[Ollama] Extracted JSON from thinking: {content}")

            logger.debug(f"[Ollama] Content type: {type(content)}")
            logger.debug(f"[Ollama] Content value: {repr(content)[:200] if content else 'EMPTY'}")

            # If content is already a dict (structured output), return it directly
            if isinstance(content, dict):
                logger.debug("[Ollama] Content is already a dict, returning directly")
                return content

            # Otherwise parse as JSON string
            if content:
                logger.debug(f"[Ollama] Response content (first 500 chars): {str(content)[:500]}")
                return self.parseStringToJson(content)
            else:
                raise AIEndpointRequestError("Empty content from Ollama - try a different model or disable thinking mode")
        except Exception as e:
            logger.error(f"[Ollama] Request failed: {e}")
            raise AIEndpointRequestError(f"Ollama request failed: {e}")
        
  

