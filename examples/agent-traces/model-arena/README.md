# Model Arena

Send one prompt to **N models side by side**, compare their responses, and pick
the best — building a win-rate leaderboard. Models are **provider-agnostic** (any
of Potato's LLM endpoints: OpenAI, Anthropic, Ollama, vLLM, Gemini, …), so the
arena isn't tied to one vendor.

## Run

```bash
python potato/flask_server.py start examples/agent-traces/model-arena/config.yaml -p 8000
```

Open the admin dashboard → **Arena**. Configure real models in `config.yaml`
(set `endpoint_type`, `model`, and any keys/base_url for your providers).

## How it works

1. Enter a prompt → it's sent to every configured model concurrently (one model
   failing never blocks the others).
2. Responses render side by side with per-model latency.
3. Click **Pick as best** → records a preference and updates the leaderboard
   (wins / comparisons / win-rate per model).

## Config

```yaml
arena:
  enabled: true
  models:
    - {label: "GPT-4o", endpoint_type: openai, model: gpt-4o}
    - {label: "Claude", endpoint_type: anthropic, model: claude-sonnet-4-6}
    - {label: "Llama", endpoint_type: ollama, model: llama3.2, base_url: http://localhost:11434}
```

## API

```bash
curl -X POST localhost:8000/admin/arena/api/run -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" -d '{"prompt": "Explain RLHF in one sentence."}'
curl localhost:8000/admin/arena/api/leaderboard -H "X-API-Key: <key>"
```

See the [Model Arena guide](../../../docs/agent-evaluation/model_arena.md).
