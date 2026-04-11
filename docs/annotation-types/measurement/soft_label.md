# Soft Label / Probability Distribution

The soft label schema allows annotators to distribute probability mass across a set of labels using constrained sliders. Rather than committing to a single category, annotators express graded membership by allocating percentages that must sum to a fixed total (default 100). This captures genuine annotation uncertainty and reflects the natural subjectivity present in many NLP tasks.

## Overview

Standard "hard" annotation forces a single label choice even when multiple labels partially apply. The soft label schema:

- Presents one slider per label, each ranging from 0 to the total budget
- Enforces a sum constraint: all sliders must total exactly `total` (default 100)
- Adjusts remaining sliders dynamically as annotators move any single slider
- Optionally displays a live distribution chart

This approach directly models the annotator's belief distribution rather than collapsing it to a single vote.

## Research Basis

- Fornaciari et al. (2021). "Beyond Black & White: Leveraging Annotator Disagreement via Soft-Label Multi-Task Learning." *ACL 2021*. Demonstrates that soft labels improve downstream model performance on subjective tasks compared to majority-vote hard labels.
- Plank et al. (2014). "Linguistically Debatable or Just Plain Wrong? NLP Researchers and Annotators Disagree on Sentiment." *ACL 2014*. Shows that annotator disagreement on sentiment is systematic and meaningful, not noise to be discarded.

## Configuration

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `annotation_type` | — | Must be `soft_label` |
| `name` | — | Schema identifier (required) |
| `description` | — | Question text shown to annotators |
| `labels` | — | List of label names (required, minimum 2) |
| `total` | `100` | Budget that all sliders must sum to |
| `min_per_label` | `0` | Minimum allocation per label |
| `show_distribution_chart` | `true` | Show a live bar chart of current distribution |
| `label_requirement.required` | `false` | Require sum to equal total before proceeding |

### YAML Example

```yaml
annotation_schemes:
  - annotation_type: soft_label
    name: sentiment_soft
    description: "Distribute 100 points across sentiment categories based on how much each applies."
    total: 100
    min_per_label: 0
    show_distribution_chart: true
    labels:
      - Positive
      - Neutral
      - Negative
    label_requirement:
      required: true
```

### Combining with Other Schemas

Soft label works well alongside a hard-label radio button for comparison studies:

```yaml
annotation_schemes:
  - annotation_type: radio
    name: sentiment_hard
    description: "Choose the best single label."
    labels:
      - Positive
      - Neutral
      - Negative

  - annotation_type: soft_label
    name: sentiment_soft
    description: "Now distribute 100 points to reflect your uncertainty."
    labels:
      - Positive
      - Neutral
      - Negative
    total: 100
```

## Output Format

Annotations are stored as a dictionary mapping each label to its allocated value:

```json
{
  "sentiment_soft": {
    "Positive": 40,
    "Neutral": 35,
    "Negative": 25
  }
}
```

The values are integers that sum to `total`. If `min_per_label` is set, no label will appear below that floor.

## Use Cases

- **Sentiment analysis** — express mixed sentiment (e.g., sarcasm, ambivalence)
- **Toxicity detection** — allocate across overlapping harm categories
- **Emotion recognition** — multi-emotion distributions rather than single labels
- **Stance detection** — partial agreement / partial disagreement
- **Soft multi-label classification** — when labels are not mutually exclusive but have graded relevance

## Troubleshooting

**Sliders do not sum to total:** Ensure `label_requirement.required: true` is set to block submission until the constraint is satisfied. The UI highlights the remaining balance in red when the sum does not match.

**Annotators all converge on equal distributions:** Consider adding anchor examples in the training phase showing extreme and mixed cases.

## Related Documentation

- [Constant Sum](constant_sum.md) — allocate integer points rather than percentages
- [Schema Gallery](../schemas_and_templates.md) — all annotation types with examples
- [Configuration Reference](../../configuration/configuration.md) — complete config options
