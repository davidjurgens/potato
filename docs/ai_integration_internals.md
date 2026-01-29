# AI Integration Internals

This document describes the internal architecture of Potato's AI support system, intended for developers who need to debug, extend, or modify the AI functionality.

For user-facing configuration documentation, see [ai_support.md](ai_support.md).

## Initialization Flow

AI support is initialized during server startup in `flask_server.py`:

```
run_server()
  └─> if ai_support.enabled:
        ├─> init_ai_prompt(config)      # Load prompt templates
        ├─> init_ai_cache_manager()      # Create endpoint & cache
        └─> init_dynamic_ai_help()       # Create UI wrapper
```

**Order matters**: The components must be initialized in this order because:
1. `init_ai_prompt()` loads the prompt templates that other components need
2. `init_ai_cache_manager()` creates the AI endpoint and cache
3. `init_dynamic_ai_help()` depends on the prompt templates being loaded

## Component Architecture

### 1. Prompt Management (`potato/ai/ai_prompt.py`)

**Global State:**
```python
ANNOTATIONS = None  # Dict of {annotation_type: {assistant_type: {prompt, output_format, img}}}
```

**Key Functions:**
- `init_ai_prompt(config)` - Loads JSON prompt templates
- `get_ai_prompt()` - Returns loaded prompts (or None if not initialized)

**Prompt Template Structure:**
```json
{
  "hint": {
    "prompt": "TASK: ... ${text} ... ${labels} ...",
    "output_format": "default_hint",
    "img": "/static/ai_assistant_img/bulb.svg",
    "name": "Hint"
  },
  "keyword": {
    "prompt": "TASK: Extract keywords... ${text} ...",
    "output_format": "default_keyword",
    "img": "/static/ai_assistant_img/highlight.svg",
    "name": "Keywords"
  }
}
```

**Template Variables:**
- `${text}` - The text being annotated
- `${description}` - Annotation task description
- `${labels}` - Available labels (for classification)
- `${min_label}`, `${max_label}` - For Likert/slider scales
- `${size}` - Scale size

### 2. Cache Manager (`potato/ai/ai_cache.py`)

**Global State:**
```python
AICACHEMANAGER = None  # Singleton AiCacheManager instance
```

**Key Functions:**
- `init_ai_cache_manager()` - Creates singleton instance
- `get_ai_cache_manager()` - Returns instance (or None)

**AiCacheManager Responsibilities:**
1. Creates AI endpoint via factory
2. Manages disk cache (if enabled)
3. Handles prefetching/warming
4. Thread pool for concurrent requests
5. Routes requests to appropriate generator

**Request Flow:**
```
get_ai_help(instance_id, annotation_id, ai_assistant)
  └─> Check cache (disk/memory)
      └─> If not cached:
          └─> compute_help()
              └─> generate_radio() / generate_multiselect() / etc.
                  └─> endpoint.get_ai(AnnotationInput)
                      └─> LLM query
```

### 3. UI Wrapper (`potato/ai/ai_help_wrapper.py`)

**Global State:**
```python
DYNAMICAIHELP = None  # Singleton DynamicAIHelp instance
```

**Key Functions:**
- `init_dynamic_ai_help()` - Creates singleton
- `get_dynamic_ai_help()` - Returns instance (or None)
- `get_ai_wrapper()` - Returns empty wrapper HTML (or empty string)
- `generate_ai_help_html()` - Renders full AI assistant HTML

**HTML Generation:**
```python
# Empty wrapper (placed in schema templates):
<div class="ai-help none"><div class="tooltip"></div></div>

# Populated wrapper (fetched via AJAX):
<div class="hint ai-assistant-container">
  <span class="ai-assistant-img"><img src="..."></span>
  <span>Hint</span>
</div>
```

### 4. Endpoint Base (`potato/ai/ai_endpoint.py`)

**Abstract Base Class:**
```python
class BaseAIEndpoint(ABC):
    @abstractmethod
    def _initialize_client(self) -> None: ...

    @abstractmethod
    def _get_default_model(self) -> str: ...

    @abstractmethod
    def query(self, prompt: str, output_format: Type[BaseModel]): ...

    def get_ai(self, data: AnnotationInput, output_format) -> str:
        # Main entry point - substitutes template and calls query()
```

**Factory Pattern:**
```python
class AIEndpointFactory:
    _endpoints = {}  # Registered endpoint classes

    @classmethod
    def register_endpoint(cls, name: str, endpoint_class): ...

    @classmethod
    def create_endpoint(cls, config) -> Optional[BaseAIEndpoint]: ...
```

## Adding a New AI Provider

1. **Create endpoint file** (`potato/ai/my_provider_endpoint.py`):
```python
from ai.ai_endpoint import BaseAIEndpoint

class MyProviderEndpoint(BaseAIEndpoint):
    def _initialize_client(self):
        self.client = MyProviderClient(api_key=self.api_key)

    def _get_default_model(self) -> str:
        return "my-default-model"

    def query(self, prompt: str, output_format):
        response = self.client.generate(
            prompt=prompt,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        return self.parseStringToJson(response)
```

2. **Register in cache manager** (`potato/ai/ai_cache.py`):
```python
from ai.my_provider_endpoint import MyProviderEndpoint
AIEndpointFactory.register_endpoint("my_provider", MyProviderEndpoint)
```

3. **Update documentation** in `docs/ai_support.md`

## Debugging AI Issues

### Check Initialization Status

```python
# In Python console or debug endpoint:
from ai.ai_help_wrapper import get_dynamic_ai_help
from ai.ai_cache import get_ai_cache_manager
from ai.ai_prompt import get_ai_prompt

print("AI Help Wrapper:", get_dynamic_ai_help())  # Should not be None
print("Cache Manager:", get_ai_cache_manager())   # Should not be None
print("Prompts loaded:", get_ai_prompt() is not None)  # Should be True
```

### Common Issues

**AI buttons don't appear:**
- Check `ai_support.enabled: true` in config
- Verify initialization functions are called (check server logs)
- Check `get_dynamic_ai_help() is not None`

**Hints/keywords don't load:**
- Check `get_ai_cache_manager() is not None`
- Verify endpoint connectivity: check `endpoint.health_check()`
- Look for errors in server logs with `debug: true`

**Ollama-specific:**
- Ensure Ollama is running: `ollama list`
- Verify model is pulled: `ollama pull <model>`
- Check default port: `curl http://localhost:11434/api/tags`

### Enable Debug Logging

```yaml
# In your config.yaml:
debug: true
```

This enables verbose logging for AI requests/responses.

## File Reference

| File | Purpose |
|------|---------|
| `potato/ai/ai_prompt.py` | Prompt template loading and management |
| `potato/ai/ai_cache.py` | Cache manager, request routing, prefetch |
| `potato/ai/ai_help_wrapper.py` | UI HTML generation |
| `potato/ai/ai_endpoint.py` | Base endpoint class and factory |
| `potato/ai/ollama_endpoint.py` | Ollama provider implementation |
| `potato/ai/openai_endpoint.py` | OpenAI provider implementation |
| `potato/ai/anthropic_endpoint.py` | Anthropic provider implementation |
| `potato/ai/gemini_endpoint.py` | Google Gemini provider implementation |
| `potato/ai/huggingface_endpoint.py` | Hugging Face provider implementation |
| `potato/ai/openrouter_endpoint.py` | OpenRouter provider implementation |
| `potato/ai/vllm_endpoint.py` | VLLM provider implementation |
| `potato/ai/prompt/*.json` | Default prompt templates per annotation type |
| `potato/ai/prompt/models_module.py` | Pydantic models for response formats |

## Testing

Run AI-related tests:

```bash
# Initialization tests
pytest tests/unit/test_ai_initialization.py -v

# Help wrapper tests
pytest tests/unit/test_ai_help_wrapper.py -v

# Endpoint tests
pytest tests/unit/test_ai_endpoints.py -v

# ICL tests
pytest tests/unit/test_icl_labeler.py -v
pytest tests/unit/test_icl_prompt_builder.py -v

# Integration tests (requires Ollama)
pytest tests/integration/test_icl_ollama_integration.py -v
```
