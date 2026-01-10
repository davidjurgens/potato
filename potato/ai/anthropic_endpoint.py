"""
Anthropic AI endpoint implementation.

This module provides integration with Anthropic's Claude API for LLM inference.
"""

import anthropic
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError

DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
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

class AnthropicEndpoint(BaseAIEndpoint):
    """Anthropic Claude endpoint for cloud-based LLM inference."""

    def _initialize_client(self) -> None:
        """Initialize the Anthropic client."""
        api_key = self.ai_config.get("api_key", "")
        if not api_key:
            raise AIEndpointRequestError("Anthropic API key is required")

        # Default timeout of 30 seconds, configurable via ai_config
        timeout = self.ai_config.get("timeout", 30)
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

    def _get_default_model(self) -> str:
        """Get the default Anthropic model."""
        return DEFAULT_MODEL

    def _get_default_hint_prompt(self) -> str:
        """Get the default hint prompt for Anthropic."""
        return DEFAULT_HINT_PROMPT

    def _get_default_keyword_prompt(self) -> str:
        """Get the default keyword prompt for Anthropic."""
        return DEFAULT_KEYWORD_PROMPT

    def query(self, prompt: str) -> str:
        """
        Send a query to Anthropic Claude and return the response.

        Args:
            prompt: The prompt to send to the model

        Returns:
            The model's response as a string

        Raises:
            AIEndpointRequestError: If the request fails
        """
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        except Exception as e:
            raise AIEndpointRequestError(f"Anthropic request failed: {e}")