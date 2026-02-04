
"""
Unified AI endpoint interface for various LLM providers.

This module provides a common interface for interacting with different LLM providers
including OpenAI, Anthropic, Hugging Face, Ollama, and VLLM endpoints.
"""

from dataclasses import dataclass, field
from enum import Enum
import logging
from abc import ABC, abstractmethod
import os
from typing import Dict, Any, Optional, List, Type, Union
import json
from string import Template

from pydantic import BaseModel

from .ai_prompt import get_ai_prompt

logger = logging.getLogger(__name__)


class Annotation_Type(Enum):
    RADIO = "radio"
    LIKERT = "likert"
    NUMBER = "number"
    TEXTBOX = "text"
    MULTISELECT = "multiselect"
    SPAN = "span"
    SELECT = "select"
    SLIDER = "slider"
    IMAGE_ANNOTATION = "image_annotation"
    VIDEO_ANNOTATION = "video_annotation"


@dataclass
class ImageData:
    """Data structure for image input to visual AI endpoints."""
    source: str  # 'url' | 'base64'
    data: str    # The URL or base64-encoded image data
    width: Optional[int] = None
    height: Optional[int] = None
    mime_type: Optional[str] = None  # e.g., 'image/jpeg', 'image/png'


@dataclass
class VisualAnnotationInput:
    """Input data structure for visual annotation AI assistance."""
    ai_assistant: str           # 'detection', 'classification', 'hint', 'pre_annotate', etc.
    annotation_type: str        # 'image_annotation' | 'video_annotation'
    task_type: str              # Specific task: 'detection', 'classification', 'scene_detection', etc.
    image_data: Union[ImageData, List[ImageData]]  # Single image or list of frames
    description: str            # Task description from annotation scheme
    labels: Optional[List[str]] = None  # Available labels for the task
    video_metadata: Optional[Dict[str, Any]] = field(default_factory=dict)  # fps, duration for video
    region: Optional[Dict[str, float]] = None  # Selected region for classification (x, y, width, height)
    confidence_threshold: float = 0.5  # Minimum confidence for detections


@dataclass
class AnnotationInput:
    ai_assistant: str
    annotation_type: Annotation_Type
    text: str
    description: str
    min_label: Optional[str] = ""
    max_label: Optional[str] = ""
    size: Optional[int] = -1
    labels: Optional[List[str]] = None
    min_value: Optional[int] = -1
    max_value: Optional[int] = -1
    step: Optional[int] = -1


@dataclass
class ModelCapabilities:
    """
    Declares what operations an AI endpoint can perform.

    This dataclass is used to define the capabilities of different AI endpoints,
    enabling the system to automatically filter AI assistant buttons and validate
    requests based on what each model can actually do.

    Attributes:
        text_generation: Can generate text (hints, rationales, descriptions)
        vision_input: Can process images as input
        bounding_box_output: Can output precise coordinate detections
        text_classification: Can classify text into categories
        image_classification: Can classify images into categories
        rationale_generation: Can generate explanations/rationales for labels
        keyword_extraction: Can extract keywords from text (not applicable to images)
    """
    text_generation: bool = False
    vision_input: bool = False
    bounding_box_output: bool = False
    text_classification: bool = False
    image_classification: bool = False
    rationale_generation: bool = False
    keyword_extraction: bool = False

    def supports_assistant(self, assistant_type: str, has_image_input: bool = False) -> bool:
        """
        Check if model supports a specific AI assistant type.

        Args:
            assistant_type: The type of AI assistant ('hint', 'keyword', 'rationale',
                          'detection', 'pre_annotate', 'classification')
            has_image_input: Whether the current content is an image

        Returns:
            True if the model supports this assistant type for the given input type
        """
        if assistant_type == "hint":
            # Hints require text generation; for images, also need vision
            if has_image_input:
                return self.text_generation and self.vision_input
            return self.text_generation

        elif assistant_type == "keyword":
            # Keywords require keyword extraction AND text input (not images)
            # Keyword highlighting doesn't make sense for images
            return self.keyword_extraction and not has_image_input

        elif assistant_type == "rationale":
            # Rationales require rationale generation; for images, also need vision
            if has_image_input:
                return self.rationale_generation and self.vision_input
            return self.rationale_generation

        elif assistant_type in ("detection", "detect", "pre_annotate"):
            # Detection requires vision and bounding box output
            return self.bounding_box_output and self.vision_input

        elif assistant_type == "classification":
            # Classification depends on input type
            if has_image_input:
                return self.image_classification and self.vision_input
            return self.text_classification

        # Unknown assistant type - default to False for safety
        return False

    def get_supported_assistants(self, has_image_input: bool = False) -> List[str]:
        """
        Get list of assistant types supported for the given input type.

        Args:
            has_image_input: Whether the current content is an image

        Returns:
            List of supported assistant type names
        """
        all_types = ["hint", "keyword", "rationale", "detection", "pre_annotate", "classification"]
        return [t for t in all_types if self.supports_assistant(t, has_image_input)]


class AIEndpointError(Exception):
    """Base exception for AI endpoint errors."""
    pass


class AIEndpointConfigError(AIEndpointError):
    """Exception raised for configuration errors."""
    pass


class AIEndpointRequestError(AIEndpointError):
    """Exception raised for request/API errors."""
    pass


class BaseAIEndpoint(ABC):
    """
    Abstract base class for AI endpoints.

    All AI endpoint implementations should inherit from this class
    and implement the required methods.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the AI endpoint with configuration.

        Args:
            config: Configuration dictionary containing endpoint-specific settings
        """
        self.config = config
        self.description = config.get("description", "")
        self.annotation_type = config.get("annotation_type", "")
        self.ai_config = config.get("ai_config", {})

        # Model configuration
        self.model = self.ai_config.get("model", self._get_default_model())
        self.max_tokens = self.ai_config.get("max_tokens", 100)
        self.temperature = self.ai_config.get("temperature", 0.1)

        # prompt
        self.prompts = get_ai_prompt()

        # Initialize the client
        self._initialize_client()

    @abstractmethod
    def _initialize_client(self) -> None:
        """Initialize the client for the specific AI provider."""
        pass

    @abstractmethod
    def _get_default_model(self) -> str:
        """Get the default model name for this provider."""
        pass

    @abstractmethod
    def query(self, prompt: str, output_format: Type[BaseModel]):
        """
        Send a query to the AI model and return the response.

        Args:
            prompt: The prompt to send to the model

        Returns:
            The model's response as a string

        Raises:
            AIEndpointRequestError: If the request fails
        """
        pass

    def parseStringToJson(self, response_content: str) -> str:
        """
        Parse the response content and extract JSON, handling markdown code blocks.
        """
        # Handle empty or None content
        if not response_content:
            raise ValueError(f"Empty response content received from AI endpoint")

        # If it's already a dict, return it
        if isinstance(response_content, dict):
            return response_content

        # Convert to string if needed
        content_str = str(response_content).strip()

        # Check for empty after stripping whitespace
        if not content_str:
            raise ValueError(f"Empty response content received from AI endpoint")

        # Try to extract JSON from markdown code blocks if present
        if '```json' in content_str:
            import re
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content_str)
            if json_match:
                content_str = json_match.group(1).strip()
        elif '```' in content_str:
            import re
            json_match = re.search(r'```\s*([\s\S]*?)\s*```', content_str)
            if json_match:
                content_str = json_match.group(1).strip()

        try:
            parsed = json.loads(content_str)
            return parsed
        except json.JSONDecodeError as e:
            # Log more details about the failure
            logger.error(f"JSON parse error: {e}")
            logger.error(f"Content length: {len(content_str)}")
            logger.error(f"Content (first 500 chars): {content_str[:500]}")
            raise ValueError(f"Failed to parse JSON from response: {e}. Content: {content_str[:200]}")

    def get_ai(self, data: AnnotationInput, output_format) -> str:
        """
        Get a hint for annotating the given text.

        Args:
            text: The text to get a hint for

        Returns:
            A helpful hint for annotation
        """
        
        try:
            # Check if annotation type exists (comparing string against enum values)
            valid_types = [e.value for e in Annotation_Type]
            if data.annotation_type not in valid_types:
                logger.warning(f"Annotation type '{data.annotation_type}' not found")
                return "Unable to generate suggestion - annotation type not configured"
                    
            # Check if ai_assistant exists
            ai_prompt = get_ai_prompt()
            if data.ai_assistant not in ai_prompt[data.annotation_type]:
                logger.warning(f"'ai_assistant' not found for {data.annotation_type}")
                return "Unable to generate suggestion - prompt not configured"
            
            template_str = self.prompts.get(data.annotation_type).get(data.ai_assistant).get("prompt")
            template = Template(template_str)
            prompt = template.substitute(
                text=data.text,
                description=data.description,
                min_label=data.min_label,
                max_label=data.max_label,
                size=data.size,
                labels=data.labels,
                min_value=data.min_value,
                max_value=data.max_value,  
                step=data.step             
            )
            return self.query(prompt, output_format)
        except Exception as e:
            logger.error(f"[get_ai] AnnotationInput: {data}")
            logger.error(f"[get_ai] Error for {data.annotation_type}/{data.ai_assistant}: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"[get_ai] Traceback:\n{traceback.format_exc()}")
            return "Unable to generate hint at this time."

    def health_check(self) -> bool:
        """
        Check if the AI endpoint is healthy and accessible.

        Returns:
            True if the endpoint is healthy, False otherwise
        """
        try:
            # Simple test query
            test_response = self.query("Hello")
            return bool(test_response and test_response.strip())
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False


class AIEndpointFactory:
    """
    Factory class for creating AI endpoint instances.
    """

    _endpoints = { }

    @classmethod
    def register_endpoint(cls, endpoint_type: str, endpoint_class: type):
        """Register a new endpoint type."""
        cls._endpoints[endpoint_type] = endpoint_class

    @classmethod
    def create_endpoint(cls, config: Dict[str, Any]) -> Optional[BaseAIEndpoint]:
        """
        Create an AI endpoint instance based on configuration.

        Args:
            config: Configuration dictionary containing ai_support settings

        Returns:
            An AI endpoint instance or None if AI support is disabled

        Raises:
            AIEndpointConfigError: If the configuration is invalid
        """
        if not config.get("ai_support", {}).get("enabled", False):
            return None

        ai_support = config["ai_support"]
        endpoint_type = ai_support.get("endpoint_type")

        if not endpoint_type:
            raise AIEndpointConfigError("endpoint_type is required when ai_support is enabled")

        if endpoint_type not in cls._endpoints:
            raise AIEndpointConfigError(f"Unknown endpoint type: {endpoint_type}")

        # Prepare endpoint configuration
        endpoint_config = {
            "ai_config": ai_support.get("ai_config", {})
        }

        try:
            endpoint_class = cls._endpoints[endpoint_type]
            return endpoint_class(endpoint_config)
        except Exception as e:
            raise AIEndpointConfigError(f"Failed to create {endpoint_type} endpoint: {e}")


# Legacy function for backward compatibility
def get_ai_endpoint(config: dict):
    """
    Get an AI endpoint instance (legacy function).

    This function is maintained for backward compatibility.
    New code should use AIEndpointFactory.create_endpoint().
    """
    return AIEndpointFactory.create_endpoint(config)


# Register built-in endpoints
try:
    from .ollama_endpoint import OllamaEndpoint
    AIEndpointFactory.register_endpoint("ollama", OllamaEndpoint)
except ImportError:
    logger.debug("Ollama endpoint not available")

try:
    from .openai_endpoint import OpenAIEndpoint
    AIEndpointFactory.register_endpoint("openai", OpenAIEndpoint)
except ImportError:
    logger.debug("OpenAI endpoint not available")

try:
    from .huggingface_endpoint import HuggingfaceEndpoint
    AIEndpointFactory.register_endpoint("huggingface", HuggingfaceEndpoint)
except ImportError:
    logger.debug("Hugging Face endpoint not available")

try:
    from .gemini_endpoint import GeminiEndpoint
    AIEndpointFactory.register_endpoint("gemini", GeminiEndpoint)
except ImportError:
    logger.debug("Gemini endpoint not available")

try:
    from .anthropic_endpoint import AnthropicEndpoint
    AIEndpointFactory.register_endpoint("anthropic", AnthropicEndpoint)
except ImportError:
    logger.debug("Anthropic endpoint not available")

try:
    from .vllm_endpoint import VLLMEndpoint
    AIEndpointFactory.register_endpoint("vllm", VLLMEndpoint)
except ImportError:
    logger.debug("VLLM endpoint not available")

# Register visual AI endpoints
try:
    from .yolo_endpoint import YOLOEndpoint
    AIEndpointFactory.register_endpoint("yolo", YOLOEndpoint)
except ImportError:
    logger.debug("YOLO endpoint not available (ultralytics not installed)")

try:
    from .ollama_vision_endpoint import OllamaVisionEndpoint
    AIEndpointFactory.register_endpoint("ollama_vision", OllamaVisionEndpoint)
except ImportError:
    logger.debug("Ollama Vision endpoint not available")

try:
    from .openai_vision_endpoint import OpenAIVisionEndpoint
    AIEndpointFactory.register_endpoint("openai_vision", OpenAIVisionEndpoint)
except ImportError:
    logger.debug("OpenAI Vision endpoint not available")

try:
    from .anthropic_vision_endpoint import AnthropicVisionEndpoint
    AIEndpointFactory.register_endpoint("anthropic_vision", AnthropicVisionEndpoint)
except ImportError:
    logger.debug("Anthropic Vision endpoint not available")
