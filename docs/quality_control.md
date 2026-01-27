# Quality Control Features

Potato provides comprehensive quality control features to ensure high-quality annotations in your projects. This guide covers four key features:

1. **Attention Checks** - Verify annotator engagement with known-answer items
2. **Gold Standards** - Track accuracy against expert-labeled items
3. **Pre-annotation Support** - Pre-fill forms with model predictions
4. **Agreement Metrics** - Calculate inter-annotator agreement in real-time

---

## Attention Checks

Attention checks are items with known correct answers that are periodically injected into the annotation flow to verify that annotators are paying attention and not randomly clicking.

### Configuration

```yaml
attention_checks:
  enabled: true

  # Path to JSON file containing attention check items
  items_file: "attention_checks.json"

  # How often to inject attention checks (choose one):
  frequency: 10              # Insert one every 10 items
  # OR
  probability: 0.1           # 10% chance per item

  # Optional: flag suspiciously fast responses
  min_response_time: 3.0     # Flag if answered in < 3 seconds

  # Failure handling
  failure_handling:
    warn_threshold: 2        # Show warning after 2 failures
    warn_message: "Please read items carefully before answering."
    block_threshold: 5       # Block user after 5 failures
    block_message: "You have been blocked due to too many incorrect responses."
```

### Attention Check Items File Format

Create a JSON file with your attention check items:

```json
[
  {
    "id": "attn_001",
    "text": "Please select 'Positive' for this item to verify you are reading carefully.",
    "expected_answer": {
      "sentiment": "positive"
    }
  },
  {
    "id": "attn_002",
    "text": "This is a test item. The correct answer is 'Negative'. Please select it now.",
    "expected_answer": {
      "sentiment": "negative"
    }
  }
]
```

**Fields:**
- `id` (required): Unique identifier for the attention check
- `text` (required): The text to display to annotators
- `expected_answer` (required): Dictionary mapping schema names to expected values

### How It Works

1. Attention check items are loaded at server startup
2. Based on `frequency` or `probability`, checks are injected into the annotation flow
3. When an annotator submits a response, it's compared to the expected answer
4. Failures are tracked per-user
5. Warnings and blocks are triggered at configured thresholds

### Admin Dashboard

View attention check statistics in the admin dashboard at `/admin`:
- Overall pass/fail rates
- Per-annotator statistics
- Individual failure history

---

## Gold Standards

Gold standards are expert-labeled items used to measure annotator accuracy. By default, gold standards are **silent** - results are recorded for admin review in the dashboard, but annotators don't see feedback. This allows you to track quality without influencing annotator behavior.

### Configuration

```yaml
gold_standards:
  enabled: true

  # Path to JSON file containing gold standard items
  items_file: "gold_standards.json"

  # How to use gold standards
  mode: "mixed"              # Options: training, mixed, separate
  # - training: Show only during training phase
  # - mixed: Mix into regular annotation (silent tracking)
  # - separate: Dedicated evaluation phase

  # For mixed mode, how often to inject
  frequency: 20              # Insert one every 20 items

  # Accuracy requirements (tracked in admin dashboard)
  accuracy:
    min_threshold: 0.7       # Minimum required accuracy (70%)
    evaluation_count: 10     # Evaluate after this many gold items

  # Feedback settings (disabled by default for silent tracking)
  # Enable for training scenarios where you want to give annotators feedback
  feedback:
    show_correct_answer: false  # Show correct answer after submission
    show_explanation: false     # Show explanation if provided

  # Auto-promotion: items become gold standards when annotators agree
  auto_promote:
    enabled: true
    min_annotators: 3          # Minimum annotators before checking
    agreement_threshold: 1.0   # 1.0 = unanimous, 0.8 = 80% agree
```

### Gold Standard Items File Format

```json
[
  {
    "id": "gold_001",
    "text": "The service was absolutely terrible and I will never return.",
    "gold_label": {
      "sentiment": "negative"
    },
    "explanation": "Strong negative language ('absolutely terrible', 'never return') clearly indicates negative sentiment.",
    "difficulty": "easy"
  },
  {
    "id": "gold_002",
    "text": "The food was okay but nothing special.",
    "gold_label": {
      "sentiment": "neutral"
    },
    "explanation": "Mixed signals balance to neutral sentiment.",
    "difficulty": "medium"
  }
]
```

**Fields:**
- `id` (required): Unique identifier
- `text` (required): The text to display
- `gold_label` (required): Dictionary with correct annotations
- `explanation` (optional): Explanation shown to annotators
- `difficulty` (optional): Metadata for analysis

### Feedback Display

After submitting a gold standard item, annotators see:
- Whether their answer was correct or incorrect
- The correct answer (if `show_correct_answer: true`)
- An explanation (if `show_explanation: true` and explanation provided)
- Accuracy warning if below threshold

### Admin Dashboard

View gold standard metrics in the admin dashboard:
- Overall accuracy across all annotators
- Per-annotator accuracy tracking
- Per-item difficulty analysis (which items are most often missed)
- Users below accuracy threshold

### Auto-Promotion to Gold Standard

You can configure Potato to automatically promote items to the gold standard pool when multiple annotators agree on the label. This is useful for:
- Growing your gold standard pool organically
- Identifying "easy" items where everyone agrees
- Reducing the burden of manually creating gold standards

```yaml
gold_standards:
  enabled: true
  items_file: "initial_gold_standards.json"  # Seed items (optional)

  auto_promote:
    enabled: true
    min_annotators: 3          # Wait for at least 3 annotators
    agreement_threshold: 1.0   # 1.0 = all must agree (unanimous)
                               # 0.8 = 80% must agree
```

**How it works:**
1. As items are annotated, the system tracks all responses
2. When `min_annotators` have annotated an item, agreement is checked
3. If agreement meets `agreement_threshold`, the item is promoted
4. Promoted items are added to the gold standard pool and used for future quality checks

**Admin visibility:**
- View promoted items in `/admin/api/quality_control`
- See "promotion candidates" (items close to threshold)
- Track which items were auto-promoted vs. manually defined

---

## Pre-annotation Support

Pre-annotation allows you to pre-fill annotation forms with model predictions, useful for:
- Active learning workflows
- Correcting model outputs
- Bootstrapping from existing annotations

### Configuration

```yaml
pre_annotation:
  enabled: true

  # Field in data items containing predictions
  field: "predictions"

  # Can annotators change pre-filled values?
  allow_modification: true

  # Show confidence scores if available
  show_confidence: true

  # Highlight items below this confidence threshold
  highlight_low_confidence: 0.7
```

### Data Format

Include predictions in your data items:

```json
{
  "id": "item_001",
  "text": "I love this product!",
  "predictions": {
    "sentiment": "positive",
    "confidence": 0.92
  }
}
```

For span annotations:

```json
{
  "id": "item_002",
  "text": "Apple announced new iPhone in California.",
  "predictions": {
    "entities": [
      {"start": 0, "end": 5, "label": "ORG", "confidence": 0.85},
      {"start": 27, "end": 37, "label": "LOC", "confidence": 0.91}
    ]
  }
}
```

### How It Works

1. When an item is loaded, the predictions field is extracted
2. If the annotator hasn't already annotated this item, predictions are used to pre-fill the form
3. Annotators can modify the pre-filled values (if `allow_modification: true`)
4. Low-confidence items can be visually highlighted

### Best Practices

- Use pre-annotation for correction workflows where you have model predictions
- Set `allow_modification: true` to let annotators fix errors
- Use confidence thresholds to flag items needing more attention
- Track modification rates to assess model quality

---

## Agreement Metrics

Real-time inter-annotator agreement metrics are available in the admin dashboard, using Krippendorff's alpha.

### Configuration

```yaml
agreement_metrics:
  enabled: true

  # Minimum annotators per item for calculation
  min_overlap: 2

  # Auto-refresh settings
  auto_refresh: true
  refresh_interval: 60       # Seconds between updates
```

### Interpreting Krippendorff's Alpha

| Alpha Value | Interpretation |
|-------------|----------------|
| α ≥ 0.8 | Good agreement - reliable for most purposes |
| 0.67 ≤ α < 0.8 | Tentative agreement - draw tentative conclusions |
| 0.33 ≤ α < 0.67 | Low agreement - review guidelines |
| α < 0.33 | Poor agreement - significant issues |

### Admin Dashboard

The Agreement tab in the admin dashboard shows:
- Overall average alpha across all schemas
- Per-schema agreement metrics
- Number of items evaluated
- Metric type (nominal vs interval)
- Human-readable interpretation

### When to Use Different Metrics

The system automatically selects the appropriate metric:
- **Nominal metric**: For categorical annotations (radio, multiselect)
- **Interval metric**: For numeric annotations (likert, slider, number)

---

## API Endpoints

### Quality Control Metrics

```
GET /admin/api/quality_control
```

Returns:
```json
{
  "enabled": true,
  "attention_checks": {
    "enabled": true,
    "total_checks": 50,
    "total_passed": 45,
    "total_failed": 5,
    "by_user": {
      "user1": {"passed": 10, "failed": 0, "pass_rate": 1.0},
      "user2": {"passed": 8, "failed": 2, "pass_rate": 0.8}
    }
  },
  "gold_standards": {
    "enabled": true,
    "total_evaluations": 30,
    "total_correct": 25,
    "by_user": {...},
    "by_item": {...}
  }
}
```

### Agreement Metrics

```
GET /admin/api/agreement
```

Returns:
```json
{
  "enabled": true,
  "overall": {
    "average_krippendorff_alpha": 0.75,
    "interpretation": "Tentative agreement"
  },
  "by_schema": {
    "sentiment": {
      "krippendorff_alpha": 0.82,
      "items_evaluated": 100,
      "interpretation": "Good agreement"
    }
  }
}
```

---

## Example Configuration

Here's a complete example with all quality control features enabled:

```yaml
annotation_task_name: "Sentiment Analysis with Quality Control"

# Main annotation scheme
annotation_schemes:
  - name: sentiment
    annotation_type: radio
    labels: [positive, negative, neutral]
    description: "Select the sentiment of the text"

# Quality Control Configuration
attention_checks:
  enabled: true
  items_file: "data/attention_checks.json"
  frequency: 15
  failure_handling:
    warn_threshold: 2
    block_threshold: 5

gold_standards:
  enabled: true
  items_file: "data/gold_standards.json"
  mode: mixed
  frequency: 25
  accuracy:
    min_threshold: 0.7
    evaluation_count: 5
  feedback:
    show_correct_answer: true
    show_explanation: true

pre_annotation:
  enabled: true
  field: "model_prediction"
  allow_modification: true

agreement_metrics:
  enabled: true
  min_overlap: 2
  refresh_interval: 60
```

---

## Troubleshooting

### Attention checks not appearing

1. Verify `items_file` path is correct (relative to task directory)
2. Check that items have required fields (`id`, `expected_answer`)
3. Ensure `frequency` or `probability` is set

### Gold standard feedback not showing

1. Check `feedback.show_correct_answer` is `true`
2. Verify items have `gold_label` field
3. Check browser console for JavaScript errors

### Agreement metrics showing "No items with N+ annotators"

1. Ensure items have been annotated by multiple users
2. Reduce `min_overlap` if needed
3. Check that annotations are being saved correctly

### Pre-annotations not appearing

1. Verify `field` matches the field name in your data
2. Check that predictions format matches expected schema
3. Ensure user hasn't already annotated the item (pre-annotations only appear for un-annotated items)
