# Solo Mode Advanced Features

Subsystems that sit on top of the core workflow described in the [Solo Mode guide](solo_mode.md): rule discovery, labeling functions, confusion analysis, confidence routing, prompt optimization, edge-case synthesis, blind suggestions, the spend cap, the response cache, decision models, gold-set scoring, prompt sensitivity and the labeling jury. Each one can be turned off. The [configuration reference](#complete-configuration-reference) below gives each one's default; rule discovery, labeling functions, confusion analysis, the refinement loop, prompt optimization and the response cache are on unless you turn them off.

## Edge Case Rule Discovery

Inspired by the Co-DETECT framework, the edge case rule system automatically discovers annotation rules from instances where the LLM has low confidence. Rules are extracted, clustered into categories, reviewed by the human annotator, and injected back into the annotation prompt.

### From a low-confidence label to a reviewed rule

1. **Rule extraction**: When the LLM labels an instance with confidence below `confidence_threshold`, it generates a generalizable rule of the form "When \<condition\> → \<action\>".
2. **Clustering**: Once enough rules accumulate (`min_rules_for_clustering`), they are clustered by semantic similarity using sentence embeddings and K-Means. Each cluster is summarized into a single category by the LLM.
3. **Human review**: Categories are presented to the annotator for approval or rejection.
4. **Prompt injection**: Approved categories are injected into the annotation prompt, either via LLM-assisted integration or by appending an "Edge Case Guidelines" section.
5. **Re-annotation**: Instances previously labeled with low confidence under old prompts are re-annotated with the improved prompt.

### Configuration

```yaml
solo_mode:
  edge_case_rules:
    enabled: true
    confidence_threshold: 0.75
    min_rules_for_clustering: 10
    target_cluster_size: 15
    auto_extract_on_labeling: true
    reannotation_enabled: true
    reannotation_confidence_threshold: 0.60
    max_reannotations_per_instance: 2
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable/disable the edge case rule system |
| `confidence_threshold` | `0.75` | Extract rules when LLM confidence is below this value |
| `min_rules_for_clustering` | `10` | Minimum unclustered rules before triggering clustering |
| `target_cluster_size` | `15` | Target number of rules per cluster (Co-DETECT recommends 10–20) |
| `auto_extract_on_labeling` | `true` | Automatically extract rules during LLM labeling |
| `reannotation_enabled` | `true` | Re-annotate low-confidence instances after prompt updates |
| `reannotation_confidence_threshold` | `0.60` | Only re-annotate instances with confidence below this |
| `max_reannotations_per_instance` | `2` | Maximum times a single instance can be re-annotated |

### Instance Selection Weight

You can direct the instance selector to prioritize instances matching edge case rules:

```yaml
solo_mode:
  instance_selection:
    edge_case_rule_weight: 0.1  # default: 0.0
```

Increase this to route more items from edge case rule clusters to the human annotator.

---

## Labeling Functions

Inspired by ALCHEmist (NeurIPS 2024), this system extracts reusable labeling functions from high-confidence LLM predictions. These functions can label new instances via keyword matching and majority voting — without additional API calls.

### Extraction, voting, acceptance

1. **Extraction**: From predictions where the LLM reports high confidence (`min_confidence`), the system asks the LLM to identify generalizable patterns (keywords, conditions). Falls back to keyword frequency analysis if the LLM is unavailable.
2. **Application**: For each new instance, all enabled labeling functions vote on a label using confidence-weighted majority voting. A keyword matches whole words only, so "no" does not match "know".
3. **Acceptance**: If vote agreement exceeds `vote_threshold`, the label is accepted without calling the LLM. A tie between labels is never accepted. Otherwise the instance is passed through to the normal LLM labeling pipeline.

### Configuration

```yaml
solo_mode:
  labeling_functions:
    enabled: true
    min_confidence: 0.85
    min_coverage: 3
    max_functions: 50
    auto_extract: true
    vote_threshold: 0.5
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable/disable labeling functions |
| `min_confidence` | `0.85` | Minimum LLM confidence for a prediction to be used for function extraction |
| `min_coverage` | `3` | Minimum instances a pattern must match to become a function |
| `max_functions` | `50` | Maximum number of active labeling functions |
| `auto_extract` | `true` | Automatically extract functions from high-confidence predictions |
| `vote_threshold` | `0.5` | Minimum vote agreement required to accept a labeling function result |

### Cost Savings

Labeling functions are most effective when your data contains recurring patterns. The stats endpoint reports:
- **coverage**: Fraction of instances labeled by functions (avoiding LLM calls)
- **accuracy**: Agreement between function labels and human labels (when available)

---

## Confusion Analysis

Enriches the standard confusion matrix with example instances, LLM reasoning, and optional root cause analysis with guideline suggestions.

### Grouping disagreements into patterns

1. **Pattern detection**: Groups human-LLM disagreements by (predicted, actual) label pairs, filtering to pairs that occur at least `min_instances_for_pattern` times.
2. **Enrichment**: Each confusion pattern includes up to 5 example instances with the original text, LLM reasoning, and confidence score.
3. **Root cause analysis** (optional): Uses the LLM to explain why a specific confusion pattern occurs.
4. **Guideline suggestions** (optional): Uses the LLM to propose a concise guideline to disambiguate the confused labels.

### Configuration

```yaml
solo_mode:
  confusion_analysis:
    enabled: true
    min_instances_for_pattern: 3
    max_patterns: 20
    auto_suggest_guidelines: false
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable/disable confusion analysis |
| `min_instances_for_pattern` | `3` | Minimum disagreements for a label pair to be reported as a pattern |
| `max_patterns` | `20` | Maximum number of confusion patterns to report |
| `auto_suggest_guidelines` | `false` | Automatically generate LLM guideline suggestions for each pattern |

### API

```
GET /solo/api/confusion-analysis
```

Returns confusion matrix data with heatmap-ready cell values, per-label accuracy, and enriched patterns.

---

## Disagreement Explorer

Provides rich aggregated data for visual exploration of human-LLM disagreements, including scatter plots, temporal timelines, per-label breakdowns, and a filterable disagreement list.

### What the explorer reads

The explorer is read-only — it aggregates data from the validation tracker and predictions without modifying any state.

**Scatter plot**: Each compared instance is plotted as (confidence, agrees/disagrees), revealing whether high-confidence predictions tend to be correct.

**Timeline**: Comparisons are bucketed into windows (default size 10). Each bucket shows its agreement rate, and the overall trend is classified as `improving`, `declining`, or `stable` based on first-half vs. second-half agreement rate difference (>5% threshold).

**Label breakdown**: Per-label statistics including total comparisons, agreement rate, and top confused-with labels.

**Disagreement list**: Sorted by confidence descending (most surprising disagreements first), filterable by label.

### API

```
GET /solo/api/disagreement-explorer
```

Returns `scatter_points`, `disagreements`, `label_breakdown`, and `summary` data.
Accepts an optional `?label=<label>` query parameter to filter to one label.

```
GET /solo/api/disagreement-timeline
```

Returns `buckets` (per-window stats) and `trend` classification.
Accepts `?bucket_size=<N>` (clamped to [2, 100], default 10).

> Note: `GET /solo/api/disagreements` (without the `-explorer` suffix) is a
> separate, simpler endpoint that returns aggregate counts only (`total`,
> `pending`, `resolved`, `pending_ids`).

---

## Refinement Loop

Orchestrates an automated cycle of confusion analysis → guideline suggestions → prompt revision → re-annotation. Monitors agreement rate trends and stops when metrics plateau.

### One refinement cycle

1. **Trigger**: After every `trigger_interval` human annotations, the loop checks whether a refinement cycle should run.
2. **Analyze**: Runs confusion analysis on current disagreement patterns.
3. **Suggest**: For each significant confusion pattern, generates a guideline suggestion.
4. **Apply**: If `auto_apply_suggestions` is true, suggestions are applied immediately. Otherwise the cycle pauses in `awaiting_approval` status for human review.
5. **Re-annotate**: Affected instances are re-annotated with the updated prompt.
6. **Evaluate**: After re-annotation, the improvement in agreement rate is measured.

### Stop Conditions

The loop automatically stops when:
- Maximum cycles reached (`max_cycles`)
- Improvement plateaus: `patience` consecutive cycles with improvement below `min_improvement`

### Configuration

```yaml
solo_mode:
  refinement_loop:
    enabled: true
    trigger_interval: 50
    min_improvement: 0.02
    max_cycles: 5
    patience: 2
    auto_apply_suggestions: false
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable/disable the refinement loop |
| `trigger_interval` | `50` | Check for refinement every N human annotations |
| `min_improvement` | `0.02` | Minimum agreement rate improvement to count as progress |
| `max_cycles` | `5` | Maximum number of refinement cycles |
| `patience` | `2` | Consecutive cycles without improvement before stopping |
| `auto_apply_suggestions` | `false` | Apply guideline suggestions without human review |

### API

```
GET /solo/api/refinement-status
```

Returns enabled state, cycle count, running/stopped state, stop reason, patience countdown, and full cycle history.

Related refinement endpoints (all require authentication):

```
POST /solo/api/refinement/trigger     # Manually trigger a refinement cycle
GET  /solo/api/refinement/log         # Full cycle history (validated framework)
GET  /solo/api/refinement/pending     # Candidates awaiting admin approval
GET  /solo/api/refinement/strategies  # List available refinement strategies
GET  /solo/api/reannotation-report    # Before/after accuracy on re-annotated instances
```

Admin-only (require `X-API-Key`):

```
POST /solo/api/refinement/reset       # Reset refinement loop state
POST /solo/api/refinement/approve     # Apply a pending refinement candidate
POST /solo/api/refinement/reject      # Reject a pending refinement candidate
```

---

## Confidence Routing

Implements cascaded model escalation: a cheap/fast model tries first, and if its confidence is below the tier threshold, the instance escalates to a more expensive/capable model. If all tiers fail, the instance is routed to the human.

### Escalating through the tiers

For each instance:
1. The first (cheapest) tier model labels the instance.
2. If confidence ≥ tier threshold → accept the label.
3. If confidence < threshold → escalate to the next tier, keeping the best result so far.
4. If all tiers are exhausted → route to the human annotation queue.

### Configuration

```yaml
solo_mode:
  confidence_routing:
    enabled: true
    tiers:
      - name: "fast"
        model:
          endpoint_type: "openai"
          model: "gpt-4o-mini"
          api_key: "${OPENAI_API_KEY}"
        confidence_threshold: 0.85
      - name: "accurate"
        model:
          endpoint_type: "anthropic"
          model: "claude-3-5-sonnet-20241022"
          api_key: "${ANTHROPIC_API_KEY}"
        confidence_threshold: 0.70
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Enable/disable confidence routing (replaces single-model labeling) |
| `tiers` | `[]` | Ordered list of model tiers, cheapest first |
| `tiers[].name` | `""` | Human-readable tier name for stats reporting |
| `tiers[].model` | — | Model configuration (same format as `labeling_models` entries) |
| `tiers[].confidence_threshold` | `0.8` | Minimum confidence to accept a label at this tier |

### Per-Tier Statistics

The stats endpoint reports per-tier metrics:
- **instances_attempted**: Total instances routed to this tier
- **instances_accepted**: Instances where confidence met the threshold
- **instances_escalated**: Instances passed to the next tier
- **acceptance_rate**: Fraction accepted at this tier
- **avg_confidence**: Mean confidence of accepted predictions
- **avg_latency_ms**: Mean response time

Plus global stats: `total_routed` and `human_routed_count`.

### API

Per-tier and global confidence-routing stats are included in the response of
`GET /solo/api/status` under `llm_stats.confidence_routing` when routing is
enabled. There is no dedicated routing-stats endpoint.

---

## Prompt Optimizer

DSPy-style automatic prompt optimization using labeled examples. The optimizer analyzes correct and incorrect predictions to iteratively improve the annotation prompt.

### One optimization pass

1. **Collect examples**: Gathers labeled instances — both correctly and incorrectly predicted by the LLM.
2. **Optimize**: Sends the current prompt along with sample correct (up to 5) and incorrect (up to 10) examples to the LLM. The LLM returns an improved prompt with a list of changes and rationale.
3. **Validate**: Checks that the optimized prompt differs from the original and is within length limits.
4. **Apply**: Updates the annotation prompt.

Optimization can run on a timer in the background or be triggered on-demand.

### Smallest Model Search

When `find_smallest_model` is enabled, the optimizer tests available models (smallest first) against labeled examples and selects the smallest model that meets `target_accuracy`. This reduces API costs by using the cheapest sufficient model.

### Configuration

```yaml
solo_mode:
  prompt_optimization:
    enabled: true
    find_smallest_model: true
    target_accuracy: 0.85
    optimization_interval_seconds: 300
    accuracy_weight: 0.7
    length_weight: 0.2
    consistency_weight: 0.1
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Enable/disable prompt optimization |
| `find_smallest_model` | `true` | Search for the cheapest model that meets accuracy targets |
| `target_accuracy` | `0.85` | Target accuracy threshold |
| `optimization_interval_seconds` | `300` | Seconds between background optimization runs |
| `accuracy_weight` | `0.7` | Weight for accuracy in optimization scoring |
| `length_weight` | `0.2` | Weight for prompt brevity |
| `consistency_weight` | `0.1` | Weight for prediction consistency |

### API

```
POST /solo/api/optimize-prompt
```

Triggers on-demand optimization. (Requires authentication.)

Optimization history is exposed via `GET /solo/api/prompts`, which returns
the prompt version history including who/what produced each version
(`user_setup`, `manual_edit`, `prompt_optimizer`, etc.).

---

## Edge Case Synthesizer

Proactively generates synthetic edge case examples to test and refine annotation prompts before large-scale labeling begins. Unlike edge case *rules* (which are discovered reactively from low-confidence predictions), the synthesizer *creates* hypothetical boundary examples.

### Synthesis, labeling, revision

1. **Synthesis**: The LLM generates examples that lie on label boundaries, have ambiguous signals, require careful interpretation, and test specific guideline aspects.
2. **Labeling**: The human annotator labels the synthesized examples.
3. **Prompt revision**: Labeled edge cases feed into the prompt revision system, providing concrete examples of how ambiguous cases should be handled.
4. **Aspect tracking**: The system tracks which guideline aspects have been tested, helping identify gaps in prompt coverage.

### Configuration

Edge case synthesis is part of the core Solo Mode workflow (phases 3–5) and uses the `labeling_models` and `revision_models` settings. No separate configuration section is required.

### API

```
GET /solo/api/edge-cases
```

Returns all synthesized edge cases with their labeling status (counts of
total, labeled, and unlabeled cases).

Edge case synthesis runs automatically when the workflow enters the
`edge_case_synthesis` phase — there is no separate trigger endpoint.
Labeling individual edge cases happens through the `/solo/edge-cases`
page route (POST with `case_id`, `label`, and optional `notes`), not via
a dedicated REST endpoint.

---

## Blind Suggestions

By default the annotate page shows the LLM's label, its confidence and an Accept button before you answer. That is fast, and it also pulls your answer toward the suggestion. Schroeder, Roy and Kabbara (Findings of ACL 2025) found that annotators shown LLM suggestions gave different labels than annotators who were not, and that judging the LLM against those assisted labels overstated its accuracy. Solo Mode hands the rest of the corpus to the LLM when your agreement with it crosses `end_human_annotation_agreement`, so agreement measured on anchored labels can end your part of the work too early.

`solo_mode.suggestions` controls when the suggestion appears:

```yaml
solo_mode:
  suggestions:
    display: blind_sample      # before_label | after_label | blind_sample
    blind_rate: 0.2
    minimum_blind_sample: 20
```

| Option | Default | Description |
|--------|---------|-------------|
| `display` | `before_label` | `before_label` shows the suggestion before you answer, as Solo Mode always has. `after_label` never shows it first; when you and the LLM disagree, the resolution page shows its label and reasoning. `blind_sample` hides it on a `blind_rate` fraction of items and shows it on the rest |
| `blind_rate` | `0.2` | Fraction of items labelled blind under `blind_sample`. The choice of items is fixed for the study, so reloading a page or restarting the server keeps the same items blind |
| `minimum_blind_sample` | `20` | Blind comparisons needed before the handoff reads blind agreement |

Every comparison between your label and the LLM's is filed as **blind** or **shown**, by whether the suggestion was on screen when you answered. A comparison made after you labelled an item, because the LLM labelled it later, is blind unless you saw an earlier suggestion for the same item. Only your first answer for an item counts toward the split. A re-label after a disagreement happens once you have seen the LLM's label, so it changes the overall agreement rate but not the blind one.

How the handoff reads agreement:

- Once there are `minimum_blind_sample` blind comparisons, the handoff compares **blind** agreement with `end_human_annotation_agreement`.
- Before that, under `after_label` and `blind_sample`, the handoff waits, unless the corpus cannot produce enough blind items. When the blind comparisons so far plus the blind items you have not yet labelled come to fewer than `minimum_blind_sample`, the handoff reads blind agreement over the blind comparisons there are. With none, it reads all agreement. A 20-item study at `blind_rate: 0.2` can easily have only one or two blind items.
- Under `before_label` it uses all comparisons until enough blind ones exist, which is the behaviour Solo Mode had before this setting.
- `minimum_validation_sample` still applies to all comparisons in every mode.

On a blind item the annotate page says the suggestion is hidden and that you will see the LLM's label if you disagree. The dashboard's **Blind Agreement** card shows blind and shown agreement side by side, the gap between them, how often you took the suggestion with the Accept button, and which agreement the handoff is reading. A large positive gap means you agree with the LLM more often when you can see its answer. The gap is reported once each side has at least 5 comparisons.

`GET /solo/api/status` reports the same numbers under `anchoring`.

---

## AI Spend Cap

Solo Mode labels the whole corpus in the background, so it is the largest AI bill a Potato study can run up. It follows the project-wide `ai_budget` settings:

```yaml
ai_budget:
  cap_usd: 25
  prices:                       # USD per million tokens, [input, output]
    my-new-model: [0.4, 1.6]
```

- **Before labeling starts**, Solo Mode estimates the cost of labeling every item the LLM has not labelled yet. If that estimate plus what the project has already spent would pass `cap_usd`, labeling does not start, and the dashboard and `POST /solo/api/start-labeling` (HTTP 402) say why.
- **Before each batch**, the same check runs on the batch. If the batch would pass the cap, background labeling pauses.
- **After each batch**, the calls actually made are recorded. Under confidence routing each tier an item reached is charged at its own price. Under a jury, each juror that was asked is charged.

The estimate counts one labeling call per item plus the uncertainty estimator's calls: one more for `direct_confidence`, `direct_uncertainty` and `token_entropy`, and `num_samples` more for `sampling_diversity`. It counts output at `max_tokens`, so it is a ceiling rather than a quote. Labeling functions cost nothing, but the estimate does not know in advance which items they will catch.

Prices come from Potato's price table or from `ai_budget.prices`. A model with no price on record reports tokens and no dollar figure, and it never blocks a run, because there is no dollar figure to compare with the cap. Self-hosted endpoints (`vllm`, `ollama`, `huggingface`, `laya`) are priced at zero.

The dashboard's **AI Spend** card shows the running total, the cap, the tokens used and the estimate for what is left. `GET /solo/api/spend` returns the same.

---

## Response Cache

A labeling call with the same model, base URL, temperature, prompt text, item and response schema as an earlier one gets the stored reply instead of a second call. This happens when you revert to an earlier prompt version, re-run a gold-set evaluation, or restart a study from a cleared state.

```yaml
solo_mode:
  cache:
    enabled: true
```

The cache lives in `state_dir/label_cache.sqlite`, or in memory when there is no `state_dir`. It also covers the follow-up question that `direct_confidence` and `direct_uncertainty` ask. It never covers `sampling_diversity`, which needs fresh samples. Only replies that parsed into a JSON object are stored, so a truncated or malformed reply is retried next time.

The key includes the model's name but not its weights. If a provider updates a model behind an unchanged name, the cache keeps returning the old replies. Set `enabled: false` when you want to measure how much the model's answers vary from run to run.

`GET /solo/api/status` reports hits and misses under `llm_stats.cache`.

---

## Decision Models

A decision model answers a fixed-choice question in one forward pass and returns a probability for every option. It does not generate text. That makes it much faster and cheaper than an LLM at labeling, and it cannot write prompts, rules or explanations. Solo Mode supports two endpoint types for them:

| `endpoint_type` | What it talks to |
|-----------------|------------------|
| `laya` | [Laya](https://huggingface.co/convaiinnovations/laya) running inside the Potato process. Apache 2.0, about 420M parameters, runs on CPU |
| `systemone` | Any server that speaks the `/v1/systemone` API: hosted Jev, OpenJev served through vLLM with its helper, or Laya's own HTTP server |

Install Laya with `pip install 'potato-annotation[decision]'`. Its weights download from Hugging Face on first use.

The usual place for a decision model is the first tier of [confidence routing](#confidence-routing). It labels everything, and only the items it is unsure about go on to the LLM:

```yaml
solo_mode:
  labeling_models:
    - endpoint_type: laya
      model: convaiinnovations/laya
  revision_models:                     # required: decision models cannot write text
    - endpoint_type: vllm
      model: google/gemma-4-12B-it-qat-w4a16-ct
      base_url: http://localhost:8001/v1
  confidence_routing:
    enabled: true
    tiers:
      - name: laya
        confidence_threshold: 0.9
        model:
          endpoint_type: laya
          model: convaiinnovations/laya
          device: cpu
      - name: llm
        confidence_threshold: 0.5
        model:
          endpoint_type: vllm
          model: google/gemma-4-12B-it-qat-w4a16-ct
          base_url: http://localhost:8001/v1
```

`examples/advanced/solo-mode/config-decision-model.yaml` is a runnable version that also turns on blind suggestions, a gold set, the spend cap and curriculum ordering.

For a `systemone` server, set `base_url` (for example `http://localhost:8002`), `model` (`jev-latest` for hosted Jev, `openjev` for OpenJev) and, if the server needs one, `api_key`.

Limits:

- **Schemes.** Decision models label `radio`, `select`, `likert` and `slider` schemes. Solo Mode refuses to start if one is set to label `multiselect`, `span` or free-text schemes.
- **Revision models.** `revision_models` must be generative. It defaults to `labeling_models`, so a study whose only model is a decision model has to set it.
- **Not under `ai_support`.** A decision model cannot be the `ai_support` endpoint, whose assistants all write text.
- **Confidence.** The confidence is the probability the model gave its chosen option. No uncertainty estimator runs, because those ask a follow-up question. Calibration varies by domain, so set the tier threshold from your own data. Score the model on a [gold set](#gold-set-and-trials) or watch the per-tier statistics rather than trusting a vendor figure.
- **Many labels.** Laya's model card reports weak accuracy on a 77-label benchmark. When it loads, it also warns that its temperature for questions with 11 or more options is out of range and clamps it, so treat its confidence on those questions with suspicion. Prefer an LLM for schemes with many labels.

---

## Response Schema

Each labeling call sends a JSON schema built from the scheme. For `radio`, `select` and `likert` the label is one of the scheme's labels. For `multiselect` it is a list of them, and for `span` it is a list of `{text, label}` objects. When edge-case discovery is on, the schema also asks for `is_edge_case` and `edge_case_rule`. Endpoints that enforce a schema (`openai`, `vllm`, `gemini`, `ollama`, `huggingface`, `openrouter`) cannot answer outside the label set. The `anthropic` endpoint receives the schema as an instruction in the prompt instead.

Before this, the schema named only `label`, `confidence` and `reasoning`. Under vLLM's guided decoding the edge-case fields the prompt asked for never came back, so edge-case rules were never discovered during labeling.

---

## Gold Set and Trials

Two checks to run before the LLM labels the corpus.

**Gold set.** Point `solo_mode.gold` at items whose answers you know:

```yaml
solo_mode:
  gold:
    file: data/gold.jsonl    # JSON, JSONL, CSV or TSV, inside the project
    id_key: id
    label_key: label
    # text_key: text         # for gold items that are not in the corpus
```

**Score saved prompt on gold set** on the prompt page, or **Score current prompt** on the dashboard's **Gold Set** card, labels the gold items with the current prompt version in the background. The score is reported for that version: accuracy, macro F1, per-class precision and recall, and a confusion table. An item the model failed to label counts as wrong rather than being skipped. Otherwise a prompt that makes the model give up on the hard items would score higher. Macro F1 averages over the labels that appear in the gold set, so a label the model invented cannot pad it. Scores are kept for each version, so you can compare them after a revision. Gold sets score `radio`, `select`, `likert` and `multiselect` schemes.

**Trial.** **Try on 10 items** on the prompt page labels 10 unlabelled items with the prompt as it stands in the editor, without saving it. It shows each item's label, confidence and reason, the label distribution, and the estimated cost of the full run.

Both use the labeling model, the response cache and the spend cap. With confidence routing on they score `labeling_models[0]`, not the cascade.

| Endpoint | |
|----------|---|
| `GET /solo/api/gold` | Whether a gold set is configured, and each prompt version's score |
| `POST /solo/api/gold/evaluate` | Score a version (`{"prompt_version": 2}`; the current one by default). Returns a job |
| `POST /solo/api/prompt/try` | `{"n": 10, "prompt": "..."}`. Returns a job |
| `GET /solo/api/jobs/<id>` | Progress (`done` of `total`) and the result |

---

## Prompt Sensitivity

Small changes to a prompt's wording can change an LLM's labels enough to change a study's conclusions (Baumann et al., "Large Language Model Hacking", 2025). The dashboard's **Prompt Sensitivity** card measures this for your prompt:

1. The revision model writes four rewordings of the current prompt. It is told to keep the labels and criteria unchanged, and any rewording that drops a label name is discarded.
2. The labeling model labels the same 20 items under the original and each rewording. The items come from the gold set if there is one, otherwise from items you have labelled, otherwise from anywhere in the corpus.
3. The card reports the **flip rate**, the fraction of items whose label differed between wordings, and Fleiss' κ across wordings, in which each wording counts as one rater.

A high flip rate means the labels depend on wording rather than on the items. Tighten the label definitions before handing the corpus to the LLM. `POST /solo/api/sensitivity` takes `n_variants` (up to 8) and `n_items` (up to 100). `GET /solo/api/sensitivity/latest` returns the most recent run. The result lists the rewordings and the items that changed label.

---

## Labeling Jury

With a jury, several models label each item and the plurality label wins. Without one, the first labeling model that answers labels the item.

```yaml
solo_mode:
  jury:
    enabled: true
    early_stop: true
    models:
      - endpoint_type: vllm
        model: google/gemma-4-12B-it-qat-w4a16-ct
        base_url: http://localhost:8001/v1
      - endpoint_type: openai
        model: gpt-4o-mini
      - endpoint_type: laya
        model: convaiinnovations/laya
```

- **radio, select, likert:** the label with the most votes wins. A tie goes to the label whose voters reported more confidence in total, then to the first model's vote. Confidence is the winner's share of the valid votes, so three agreeing jurors give 1.0 and two of three give 0.67.
- **multiselect:** a label is kept when more than half the valid votes include it.
- **early_stop:** the remaining jurors are not asked once their votes could not change the winner. With three jurors, two that agree settle the item. Early stopping does not apply to multiselect.

A juror that errors does not vote. The stored prediction's model is `jury:<model,model,...>`, and its reasoning lists each juror's vote. A jury needs at least two models, works with `radio`, `select`, `likert` and `multiselect` schemes, and cannot be combined with confidence routing.

---

## Schema-Specific Thresholds

Solo Mode supports schema-specific agreement thresholds for annotation types where exact match is too strict. These are configured in the `thresholds` section:

```yaml
solo_mode:
  thresholds:
    # Core thresholds
    end_human_annotation_agreement: 0.90
    minimum_validation_sample: 50
    confidence_low: 0.5
    confidence_high: 0.8
    periodic_review_interval: 100

    # Schema-specific thresholds
    likert_tolerance: 1
    multiselect_jaccard_threshold: 0.5
    textbox_embedding_threshold: 0.7
    span_overlap_threshold: 0.5
```

| Option | Default | Description |
|--------|---------|-------------|
| `likert_tolerance` | `1` | Maximum allowed difference between human and LLM Likert ratings to count as agreement (e.g., tolerance of 1 means a human rating of 3 agrees with LLM ratings of 2, 3, or 4) |
| `multiselect_jaccard_threshold` | `0.5` | Minimum Jaccard similarity between human and LLM multiselect label sets to count as agreement |
| `textbox_embedding_threshold` | `0.7` | Minimum cosine similarity between human and LLM text embeddings to count as agreement |
| `span_overlap_threshold` | `0.5` | Minimum token-level overlap (IoU) between human and LLM spans to count as agreement |

---

## Instance Selection Weights

The instance selector uses a weighted mixture to choose which instances the human should annotate next. In addition to the core weights documented in the [Solo Mode guide](solo_mode.md#instance-selection), two additional weights are available for advanced features:

```yaml
solo_mode:
  instance_selection:
    low_confidence_weight: 0.3
    diversity_weight: 0.2
    random_weight: 0.2
    disagreement_weight: 0.1
    edge_case_rule_weight: 0.1
    cartography_weight: 0.1
```

| Weight | Default | Description |
|--------|---------|-------------|
| `low_confidence_weight` | `0.4` | Prioritize instances where the LLM is uncertain |
| `diversity_weight` | `0.3` | Prioritize instances from different embedding clusters |
| `random_weight` | `0.2` | Random sample for calibration |
| `disagreement_weight` | `0.1` | Show an item where you and the LLM disagreed again for re-review, once for each prompt version that labelled it. An item counts as a disagreement while any of its schemas disagrees |
| `edge_case_rule_weight` | `0.0` | Prioritize instances matching discovered edge case rules |
| `cartography_weight` | `0.0` | Prioritize instances based on dataset cartography (training dynamics) |

Weights are automatically normalized to sum to 1.0 (a warning is logged if they don't).

### Curriculum Ordering

Without a curriculum the weighted pools pick from your first item on, and the largest default weight belongs to the pool of items the LLM is least sure of. The curriculum starts you on easy items instead. Your first labels then establish agreement on the clear cases, and the hard cases come once you have a feel for the task. The idea comes from Annotation Curricula (Lee et al., *Computational Linguistics* 2022).

```yaml
solo_mode:
  instance_selection:
    curriculum:
      enabled: true
      warmup_items: 20
      ramp_items: 30
      difficulty_signal: confidence
      window: 5
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Turn curriculum ordering on |
| `warmup_items` | `20` | Your first N labels come from the easiest items |
| `ramp_items` | `30` | Over the next N labels, the target moves from the easiest item to the hardest |
| `difficulty_signal` | `confidence` | How difficulty is measured: `confidence` (one minus the LLM's lowest confidence across the item's schemas), `cartography` (how much the LLM's confidence varied across prompt versions), or `combined` (the average of whichever of the two an item has) |
| `window` | `5` | How many items near the target difficulty are candidates for each pick. The selector rotates the LLM's predicted label within this window, so a skewed dataset does not give you twenty copies of its most common class in a row. Set it to `1` for strict difficulty order |

After `warmup_items + ramp_items` labels, the weighted pools above take over. Some details:

- Only items the LLM has already labelled have a difficulty. An item with no prediction yet waits until one arrives. If nothing has been predicted, as at a cold start, the weighted pools choose instead.
- The curriculum applies to new items only. When the pools pick a re-review of an earlier disagreement, that re-review still happens. Otherwise your first disagreements would wait until the curriculum ended.
- Under confidence routing, an item's difficulty uses the lowest confidence any tier gave it. An item the first tier escalated was hard for that tier, even if the tier that accepted it reports full confidence.
- Self-reported confidence clusters near 1.0, so many items tie. Ties are broken at random rather than in data-file order.
- The curriculum's progress counts your labels, which are saved, so a restart resumes at the right stage. The label rotation is kept in memory and starts over after a restart.

`GET /solo/api/status` reports the stage in its `curriculum` field: `warmup`, `ramp` or `done`, plus your label count and the current target difficulty from 0 (easiest) to 1 (hardest).

---

## Complete Configuration Reference

Below is a comprehensive YAML configuration showing all advanced Solo Mode options with their defaults:

```yaml
solo_mode:
  enabled: true

  # LLM models for annotation labeling (tried in order)
  labeling_models:
    - endpoint_type: "anthropic"
      model: "claude-3-5-sonnet-20241022"
      api_key: "${ANTHROPIC_API_KEY}"
      max_tokens: 1000
      temperature: 0.1

  # LLM models for prompt revision (defaults to labeling_models if empty)
  revision_models:
    - endpoint_type: "anthropic"
      model: "claude-3-5-sonnet-20241022"

  # Embedding model for diversity and similarity
  embedding:
    model_name: "all-MiniLM-L6-v2"

  # Uncertainty estimation
  uncertainty:
    strategy: "direct_confidence"      # direct_confidence | direct_uncertainty | token_entropy | sampling_diversity
    num_samples: 5                     # For sampling_diversity
    sampling_temperature: 1.0          # For sampling_diversity

  # Agreement and quality thresholds
  thresholds:
    end_human_annotation_agreement: 0.90
    minimum_validation_sample: 50
    confidence_low: 0.5
    confidence_high: 0.8
    periodic_review_interval: 100
    likert_tolerance: 1
    multiselect_jaccard_threshold: 0.5
    textbox_embedding_threshold: 0.7
    span_overlap_threshold: 0.5

  # Instance selection weights (auto-normalized to sum to 1.0)
  instance_selection:
    low_confidence_weight: 0.4
    diversity_weight: 0.3
    random_weight: 0.2
    disagreement_weight: 0.1
    edge_case_rule_weight: 0.0
    cartography_weight: 0.0
    llm_predicted_weight: 0.0
    curriculum:
      enabled: false
      warmup_items: 20
      ramp_items: 30
      difficulty_signal: confidence
      window: 5

  # Batch sizes
  batches:
    llm_labeling_batch: 50
    max_parallel_labels: 200

  # Prompt optimization
  prompt_optimization:
    enabled: true
    find_smallest_model: true
    target_accuracy: 0.85
    optimization_interval_seconds: 300
    accuracy_weight: 0.7
    length_weight: 0.2
    consistency_weight: 0.1

  # Edge case rule discovery (Co-DETECT)
  edge_case_rules:
    enabled: true
    confidence_threshold: 0.75
    min_rules_for_clustering: 10
    target_cluster_size: 15
    auto_extract_on_labeling: true
    reannotation_enabled: true
    reannotation_confidence_threshold: 0.60
    max_reannotations_per_instance: 2

  # Labeling functions (ALCHEmist)
  labeling_functions:
    enabled: true
    min_confidence: 0.85
    min_coverage: 3
    max_functions: 50
    auto_extract: true
    vote_threshold: 0.5

  # Confidence routing (cascaded escalation)
  confidence_routing:
    enabled: false
    tiers: []

  # Confusion analysis
  confusion_analysis:
    enabled: true
    min_instances_for_pattern: 3
    max_patterns: 20
    auto_suggest_guidelines: false

  # Automated refinement loop
  refinement_loop:
    enabled: true
    trigger_interval: 50
    min_improvement: 0.02
    max_cycles: 5
    patience: 2
    auto_apply_suggestions: false

  # When the suggestion is shown; blind vs shown agreement
  suggestions:
    display: before_label
    blind_rate: 0.2
    minimum_blind_sample: 20

  # Reuse replies to identical labeling calls
  cache:
    enabled: true

  # Items with known answers for scoring prompt versions
  gold:
    file: null
    id_key: id
    label_key: label

  # Several models vote on each item
  jury:
    enabled: false
    early_stop: true
    models: []
```

---

## Related Documentation

- [Solo Mode](solo_mode.md) — Core workflow and getting started
- [Solo Mode Developer Guide](solo_mode_developer_guide.md) — Architecture and extension points
- [AI Support](../ai-intelligence/ai_support.md) — General AI endpoint configuration
- [Active Learning](../ai-intelligence/active_learning_guide.md) — ML-based instance prioritization (non-Solo Mode)
