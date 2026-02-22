# Triage Annotation Schema

The triage annotation schema provides a Prodigy-style binary accept/reject/skip interface optimized for rapid data curation tasks. This schema is ideal for filtering large datasets quickly, performing data quality checks, or any task requiring quick binary decisions.

## Overview

The triage schema presents three large, visually distinct buttons:
- **Keep** (green) - Accept the item for inclusion
- **Discard** (red) - Reject the item
- **Unsure** (gray) - Skip when uncertain

With auto-advance enabled (default), annotators can process hundreds of items per hour using just keyboard shortcuts.

## Quick Start

Add a triage annotation scheme to your configuration:

```yaml
annotation_schemes:
  - annotation_type: triage
    name: data_quality
    description: Is this data sample suitable for training?
    auto_advance: true
    show_progress: true
```

Run the example project:

```bash
python potato/flask_server.py start examples/advanced/triage/config.yaml -p 8000
```

## Configuration Options

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `annotation_type` | string | Must be `"triage"` |
| `name` | string | Unique identifier for this schema |
| `description` | string | Instructions displayed to annotators |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `accept_label` | string | `"Keep"` | Text label for the accept button |
| `reject_label` | string | `"Discard"` | Text label for the reject button |
| `skip_label` | string | `"Unsure"` | Text label for the skip button |
| `auto_advance` | boolean | `true` | Automatically move to next item after selection |
| `show_progress` | boolean | `true` | Display progress bar in the triage widget |
| `accept_key` | string | `"1"` | Keyboard shortcut for accept |
| `reject_key` | string | `"2"` | Keyboard shortcut for reject |
| `skip_key` | string | `"3"` | Keyboard shortcut for skip |

## Example Configurations

### Basic Data Quality Filtering

```yaml
annotation_schemes:
  - annotation_type: triage
    name: quality_filter
    description: Is this text high quality and suitable for training?
    auto_advance: true
```

### Custom Labels for Content Moderation

```yaml
annotation_schemes:
  - annotation_type: triage
    name: content_moderation
    description: Does this content violate community guidelines?
    accept_label: "Safe"
    reject_label: "Violates"
    skip_label: "Review Later"
    auto_advance: true
```

### Custom Keyboard Shortcuts

```yaml
annotation_schemes:
  - annotation_type: triage
    name: sentiment_triage
    description: Does this review express a clear sentiment?
    accept_key: "a"
    reject_key: "r"
    skip_key: "s"
```

### Without Auto-Advance (For Careful Review)

```yaml
annotation_schemes:
  - annotation_type: triage
    name: careful_review
    description: Review each item carefully
    auto_advance: false
    show_progress: true
```

### Combined with Other Schemas

Triage can be combined with other annotation types when you need both filtering and detailed annotation:

```yaml
annotation_schemes:
  # First, triage the data
  - annotation_type: triage
    name: include_item
    description: Should this item be included in the dataset?
    auto_advance: false  # Don't auto-advance when combined

  # If included, annotate further
  - annotation_type: radio
    name: category
    description: What category does this belong to?
    labels: ["News", "Opinion", "Review", "Other"]
```

## Keyboard Shortcuts

Default keyboard shortcuts are designed for rapid one-handed operation:

| Key | Action |
|-----|--------|
| `1` | Keep (Accept) |
| `2` | Discard (Reject) |
| `3` | Unsure (Skip) |

The keys 1, 2, 3 are adjacent on the keyboard, allowing fast annotation without looking at the keyboard.

## Output Format

Triage annotations are saved in the standard annotation format:

```json
{
  "data_quality": {
    "labels": {
      "decision": "accept"
    }
  }
}
```

Possible values for the decision field:
- `"accept"` - Item was marked as Keep
- `"reject"` - Item was marked as Discard
- `"skip"` - Item was marked as Unsure

## UI Features

### Progress Indicator

When `show_progress: true`, a progress bar displays:
- Current item number
- Total item count
- Visual progress bar

### Visual Feedback

- Buttons show clear visual states when selected
- Smooth animations provide feedback on selection
- Color coding matches decision semantics (green=accept, red=reject)

### Accessibility

- Full keyboard navigation support
- ARIA labels for screen readers
- High contrast mode support
- Reduced motion support for users who prefer it

## Use Cases

### Data Quality Filtering

Filter noisy data from web crawls or user-generated content:

```yaml
annotation_schemes:
  - annotation_type: triage
    name: quality
    description: Is this text grammatically correct and coherent?
    accept_label: "Good Quality"
    reject_label: "Poor Quality"
    skip_label: "Borderline"
```

### Relevance Filtering

Filter search results or recommendations:

```yaml
annotation_schemes:
  - annotation_type: triage
    name: relevance
    description: Is this document relevant to the query?
    accept_label: "Relevant"
    reject_label: "Not Relevant"
    skip_label: "Partially Relevant"
```

### Content Moderation

Review user-generated content for policy violations:

```yaml
annotation_schemes:
  - annotation_type: triage
    name: moderation
    description: Does this content comply with community guidelines?
    accept_label: "Approve"
    reject_label: "Remove"
    skip_label: "Escalate"
```

### Training Data Curation

Curate datasets for machine learning:

```yaml
annotation_schemes:
  - annotation_type: triage
    name: training_data
    description: Should this example be included in the training set?
    accept_label: "Include"
    reject_label: "Exclude"
    skip_label: "Maybe"
```

## Best Practices

1. **Use auto-advance for high-throughput tasks**: When items are simple and decisions are quick, auto-advance significantly improves throughput.

2. **Disable auto-advance for complex decisions**: When annotators need time to think or make additional annotations, disable auto-advance.

3. **Provide clear descriptions**: Make the triage criteria unambiguous to ensure consistent annotations.

4. **Use meaningful labels**: Customize labels to match your specific use case rather than using generic "Accept/Reject".

5. **Combine with attention checks**: For crowdsourcing, insert known items to verify annotator quality.

6. **Set appropriate time alerts**: Disable or set high time alerts (`alert_time_each_instance: 0`) for triage tasks since decisions are intentionally fast.

## Comparison with Other Annotation Tools

| Feature | Potato Triage | Prodigy | Label Studio |
|---------|---------------|---------|--------------|
| Three-button interface | Yes | Yes | Partial |
| Auto-advance | Yes | Yes | Yes |
| Keyboard shortcuts | Yes (customizable) | Yes | Yes |
| Progress indicator | Yes | Yes | Yes |
| Custom labels | Yes | Partial | Yes |
| Combined schemas | Yes | No | Yes |
| Self-hosted | Yes | Yes | Yes |

## Troubleshooting

### Auto-advance Not Working

1. Verify `auto_advance: true` is set in the config
2. Check browser console for JavaScript errors
3. Ensure `navigateToNext()` function is available (part of annotation.js)

### Keyboard Shortcuts Not Responding

1. Ensure you're not focused in a text input field
2. Check if custom keybindings conflict with browser shortcuts
3. Verify triage.js is being loaded

### Progress Bar Not Updating

1. Check that `show_progress: true` is set
2. Verify the progress counter element exists in the template
3. Check browser console for errors

## Related Documentation

- [Schemas and Templates](schemas_and_templates.md) - Overview of all annotation types
- [Quality Control](quality_control.md) - Attention checks and gold standards
- [Crowdsourcing](crowdsourcing.md) - Deploying triage tasks to crowdworkers
