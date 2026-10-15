# Labeling engine configuration

Everything the engine does is set in one `labeling_engine` block. An invalid
block stops the server at boot and lists every problem at once. To have
annotators served the engine's requests, also set
`assignment_strategy: engine`; that strategy without an enabled engine is a
validation error.

```yaml
assignment_strategy: engine

labeling_engine:
  enabled: true
  schemas: [sentiment]            # default: every scheme a source can label
  sources: [...]
  cascade: [laya, gemma]          # default: the first source alone
  contracts: [...]
  humans: {...}
  crowd: {...}
  budgets: {...}
  runtime: {...}
  features: {...}
  redaction: {...}
  distill: {...}
```

## Top-level keys

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Turn the engine on. An enabled engine needs at least one source. |
| `schemas` | all | The annotation schemes the engine labels. Under `assignment_strategy: engine`, a scheme left out is answered only on the items the engine sends to people for its own schemes, not on every item; validation warns about it. A scheme no source can label (free text, for one) cannot be in the engine, so under this strategy it is never answered on every item; use another assignment strategy if it must be. |
| `sources` | `[]` | The models. See [Sources](#sources). |
| `cascade` | first source | Source ids in the order they are tried. People come after the last. |
| `contracts` | `[]` | What the labels must satisfy. See [Contracts](contracts.md). |

## Sources

Every source has an `id` (unique) and a `kind`. Unknown keys are an error.

| Key | Default | Meaning |
|---|---|---|
| `id` | required | Name used in `cascade`, the call log and the certificate. |
| `kind` | required | One of `llm`, `vlm`, `decision`, `detector`, `judge`, `jury`, `trained`, `static`, `fixture`, `asr`, `lf`, `simulator`. |
| `endpoint_type` | required for `llm`, `vlm`, `decision`, `judge` | The AI endpoint (`vllm`, `openai`, `anthropic`, `gemini`, `ollama`, `openrouter`, `openai_vision`, `ollama_vision`, `laya`, `systemone`, ...). `detector` defaults to `yolo`. |
| `model` | endpoint default | Model name. |
| `base_url` | none | Server URL for self-hosted or OpenAI-compatible endpoints. |
| `api_key` | none | Never hashed into a version and never exported. `${ENV_VAR}` is substituted. |
| `temperature` | `0.0` | 0 to 2. |
| `max_tokens` | `256` | Output token limit per call. |
| `timeout` | endpoint default | Seconds per call. |
| `prompt` | built from the scheme | Prompt template. Changing it makes a new source version. |
| `confidence` | `{method: auto}` | How the source states confidence. See below. |
| `concurrency` | `runtime.concurrency` | Parallel calls to this source. |
| `schemas` | all engine schemes | Restrict the source to these schemes. |
| `options` | `{}` | Kind-specific options, listed below. |
| `judge` | `{}` | `judge` only: the same options as `options`, under their own key; `options` wins where both set one. |
| `members` | none | `jury` only: at least two other source ids. |
| `aggregation` | `plurality` | `jury` only. Plurality is the one rule. |
| `field` / `predictions_file` | none | `static` only: where the existing labels are. The field holds `{scheme: label}`, or a bare label when the source labels one scheme. A field of the wrong shape on every item fails the run with a message naming it. |
| `error_rate`, `seed` | | `fixture` only: a synthetic source with a known error rate, for tests. |
| `revision` | none | A model revision to record in the version (for example a checkpoint hash). |

Everything that can change an answer (model, prompt, temperature, options)
goes into the source's version hash. A new version makes every contract that
depends on the source `stale`.

An answer that is not a value the scheme can hold (a label not in its list, a
number field that is not a number, a list on a one-of-N scheme) is recorded
as an error, never as a label, and the run's message counts them. An item
whose calls fail is asked again on later runs, at most three times per
source version; after that it waits for a changed source (a fixed key or
prompt is a new version). A run in which a source fails does not stop the
other tiers: the next tier labels every item, and `potato label run` exits
with status 1 and names the source.

### Confidence methods

| `confidence.method` | Applies to | What it does |
|---|---|---|
| `verbalized` | `llm`, `vlm`, `judge` | The model states 0-100 in its reply. One call; the least reliable. |
| `k_sample` | `llm` | `samples` replies (default 5) at `sample_temperature` (default 0.7). The label is the most common answer; confidence is its share. Costs k calls. |
| `logprob` | `llm` | Labels are lettered and the model answers with one letter. Confidence is read from the first token's probabilities. One call, usually the best calibrated. Needs a backend that returns logprobs (vLLM, OpenAI-compatible) and at most 20 labels; a scheme with more is a validation error. |
| `native` | `decision`, `detector`, `trained` | The model's own probabilities. Not available on an `llm` source (a validation error). |
| `auto` | all | `native` where the source has it, otherwise `verbalized`. |

### Kind-specific options

- **`decision`** (Laya in-process, or any `/v1/systemone` server such as hosted
  Jev or OpenJev): one forward pass returns a probability for every option.
  Works on `radio`, `select`, `likert` and `slider` schemes. `endpoint_type`
  must be `laya` or `systemone`, and `systemone` needs `base_url` (the
  server root; a URL ending in `/v1/systemone` is accepted too). The state is
  sent as `{"text": ...}` in both cases, so one checkpoint gives the same
  answers in-process and behind `laya-serve`; `options: {state_key: ""}`
  sends the bare string instead. On rating scales (`likert`, `slider`) Laya's
  scores can barely follow the scale: check a few items before relying on
  it.
- **`detector`** (`image_annotation`): `keep_threshold` (0.35), boxes at or
  above it are the prediction; `candidate_threshold` (0.05), boxes between the
  two lower the image's confidence; `label_map`, detector class to scheme
  label (unmapped classes are ignored); `image_field`, the item field with the
  image path or URL. Paths resolve as the annotation page resolves them:
  `/media/x.jpg` under the task's `media_directory`, a relative path under
  `task_dir`.
- **`judge`**: `rubric` (default: the scheme's description), `fields` (item
  fields shown to the judge, in order), `swap_order` (ask twice with the label
  order reversed; a verdict that flips becomes an abstention). On agent-trace
  schemes (`process_reward`, `trajectory_eval`, ...) the judge labels each
  step.
- **`vlm`**: a vision endpoint (`openai_vision`, `anthropic_vision`,
  `ollama_vision`); for a self-hosted model behind an OpenAI-compatible
  server, use `openai_vision` with `base_url`.
- **`trained`**: `artifact_dir`, `trainer` (default `sklearn-text`), `run_id`.
  Usually created by distillation rather than written by hand.

## humans

| Key | Default | Meaning |
|---|---|---|
| `pools` | `[team]` | Who labels: `team`, `crowd`, `solo`. |
| `calibration_rate` | `auto` | Share of items sampled for blind calibration. `auto` picks a rate from the contracts' projections: enough labels per class to be testable, at most half of a small study and a fifth of one over 1,000 items. |
| `dev_fraction` | `0.5` | Share of calibration labels used to choose thresholds; the rest test them. |
| `min_calibration_per_class` | `10` | Floor per class before per-class contracts are tested. |
| `audit_rate` | `0.02` | Share of newly accepted machine labels sent back to people, blind, to watch for drift. |
| `overlap` | `0.0` | Share of calibration items labeled by several people. |
| `overlap_k` | `3` | People per overlap item. The `no_worse_than_human` contract needs 3. |
| `distribution_k` | `5` | People per item for `distributional` contracts. |
| `truth` | `majority` | How several people's labels on one item become the label contracts test against: `majority` or `dawid_skene`. |
| `verify_visibility` | `shown` | Whether a verify request shows the machine's answer (`shown`) or not (`blind`). |

## crowd

Used when `crowd` is in `humans.pools`. Only Prolific can be driven by the
engine.

| Key | Default | Meaning |
|---|---|---|
| `provider` | `prolific` | |
| `study_id` | none | The Prolific study to resize. |
| `reward_usd` | none | Reward per place, for cost projections. |
| `per_worker_quota` | `20` | Requests per worker; places are `ceil(open requests / quota)`. |

Crowd recruiting is a dry run by default: the planner reports what it would
do. Spending money needs `features.crowd_live_spend: true` and a
`budgets.human_usd` cap; without both the config is rejected.

## budgets

| Key | Meaning |
|---|---|
| `model_usd` | Stop calling priced models once this much is spent. Each call reserves its projected cost first. Models with no price (and self-hosted models on `localhost`) are not limited by it. |
| `human_usd` | Ceiling on crowd spend. Required for live crowd spend. |
| `human_labels` | Maximum human requests the engine may open, counted when each request is opened. |

## runtime

| Key | Default | Meaning |
|---|---|---|
| `batch_size` | `32` | Items per committed chunk. A killed run resumes at the next chunk without repeating calls. |
| `concurrency` | `4` | Parallel calls per source (overridden by a source's own `concurrency`). |
| `cache` | `true` | Reuse replies to identical requests from the same source version. |
| `retries` | `2` | Extra attempts after a timeout, connection error, 429 or 5xx. Every attempt is logged. |
| `planner_interval` | `30` | Seconds between planner passes in the server. |
| `hold_minutes` | `60` | Minutes a person may hold a request without answering before it goes back to the pool. The item also leaves their page, so a tab left open cannot answer it later. |

## features

All off by default except `drift`.

| Key | What it turns on |
|---|---|
| `drift` | On by default. Act on audit results: when audits show the accepted labels' error rate is above target, the contract reads `violated`, machine labels on that scheme are no longer accepted, and fresh calibration labels are drawn. Each certification starts a new audit sequence, so certifying again after a fix restores acceptance. Set it to `false` to report a breach only; the contract then reads "met, audits breached". |
| `distill` | Train a model on the study's labels and put it first in the cascade (see `distill` below). |
| `optimize` | Have each planner pass score every subset of the cascade on dev labels and report the cheapest one that keeps the contracts' coverage (`GET /api/engine/v1/schemes/<name>/optimize`). Nothing is applied; adopting a cascade is a config change and a new certification. |
| `crowd_recruit` | Let the planner size the Prolific study (dry run unless `crowd_live_spend`). |
| `crowd_live_spend` | Actually change the Prolific study. Needs the `crowd` pool and `budgets.human_usd`. |
| `pii_redaction` | Mask emails, URLs, IP addresses, card numbers, SSNs, phone numbers and @handles before text goes to a third-party API. The call log records what was masked as categories and hashes, never the text. |
| `payload_capture` | Keep full prompts and replies under `<task_dir>/engine_payloads/`. Off by default; the call log keeps hashes only. |

## redaction

`categories`: which of `email`, `url`, `ip`, `card`, `ssn`, `phone`, `handle`
to mask (default: all). Applies only with `features.pii_redaction`, and only
to third-party APIs. Self-hosted endpoint types (`vllm`, `ollama`, `laya`,
`yolo`, ...) are not masked wherever they run, and neither is any endpoint
whose `base_url` is on this machine.

## distill

With `features.distill` on:

| Key | Default | Meaning |
|---|---|---|
| `trainer` | `sklearn-text` | A trainer from `potato/training`. |
| `min_labels` | `200` | Train only once this many labels exist. |
| `include_silver` | `true` | Also train on machine labels a contract certified (marked silver). |
| `every` | `2.0` | Retrain when the label count has grown by this factor. |
| `modality` | `auto` | `text`, `image`, or `auto`: image when most items name an image file (`.jpg`, `.png`, ...). |
| `image_field` | the text key | The item field holding the image, when it is not the field the page shows. |

On an image study the distilled model is an image classifier: `sklearn-text`
fits a classifier over CLIP embeddings (`clip-ViT-B-32`) of each image file,
where a text model would have read only the image's URL. That needs
`sentence-transformers` and `pillow` (`pip install sentence-transformers
pillow`); without them distillation logs the install hint and the cascade
stays as configured. Images must be stored locally (under `media_directory`,
or a path relative to `task_dir`): remote URLs are not downloaded, so items
that point at another host are left out of training and the distilled tier
gives them no label, which sends them on to the next tier.

Items in the cert and audit splits never go into the training set.

## Validation

`potato validate config.yaml` checks the block with the rest of the config.
Errors name the key: `labeling_engine.sources[1].kind must be one of ...`,
`labeling_engine.contracts[0].error is required for selective_risk`.
Validation also refuses:

- a contract key the contract kind does not read (a typo of `error`, say);
- a contract on a scheme no cascade source can label, with each source's
  reason;
- a contract on a scheme the engine cannot score (free text, pairwise);
- a `decision` source whose `endpoint_type` is not a decision model, and an
  `llm`, `vlm` or `judge` source whose is;
- `no_worse_than_human` with `humans.overlap_k` below 3.

It warns when `budgets.human_labels` is too small to certify a
`selective_risk` contract even if every machine answer were right.

## Related documentation

- [Overview](overview.md)
- [Contracts](contracts.md)
- [Command line, API and SDK](cli-and-api.md)
- [AI endpoints](../ai-intelligence/ai_support.md)
