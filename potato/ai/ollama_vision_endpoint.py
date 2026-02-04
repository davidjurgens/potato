"""
Ollama Vision AI Endpoint

This module provides integration with Ollama vision models for local
visual AI inference. Supports LLaVA, Llama 3.2 Vision, BakLLaVA, and Qwen-VL models.
"""

import base64
import json
import logging
from typing import Any, Dict, List, Type, Union

from pydantic import BaseModel

from .ai_endpoint import AIEndpointRequestError, ImageData, ModelCapabilities
from .visual_ai_endpoint import BaseVisualAIEndpoint

logger = logging.getLogger(__name__)

# Default vision model
DEFAULT_MODEL = "llava:latest"

# Models known to support vision (used only for warning suppression, not to restrict usage)
# Any Ollama model can be used - this list just prevents "may not support vision" warnings
# for models we know are vision-capable
VISION_MODELS = [
    # LLaVA family
    "llava",
    "llava-llama3",
    "llava-phi3",
    "bakllava",
    # Llama Vision
    "llama3.2-vision",
    # Qwen Vision-Language
    "qwen2.5-vl",
    "qwen2-vl",
    "qwen3-vl",
    # Other vision models
    "moondream",
    "minicpm-v",
    "gemma3",  # Gemma 3 has vision capabilities
]


class OllamaVisionEndpoint(BaseVisualAIEndpoint):
    """
    Ollama Vision endpoint for multimodal local inference.

    Supports vision-capable models like LLaVA, Llama 3.2 Vision, BakLLaVA.
    Images are sent as base64 in the 'images' field.

    Configuration options:
    - model: Vision model to use (default: llava:latest)
    - base_url: Ollama server URL (default: http://localhost:11434)
    - timeout: Request timeout in seconds (default: 120)
    - max_tokens: Maximum response tokens (default: 500)
    - temperature: Sampling temperature (default: 0.1)
    """

    # Capabilities declaration for vision-capable Ollama models (LLaVA, Qwen-VL, etc.)
    # Note: VLLMs can generate text about images but cannot do precise bounding box detection
    # Keyword extraction is disabled because it doesn't apply to image content
    CAPABILITIES = ModelCapabilities(
        text_generation=True,
        vision_input=True,
        bounding_box_output=False,  # VLLMs are not reliable for precise bbox coordinates
        text_classification=True,
        image_classification=True,
        rationale_generation=True,
        keyword_extraction=False,  # Keywords don't apply to images
    )

    def _initialize_client(self) -> None:
        """Initialize the Ollama client."""
        try:
            import ollama
        except ImportError:
            raise AIEndpointRequestError(
                "ollama package is required. Install it with: pip install ollama"
            )

        timeout = self.ai_config.get("timeout", 120)  # Vision models can be slower
        host = self.ai_config.get("base_url", "http://localhost:11434")

        self.client = ollama.Client(host=host, timeout=timeout)

        # Verify connection and model availability
        try:
            models = self.client.list()
            logger.info(f"Connected to Ollama at {host}")

            # Check if the specified model is a known vision model
            # This is just informational - any model can be used
            model_lower = self.model.lower()
            is_known_vision_model = any(vm in model_lower for vm in VISION_MODELS)
            if not is_known_vision_model:
                logger.info(
                    f"Model '{self.model}' not in known vision models list. "
                    f"This is fine if it supports vision - proceeding anyway."
                )

        except Exception as e:
            raise AIEndpointRequestError(f"Failed to connect to Ollama: {e}")

    def _get_default_model(self) -> str:
        """Get the default vision model."""
        return DEFAULT_MODEL

    def query(self, prompt: str, output_format: Type[BaseModel]) -> Any:
        """
        Standard text query (falls back to text-only mode).

        For vision tasks, use query_with_image() instead.
        """
        try:
            options = {
                'temperature': self.temperature,
                'num_predict': self.max_tokens
            }

            response = self.client.chat(
                model=self.model,
                messages=[{'role': 'user', 'content': prompt}],
                options=options,
                format=output_format.model_json_schema(),
                think=False,
            )

            message = response.get('message') if hasattr(response, 'get') else getattr(response, 'message', None)
            if message is None:
                raise AIEndpointRequestError("No message in Ollama response")

            content = message.get('content') if hasattr(message, 'get') else getattr(message, 'content', None)

            if isinstance(content, dict):
                return content

            if content:
                return self.parseStringToJson(content)
            else:
                raise AIEndpointRequestError("Empty content from Ollama")

        except Exception as e:
            raise AIEndpointRequestError(f"Ollama query failed: {e}")

    def query_with_image(
        self,
        prompt: str,
        image_data: Union[ImageData, List[ImageData]],
        output_format: Type[BaseModel]
    ) -> Any:
        """
        Send a query with image(s) to Ollama vision model.

        Args:
            prompt: Text prompt describing what to analyze
            image_data: Single ImageData or list of ImageData
            output_format: Pydantic model for structured output

        Returns:
            Parsed response according to output_format

        Raises:
            AIEndpointRequestError: If the request fails
        """
        try:
            # Prepare images
            images = [image_data] if isinstance(image_data, ImageData) else image_data

            # Convert to base64 if needed
            image_base64_list = []
            for img in images:
                b64_data = self._get_base64_image(img)
                image_base64_list.append(b64_data)

            # Build message with images
            options = {
                'temperature': self.temperature,
                'num_predict': self.max_tokens
            }

            # Ollama expects images as a list of base64 strings
            response = self.client.chat(
                model=self.model,
                messages=[{
                    'role': 'user',
                    'content': prompt,
                    'images': image_base64_list
                }],
                options=options,
                format=output_format.model_json_schema(),
                think=False,
            )

            logger.debug(f"Ollama vision response type: {type(response)}")

            # Extract content from response
            message = response.get('message') if hasattr(response, 'get') else getattr(response, 'message', None)
            if message is None:
                raise AIEndpointRequestError("No message in Ollama vision response")

            content = message.get('content') if hasattr(message, 'get') else getattr(message, 'content', None)

            logger.debug(f"Ollama vision content type: {type(content)}")

            # Parse response
            if isinstance(content, dict):
                return content

            if content:
                return self.parseStringToJson(content)
            else:
                raise AIEndpointRequestError("Empty content from Ollama vision model")

        except AIEndpointRequestError:
            raise
        except Exception as e:
            logger.error(f"Ollama vision query failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise AIEndpointRequestError(f"Ollama vision query failed: {e}")

    def _get_base64_image(self, image_data: ImageData) -> str:
        """
        Get base64-encoded image data.

        Args:
            image_data: ImageData object

        Returns:
            Base64-encoded image string (without data URL prefix)
        """
        if image_data.source == "base64":
            # Already base64, just return the data
            return image_data.data

        elif image_data.source == "url":
            # Download and convert to base64
            downloaded = self.download_image_to_base64(image_data.data)
            return downloaded.data

        else:
            raise AIEndpointRequestError(f"Unknown image source: {image_data.source}")

    def analyze_image(
        self,
        image_path_or_url: str,
        prompt: str,
        output_format: Type[BaseModel] = None
    ) -> Any:
        """
        Convenience method for analyzing a single image.

        Args:
            image_path_or_url: Path to image file or URL
            prompt: Analysis prompt
            output_format: Optional output format model

        Returns:
            Analysis result
        """
        # Prepare image data
        if image_path_or_url.startswith(("http://", "https://")):
            image_data = self.download_image_to_base64(image_path_or_url)
        else:
            image_data = self.encode_image_to_base64(image_path_or_url)

        # Use a generic format if not specified
        if output_format is None:
            from .prompt.models_module import GeneralHintFormat
            output_format = GeneralHintFormat

        return self.query_with_image(prompt, image_data, output_format)

    def describe_image(self, image_path_or_url: str) -> str:
        """
        Get a natural language description of an image.

        Args:
            image_path_or_url: Path to image file or URL

        Returns:
            Text description of the image
        """
        # Use a simple model that returns text
        class DescriptionFormat(BaseModel):
            description: str

        result = self.analyze_image(
            image_path_or_url,
            "Describe this image in detail. What objects, people, or scenes do you see?",
            DescriptionFormat
        )

        if isinstance(result, dict) and "description" in result:
            return result["description"]
        return str(result)

    def health_check(self) -> bool:
        """
        Check if the Ollama vision model is available.

        Returns:
            True if model is ready, False otherwise
        """
        try:
            # Try to list models
            self.client.list()
            return True
        except Exception as e:
            logger.error(f"Ollama vision health check failed: {e}")
            return False
