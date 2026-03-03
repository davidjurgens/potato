# Solo Mode Advanced Features

This page documents advanced subsystems available in Solo Mode that go beyond the core 10-phase workflow described in the [Solo Mode guide](solo_mode.md). These features enable automated quality improvement, cost optimization, and deeper analysis of annotation patterns.

## Edge Case Rule Discovery

Inspired by the Co-DETECT framework, the edge case rule system automatically discovers annotation rules from instances where the LLM has low confidence. Rules are extracted, clustered into categories, reviewed by the human annotator, and injected back into the annotation prompt.

### How It Works

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

### How It Works

1. **Extraction**: From predictions where the LLM reports high confidence (`min_confidence`), the system asks the LLM to identify generalizable patterns (keywords, conditions). Falls back to keyword frequency analysis if the LLM is unavailable.
2. **Application**: For each new instance, all enabled labeling functions vote on a label using confidence-weighted majority voting.
3. **Acceptance**: If vote agreement exceeds `vote_threshold`, the label is accepted without calling the LLM. Otherwise the instance is passed through to the normal LLM labeling pipeline.

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

### How It Works

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
GET /solo/api/confusion
```

Returns confusion matrix data with heatmap-ready cell values, per-label accuracy, and enriched patterns.

---

## Disagreement Explorer

Provides rich aggregated data for visual exploration of human-LLM disagreements, including scatter plots, temporal timelines, per-label breakdowns, and a filterable disagreement list.

### How It Works

The explorer is read-only — it aggregates data from the validation tracker and predictions without modifying any state.

**Scatter plot**: Each compared instance is plotted as (confidence, agrees/disagrees), revealing whether high-confidence predictions tend to be correct.

**Timeline**: Comparisons are bucketed into windows (default size 10). Each bucket shows its agreement rate, and the overall trend is classified as `improving`, `declining`, or `stable` based on first-half vs. second-half agreement rate difference (>5% threshold).

**Label breakdown**: Per-label statistics including total comparisons, agreement rate, and top confused-with labels.

**Disagreement list**: Sorted by confidence descending (most surprising disagreements first), filterable by label.

### API

```
GET /solo/api/disagreements
```

Returns `scatter_points`, `disagreements`, `label_breakdown`, and `summary` data.

```
GET /solo/api/disagreements/timeline
```

Returns `buckets` (per-window stats) and `trend` classification.

---

## Refinement Loop

Orchestrates an automated cycle of confusion analysis → guideline suggestions → prompt revision → re-annotation. Monitors agreement rate trends and stops when metrics plateau.

### How It Works

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
GET /solo/api/refinement/status
```

Returns enabled state, cycle count, running/stopped state, stop reason, patience countdown, and full cycle history.

---

## Confidence Routing

Implements cascaded model escalation: a cheap/fast model tries first, and if its confidence is below the tier threshold, the instance escalates to a more expensive/capable model. If all tiers fail, the instance is routed to the human.

### How It Works

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

```
GET /solo/api/routing/stats
```

Returns per-tier and global routing statistics.

---

## Prompt Optimizer

DSPy-style automatic prompt optimization using labeled examples. The optimizer analyzes correct and incorrect predictions to iteratively improve the annotation prompt.

### How It Works

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

Triggers on-demand optimization.

```
GET /solo/api/optimization/history
```

Returns optimization history including before/after accuracy, changes made, and rationale.

---

## Edge Case Synthesizer

Proactively generates synthetic edge case examples to test and refine annotation prompts before large-scale labeling begins. Unlike edge case *rules* (which are discovered reactively from low-confidence predictions), the synthesizer *creates* hypothetical boundary examples.

### How It Works

1. **Synthesis**: The LLM generates examples that lie on label boundaries, have ambiguous signals, require careful interpretation, and test specific guideline aspects.
2. **Labeling**: The human annotator labels the synthesized examples.
3. **Prompt revision**: Labeled edge cases feed into the prompt revision system, providing concrete examples of how ambiguous cases should be handled.
4. **Aspect tracking**: The system tracks which guideline aspects have been tested, helping identify gaps in prompt coverage.

### Configuration

Edge case synthesis is part of the core Solo Mode workflow (phases 3–5) and uses the `labeling_models` and `revision_models` settings. No separate configuration section is required.

### API

```
POST /solo/api/synthesize-edge-cases
```

Generates new edge cases based on the current task description and prompt.

```
GET /solo/api/edge-cases
```

Returns all synthesized edge cases with their labeling status.

```
POST /solo/api/edge-cases/{case_id}/label
```

Records a human label for a synthesized edge case.

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
| `disagreement_weight` | `0.1` | Prioritize instances with prior human-LLM disagreement |
| `edge_case_rule_weight` | `0.0` | Prioritize instances matching discovered edge case rules |
| `cartography_weight` | `0.0` | Prioritize instances based on dataset cartography (training dynamics) |

Weights are automatically normalized to sum to 1.0 (a warning is logged if they don't).

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
```

---

## Related Documentation

- [Solo Mode](solo_mode.md) — Core workflow and getting started
- [Solo Mode Developer Guide](solo_mode_developer_guide.md) — Architecture and extension points
- [AI Support](ai_support.md) — General AI endpoint configuration
- [Active Learning](active_learning_guide.md) — ML-based instance prioritization (non-Solo Mode)
