# Solo Mode

Solo Mode enables a single annotator to efficiently label large datasets with LLM assistance through collaborative annotation.

## Overview

Solo Mode provides a streamlined workflow where a human annotator works alongside an LLM to annotate data. The system learns from human feedback, progressively improving its predictions until the human can step back and let the LLM complete the remaining annotations autonomously.

### Key Features

- **Prompt Synthesis**: Automatically generate annotation guidelines from task descriptions
- **Edge Case Testing**: Generate and label difficult examples to refine prompts
- **Parallel Annotation**: Human and LLM annotate simultaneously
- **Disagreement Resolution**: Resolve conflicts between human and LLM labels
- **Uncertainty-Based Selection**: Prioritize instances where LLM is uncertain
- **Progressive Autonomy**: Transition to autonomous LLM labeling as agreement improves
- **Final Validation**: Validate a sample of LLM-only labels

## Configuration

Enable Solo Mode in your project's `config.yaml`:

```yaml
solo_mode:
  enabled: true

  # Models for labeling (tried in order)
  labeling_models:
    - endpoint_type: "anthropic"
      model: "claude-3-5-sonnet-20241022"
      api_key: "${ANTHROPIC_API_KEY}"
    - endpoint_type: "openai"
      model: "gpt-4o-mini"
      api_key: "${OPENAI_API_KEY}"

  # Models for prompt revision
  revision_models:
    - endpoint_type: "anthropic"
      model: "claude-3-5-sonnet-20241022"

  # Uncertainty estimation strategy
  uncertainty:
    strategy: "direct_confidence"  # Options: direct_confidence, direct_uncertainty, token_entropy, sampling_diversity
    num_samples: 5                 # For sampling_diversity
    sampling_temperature: 1.0      # For sampling_diversity

  # Thresholds
  thresholds:
    end_human_annotation_agreement: 0.90    # Required agreement rate to stop human annotation
    minimum_validation_sample: 50           # Minimum comparisons before ending
    confidence_low: 0.5                     # Low confidence threshold
    confidence_high: 0.8                    # High confidence threshold
    periodic_review_interval: 100           # Review LLM labels every N instances

  # Instance selection weights (must sum to 1.0)
  instance_selection:
    low_confidence_weight: 0.4    # Prioritize uncertain instances
    diversity_weight: 0.3         # Prioritize diverse instances
    random_weight: 0.2            # Random sample for calibration
    disagreement_weight: 0.1      # Prioritize prior disagreements

  # Batch sizes
  batches:
    llm_labeling_batch: 50        # Instances to label per batch
    max_parallel_labels: 200       # Max LLM labels ahead of human

  # Prompt optimization (optional)
  prompt_optimization:
    enabled: true
    find_smallest_model: true
    target_accuracy: 0.85
```

## Workflow Phases

Solo Mode progresses through the following phases:

### 1. Setup
- Enter task description
- Upload data file
- Generate initial prompt

### 2. Prompt Review
- Review and edit the generated prompt
- Add clarifying examples
- Refine edge case handling

### 3. Edge Case Synthesis
- LLM generates difficult examples
- Examples test boundary conditions
- Helps identify prompt weaknesses

### 4. Edge Case Labeling
- Label the synthesized edge cases
- Labels used to improve prompt
- Validates prompt clarity

### 5. Prompt Validation
- LLM relabels edge cases with improved prompt
- Verify prompt improvements work
- Iterate if necessary

### 6. Parallel Annotation
- Human and LLM annotate simultaneously
- LLM labels instances in background
- Human labels prioritized instances

### 7. Disagreement Resolution
- Review instances where human and LLM disagree
- Decide on correct label
- Improve understanding of edge cases

### 8. Periodic Review
- Periodically review low-confidence LLM labels
- Approve or correct predictions
- Maintain quality during autonomous phase

### 9. Autonomous Labeling
- Agreement threshold reached
- LLM completes remaining instances
- Human monitors progress

### 10. Final Validation
- Validate sample of LLM-only labels
- Confirm quality meets standards
- Export final dataset

## Uncertainty Estimation

Solo Mode uses uncertainty estimation to prioritize which instances the human should label. Four strategies are available:

### Direct Confidence
Asks the LLM to rate its confidence (0-100). Simple and works with all models.

```yaml
uncertainty:
  strategy: "direct_confidence"
```

### Direct Uncertainty
Asks the LLM to rate its uncertainty directly. Alternative framing that may work better for some models.

```yaml
uncertainty:
  strategy: "direct_uncertainty"
```

### Token Entropy
Uses entropy of answer token probabilities. More objective but requires logprobs support (OpenAI, vLLM).

```yaml
uncertainty:
  strategy: "token_entropy"
```

### Sampling Diversity
Runs the LLM multiple times at high temperature and measures label diversity. Most accurate but expensive.

```yaml
uncertainty:
  strategy: "sampling_diversity"
  num_samples: 5
  sampling_temperature: 1.0
```

## Instance Selection

Instances are selected for human annotation using a weighted mixture:

| Pool | Weight | Description |
|------|--------|-------------|
| Low Confidence | 40% | Instances where LLM is uncertain |
| Diverse | 30% | Instances from different embedding clusters |
| Random | 20% | Random sample for calibration |
| Disagreement | 10% | Instances with prior human-LLM disagreement |

Adjust weights in config:

```yaml
instance_selection:
  low_confidence_weight: 0.4
  diversity_weight: 0.3
  random_weight: 0.2
  disagreement_weight: 0.1
```

## API Endpoints

Solo Mode provides API endpoints for monitoring and control:

### Status
```
GET /solo/api/status
```
Returns current phase, annotation stats, agreement metrics.

### Prompts
```
GET /solo/api/prompts
```
Returns prompt version history.

### Predictions
```
GET /solo/api/predictions
```
Returns all LLM predictions.

### Control
```
POST /solo/api/advance-phase
POST /solo/api/pause-labeling
POST /solo/api/resume-labeling
POST /solo/api/optimize-prompt
```

### Export
```
GET /solo/api/export
```
Exports all annotations and predictions.

## Best Practices

### Writing Good Task Descriptions

1. Be specific about what you're labeling
2. Define each label clearly
3. Explain what makes something ambiguous
4. Include examples of edge cases

### Prompt Refinement

1. Start with the generated prompt
2. Add examples for difficult cases
3. Clarify ambiguous criteria
4. Keep prompts concise but complete

### Monitoring Progress

1. Check agreement rate regularly
2. Review confusion patterns
3. Adjust prompts when accuracy drops
4. Validate LLM-only labels periodically

## Troubleshooting

### Low Agreement Rate

- Check if labels are clearly defined
- Review confusion patterns to find systematic errors
- Add examples for problematic cases
- Consider splitting ambiguous categories

### LLM Not Labeling

- Verify API credentials are correct
- Check model availability
- Review logs for errors
- Try fallback models

### Slow Performance

- Reduce batch sizes
- Use faster models for labeling
- Limit parallel labels

## Example Project

See `project-hub/simple_examples/simple-solo-mode/` for a complete working example.

## Developer Documentation

For extending Solo Mode or understanding the implementation, see the [Solo Mode Developer Guide](solo_mode_developer_guide.md).
