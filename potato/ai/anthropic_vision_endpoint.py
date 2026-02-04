"""
Anthropic Vision AI Endpoint

This module provides integration with Anthropic's Claude models for visual
analysis using the image content block format.
"""

import base64
import logging
from typing import Any, Dict, List, Type, Union

from pydantic import BaseModel

from .ai_endpoint import AIEndpointRequestError, ImageData, ModelCapabilities
from .visual_ai_endpoint import BaseVisualAIEndpoint

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"

# Supported image types for Claude
SUPPORTED_MEDIA_TYPES = [
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp"
]


class AnthropicVisionEndpoint(BaseVisualAIEndpoint):
    """
    Anthropic Vision endpoint for Claude models with vision capabilities.

    Uses the image content block format for multimodal inputs.

    Configuration options:
    - model: Model to use (default: claude-sonnet-4-20250514)
    - api_key: Anthropic API key (can also use ANTHROPIC_API_KEY env var)
    - max_tokens: Maximum response tokens (default: 1024)
    - temperature: Sampling temperature (default: 0.1)
    """

    # Capabilities declaration for Anthropic Claude vision models
    # Claude models can understand images and generate detailed reasoning but bboxes are approximate
    CAPABILITIES = ModelCapabilities(
        text_generation=True,
        vision_input=True,
        bounding_box_output=False,  # Claude bboxes are approximate, not precise
        text_classification=True,
        image_classification=True,
        rationale_generation=True,
        keyword_extraction=False,  # Keywords don't apply to images
    )

    def _initialize_client(self) -> None:
        """Initialize the Anthropic client."""
        try:
            import anthropic
        except ImportError:
            raise AIEndpointRequestError(
                "anthropic package is required. Install it with: pip install anthropic"
            )

        import os

        api_key = self.ai_config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise AIEndpointRequestError(
                "Anthropic API key is required. Set it in config or ANTHROPIC_API_KEY env var."
            )

        timeout = self.ai_config.get("timeout", 60)

        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        logger.info(f"Anthropic Vision client initialized with model: {self.model}")

    def _get_default_model(self) -> str:
        """Get the default Anthropic model."""
        return DEFAULT_MODEL

    def query(self, prompt: str, output_format: Type[BaseModel]) -> Any:
        """
        Standard text query without images.

        Args:
            prompt: Text prompt
            output_format: Pydantic model for structured output

        Returns:
            Parsed response
        """
        try:
            # Add JSON instruction to prompt
            json_prompt = f"""{prompt}

Please respond with valid JSON matching this schema:
{output_format.model_json_schema()}"""

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": json_prompt}],
            )

            content = response.content[0].text
            return self.parseStringToJson(content)

        except Exception as e:
            raise AIEndpointRequestError(f"Anthropic query failed: {e}")

    def query_with_image(
        self,
        prompt: str,
        image_data: Union[ImageData, List[ImageData]],
        output_format: Type[BaseModel]
    ) -> Any:
        """
        Send a query with image(s) to Claude vision model.

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

            # Build content array with images first, then text
            content = []

            for img in images:
                image_block = self._build_image_block(img)
                content.append(image_block)

            # Add JSON instruction to prompt
            json_prompt = f"""{prompt}

Please respond with valid JSON matching this schema:
{output_format.model_json_schema()}

Only return the JSON object, no other text."""

            content.append({"type": "text", "text": json_prompt})

            # Make request
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": content}],
            )

            response_content = response.content[0].text
            logger.debug(f"Anthropic vision response: {response_content[:500] if response_content else 'empty'}")

            return self.parseStringToJson(response_content)

        except AIEndpointRequestError:
            raise
        except Exception as e:
            logger.error(f"Anthropic vision query failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise AIEndpointRequestError(f"Anthropic vision query failed: {e}")

    def _build_image_block(self, image_data: ImageData) -> Dict[str, Any]:
        """
        Build image content block for Anthropic API.

        Args:
            image_data: ImageData object

        Returns:
            Dict with type: "image" and source content
        """
        if image_data.source == "url":
            # Claude supports URL sources directly
            return {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": image_data.data
                }
            }

        elif image_data.source == "base64":
            # Determine media type
            media_type = image_data.mime_type or "image/jpeg"

            # Validate media type
            if media_type not in SUPPORTED_MEDIA_TYPES:
                logger.warning(f"Media type {media_type} may not be supported. Using image/jpeg.")
                media_type = "image/jpeg"

            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_data.data
                }
            }

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
            # Claude can use URLs directly
            image_data = self.create_url_image_data(image_path_or_url)
        else:
            image_data = self.encode_image_to_base64(image_path_or_url)

        # Use a generic format if not specified
        if output_format is None:
            from .prompt.models_module import GeneralHintFormat
            output_format = GeneralHintFormat

        return self.query_with_image(prompt, image_data, output_format)

    def detect_objects(
        self,
        image_path_or_url: str,
        labels: List[str] = None
    ) -> Dict[str, Any]:
        """
        Detect objects in an image and return bounding boxes.

        Args:
            image_path_or_url: Path to image file or URL
            labels: Optional list of labels to detect

        Returns:
            Dict with detections list
        """
        from .prompt.models_module import VisualDetectionFormat

        labels_str = ", ".join(labels) if labels else "all visible objects"

        prompt = f"""Analyze this image and detect objects. For each object, provide:
1. The label (from: {labels_str})
2. A bounding box with normalized coordinates (0-1 range)
3. Confidence score (0-1)

Return a JSON object with this exact structure:
{{
    "detections": [
        {{
            "label": "object_name",
            "bbox": {{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}},
            "confidence": 0.95
        }}
    ]
}}

Important:
- Coordinates are normalized (0-1) where x,y is the top-left corner
- x increases left to right, y increases top to bottom
- width and height are also normalized (0-1)
- Only include objects you can clearly identify
- Estimate bounding boxes as accurately as possible"""

        # Prepare image
        if image_path_or_url.startswith(("http://", "https://")):
            image_data = self.create_url_image_data(image_path_or_url)
        else:
            image_data = self.encode_image_to_base64(image_path_or_url)

        return self.query_with_image(prompt, image_data, VisualDetectionFormat)

    def get_annotation_hint(
        self,
        image_path_or_url: str,
        task_description: str,
        labels: List[str]
    ) -> Dict[str, Any]:
        """
        Get a hint for annotating an image without revealing exact locations.

        Args:
            image_path_or_url: Path to image file or URL
            task_description: Description of the annotation task
            labels: Available labels

        Returns:
            Dict with hint text and optional suggested label
        """
        labels_str = ", ".join(labels)

        prompt = f"""You are helping an annotator with this task: {task_description}

Available labels: {labels_str}

Provide a helpful hint that guides the annotator without giving away the exact answer.
The hint should:
1. Point out relevant features to consider
2. Suggest what to look for
3. Not explicitly state the answer or exact locations

Return JSON:
{{
    "hint": "Your helpful hint here",
    "suggested_focus": "What area or aspect to focus on"
}}"""

        # Prepare image
        if image_path_or_url.startswith(("http://", "https://")):
            image_data = self.create_url_image_data(image_path_or_url)
        else:
            image_data = self.encode_image_to_base64(image_path_or_url)

        class HintFormat(BaseModel):
            hint: str
            suggested_focus: str

        return self.query_with_image(prompt, image_data, HintFormat)

    def health_check(self) -> bool:
        """
        Check if the Anthropic API is accessible.

        Returns:
            True if API is reachable, False otherwise
        """
        try:
            # Simple test message
            self.client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "Hello"}]
            )
            return True
        except Exception as e:
            logger.error(f"Anthropic health check failed: {e}")
            return False
