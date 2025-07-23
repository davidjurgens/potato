"""
Ollama AI endpoint implementation.

This module provides integration with Ollama for local LLM inference.
"""

import ollama
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError

DEFAULT_MODEL = "llama3.2"
DEFAULT_HINT_PROMPT = '''You are assisting a user with an annotation task.
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

class OllamaEndpoint(BaseAIEndpoint):
    """Ollama endpoint for local LLM inference."""

    def _initialize_client(self) -> None:
        """Initialize the Ollama client."""
        # Ollama client is initialized automatically when needed
        # Check if Ollama is available
        try:
            # Test connection
            ollama.list()
        except Exception as e:
            raise AIEndpointRequestError(f"Failed to connect to Ollama: {e}")

    def _get_default_model(self) -> str:
        """Get the default Ollama model."""
        return DEFAULT_MODEL

    def _get_default_hint_prompt(self) -> str:
        """Get the default hint prompt for Ollama."""
        return DEFAULT_HINT_PROMPT

    def _get_default_keyword_prompt(self) -> str:
        """Get the default keyword prompt for Ollama."""
        return DEFAULT_KEYWORD_PROMPT

    def query(self, prompt: str) -> str:
        """
        Send a query to Ollama and return the response.

        Args:
            prompt: The prompt to send to the model

        Returns:
            The model's response as a string

        Raises:
            AIEndpointRequestError: If the request fails
        """
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{'role': 'user', 'content': prompt}],
                options={
                    'temperature': self.temperature,
                    'num_predict': self.max_tokens
                }
            )
            return response['message']['content']
        except Exception as e:
            raise AIEndpointRequestError(f"Ollama request failed: {e}")
