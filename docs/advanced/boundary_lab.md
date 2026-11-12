# Boundary Lab: Counterfactual Boundary Probing

Every annotation tool collects **point labels**: item X gets label Y. Boundary Lab makes
Potato collect **decision boundaries**. The moment an annotator commits a label, Potato
shows minimal counterfactual edits of the text and asks, one probe at a time:

> *You said **Polite**. Would that survive this edit?*

Each answer takes one click. Ordinary annotation then produces three artifacts that a
plain label export cannot:

1. **Contrast sets, for free.** Every answered probe is a labeled
   *(original, counterfactual)* pair — the counterfactually-augmented data shown to
   improve model robustness (Gardner et al. 2020, *Evaluating Models' Local Decision
   Boundaries via Contrast Sets*; Kaushik et al. 2020, *Learning the Difference that
   Makes a Difference*) — normally built as an expensive separate effort.
2. **Boundary rationales.** When a label flips, the annotator says what crossed the
   line. These rationales pinpoint exactly where your codebook is ambiguous.
3. **Invisible quality control.** *Invariance probes* are meaning-preserving
   paraphrases; a consistent annotator never flips on them. Annotators who do are
   flagged on the dashboard — an attention signal collected without planting a single
   fake gold item.

## Quick start

```bash
python potato/flask_server.py start examples/advanced/boundary-probing/config.yaml -p 8000 --debug --debug-phase annotation
```

Label an item and the probe panel slides in at the bottom right. The dashboard lives at
`/boundary/dashboard` (admin access; debug mode passes automatically).

## Configuration

```yaml
boundary_probing:
  enabled: true
  schema: politeness          # annotation scheme to probe (default: first radio scheme)
  probes_per_item: 3          # probes per (instance, label), invariance probe included
  include_invariance: true    # add one paraphrase probe (the QC signal)
  sources:                    # probe generation tiers, in priority order
    - precomputed
    - llm
    - rules
  precomputed_key: counterfactuals   # item-data field for precomputed probes
  rationale_on_flip: true     # ask "what crossed the line?" when a label flips
  debounce_ms: 900            # delay between label selection and probe fetch
  # ai_support: {...}         # optional endpoint override; defaults to global ai_support
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Master switch. |
| `schema` | first radio scheme | Which annotation scheme's labels get probed. |
| `probes_per_item` | `3` | Total probes per (instance, label). |
| `include_invariance` | `true` | Reserve one slot for a paraphrase probe. |
| `sources` | `[precomputed, llm, rules]` | Generation tiers; later tiers fill slots earlier tiers leave empty. |
| `precomputed_key` | `counterfactuals` | Item field holding curated probes. |
| `rationale_on_flip` | `true` | Collect a free-text rationale on flips. |
| `debounce_ms` | `900` | Frontend debounce before fetching probes. |
| `ai_support` | global block | Endpoint override for LLM generation. |

### Probe sources

**`precomputed`** — ship curated counterfactuals with your data. Deterministic, ideal
for controlled studies:

```json
{"id": "req_02", "text": "Send me the slides before the meeting.",
 "counterfactuals": [
   {"text": "Please send me the slides before the meeting.", "kind": "flip",
    "edit_hint": "added \"please\""},
   {"text": "Before the meeting, send me the slides.", "kind": "invariance",
    "edit_hint": "reordered clauses"}
 ]}
```

**`llm`** — generate probes on the fly with any configured AI endpoint (Anthropic,
OpenAI, Ollama, vLLM, …). Uses the global `ai_support` block unless
`boundary_probing.ai_support` overrides it. Probes are generated once per
(instance, label) and shared across annotators, so LLM cost is bounded by your dataset
size, not your annotator count.

**`rules`** — deterministic lexical transforms (negation toggles, intensifier swaps,
politeness markers, punctuation heat; contraction/greeting paraphrases for invariance).
No dependencies; guarantees the feature degrades gracefully when no LLM is configured.

### Probe kinds and verdicts

| Kind | Meaning | Expected behavior |
|------|---------|-------------------|
| `flip` | Smallest edit intended to cross the label boundary | May flip or hold — both are informative |
| `invariance` | Meaning-preserving paraphrase | Should **never** flip; flips indicate inconsistency |

Annotators answer each probe with **holds** (label survives), **flips** (label
changes — they pick the new label and optionally say why), or **can't tell**.

## The dashboard (`/boundary/dashboard`)

- **Boundary sensitivity by label** — of the minimal edits aimed at each label, the
  share that flipped. A 90% flip rate means the label lives on a knife's edge; 10%
  means it's robust to small perturbations.
- **Annotator invariance consistency** — per-annotator hold rate on paraphrase probes,
  flagged red below 60%.
- **Where labels flip** — a gallery of confirmed flips with word-level diffs and the
  annotators' rationales.

## Contrast-set export

`GET /boundary/api/export` (admin) downloads JSONL, one labeled pair per answered probe:

```json
{"instance_id": "req_02", "schema": "politeness",
 "original_text": "Send me the slides before the meeting.",
 "original_label": "Impolite",
 "counterfactual_text": "Please send me the slides before the meeting.",
 "counterfactual_label": "Neutral",
 "kind": "flip", "flipped": true,
 "rationale": "please softens the command",
 "edit_hint": "added \"please\"", "probe_source": "precomputed",
 "annotator": "alice", "timestamp": 1783827299.4}
```

`holds` verdicts export with `counterfactual_label` equal to the original label —
useful as hard negatives. `unsure` verdicts are excluded.

Raw state lives under `{output_annotation_dir}/boundary/` as append-only
`probes.jsonl` and `responses.jsonl`.

## API reference

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/boundary/api/probe` | POST | session | Fetch/generate probes for (instance, schema, label) |
| `/boundary/api/respond` | POST | session | Record a verdict |
| `/boundary/dashboard` | GET | admin | Dashboard page |
| `/boundary/api/stats` | GET | admin | Dashboard aggregates |
| `/boundary/api/export` | GET | admin | Contrast-set JSONL |

## Design notes

- Probes are cached per (instance, schema, label) and shared across annotators, so
  invariance consistency is comparable between annotators.
- The probe panel is an overlay; it never blocks the main annotation flow, and probe
  answers are optional. Dismiss it with the × at any time.
- Probing currently targets one single-choice (radio) scheme per task.

## Related documentation

- [Quality Control](../workflow/quality_control.md) — attention checks and gold standards
- [AI Support](../ai-intelligence/ai_support.md) — configuring AI endpoints
- [Admin Dashboard](../administration/admin_dashboard.md) — the main admin interface
