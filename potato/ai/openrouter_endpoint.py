"""
OpenRouter endpoint implementation.
This module provides integration with OpenRouter's API for LLM inference.
"""
import requests
from .ai_endpoint import BaseAIEndpoint, AIEndpointRequestError

DEFAULT_MODEL = "openai/gpt-4o-mini"

class OpenRouterEndpoint(BaseAIEndpoint):
    """OpenRouter endpoint for cloud-based LLM inference."""
    
    # Models that support structured output
    STRUCTURED_OUTPUT_MODELS = {
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "openai/gpt-4-turbo",
        "anthropic/claude-3-5-sonnet",
        "deepseek/deepseek-r1:free"
    }
    
    def _initialize_client(self) -> None:
        """Initialize the OpenAI client."""
        api_key = self.ai_config.get("api_key", "")
        if not api_key:
            raise AIEndpointRequestError("OpenRouter API key is required")
    
    def _get_default_model(self) -> str:
        """Get the default OpenAI model."""
        return DEFAULT_MODEL
    
    def supports_structured_output(self) -> bool:
        """Check if the current model supports structured output."""
        model = self.model or DEFAULT_MODEL
        return any(model.startswith(prefix.split('/')[0]) or model in self.STRUCTURED_OUTPUT_MODELS 
                   for prefix in self.STRUCTURED_OUTPUT_MODELS)
    
    def query(self, prompt: str, output_format: dict) -> str:
        """
        Send a query to OpenRouter and return the response.
        
        Args:
            prompt: The prompt to send to the model (as messages list or string)
            output_format: Pydantic model for structured output
            
        Returns:
            The model's response as a string
            
        Raises:
            AIEndpointRequestError: If the request fails
        """
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            print("keykeykey", self.ai_config.get('api_key'))
            headers = {
                "Authorization": f"Bearer {self.ai_config.get('api_key')}",
                "Content-Type": "application/json"
            }
            
            messages = [{"role": "user", "content": prompt}]
            schema = output_format.model_json_schema()
            
            body = {
                "model": self.model or DEFAULT_MODEL,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
            
            # Handle structured output based on model support
            if self.supports_structured_output():
                    body["messages"] = messages
                    body["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "response",
                            "schema": schema,
                            "strict": True
                        }
                    }
            else:
                # If model does not support structured format, just send raw prompt
                body["messages"] = messages
            
            r = requests.post(url, headers=headers, json=body)
            
            if r.status_code >= 400:
                raise AIEndpointRequestError(f"OpenRouter error {r.status_code}: {r.text}")
            
            data = r.json()
            print("openrouter data", data)
            if self.supports_structured_output():
                return self.parseStringToJson(data["choices"][0]["message"]["content"])
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            raise AIEndpointRequestError(f"OpenRouter request failed: {e}")