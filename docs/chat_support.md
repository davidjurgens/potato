# Chat Support (LLM Annotator Assistance)

Chat Support adds a collapsible sidebar where annotators can have multi-turn conversations with an LLM about the current annotation instance. The LLM is given context about the task and current text, helping annotators think through difficult cases without giving direct answers.

## Quick Start

Add a `chat_support` section to your YAML config:

```yaml
chat_support:
  enabled: true
  endpoint_type: ollama
  ai_config:
    model: llama3.2
    temperature: 0.7
    max_tokens: 500
```

## Configuration Reference

### `chat_support`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable/disable chat support |
| `endpoint_type` | string | required | LLM provider: `openai`, `anthropic`, `ollama`, `huggingface`, `gemini`, `vllm`, `openrouter` |
| `ai_config` | dict | `{}` | Provider-specific configuration |
| `system_prompt` | dict | `{}` | System prompt customization |
| `ui` | dict | `{}` | UI appearance settings |

### `chat_support.ai_config`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | string | provider default | Model name (e.g., `llama3.2`, `gpt-4o-mini`, `claude-sonnet-4-20250514`) |
| `temperature` | float | `0.7` | Response creativity (0.0-2.0) |
| `max_tokens` | int | `500` | Maximum response length |
| `api_key` | string | — | API key (required for cloud providers) |
| `base_url` | string | — | Custom API base URL (for ollama, vllm) |
| `timeout` | int | `30` | Request timeout in seconds |

### `chat_support.system_prompt`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `template` | string | built-in | Custom system prompt template |

The system prompt template supports these variables:

- `{task_name}` — The annotation task name from config
- `{task_description}` — The task description
- `{annotation_labels}` — Summary of available labels across all schemes
- `{instance_text}` — The current instance text being annotated
- `{instance_id}` — The current instance ID

### `chat_support.ui`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | string | `"Ask AI"` | Sidebar header and toggle button text |
| `placeholder` | string | `"Ask about this annotation..."` | Input placeholder text |
| `sidebar_width` | int | `380` | Sidebar width in pixels (200-800) |
| `max_history_per_instance` | int | `50` | Max messages stored per instance |

## Example Configurations

### Ollama (Local)

```yaml
chat_support:
  enabled: true
  endpoint_type: ollama
  ai_config:
    model: llama3.2
    temperature: 0.7
    max_tokens: 500
    base_url: http://localhost:11434
```

### OpenAI

```yaml
chat_support:
  enabled: true
  endpoint_type: openai
  ai_config:
    model: gpt-4o-mini
    api_key: sk-your-key-here
    temperature: 0.7
    max_tokens: 500
```

### Anthropic

```yaml
chat_support:
  enabled: true
  endpoint_type: anthropic
  ai_config:
    model: claude-sonnet-4-20250514
    api_key: sk-ant-your-key-here
    temperature: 0.7
    max_tokens: 500
```

### Custom System Prompt

```yaml
chat_support:
  enabled: true
  endpoint_type: ollama
  ai_config:
    model: llama3.2
  system_prompt:
    template: |
      You are a helpful assistant for the annotation task "{task_name}".

      Task: {task_description}
      Labels: {annotation_labels}

      The annotator is reading: {instance_text}

      Provide guidance without revealing the answer.
      Focus on helping them understand the text.
```

## How It Works

1. A toggle button appears in the navigation bar (right side)
2. Clicking it opens a sidebar with a chat interface
3. The annotator types a question and presses Enter (or clicks Send)
4. The LLM receives the current instance text and task context as a system prompt
5. The response appears in the chat
6. Conversation history is preserved per instance — navigating away and back restores the chat
7. All chat interactions are saved in `user_state.json` for research analysis

## Data Format

Chat history is stored in `user_state.json` under each instance's behavioral data:

```json
{
  "instance_id_to_behavioral_data": {
    "instance_1": {
      "chat_history": [
        {
          "role": "user",
          "content": "What does this mean?",
          "timestamp": 1709000000.0,
          "instance_id": "instance_1",
          "response_time_ms": null
        },
        {
          "role": "assistant",
          "content": "This text discusses...",
          "timestamp": 1709000002.5,
          "instance_id": "instance_1",
          "response_time_ms": 2500
        }
      ],
      "interactions": [
        {
          "event_type": "chat_message_sent",
          "target": "chat_sidebar",
          "metadata": {
            "message_length": 22,
            "response_length": 45,
            "response_time_ms": 2500
          }
        }
      ]
    }
  }
}
```

## Analyzing Chat Data

Chat data can be extracted from `user_state.json` for analysis:

```python
import json

with open("annotation_output/user_state.json") as f:
    user_states = json.load(f)

for username, state in user_states.items():
    bd = state.get("instance_id_to_behavioral_data", {})
    for instance_id, data in bd.items():
        chat = data.get("chat_history", [])
        if chat:
            print(f"User {username}, Instance {instance_id}: {len(chat)} messages")
            for msg in chat:
                print(f"  [{msg['role']}] {msg['content'][:80]}")
```

## Troubleshooting

**Chat button doesn't appear:**
- Verify `chat_support.enabled: true` in config
- Check browser console for errors loading `/api/chat/config`

**"Chat support is not configured" error:**
- Check server logs for endpoint initialization errors
- For Ollama: ensure `ollama serve` is running
- For cloud providers: verify API key is correct

**Slow responses:**
- Increase `ai_config.timeout` if responses are being cut off
- Try a smaller/faster model
- For Ollama: ensure the model is already pulled (`ollama pull llama3.2`)

## Related Documentation

- [AI Support](ai_support.md) — Structured AI label suggestions (different feature)
- [Behavioral Tracking](behavioral_tracking.md) — How interaction data is collected
