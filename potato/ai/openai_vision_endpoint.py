"""
OpenAI Vision AI Endpoint

Integration with OpenAI's vision models (GPT-4o, GPT-4o-mini)
for visual analysis and annotation assistance.
"""

import base64
import logging
from typing import Any, Dict, List, Type, Union

from pydantic import BaseModel

from .ai_endpoint import AIEndpointRequestError, ImageData, ModelCapabilities
from .visual_ai_endpoint import BaseVisualAIEndpoint

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o"


class OpenAIVisionEndpoint(BaseVisualAIEndpoint):
    """
    OpenAI Vision endpoint for GPT-4o and GPT-4o-mini vision capabilities.

    Supports both URL and base64 image inputs using the image_url content type.

    Configuration options:
    - model: Model to use (gpt-4o, gpt-4o-mini) (default: gpt-4o)
    - api_key: OpenAI API key (can also use OPENAI_API_KEY env var)
    - base_url: An OpenAI-compatible server to talk to instead of OpenAI --
      vLLM, SGLang, LM Studio, llama.cpp, LiteLLM, OpenRouter. Setting it also
      makes the API key optional, because self-hosted servers usually have none
      and requiring a placeholder just to reach a local GPU is a papercut that
      sends people to write their own endpoint class.
    - max_tokens: Maximum response tokens (default: 1000)
    - temperature: Sampling temperature (default: 0.1)
    - detail: Image detail level - 'low', 'high', or 'auto' (default: auto)
    - json_mode: Request ``response_format={"type": "json_object"}`` (default
      True). Servers without constrained decoding reject it; the endpoint
      detects that and retries once without, so this rarely needs setting.
    """

    # Capabilities declaration for OpenAI vision models (GPT-4o, GPT-4o-mini)
    # These models can understand images and generate text but bounding boxes are approximate
    CAPABILITIES = ModelCapabilities(
        text_generation=True,
        vision_input=True,
        bounding_box_output=False,  # GPT-4V bboxes are approximate, not precise
        text_classification=True,
        image_classification=True,
        rationale_generation=True,
        keyword_extraction=False,  # Keywords don't apply to images
    )

    def _initialize_client(self) -> None:
        """Initialize the OpenAI client."""
        try:
            import openai
        except ImportError:
            raise AIEndpointRequestError(
                "openai package is required. Install it with: pip install openai"
            )

        import os

        base_url = self.ai_config.get("base_url") or self.ai_config.get("api_base")
        if base_url:
            # Accept either the server root or an OpenAI-style ".../v1", the
            # same tolerance VLLMEndpoint applies -- people paste both.
            base_url = str(base_url).rstrip("/")
            if not base_url.endswith("/v1"):
                base_url = base_url + "/v1"

        api_key = self.ai_config.get("api_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            if not base_url:
                raise AIEndpointRequestError(
                    "OpenAI API key is required. Set it in config or OPENAI_API_KEY env var."
                )
            # The client insists on a non-empty key even when the server
            # ignores it entirely.
            api_key = "not-needed"

        timeout = self.ai_config.get("timeout", 60)
        self.detail = self.ai_config.get("detail", "auto")
        self.json_mode = bool(self.ai_config.get("json_mode", True))

        kwargs = {"api_key": api_key, "timeout": timeout}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = openai.OpenAI(**kwargs)
        self.base_url = base_url
        logger.info("OpenAI Vision client initialized with model: %s%s",
                    self.model, f" at {base_url}" if base_url else "")

    def _create(self, messages):
        """One chat completion, retrying without JSON mode if it is rejected.

        An OpenAI-compatible server built without constrained decoding answers
        ``response_format`` with a 400. Failing the whole request there would
        make every such server look like it has no vision support, when in
        fact only the JSON guarantee is missing -- and the responses are then
        parsed leniently anyway (``parseStringToJson``).
        """
        kwargs = dict(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        if self.json_mode:
            try:
                return self.client.chat.completions.create(
                    response_format={"type": "json_object"}, **kwargs)
            except Exception as exc:  # noqa: BLE001
                if "response_format" not in str(exc):
                    raise
                logger.info(
                    "Server rejected JSON mode (%s); retrying without it and "
                    "parsing leniently.", exc)
                self.json_mode = False
        return self.client.chat.completions.create(**kwargs)

    def _get_default_model(self) -> str:
        """Get the default OpenAI vision model."""
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
            response = self._create([{"role": "user", "content": prompt}])
            content = response.choices[0].message.content
            return self.parseStringToJson(content)

        except Exception as e:
            raise AIEndpointRequestError(f"OpenAI query failed: {e}")

    def query_with_image(
        self,
        prompt: str,
        image_data: Union[ImageData, List[ImageData]],
        output_format: Type[BaseModel]
    ) -> Any:
        """
        Send a query with image(s) to OpenAI vision model.

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

            # Build content array with text and images
            content = [{"type": "text", "text": prompt}]

            for img in images:
                image_content = self._build_image_content(img)
                content.append(image_content)

            # Make request
            response = self._create([{"role": "user", "content": content}])

            response_content = response.choices[0].message.content
            logger.debug(f"OpenAI vision response: {response_content[:500] if response_content else 'empty'}")

            return self.parseStringToJson(response_content)

        except AIEndpointRequestError:
            raise
        except Exception as e:
            logger.error(f"OpenAI vision query failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise AIEndpointRequestError(f"OpenAI vision query failed: {e}")

    def _build_image_content(self, image_data: ImageData) -> Dict[str, Any]:
        """
        Build image content block for OpenAI API.

        Args:
            image_data: ImageData object

        Returns:
            Dict with type: "image_url" and image_url content
        """
        if image_data.source == "url":
            # Direct URL reference
            return {
                "type": "image_url",
                "image_url": {
                    "url": image_data.data,
                    "detail": self.detail
                }
            }

        elif image_data.source == "base64":
            # Data URL format
            mime_type = image_data.mime_type or "image/jpeg"
            data_url = f"data:{mime_type};base64,{image_data.data}"

            return {
                "type": "image_url",
                "image_url": {
                    "url": data_url,
                    "detail": self.detail
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
        # Prepare image data - use URL directly if possible
        if image_path_or_url.startswith(("http://", "https://")):
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

Return JSON with this structure:
{{
    "detections": [
        {{
            "label": "object_name",
            "bbox": {{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}},
            "confidence": 0.95
        }}
    ]
}}

Coordinates are normalized (0-1) where x,y is the top-left corner.
Only include objects you can clearly identify with confidence > 0.5."""

        # Prepare image
        if image_path_or_url.startswith(("http://", "https://")):
            image_data = self.create_url_image_data(image_path_or_url)
        else:
            image_data = self.encode_image_to_base64(image_path_or_url)

        return self.query_with_image(prompt, image_data, VisualDetectionFormat)

    def describe_region(
        self,
        image_path_or_url: str,
        region: Dict[str, float],
        labels: List[str] = None
    ) -> Dict[str, Any]:
        """
        Describe or classify a specific region in an image.

        Args:
            image_path_or_url: Path to image file or URL
            region: Dict with x, y, width, height (normalized 0-1)
            labels: Optional list of possible labels

        Returns:
            Classification result with suggested label and confidence
        """
        labels_str = ", ".join(labels) if labels else "any appropriate category"

        prompt = f"""Look at the region marked in this image:
- Region: x={region['x']:.2f}, y={region['y']:.2f}, width={region['width']:.2f}, height={region['height']:.2f}
(Coordinates are normalized 0-1, where 0,0 is top-left)

Classify what you see in this region from these options: {labels_str}

Return JSON:
{{
    "suggested_label": "label_name",
    "confidence": 0.85,
    "reasoning": "Brief explanation"
}}"""

        # Prepare image
        if image_path_or_url.startswith(("http://", "https://")):
            image_data = self.create_url_image_data(image_path_or_url)
        else:
            image_data = self.encode_image_to_base64(image_path_or_url)

        class RegionClassificationFormat(BaseModel):
            suggested_label: str
            confidence: float
            reasoning: str

        return self.query_with_image(prompt, image_data, RegionClassificationFormat)

    def health_check(self) -> bool:
        """
        Check if the OpenAI API is accessible.

        Returns:
            True if API is reachable, False otherwise
        """
        try:
            # Simple models list check
            self.client.models.list()
            return True
        except Exception as e:
            logger.error(f"OpenAI health check failed: {e}")
            return False
