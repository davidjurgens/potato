# AI Support in Potato

Potato provides integrated AI support to enhance annotation workflows with intelligent hints, keyword highlighting, and label suggestions. This feature uses Large Language Models (LLMs) to provide contextual assistance to annotators without revealing the correct answers.

## Overview

AI support in Potato offers four main features:

1. **Intelligent Hints**: Provides contextual guidance to help annotators think about the annotation task, with an optional suggested label
2. **Keyword Highlighting**: Identifies and highlights relevant keywords in the text with visual box overlays
3. **Label Rationales**: Generates explanations for why each label might apply to the text, helping annotators understand the reasoning behind different classifications
4. **Label Suggestions**: Visually highlights which labels the AI thinks are most likely (with sparkle indicator on hint)

## Supported LLM Providers

Potato supports multiple LLM providers, allowing you to choose the best option for your needs:

### Cloud-Based Providers
- **OpenAI** (GPT-4, GPT-3.5-turbo, etc.)
- **Anthropic** (Claude models)
- **Google Gemini** (Gemini models)
- **Hugging Face** (Various open models)
- **OpenRouter** (Access to multiple providers)

### Local Providers
- **Ollama** (Local model inference)
- **VLLM** (High-performance local inference)

## Configuration

AI support is configured in your YAML configuration file under the `ai_support` section. The configuration is optional - if not present, AI features will be disabled.

### Basic Configuration Structure

```yaml
ai_support:
  enabled: true
  endpoint_type: "openai"  # or "anthropic", "huggingface", "ollama", "gemini", "vllm", "open_router"
  ai_config:
    model: "gpt-4o-mini"
    api_key: "your-api-key-here"
    temperature: 0.7
    max_tokens: 100
    include:
      all: true  # Enable AI for all annotation schemes
  cache_config:
    disk_cache:
      enabled: true
      path: "ai_cache/cache.json"
    prefetch:
      warm_up_page_count: 10  # Pre-generate on startup
      on_next: 5              # Prefetch when navigating forward
      on_prev: 2              # Prefetch when navigating backward
```

### Configuration Options

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `enabled` | boolean | Yes | Enable/disable AI support |
| `endpoint_type` | string | Yes | The LLM provider to use |
| `ai_config.model` | string | No | Model name (uses provider default if not specified) |
| `ai_config.api_key` | string | Yes* | API key for cloud providers |
| `ai_config.temperature` | float | No | Response randomness (0.0-2.0, default: 0.7) |
| `ai_config.max_tokens` | integer | No | Maximum response length (default: 100) |
| `ai_config.include.all` | boolean | No | Enable AI for all annotation schemes (default: false) |
| `ai_config.include.special_include` | object | No | Per-page, per-annotation customization |
| `cache_config.disk_cache.enabled` | boolean | No | Enable disk caching (default: false) |
| `cache_config.disk_cache.path` | string | No* | Path to cache file (required if caching enabled) |
| `cache_config.prefetch.warm_up_page_count` | integer | No | Pre-generate hints for first N instances on startup |
| `cache_config.prefetch.on_next` | integer | No | Prefetch N instances ahead when navigating forward |
| `cache_config.prefetch.on_prev` | integer | No | Prefetch N instances when navigating backward |

*Required for cloud-based providers (OpenAI, Anthropic, Hugging Face, Gemini)

## Caching and Pre-generation

For better performance, especially with large annotation tasks, Potato can pre-generate AI hints and cache them to disk. This avoids delays when annotators request AI assistance.

### How Caching Works

1. **Startup Warmup**: When Potato starts, it pre-generates AI hints for the first N instances (configured by `warm_up_page_count`)
2. **Look-ahead Prefetch**: When an annotator navigates, hints for upcoming instances are generated in the background
3. **Disk Persistence**: Generated hints are saved to disk, surviving server restarts

### Cache Configuration Example

```yaml
ai_support:
  enabled: true
  endpoint_type: "openai"
  ai_config:
    model: "gpt-4o-mini"
    api_key: "${OPENAI_API_KEY}"
    include:
      all: true
  cache_config:
    disk_cache:
      enabled: true
      path: "annotation_output/ai_cache.json"
    prefetch:
      warm_up_page_count: 20   # Pre-generate first 20 instances
      on_next: 10              # Prefetch 10 ahead when moving forward
      on_prev: 3               # Prefetch 3 behind when moving backward
```

## Multi-Schema Support

AI assistance works with multiple annotation schemes per instance. Each scheme gets its own AI hints and suggestions.

### Enabling AI for Specific Schemes

Use `special_include` to enable AI for specific pages and annotation schemes:

```yaml
ai_support:
  enabled: true
  endpoint_type: "openai"
  ai_config:
    model: "gpt-4o-mini"
    api_key: "${OPENAI_API_KEY}"
    include:
      all: false  # Don't enable for all by default
      special_include:
        # Page 0: Enable hint and keyword for annotation_id 0
        "0":
          "0": ["hint", "keyword"]
        # Page 1: Enable only hint for annotation_id 1
        "1":
          "1": ["hint"]
        # Page 2: Enable all AI types for both annotation schemes
        "2":
          "0": ["hint", "keyword"]
          "1": ["hint", "keyword"]
```

This allows fine-grained control over which instances and annotation schemes receive AI assistance.

## Custom Prompts

### Prompt Template Files

AI prompts are stored in JSON files in `potato/ai/prompt/`. Each annotation type has its own prompt file:

- `radio.json` - For radio button (single-choice) annotations
- `likert.json` - For Likert scale annotations
- `multiselect.json` - For checkbox (multi-choice) annotations
- `span.json` - For span/highlight annotations
- `slider.json` - For slider annotations
- `select.json` - For dropdown annotations
- `number.json` - For numeric input annotations
- `textbox.json` - For free-text annotations

### Prompt Structure

Each prompt file contains templates for different AI assistance types:

```json
{
  "hint": {
    "name": "Hint",
    "prompt": "TASK: Generate annotation guidance for single-choice selection.\n\nINPUT DETAILS:\n- Text to annotate: \"${text}\"\n- Annotation task: ${description}\n- Available labels: ${labels}\n\nINSTRUCTIONS:\n1. Analyze the text...",
    "output_format": "default_hint",
    "img": "/static/ai_assistant_img/blub.svg"
  },
  "keyword": {
    "name": "Keyword",
    "prompt": "TASK: Extract words/phrases that relate to each label...",
    "output_format": "default_keyword",
    "img": "/static/ai_assistant_img/highlight.svg"
  },
  "rationale": {
    "name": "Rationale",
    "prompt": "TASK: Generate rationales explaining why each label might apply...",
    "output_format": "default_rationale",
    "img": "/static/ai_assistant_img/question.svg"
  }
}
```

### Available Template Variables

| Variable | Description |
|----------|-------------|
| `${text}` | The text being annotated |
| `${description}` | The annotation task description |
| `${labels}` | Available labels (for classification tasks) |
| `${min_label}` | Minimum label (for Likert/slider) |
| `${max_label}` | Maximum label (for Likert/slider) |
| `${size}` | Scale size (for Likert) |
| `${min_value}` | Minimum value (for slider/number) |
| `${max_value}` | Maximum value (for slider/number) |

### Output Formats

The `output_format` field specifies the expected response structure:

- `default_hint`: Returns `{hint: string, suggestive_choice: string|number}`
- `default_keyword`: Returns `{label_keywords: [{label: string, keywords: [string]}]}`
- `default_rationale`: Returns `{rationales: [{label: string, reasoning: string}]}`

## Provider-Specific Configuration

### OpenAI

```yaml
ai_support:
  enabled: true
  endpoint_type: "openai"
  ai_config:
    model: "gpt-4o-mini"  # or "gpt-4", "gpt-3.5-turbo", etc.
    api_key: "sk-..."
    temperature: 0.7
    max_tokens: 100
```

**Setup:**
1. Get an API key from [OpenAI](https://platform.openai.com/api-keys)
2. Install the OpenAI Python package: `pip install openai`

### Anthropic (Claude)

```yaml
ai_support:
  enabled: true
  endpoint_type: "anthropic"
  ai_config:
    model: "claude-3-5-sonnet-20241022"
    api_key: "sk-ant-..."
    temperature: 0.7
    max_tokens: 100
```

**Setup:**
1. Get an API key from [Anthropic](https://console.anthropic.com/)
2. Install the Anthropic Python package: `pip install anthropic`

### Google Gemini

```yaml
ai_support:
  enabled: true
  endpoint_type: "gemini"
  ai_config:
    model: "gemini-2.0-flash-exp"
    api_key: "AIza..."
    temperature: 0.7
    max_tokens: 100
```

**Setup:**
1. Get an API key from [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Install the Google Generative AI package: `pip install google-generativeai`

### Hugging Face

```yaml
ai_support:
  enabled: true
  endpoint_type: "huggingface"
  ai_config:
    model: "meta-llama/Llama-3.2-3B-Instruct"
    api_key: "hf_..."
    temperature: 0.7
    max_tokens: 100
```

**Setup:**
1. Get an API key from [Hugging Face](https://huggingface.co/settings/tokens)
2. Install the Hugging Face Hub package: `pip install huggingface-hub`

### OpenRouter

```yaml
ai_support:
  enabled: true
  endpoint_type: "open_router"
  ai_config:
    model: "openai/gpt-4o-mini"  # Any model available on OpenRouter
    api_key: "sk-or-..."
    temperature: 0.7
    max_tokens: 100
```

**Setup:**
1. Get an API key from [OpenRouter](https://openrouter.ai/)
2. Install requests: `pip install requests`

### Ollama (Local)

```yaml
ai_support:
  enabled: true
  endpoint_type: "ollama"
  ai_config:
    model: "llama3.2"
    temperature: 0.7
    max_tokens: 100
```

**Setup:**
1. Install Ollama from [ollama.ai](https://ollama.ai/)
2. Pull a model: `ollama pull llama3.2`
3. Install the Ollama Python package: `pip install ollama`

### VLLM (Local)

```yaml
ai_support:
  enabled: true
  endpoint_type: "vllm"
  ai_config:
    model: "meta-llama/Llama-3.2-3B-Instruct"
    base_url: "http://localhost:8000"
    api_key: ""  # Optional
    temperature: 0.7
    max_tokens: 100
```

**Setup:**
1. Install VLLM: `pip install vllm`
2. Start a VLLM server:
   ```bash
   vllm serve meta-llama/Llama-3.2-3B-Instruct --host 0.0.0.0 --port 8000
   ```

## Environment Variables

For security, use environment variables for API keys:

```yaml
ai_support:
  enabled: true
  endpoint_type: "openai"
  ai_config:
    model: "gpt-4o-mini"
    api_key: "${OPENAI_API_KEY}"
```

Then set the environment variable:
```bash
export OPENAI_API_KEY="sk-..."
```

## Usage in Annotation Interface

When AI support is enabled, annotators will see AI assistance buttons on each annotation scheme:

1. **Hint Button** (lightbulb icon): Click to get contextual guidance
   - Shows a tooltip with the hint text
   - May include a suggested label (highlighted with sparkle indicator on the actual label button)

2. **Keyword Button** (highlight icon): Click to highlight relevant text
   - Draws box overlays around keywords identified by the AI
   - Each keyword is associated with a specific label

3. **Rationale Button** (question mark icon): Click to see reasoning for each label
   - Shows a tooltip with explanations for why each label might apply
   - Provides balanced reasoning for all available labels, helping annotators understand the classification criteria
   - Useful for training annotators or when decisions are difficult

### Visual Indicators

- **Suggested Labels**: When the AI suggests a specific label, it gets highlighted with:
  - An amber/gold border around the label option
  - A subtle pulsing glow effect
  - A sparkle emoji indicator

- **Keyword Highlights**: Text keywords are highlighted with:
  - An amber border box (not a background highlight)
  - A subtle glow effect
  - Hover tooltip showing the AI's reasoning

## Troubleshooting

### Common Issues

1. **"API key is required" error**
   - Ensure you've provided a valid API key for cloud-based providers
   - Check that the API key has the necessary permissions

2. **"Failed to connect" error (Ollama/VLLM)**
   - Verify that Ollama is running: `ollama list`
   - Check that VLLM server is accessible at the configured URL
   - Ensure the model is available: `ollama pull model-name`

3. **"Model not found" error**
   - Verify the model name is correct for your provider
   - For local providers, ensure the model is installed/downloaded

4. **Rate limiting errors**
   - Reduce request frequency
   - Enable caching to reduce API calls
   - Consider using a local provider for high-volume annotation

5. **Keyword highlighting not working**
   - Ensure the span-core.js file is loaded (check browser console)
   - Verify the SpanManager is initialized
   - Check that the text content element exists

### Debug Mode

Enable debug mode to see detailed AI request/response logs:

```yaml
debug: true
ai_support:
  enabled: true
  endpoint_type: "openai"
  # ... rest of config
```

## Best Practices

1. **Enable caching**: For production use, always enable disk caching to improve response times
2. **Use warmup**: Set `warm_up_page_count` to pre-generate hints for common starting points
3. **Test thoroughly**: Verify AI responses are helpful but not revealing answers
4. **Monitor costs**: Cloud providers charge per request; caching helps reduce costs
5. **Consider local options**: For high-volume annotation, local providers (Ollama, VLLM) are more cost-effective
6. **Customize prompts**: Edit the JSON prompt files to tailor AI responses to your specific task
7. **Security**: Never commit API keys to version control; use environment variables

## Complete Configuration Example

```yaml
annotation_task_name: Sentiment Analysis with AI Support

data_files:
  - data/reviews.json

item_properties:
  id_key: id
  text_key: text

annotation_schemes:
  - annotation_type: radio
    annotation_id: 0
    name: sentiment
    description: "What is the sentiment of this text?"
    labels: ["positive", "negative", "neutral"]

  - annotation_type: multiselect
    annotation_id: 1
    name: topics
    description: "What topics are discussed?"
    labels: ["product", "service", "price", "quality"]

ai_support:
  enabled: true
  endpoint_type: "openai"
  ai_config:
    model: "gpt-4o-mini"
    api_key: "${OPENAI_API_KEY}"
    temperature: 0.7
    max_tokens: 150
    include:
      all: true  # Enable AI for all annotation schemes
  cache_config:
    disk_cache:
      enabled: true
      path: "annotation_output/ai_cache.json"
    prefetch:
      warm_up_page_count: 20
      on_next: 10
      on_prev: 3
```

This configuration provides a complete AI-assisted annotation setup with caching, multi-schema support, and automatic pre-generation for optimal user experience.
