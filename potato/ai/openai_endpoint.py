"""
OpenAI AI endpoint implementation.

This module provides integration with OpenAI's API for LLM inference.
"""

from openai import OpenAI
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError

DEFAULT_MODEL = "gpt-4o-mini"
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

class OpenAIEndpoint(BaseAIEndpoint):
    """OpenAI endpoint for cloud-based LLM inference."""

    def _initialize_client(self) -> None:
        """Initialize the OpenAI client."""
        api_key = self.ai_config.get("api_key", "")
        if not api_key:
            raise AIEndpointRequestError("OpenAI API key is required")

        self.client = OpenAI(api_key=api_key)

    def _get_default_model(self) -> str:
        """Get the default OpenAI model."""
        return DEFAULT_MODEL

    def _get_default_hint_prompt(self) -> str:
        """Get the default hint prompt for OpenAI."""
        return DEFAULT_HINT_PROMPT

    def _get_default_keyword_prompt(self) -> str:
        """Get the default keyword prompt for OpenAI."""
        return DEFAULT_KEYWORD_PROMPT

    def query(self, prompt: str) -> str:
        """
        Send a query to OpenAI and return the response.

        Args:
            prompt: The prompt to send to the model

        Returns:
            The model's response as a string

        Raises:
            AIEndpointRequestError: If the request fails
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            raise AIEndpointRequestError(f"OpenAI request failed: {e}")

