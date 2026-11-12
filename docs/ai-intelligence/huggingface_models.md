# Using HuggingFace Models in Potato

This guide shows how to point Potato's language-model features at a model hosted on
HuggingFace, whether through the serverless Inference API, a dedicated Inference
Endpoint, a self-hosted TGI/vLLM server, or a fully local model. It walks through
three of them in detail: AI hints, Solo Mode and judge calibration. The others take the
same `endpoint_type` / `model` / `api_key` / `base_url` keys, except `active_learning.llm`.

| Feature | What the LLM does | Config block |
|---------|-------------------|--------------|
| **AI hints** | Suggests labels inline in the annotation UI | `ai_support` |
| **Chat** | Answers annotator questions in a sidebar | `chat_support` |
| **ICL labeling** | Labels items from high-agreement examples | `icl_labeling` (uses the `ai_support` endpoint) |
| **Annotation critique** | Reviews drawn regions | per-scheme `ai_support.critique` (uses the top-level `ai_support` endpoint) |
| **Solo mode** | Auto-labels items while you calibrate (human-in-the-loop) | `solo_mode.labeling_models[]` |
| **Judge calibration** | Acts as an LLM judge you align against blind human labels | `judge_calibration.models[]` |
| **Labeling engine** | Labels items as `llm` or `judge` sources | `labeling_engine.sources[]` |
| **Active learning LLM** | Cold-start labels and ICL ensemble | `active_learning.llm` (its own keys: `endpoint_url`, an OpenAI-compatible chat completions URL, and `model_name`) |

`icl_labeling` and `judge_calibration` still work in 2.11 and are planned for removal
in 3.0; the [labeling engine](../labeling-engine/overview.md) replaces them. See
[Migrating to the labeling engine](../labeling-engine/migration.md), or run
`potato label migrate-config config.yaml --out config-engine.yaml`.

See also: [AI support](ai_support.md) · [Solo mode](../solo-mode/solo_mode.md) ·
[Judge calibration](judge_calibration.md).

---

## Two ways to reach a HuggingFace model

### Path A — the native `huggingface` endpoint (recommended)

Uses `huggingface_hub.InferenceClient`, so it works with the HuggingFace serverless
Inference API and with dedicated [Inference Endpoints](https://huggingface.co/inference-endpoints).
An API token is **required**.

```yaml
endpoint_type: huggingface
model: meta-llama/Llama-3.2-3B-Instruct   # any chat/instruct model on the Hub
api_key: ${HF_TOKEN}                       # required — your HF access token
temperature: 0.7
max_tokens: 150
timeout: 30
```

### Path B — OpenAI-compatible `base_url`

HuggingFace (and TGI/vLLM/Ollama) expose OpenAI-compatible `/v1` endpoints, so you can
also use `endpoint_type: openai` with a custom `base_url`. Handy when you already run an
inference server or want the HF router.

```yaml
# HuggingFace router (OpenAI-compatible)
endpoint_type: openai
model: meta-llama/Llama-3.2-3B-Instruct
api_key: ${HF_TOKEN}
base_url: https://router.huggingface.co/v1

# Self-hosted TGI / vLLM
# endpoint_type: openai
# model: meta-llama/Llama-3.2-3B-Instruct
# api_key: EMPTY
# base_url: http://your-server:8080/v1

# Fully local (vLLM / Ollama OpenAI shim)
# endpoint_type: vllm
# model: Qwen/Qwen3-4B
# base_url: http://localhost:8000/v1
```

Both paths accept the same generation keys: `model`, `api_key`, `base_url` (Path B),
`temperature`, `max_tokens`, `timeout`.

> **Get a token:** create a `read`-scoped token at
> [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) and export it:
> `export HF_TOKEN=hf_xxx`. Potato expands `${HF_TOKEN}` from the environment.

---

## Wiring it into each feature

### 1. AI hints (`ai_support`)

```yaml
ai_support:
  enabled: true
  endpoint_type: huggingface
  ai_config:
    model: meta-llama/Llama-3.2-3B-Instruct
    api_key: ${HF_TOKEN}
    temperature: 0.7
    max_tokens: 150
    include:
      all: true          # enable hints for every scheme
  cache_config:
    disk_cache:
      enabled: true
      path: annotation_output/ai_cache.json
```

You can keep the endpoint details in a separate gitignored file instead of inline:

```yaml
ai_support:
  enabled: true
  ai_config_file: ai-config.yaml   # holds endpoint_type/model/api_key/base_url
  ai_config:
    temperature: 0.7
    max_tokens: 150
    include: {all: true}
```

### 2. Solo mode (`solo_mode.labeling_models[]`)

Each entry is an endpoint; list more than one for fallback/ensembling.

```yaml
solo_mode:
  enabled: true
  labeling_models:
    - endpoint_type: huggingface
      model: meta-llama/Llama-3.1-8B-Instruct
      api_key: ${HF_TOKEN}
      temperature: 0.1
      max_tokens: 1000
  uncertainty:
    strategy: direct_confidence
```

### 3. Judge calibration (`judge_calibration.models[]`)

`judge_calibration` is planned for removal in 3.0. In the labeling engine, the same
model is a source with `kind: judge` and the same `endpoint_type`, `model` and
`api_key` keys, under `labeling_engine.sources[]`; see
[Labeling engine configuration](../labeling-engine/configuration.md#sources).

```yaml
judge_calibration:
  enabled: true
  prompt: |
    You are an impartial expert annotator. Classify the sentiment as exactly one of:
    positive, negative, neutral.
  models:
    - endpoint_type: huggingface
      model: meta-llama/Llama-3.1-8B-Instruct
      api_key: ${HF_TOKEN}
      temperature: 0.7      # must be > 0 so repeated samples vary
      max_tokens: 1000
  k_samples: 5
  schemas: [sentiment]
```

---

## Local vs. hosted — which path?

| You want… | Use |
|-----------|-----|
| Zero infra, just a token | Path A, serverless Inference API |
| Guaranteed throughput / a pinned model | Path A against a dedicated **Inference Endpoint** URL |
| You already run TGI or vLLM | Path B with that server's `/v1` `base_url` |
| Fully offline / no data leaves the machine | `endpoint_type: ollama` or `vllm` with a `localhost` `base_url` |
| A model not on HF | OpenAI/Anthropic/Gemini endpoints (see [AI support](ai_support.md)) |

---

## Running on HuggingFace Spaces

When Potato runs as a Space, set `HF_TOKEN` as a **Space secret** (Settings → Variables and
secrets). The same `${HF_TOKEN}` references above then resolve inside the container, so the
AI-assisted demos work without any code change. See the
[Spaces deployment guide](../data-export/huggingface_spaces.md).

---

## Troubleshooting

- **"Hugging Face API key is required"** — the native endpoint needs `api_key`; set
  `HF_TOKEN` (Path A) or `api_key: EMPTY` against a local server (Path B).
- **403 / model not served** — not every model is available on the serverless API. Pick a
  served chat model, or stand up a dedicated Inference Endpoint / local server.
- **Slow first hint** — serverless models cold-start. Enable `cache_config.prefetch` to warm
  upcoming items, or use a dedicated endpoint.
- **Malformed JSON from the model** — prefer instruct/chat models; small base models often
  ignore the structured-output schema.

## Related

- [AI support / hints](ai_support.md)
- [Solo mode](../solo-mode/solo_mode.md)
- [Judge calibration](judge_calibration.md)
- [Deploy Potato on HuggingFace Spaces](../data-export/huggingface_spaces.md)
