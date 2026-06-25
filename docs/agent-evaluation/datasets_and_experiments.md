# Datasets & Experiments

Potato's evaluation backbone: **versioned datasets** of evaluation examples and
**experiments** that score outputs against them with programmatic
[evaluators](evaluators.md). Together they turn Potato from "annotate once" into
"evaluate continuously" — curate a test set, run evaluators, and track scores
across prompt/model versions over time.

## Enabling

```yaml
datasets:
  enabled: true
  storage: file   # "file" (default) | "sqlite"
```

`storage` selects the backend:

- **`file`** — git-diffable JSONL snapshots under
  `<output_annotation_dir>/eval_store/datasets/`. The default.
- **`sqlite`** — a single `<output_annotation_dir>/eval_store/datasets.sqlite`,
  for large dataset/experiment counts and faster queries.

When enabled, the admin dashboard shows a **Datasets & Experiments** link in its
header.

## Datasets

A **dataset** is a named collection of **examples**:

| Field | Meaning |
|-------|---------|
| `id` | Unique example id |
| `inputs` | The task input (prompt, trace, question) |
| `reference_outputs` | Optional gold output / reference trajectory |
| `metadata` | Arbitrary extra fields (e.g. `outputs`, `rejected`, source) |
| `split` | `test` (default), `train`, … |

### Versioning

Every add/update/delete creates a new **immutable version** (`v0001`, `v0002`,
…). Versions can be **tagged** (e.g. `prod`), and reads can pin a version with
`as_of`:

- `as_of=latest` (default) — newest version
- `as_of=prod` — the version carrying the `prod` tag
- `as_of=v0002` — an explicit version id

A tag points to exactly one version; re-tagging moves it.

### Curating examples

- **From the live task** — *Import loaded instances* (or `POST .../import_instances`)
  turns the task's loaded instances into examples.
- **From ingested traces only** — *Import ingested traces* (or `POST .../import_traces`)
  imports just the runtime-ingested traces (webhook / LangSmith / Langfuse),
  optionally filtered to one `source`.
- **With human annotations as references** — tick *include human annotations as
  references* (or pass `include_annotations: true`). The aggregated human
  annotation per scheme becomes each example's `reference_outputs`. Two methods
  (`aggregation_method`):
    - `majority` (default) — exact-match majority vote; vote counts + agreement
      recorded in metadata.
    - `dawid_skene` — **worker-reliability-weighted consensus**. Dawid-Skene
      jointly estimates each annotator's reliability (via EM over their confusion
      matrices) and re-weights votes accordingly, so a careful annotator outvotes
      a careless one and you get a per-example confidence. This is the standard
      upgrade over majority vote for noisy crowds; per-annotator reliability and
      per-example confidence are recorded in metadata. (See
      `potato/server_utils/consensus.py`.)
- **Via the API** — add examples directly (see below).
- Otherwise reference outputs can be added later, or scored against `metadata['outputs']`.

## Experiments

An **experiment** runs one or more evaluators against a dataset version and
records per-example results plus aggregate scores. Pick a dataset and evaluators
on the overview page and click **Run**, or `POST .../experiments/run`.

The flagship agent evaluators (`trajectory_match`, `tool_use`,
`tool_call_accuracy`, `llm_trajectory_judge`) appear first in the picker. See
[Evaluators](evaluators.md) for the full list and semantics.

> LLM-judge evaluators call your configured `ai_support` endpoint and may take a
> while on large datasets.

### Comparing experiments

Select two or more experiments and **Compare** to see aggregate scores side by
side. The first is the baseline; deltas and the best value per metric are
highlighted so regressions stand out.

Each delta is annotated with a **paired-bootstrap significance** badge and a 95%
confidence interval, computed per-example against the baseline (aligned by
`example_id`). A change is flagged **significant** only when its CI excludes 0 —
so a +0.02 that's really noise reads as **n.s.**, while a decisive gain reads as
**significant**. This is the same statistics layer
(`potato/server_utils/eval_stats.py`: bootstrap CIs, Wilson intervals for
win-rates, paired significance) used by the [Model Arena](model_arena.md)
leaderboard, so error bars and significance are consistent across the suite.

## Export to fine-tuning data

Any dataset version exports to JSONL for fine-tuning, reusing the same record
shapes as the [trajectory correction](trajectory_correction.md) exporter:

- **SFT** — `{"prompt": <inputs>, "completion": <reference_outputs>}`
  (examples without `reference_outputs` are skipped).
- **DPO** — `{"prompt": <inputs>, "chosen": <reference_outputs>, "rejected": <metadata.rejected | metadata.outputs>}`
  (examples without both are skipped).

Use the *Export SFT* / *Export DPO* buttons on the dataset detail page, or:

```bash
curl -OJ "http://localhost:8000/datasets/api/datasets/agent-eval-v1/export?format=sft"
```

The `X-Skipped-Examples` response header reports how many examples were skipped.

## Reward data & the eval→improve loop

Beyond SFT/DPO, the suite turns evaluations into **reward-model data** and closes
the loop to prompt improvement — each step human-grounded:

- **Rubrics-as-Rewards (E9)** — `GET /datasets/api/experiments/<id>/export_rewards`
  converts an experiment's [rubric-DAG](evaluators.md) / [agent-as-judge](evaluators.md)
  results into **criterion-level reward rows** (`{prompt, response, reward, criteria}`)
  for RM/RLVR training in non-verifiable domains. (`server_utils/rubric_reward.py`.)
- **Active preference sampling (E10)** — `GET /admin/arena/api/suggest_pairs?strategy=uncertainty`
  ranks which response pairs to label next by how *informative* the comparison is
  (closest Bradley-Terry scores first), with an honest `random` baseline.
  (`server_utils/active_preference.py`.)
- **Metric induction (E11)** — `GET /admin/api/induce-metrics?schema=<free-text scheme>`
  mines recurring evaluation metrics from annotators' free-text comments (AutoLibra-
  style) and proposes candidates for a human to confirm into a rubric.
  (`server_utils/metric_induction.py`.)
- **Eval→improve export (E12)** — `GET /datasets/api/datasets/<name>/optimize_export?fmt=gepa`
  exports a curated dataset as a GEPA/DSPy optimization trainset; the optimizer
  proposes a prompt rewrite, surfaced as a `PromptDiff` a human **approves or
  rejects** before it ships (the optimizer never silently changes the prompt).
  (`server_utils/prompt_optimization.py`.)

## API reference

All endpoints require admin auth (`X-API-Key` header or admin session).

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/datasets/api/datasets` | List datasets |
| POST | `/datasets/api/datasets` | Create a dataset |
| GET | `/datasets/api/datasets/<name>` | Dataset detail (versions) |
| DELETE | `/datasets/api/datasets/<name>` | Delete a dataset |
| GET | `/datasets/api/datasets/<name>/examples` | List examples (`as_of`, `splits`) |
| POST | `/datasets/api/datasets/<name>/examples` | Add examples (new version) |
| POST | `/datasets/api/datasets/<name>/tag` | Tag a version |
| GET | `/datasets/api/datasets/<name>/export?format=sft\|dpo` | Export JSONL |
| POST | `/datasets/api/datasets/<name>/import_instances` | Curate from loaded instances (`include_annotations`) |
| POST | `/datasets/api/datasets/<name>/import_traces` | Curate from ingested traces (`source`, `include_annotations`) |
| POST | `/datasets/api/experiments/run` | Run an experiment |
| GET | `/datasets/api/experiments` | List experiments (summaries) |
| GET | `/datasets/api/experiments/<id>` | Experiment detail |

### Inspecting & controlling the annotation process

The eval-admin API (`/admin/eval/...`, admin-only) inspects and controls the
annotation process for these tasks — surfaced as the **Annotation process** panel
on the overview page:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/eval/status` | Overview: datasets, experiments, annotation progress, ingested-trace counts, assignment state |
| GET | `/admin/eval/progress` | Per-instance annotation status (source, #annotators, saturated, triage priority) |
| GET | `/admin/eval/ingested_traces` | Runtime-ingested traces with source breakdown |
| POST | `/admin/eval/assignment` | `{action: "pause"\|"resume"}` — freeze/resume new assignments (existing assignments untouched) |

For full inter-annotator agreement use [`/admin/iaa`](../admin_dashboard.md); for
per-annotator timing use `/admin/api/annotators`.

### Example

```bash
curl -X POST http://localhost:8000/datasets/api/datasets \
  -H "Content-Type: application/json" \
  -d '{"name": "agent-eval-v1", "description": "Tool-use correctness"}'

curl -X POST http://localhost:8000/datasets/api/experiments/run \
  -H "Content-Type: application/json" \
  -d '{"dataset": "agent-eval-v1",
       "evaluators": [{"name": "trajectory_match", "params": {"mode": "unordered"}}]}'
```

## Example project

`examples/agent-traces/experiments/` is a runnable demo:

```bash
python potato/flask_server.py start examples/agent-traces/experiments/config.yaml -p 8000
```

## Related

- [Programmatic evaluators](evaluators.md)
- [Trajectory correction → SFT/DPO](trajectory_correction.md)
- [Triage queue](triage_queue.md)
