# Deploying the Potato Spaces Catalog

This is the operational runbook for stamping out and publishing the Potato demo Spaces
defined in [`spaces_manifest.yaml`](spaces_manifest.yaml). For deploying a *single* custom
annotation project (your own data), see [`deploy.md`](deploy.md) instead.

## How it works

Every Space is generated from an existing `examples/` project — the manifest is the only
source of truth. The flow is:

```
spaces_manifest.yaml  ──build_space.py──▶  spaces-build/<id>/  ──deploy_space.py──▶  <org>/<id> on HF
```

- **`build_space.py`** assembles a self-contained Space dir (config + data + layouts, the
  `potato/` source, Dockerfile/entrypoint, a generated HF `README.md`, and a `.gitattributes`
  for media demos).
- **`deploy_space.py`** creates the Docker Space repo and uploads the build via
  `huggingface_hub` (auto-handles git-lfs; respects your stored login).

## One-time setup

```bash
pip install huggingface_hub
huggingface-cli login            # or: export HF_TOKEN=hf_xxx
```

## Build

```bash
# List the catalog (64 spaces; flags: lfs / ai / gated)
python deployment/huggingface-spaces/build_space.py --list

# Build one
python deployment/huggingface-spaces/build_space.py agent-trace-evaluation

# Build all into spaces-build/
python deployment/huggingface-spaces/build_space.py --all
```

## Deploy

```bash
# One Space (org = your HF user or org, e.g. Blablablab)
python deployment/huggingface-spaces/deploy_space.py agent-trace-evaluation Blablablab

# Everything that's self-contained and non-AI (recommended first wave):
python deployment/huggingface-spaces/deploy_space.py --all Blablablab --ready-only
```

Flags:
- `--ready-only` — also skip `needs_ai` demos (they require an LLM endpoint to be useful).
- `--include-gated` — include the live/ingestion variants (only after the boot-check confirms
  they render from bundled static data).
- `--private` — create the Space private.

## Categories & flags

| Flag | Meaning | Deploy guidance |
|------|---------|-----------------|
| _(none)_ | Self-contained, static data | Deploy freely. |
| `lfs` | Bundles media (image/audio/video/pdf) | Deploy freely; upload handles lfs. |
| `ai` | Calls an LLM at annotation time | Wire `ai_support`/`solo_mode`/`judge_calibration` to the HF Inference API (`HF_TOKEN`) before deploy, or it degrades. See [`huggingface_models.md`](../../docs/ai-intelligence/huggingface_models.md). |
| `gated` | Live/ingestion variant | Deploy **only** if the boot-check shows it renders from bundled static traces without a live backend. |

## Suggested waves

1. **Wave 1 — flagships:** `agent-trace-evaluation`, `ner-span`, `video-annotation`,
   `sentiment-analysis`, `llm-preference`, `qda-mode`, `image-bbox`, `rag-evaluation`,
   `web-agent-review`, `judge-calibration`.
2. **Wave 2 — rest of the agent catalog.**
3. **Wave 3 — remaining classification / span / multimodal / advanced / custom.**

After each Space is live: open it, confirm the annotation phase loads, then add it to the
HF Collection.

## Adding a new Space later

Add one entry to `spaces_manifest.yaml`, then `build_space.py <id>` + `deploy_space.py <id> <org>`.
No code changes required.
