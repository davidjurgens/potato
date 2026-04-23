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

    def query(self, prompt: str, output_format=None) -> str:
        """
        Send a query to VLLM and return the response.

        Args:
            prompt: The prompt to send to the model
            output_format: Optional Pydantic model class for structured output.
                          When provided, the schema is sent as guided_json for
                          constrained generation (vLLM native feature).

        Returns:
            The model's response as a string (or parsed dict for structured output)

        Raises:
            AIEndpointRequestError: If the request fails
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            # Think mode: configurable via ai_config['think']
            # For qwen3/qwen3.5 on vLLM, this controls enable_thinking
            think = self.ai_config.get('think', False)

            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": think},
            }

            # Add structured output via guided_json if schema provided
            if output_format is not None and hasattr(output_format, 'model_json_schema'):
                payload["guided_json"] = output_format.model_json_schema()

            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout
            )

            if response.status_code != 200:
                raise AIEndpointRequestError(
                    f"VLLM request failed with status {response.status_code}: "
                    f"{response.text[:500]}"
                )

            result = response.json()
            message = result["choices"][0]["message"]
            content = message.get("content") or ""

            # When thinking is enabled, content may be empty while reasoning
            # has the thinking. Check if content has the actual answer.
            if not content and message.get("reasoning"):
                reasoning = message["reasoning"]
                logger.debug(
                    f"[vLLM] Content empty, reasoning present "
                    f"({len(reasoning)} chars). Model may need more tokens."
                )
                # Try to extract JSON from reasoning as last resort
                content = reasoning

            if content:
                return self.parseStringToJson(content)

            raise AIEndpointRequestError(
                "Empty content from vLLM - model may need more max_tokens "
                "or thinking mode disabled"
            )

        except requests.exceptions.RequestException as e:
            raise AIEndpointRequestError(f"VLLM request failed: {e}")
        except (KeyError, IndexError) as e:
            raise AIEndpointRequestError(f"Invalid VLLM response format: {e}")

    def chat_query(self, messages, **kwargs) -> str:
        """Send a multi-turn chat to vLLM."""
        import logging
        logger = logging.getLogger(__name__)

        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            think = self.ai_config.get('think', False)

            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": think},
            }

            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout
            )

            if response.status_code != 200:
                raise AIEndpointRequestError(
                    f"VLLM chat failed: {response.status_code}"
                )

            result = response.json()
            content = result["choices"][0]["message"].get("content") or ""
            return content

        except requests.exceptions.RequestException as e:
            raise AIEndpointRequestError(f"VLLM chat failed: {e}")