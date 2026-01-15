# AI-Assisted In-Context Learning (ICL) Labeling

Potato's ICL labeling feature enables AI-assisted annotation by using high-confidence human annotations as in-context examples to guide an LLM in labeling remaining data. The system tracks LLM confidence and routes some predictions back to humans for verification, enabling accuracy assessment and iterative improvement.

## Overview

The ICL labeling system:

1. **Collects High-Confidence Examples**: Identifies instances where annotators agree (e.g., 80%+ agreement)
2. **Labels with LLM**: Uses examples to prompt an LLM for labeling unlabeled instances
3. **Tracks Confidence**: Records LLM confidence scores for each prediction
4. **Verifies Accuracy**: Routes a sample of LLM-labeled instances to humans for blind verification
5. **Reports Metrics**: Calculates and displays LLM accuracy based on verification results

## Features

### Automatic Example Collection

The system automatically identifies high-confidence examples where multiple annotators agree:

- Configurable agreement threshold (default: 80%)
- Minimum annotator count requirement (default: 2)
- Automatic refresh on configurable interval
- Per-schema example pools

### LLM Labeling with Limits

To enable iterative improvement rather than bulk labeling:

- **Max total labels**: Limit the total number of LLM predictions
- **Max unlabeled ratio**: Only label a percentage of remaining data (e.g., 50%)
- **Pause on low accuracy**: Automatically pause if accuracy drops below threshold
- Batch processing with configurable intervals

### Blind Verification

Verification uses "blind labeling" - annotators see the instance as a normal task without knowing the LLM's prediction. This ensures unbiased accuracy assessment:

- Configurable sample rate (default: 20% of LLM labels)
- Multiple selection strategies: low_confidence, random, mixed
- Verification tasks mixed naturally with regular assignments

## Configuration

ICL labeling requires `ai_support` to be enabled (reuses that endpoint configuration):

```yaml
# AI endpoint configuration (required)
ai_support:
  enabled: true
  endpoint_type: "openai"  # or "anthropic", "ollama", etc.
  ai_config:
    model: "gpt-4o-mini"
    api_key: "${OPENAI_API_KEY}"

# ICL labeling configuration
icl_labeling:
  enabled: true

  # Example selection settings
  example_selection:
    min_agreement_threshold: 0.8      # 80% annotators must agree
    min_annotators_per_instance: 2    # Minimum annotations for consensus
    max_examples_per_schema: 10       # Max examples per schema in prompt
    refresh_interval_seconds: 300     # How often to refresh examples (5 min)

  # LLM labeling settings
  llm_labeling:
    batch_size: 20                    # Max instances per batch
    trigger_threshold: 5              # Min examples before LLM labeling starts
    confidence_threshold: 0.7         # Min confidence to accept prediction
    batch_interval_seconds: 600       # Time between batch runs (10 min)

    # Limits to prevent labeling entire dataset at once
    max_total_labels: 100             # Max instances to label total (null for unlimited)
    max_unlabeled_ratio: 0.5          # Max portion of unlabeled to label (50%)
    pause_on_low_accuracy: true       # Pause labeling if accuracy drops
    min_accuracy_threshold: 0.7       # Accuracy threshold for pausing (70%)

  # Human verification settings
  verification:
    enabled: true
    sample_rate: 0.2                  # 20% of LLM labels verified
    selection_strategy: "low_confidence"  # Options: "low_confidence", "random", "mixed"
    mix_with_regular_assignments: true
    assignment_mix_rate: 0.2          # 20% chance of getting verification task

  # Persistence settings
  persistence:
    predictions_file: "icl_predictions.json"
```

### Configuration Options

#### Example Selection

| Option | Default | Description |
|--------|---------|-------------|
| `min_agreement_threshold` | 0.8 | Minimum proportion of annotators who must agree |
| `min_annotators_per_instance` | 2 | Minimum number of annotations required |
| `max_examples_per_schema` | 10 | Maximum examples per schema in prompts |
| `refresh_interval_seconds` | 300 | How often to refresh example pool |

#### LLM Labeling

| Option | Default | Description |
|--------|---------|-------------|
| `batch_size` | 20 | Maximum instances to label per batch |
| `trigger_threshold` | 5 | Minimum examples needed to start labeling |
| `confidence_threshold` | 0.7 | Minimum confidence to accept a prediction |
| `batch_interval_seconds` | 600 | Time between automatic batch runs |
| `max_total_labels` | null | Maximum total LLM predictions (null = unlimited) |
| `max_unlabeled_ratio` | 0.5 | Maximum portion of unlabeled data to label |
| `pause_on_low_accuracy` | true | Whether to pause on low accuracy |
| `min_accuracy_threshold` | 0.7 | Accuracy threshold for pausing |

#### Verification

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | true | Enable human verification workflow |
| `sample_rate` | 0.2 | Proportion of LLM labels to verify |
| `selection_strategy` | "low_confidence" | How to select verification instances |
| `mix_with_regular_assignments` | true | Mix verification with regular tasks |
| `assignment_mix_rate` | 0.2 | Probability of assigning verification |

### Selection Strategies

- **low_confidence**: Prioritizes verifying LLM's least confident predictions first
- **random**: Random sampling from all predictions
- **mixed**: 50% low confidence + 50% random

## Admin API

### Status Endpoint

```http
GET /admin/api/icl/status
```

Returns overall ICL labeler status including:
- Whether ICL is enabled
- Number of high-confidence examples per schema
- Total predictions made
- Verification queue size
- Accuracy metrics
- Labeling limits status

### Examples Endpoint

```http
GET /admin/api/icl/examples
GET /admin/api/icl/examples?schema=sentiment
```

Returns high-confidence examples, optionally filtered by schema.

### Predictions Endpoint

```http
GET /admin/api/icl/predictions
GET /admin/api/icl/predictions?schema=sentiment&status=pending
```

Returns LLM predictions with optional filtering by schema and verification status.

### Accuracy Endpoint

```http
GET /admin/api/icl/accuracy
GET /admin/api/icl/accuracy?schema=sentiment
```

Returns accuracy metrics based on human verification results.

### Manual Trigger Endpoint

```http
POST /admin/api/icl/trigger
Content-Type: application/json

{"schema_name": "sentiment"}
```

Manually trigger batch labeling for a specific schema.

### Record Verification Endpoint

```http
POST /api/icl/record_verification
Content-Type: application/json

{
    "instance_id": "doc_001",
    "schema_name": "sentiment",
    "human_label": "positive"
}
```

Manually record a verification result (usually handled automatically).

## Usage Example

### 1. Configure Your Project

Add ICL labeling to your project config:

```yaml
# project.yaml
ai_support:
  enabled: true
  endpoint_type: "openai"
  ai_config:
    model: "gpt-4o-mini"
    api_key: "${OPENAI_API_KEY}"

icl_labeling:
  enabled: true
  example_selection:
    min_agreement_threshold: 0.8
    min_annotators_per_instance: 2
  llm_labeling:
    batch_size: 10
    max_total_labels: 50  # Start small
  verification:
    enabled: true
    sample_rate: 0.3  # Verify 30% for initial accuracy estimate
```

### 2. Collect Human Annotations

Have annotators label data normally. As they reach consensus (80%+ agreement), those instances become available as examples.

### 3. Monitor Progress

Check the admin API or dashboard:

```bash
curl http://localhost:8000/admin/api/icl/status
```

### 4. Review Accuracy

Once verifications are complete, check accuracy:

```bash
curl http://localhost:8000/admin/api/icl/accuracy
```

### 5. Iterate

Based on accuracy:
- If accuracy is high (>80%), increase `max_total_labels` or `max_unlabeled_ratio`
- If accuracy is low, add more human examples before continuing

## Best Practices

1. **Start Small**: Begin with conservative limits (`max_total_labels: 50`) to assess accuracy before scaling up

2. **Verify Early**: Use a higher `sample_rate` initially (e.g., 0.3-0.5) to get confident accuracy estimates

3. **Monitor Actively**: Check accuracy metrics regularly through the admin API

4. **Adjust Thresholds**: If LLM accuracy is low, try:
   - Increasing `min_agreement_threshold` for cleaner examples
   - Increasing `trigger_threshold` for more examples before labeling
   - Lowering `confidence_threshold` to reject uncertain predictions

5. **Use Selection Strategies**:
   - `low_confidence`: Best for identifying problematic categories
   - `random`: Best for unbiased accuracy estimates
   - `mixed`: Balanced approach

## Data Storage

ICL predictions are stored in the output directory:

```
output/
  annotations/
    icl_predictions.json  # All predictions and state
```

Predictions include:
- Instance ID and schema
- Predicted label and confidence score
- Examples used for prediction
- Verification status and results
- Timestamps and model info

## Troubleshooting

### LLM Not Labeling

1. Check if `ai_support` is properly configured
2. Verify enough high-confidence examples exist (check `/admin/api/icl/status`)
3. Check if labeling is paused due to limits or low accuracy

### Low Accuracy

1. Increase `min_agreement_threshold` for cleaner examples
2. Add more annotation guidelines/instructions
3. Check if the LLM model is appropriate for your task
4. Review examples being used (check `/admin/api/icl/examples`)

### Verification Tasks Not Appearing

1. Verify `verification.enabled` is true
2. Check `mix_with_regular_assignments` is true
3. Ensure `assignment_mix_rate` is reasonable (0.1-0.3)
4. Verify there are pending verifications in the queue

## Related Documentation

- [AI Support](ai_support.md) - General AI endpoint configuration
- [Active Learning Guide](active_learning_guide.md) - Related AI-assisted features
- [Admin Dashboard](admin_dashboard.md) - Monitoring and administration
