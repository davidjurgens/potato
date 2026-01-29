# Ollama AI-Assisted Annotation Demo

This example demonstrates all of Potato's AI enhancement features using a **local Ollama instance** - no cloud API keys required!

## AI Features Demonstrated

1. **Intelligent Hints** (lightbulb icon)
   - Click to get contextual guidance about the annotation task
   - Includes a suggested label that gets highlighted in the UI

2. **Keyword Highlighting** (highlight icon)
   - AI identifies and highlights relevant words/phrases in the text
   - Hover over highlights to see the AI's reasoning

3. **Label Suggestions**
   - Visual sparkle indicator on suggested labels
   - Amber border highlights the AI's recommendation

## Prerequisites

### 1. Install Ollama

Download and install Ollama from [ollama.ai](https://ollama.ai/)

**macOS:**
```bash
brew install ollama
```

**Linux:**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

**Windows:**
Download the installer from [ollama.ai/download](https://ollama.ai/download)

### 2. Pull a Model

```bash
ollama pull qwen3:0.6b
```

This demo uses Qwen3 0.6B - a fast, lightweight model ideal for local inference.

Other compatible models:
- `ollama pull qwen3:1.7b` - Larger, more capable variant
- `ollama pull llama3.2` - Meta's Llama 3.2
- `ollama pull mistral` - Good for simple tasks
- `ollama pull phi3` - Microsoft's compact model

### 3. Start Ollama

Ollama usually runs automatically after installation. Verify it's running:

```bash
ollama list
```

If not running, start it:
```bash
ollama serve
```

### 4. Install Python Dependency

```bash
pip install ollama
```

## Running the Demo

From the potato root directory:

```bash
python potato/flask_server.py start project-hub/simple_examples/ollama-ai-demo/config.yaml -p 8000
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

## Using AI Features

Once annotating:

1. **Get a Hint**: Click the lightbulb icon next to any annotation scheme
   - A tooltip appears with contextual guidance
   - The AI's suggested label gets a sparkle indicator

2. **Highlight Keywords**: Click the highlight icon
   - Relevant phrases get amber box overlays
   - Hover over highlights to see reasoning

3. **Follow Suggestions**: Labels with sparkle indicators are AI recommendations
   - You can accept or override them
   - All final decisions are yours

## Annotation Task

The demo includes 12 synthesized product reviews covering various scenarios:
- Different sentiments (positive, negative, neutral, mixed)
- Various product types and price points
- Real-world review patterns

You'll classify each review's **sentiment** as:
- **Positive** - Satisfaction, happiness, approval
- **Negative** - Dissatisfaction, frustration, disapproval
- **Neutral** - Factual, balanced, no strong emotion
- **Mixed** - Contains both positive and negative sentiments

## Configuration Highlights

```yaml
ai_support:
  enabled: true
  endpoint_type: ollama
  ai_config:
    model: qwen3:0.6b
    temperature: 0.7
    max_tokens: 150
    include:
      all: true  # Enable AI for all annotation schemes
  cache_config:
    disk_cache:
      enabled: true
      path: annotation_output/ai_cache.json
    prefetch:
      warm_up_page_count: 5
      on_next: 3
      on_prev: 1
```

## Troubleshooting

**"Failed to connect" error:**
- Ensure Ollama is running: `ollama list`
- Check Ollama is on default port: `curl http://localhost:11434/api/tags`

**Slow responses:**
- First request loads the model into memory (can take a few seconds)
- Subsequent requests are faster
- qwen3:0.6b is already very fast; for even better quality try `qwen3:1.7b`

**Model not found:**
- Pull the model: `ollama pull qwen3:0.6b`
- Or change `model` in config.yaml to one you have installed

## Switching to Cloud Providers

To use OpenAI, Anthropic, or other cloud providers instead, see the [AI Support Documentation](../../../docs/ai_support.md).

Example OpenAI config:
```yaml
ai_support:
  enabled: true
  endpoint_type: openai
  ai_config:
    model: gpt-4o-mini
    api_key: ${OPENAI_API_KEY}
    # ... rest of config
```
