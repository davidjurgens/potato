
"""
Unified AI endpoint interface for various LLM providers.

This module provides a common interface for interacting with different LLM providers
including OpenAI, Anthropic, Hugging Face, Ollama, and VLLM endpoints.
"""

from dataclasses import dataclass
from enum import Enum
import logging
from abc import ABC, abstractmethod
import os
from typing import Dict, Any, Optional, List, Type
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
        try:
            parsed = json.loads(response_content)
            return parsed
        except json.JSONDecodeError:
            raise ValueError(f"Failed to parse JSON from ollama response: {response_content}")

    def get_ai(self, data: AnnotationInput, output_format) -> str:
        """
        Get a hint for annotating the given text.

        Args:
            text: The text to get a hint for

        Returns:
            A helpful hint for annotation
        """
        
        try:
            # Check if annotation type exists
            if data.annotation_type not in Annotation_Type:
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
            logger.error(data)
            logger.error(f"Error getting hint: {data.annotation_type, data.ai_assistant, e}")
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

