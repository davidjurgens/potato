import requests

class AIEndpointClient:
    def __init__(self, endpoint: str, api_key: str):
        self.endpoint = endpoint
        self.api_key = api_key

    def get_ai_response(self, message: str) -> str:
        response = requests.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"message": message},
        )
        return response.json()["response"]


def get_ai_endpoint(config: dict):
    # Check what kind of endpoint the admin was requested

    # Get the AI support option from the config
    ai_support = config["ai_support"]

    # If the AI support is enabled, get the endpoint type
    if ai_support["enabled"]:
        print("ai_support enabled")
        endpoint_type = ai_support["endpoint_type"]
        if endpoint_type == "ollama":

            # Only do the import if we need it prevent unnecessary imports on small systems
            from .ollama_endpoint import OllamaEndpoint

            return OllamaEndpoint(config)
        # Open AI API
        elif endpoint_type == "openai":
            from .openai_endpoint import OpenAIEndpoint

            return OpenAIEndpoint(config)
        
        # Huggingface API
        elif endpoint_type == "huggingface":
            from .huggingface_endpoint import HuggingfaceEndpoint
            return HuggingfaceEndpoint(config)
        
        # Gemini API
        elif endpoint_type == "gemini":
            from .gemini_endpoint import GeminiEndpoint

            return GeminiEndpoint(config)
        else:
            raise ValueError(f"Unknown endpoint type: {endpoint_type}")

    # If the AI support is disabled, return None
    return None


