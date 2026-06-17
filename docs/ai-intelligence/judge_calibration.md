# Judge Calibration

Judge Calibration is a lightweight workflow for **auto-labeling data with one or
more LLM judges and calibrating them against human ground truth**. You write a
judge prompt, pick the LLMs (local via Ollama/vLLM, or API-based like
OpenAI/Anthropic/Gemini), and Potato samples each model *k* times over your data.
You then **blind**-label a sample (without seeing the LLM answers) and Potato
produces a report: per-LLM accuracy, inter-annotator agreement (human↔LLM and
LLM↔LLM), calibration (ECE + reliability), and confusion matrices — plus a file
of every LLM's labels on your data.

It is a deliberately simpler cousin of [Solo Mode](../solo-mode/solo_mode.md)
(no prompt-refinement loops, edge-case synthesis, or disagreement UI) and is
distinct from [Judge Alignment](../agent-evaluation/judge_alignment.md), which
calibrates a *single* judge with self-reported confidence and shows suggestions
inline. Judge Calibration uses **multiple** judges, **empirical** confidence
(the vote fraction across the *k* samples), and keeps the human strictly blind.

## How it works

```
SETUP → GENERATING → HUMAN_CALIBRATION → REPORT → COMPLETED
```

1. **GENERATING** — each model is queried *k* times per item. The modal label is
   the prediction; the fraction of the *k* samples agreeing with it is the
   confidence. Results are written to a dedicated store (never mixed into the
   annotation data, so humans can't see them).
2. **HUMAN_CALIBRATION** — Potato draws a sample of the labeled items (random /
   stratified) and one or more humans blind-label them through the normal
   `/annotate` interface.
3. **REPORT** — metrics are computed over the human∩LLM overlap and written to
   the output directory.

## Quick start

```bash
python potato/flask_server.py start examples/ai-assisted/judge-calibration/config.yaml -p 8000 --debug
```

- Open `http://localhost:8000/judge_calibration/admin` to configure and run.
- Watch progress; when generation finishes, blind-label the sample at
  `http://localhost:8000/annotate`.
- Click **Build report**, then open `http://localhost:8000/judge_calibration/report`.

The example uses a local Ollama model, so no API key is required (start Ollama and
`ollama pull llama3.2:3b` first).

## Configuration

```yaml
judge_calibration:
  enabled: true
  prompt: |                       # supports {text}, {labels}, {description}
    You are an impartial expert annotator. Classify the sentiment as exactly
    one of: positive, negative, neutral.
  models:
    - endpoint_type: openai        # openai|anthropic|ollama|vllm|gemini|openrouter|huggingface
      model: gpt-4o-mini
      api_key: ${OPENAI_API_KEY}   # env-var expansion supported
      temperature: 0.7             # MUST be > 0 so the k samples vary
    - endpoint_type: ollama
      model: llama3.1:8b
      base_url: http://localhost:11434
      temperature: 0.7
  k_samples: 5                     # samples per model per item
  max_items: 1000                  # cap on items the LLMs label (null = all)
  fraction: null                   # alternative to max_items (0 < f <= 1)
  sampling:
    strategy: stratified           # random | stratified | all
    stratify_by: null              # item-data field; null = stratify by modal LLM label
    sample_size: 200               # how many items humans blind-label
    seed: 42
  human:
    num_raters: 1                  # 1 = solo researcher; N adds human↔human IAA
    gold: single                   # single | majority (majority across humans)
  schemas: [sentiment]             # annotation_scheme names to evaluate ([] = all)
  calibration:
    n_bins: 10                     # ECE / reliability-diagram bins
  output:
    dir: judge_calibration_output
    files:
      labels: llm_labels.jsonl
      report_json: report.json
      report_html: report.html
  state_dir: judge_calibration_state
```

You can also override most of these interactively in the admin wizard and re-run.

### Supported annotation types

| Type | Status | Metrics |
|------|--------|---------|
| `radio` / `select` | ✅ | accuracy, P/R/F1, Cohen/Fleiss κ, Krippendorff α (nominal), ECE, confusion |
| `likert` | ✅ | the above + MAE + Krippendorff α (interval/ordinal) |
| `multiselect` | ✅ | per-label P/R/F1, mean Jaccard, exact-match accuracy + calibration |
| `span` | ⚠️ experimental | IoU-matched P/R/F1, mean IoU, span-F1 agreement, span-level calibration |

### Span calibration (experimental)

For `span` schemas the judge returns character-offset spans `{start, end, label}`.
Across the *k* samples, spans are **clustered** (same label + IoU ≥ 0.5); a
cluster's confidence is the fraction of samples that produced it, and clusters
below 0.5 confidence are dropped. Metrics use **IoU matching** (a predicted span
matches a gold span when their label is equal and IoU ≥ 0.5): per-model
precision/recall/F1, mean IoU of matched spans, and span-level calibration
(confidence = the span's cluster confidence; correct = whether it matched gold).
Span gold uses a single human (majority-gold falls back to single for spans).
The clustering and matching are heuristic — treat span numbers as directional.

**Span agreement (three complementary metrics).** Span-F1 is intuitive but
*not* chance-corrected, so the report also gives two chance-corrected measures:

- **Span F1** — mean pairwise IoU-matched F1 across raters (human↔LLM / LLM↔LLM /
  human↔human). Familiar (NER/brat-style), but not corrected for chance.
- **Token κ / Krippendorff α** — each instance is cut at every span boundary any
  annotator drew; each atomic segment gets that annotator's label (or `O`), then
  ordinary Cohen/Fleiss κ and Krippendorff α (nominal) run over the segments.
  Chance-corrected and reuses Potato's `agreement.py`. Caveat: `O` segments can
  inflate agreement; only segments inside annotated regions are counted, which
  limits but doesn't remove this.
- **γ (Gamma, approximate)** — a self-contained, dependency-free reimplementation
  of the *core ideas* of Mathet et al. (2015): γ = 1 − observed/expected disorder,
  where disorder is the best-alignment dissimilarity between two annotators' spans
  (positional + categorical) and the expected baseline comes from randomly
  relocated "chance" annotators. It is computed **pairwise** (then averaged) using
  a Hungarian alignment, **not** the full multi-annotator continuum solver — so it
  approximates, and is not bit-exact with, the canonical
  [`pygamma-agreement`](https://github.com/bootphon/pygamma-agreement) package. Use
  that package if you need the peer-reviewed implementation.

## Metrics in the report

- **Accuracy / Precision / Recall / F1** — each LLM vs the human gold label.
- **Cohen's κ (pairwise)** — partitioned into human↔LLM, LLM↔LLM, human↔human.
- **Fleiss' κ** and **Krippendorff's α** — across all raters (humans + each LLM).
- **ECE** (Expected Calibration Error) + **reliability bins** + **Brier score** —
  how well the vote-fraction confidence tracks correctness.
- **Confusion matrix** — per LLM, vs the human gold.
- For likert: **MAE**. For multiselect: **mean Jaccard** and **exact-match accuracy**.

## Output files

Written under `output.dir`:

- **`llm_labels.jsonl`** — one line per (model, item, schema): `modal_label`,
  `confidence`, `k`, and the raw `samples`. Covers every labeled item.
- **`report.json`** — the full structured metrics report.
- **`report.html`** — a human-readable summary.

## Caveats

- **Set `temperature > 0`.** With `k_samples > 1` and temperature 0 the samples are
  identical, so confidence is always 1.0 and the calibration report is
  meaningless. A startup warning is emitted in this case.
- **Blindness is structural.** LLM labels live entirely in a separate store and are
  never injected into the annotation UI, so annotators cannot see them.
- **Metrics use the overlap.** Numbers are computed over items that both the LLMs
  and the human(s) labeled (restricted to the calibration sample when one was
  drawn). Items only one side labeled are excluded.
- **Span support is experimental** — its clustering/IoU heuristics (see above)
  are directional, not exact.

## Admin endpoints

All require an admin API key (`X-API-Key` header; bypassed in `--debug`):

| Endpoint | Purpose |
|----------|---------|
| `GET /judge_calibration/admin` | Setup wizard |
| `POST /judge_calibration/run` | Apply overrides + start generation |
| `GET /judge_calibration/progress` | Live progress (JSON) |
| `POST /judge_calibration/report` | Build the report |
| `GET /judge_calibration/report` | View the HTML report |

## Related

- [Judge Alignment](../agent-evaluation/judge_alignment.md) — single-judge inline calibration
- [Solo Mode](../solo-mode/solo_mode.md) — full human-LLM collaborative labeling
- [AI Support](ai_support.md) — per-item AI label suggestions
