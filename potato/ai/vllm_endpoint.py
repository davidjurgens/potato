"""
VLLM AI endpoint implementation.

This module provides integration with VLLM for local LLM inference.
"""

import requests
import json
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError

DEFAULT_MODEL = "meta-llama/Llama-3.2-3B-Instruct"
DEFAULT_HINT_PROMPT = '''
    You are assisting a user with an annotation task.
        The annotation instruction is : {description}
        The annotation task type is: {annotation_type}
        The sentence (or item) to annotate is : {text}
        Your goal is to generate a short, helpful hint that guides the annotator in how to think about the input — **without providing the answer**.

        The hint should:
        - Highlight key aspects of the input relevant to the task
        - Encourage thoughtful reasoning or observation
        - Point to subtle features (tone, wording, structure, implication) that matter for the annotation
        - Be specific and informative, not vague or generic
        '''

DEFAULT_KEYWORD_PROMPT = '''
    You are assisting a user with an annotation task.
        The annotation instruction is : {description}
        The annotation task type is: {annotation_type}
        The sentence (or item) to annotate is : {text}
        Your goal is : Print out just a sequence of keywords, not sentences, in the text that most relate to the task. Do not explain your answer. Do not print out the entire text. If no part of the text relates to the task, print the empty string.
    '''

class VLLMEndpoint(BaseAIEndpoint):
    """VLLM endpoint for local LLM inference."""

    def _initialize_client(self) -> None:
        """Initialize the VLLM client."""
        self.base_url = self.ai_config.get("base_url", "http://localhost:8000")
        self.api_key = self.ai_config.get("api_key", "")
        # Default timeout of 30 seconds, configurable via ai_config
        self.timeout = self.ai_config.get("timeout", 30)

        # Test connection
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            if response.status_code != 200:
                raise AIEndpointRequestError(f"VLLM server not healthy: {response.status_code}")
        except requests.exceptions.RequestException as e:
            raise AIEndpointRequestError(f"Failed to connect to VLLM server at {self.base_url}: {e}")

    def _get_default_model(self) -> str:
        """Get the default VLLM model."""
        return DEFAULT_MODEL

    def _get_default_hint_prompt(self) -> str:
        """Get the default hint prompt for VLLM."""
        return DEFAULT_HINT_PROMPT

    def _get_default_keyword_prompt(self) -> str:
        """Get the default keyword prompt for VLLM."""
        return DEFAULT_KEYWORD_PROMPT

    def query(self, prompt: str) -> str:
        """
        Send a query to VLLM and return the response.

        Args:
            prompt: The prompt to send to the model

        Returns:
            The model's response as a string

        Raises:
            AIEndpointRequestError: If the request fails
        """
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "stream": False
            }

            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout
            )

            if response.status_code != 200:
                raise AIEndpointRequestError(f"VLLM request failed with status {response.status_code}: {response.text}")

            result = response.json()
            return result["choices"][0]["message"]["content"]

        except requests.exceptions.RequestException as e:
            raise AIEndpointRequestError(f"VLLM request failed: {e}")
        except (KeyError, IndexError) as e:
            raise AIEndpointRequestError(f"Invalid VLLM response format: {e}")
        except json.JSONDecodeError as e:
            raise AIEndpointRequestError(f"Invalid JSON response from VLLM: {e}")