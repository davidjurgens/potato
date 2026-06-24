# Model Arena

Send one prompt to **N models side by side**, compare their responses, and pick
the best — building a win-rate leaderboard. The arena is **provider-agnostic**:
every model is built through Potato's `AIEndpointFactory`, so you can compare
OpenAI, Anthropic, Ollama, vLLM, Gemini, OpenRouter, … in the same view, not
just one vendor. (This generalizes the older Anthropic-vision-only live agent.)

## Enabling

```yaml
arena:
  enabled: true
  models:
    - {label: "GPT-4o",  endpoint_type: openai,    model: gpt-4o}
    - {label: "Claude",  endpoint_type: anthropic, model: claude-sonnet-4-6}
    - {label: "Llama",   endpoint_type: ollama,    model: llama3.2, base_url: http://localhost:11434}
```

Each entry maps to an `AIEndpointFactory` config (`endpoint_type`, `model`,
`base_url`, `temperature`, and an optional `ai_config` for keys/params). When
enabled, the admin dashboard shows an **Arena** link.

## How it works

1. Enter a prompt → it's sent to every model **concurrently**. One model failing
   (bad key, provider down) never blocks the others — its card shows the error.
2. Responses render side by side, each with per-model latency.
3. Click **Pick as best** → records a preference and updates the **leaderboard**.

## Leaderboard: Bradley-Terry + Elo (not just win-rate)

A raw win-rate treats beating a weak model the same as beating a strong one. The
arena instead ranks models by a **Bradley-Terry** score (a maximum-likelihood
strength that accounts for *who you beat*) and also reports an **Elo** rating
updated after every comparison. Win-rate is still shown for reference.

- A bare **winner** counts as that model beating every other model in the run.
- A full **ranking** (`["A", "B", "C"]`) expands into all pairwise outcomes.

Both metrics need no extra config — they appear once you record preferences.

## Export DPO preference data

Every "Pick as best" is a human preference, so the arena doubles as a **DPO
data-collection** surface. **Export DPO** (button on the leaderboard, or
`GET /admin/arena/api/export_dpo`) returns one `{prompt, chosen, rejected}` triple
per winner-vs-loser pair where both response texts are available — ready for
preference fine-tuning (DPO/KTO).

## API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/admin/arena/api/run` | `{prompt}` → per-model responses (`label, response, latency_ms, error`) |
| POST | `/admin/arena/api/preference` | `{prompt, winner, ranking?}` → record a pick |
| GET | `/admin/arena/api/leaderboard` | Bradley-Terry score + Elo + wins/comparisons/win-rate per model |
| GET | `/admin/arena/api/export_dpo` | human preferences as DPO `{prompt, chosen, rejected}` pairs |

```bash
curl -X POST localhost:8000/admin/arena/api/run -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" -d '{"prompt": "Explain RLHF in one sentence."}'
```

## Example

`examples/agent-traces/model-arena/` is a runnable demo (configure real models
in its `config.yaml`).

## Related

- [Live Agent Interaction](live_agent.md) — observe a single live browser agent
- [Datasets & Experiments](datasets_and_experiments.md) — for offline, dataset-scale comparison
- [Pairwise Comparison](../annotation-types/comparison/pairwise_annotation.md) — annotate A/B preferences in the main flow
