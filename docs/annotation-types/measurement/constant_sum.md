# Constant Sum / Points Allocation

The constant sum schema presents annotators with a fixed budget of points to allocate across a set of categories. Unlike soft labels which are percentage-based, constant sum tasks can use any total and are framed explicitly as an allocation exercise: "distribute 100 points across these topics according to how relevant each is." This framing naturally encourages comparative judgments rather than independent ratings of each category.

## Overview

Constant sum (also called budget allocation) is a measurement technique from marketing research adapted for NLP annotation:

- Annotators receive a fixed budget (e.g., 100 points)
- They enter values for each category using number inputs or sliders
- The UI enforces the constraint that all values sum exactly to the total
- Remaining budget is displayed as a running counter

This approach elicits relative importance judgments and prevents scale-usage bias (the tendency to rate everything high or low when using independent scales).

## Research Basis

- Louviere et al. (2015). *Best-Worst Scaling: Theory, Methods and Applications*. Cambridge University Press. Discusses constant sum as a foundational comparative measurement technique alongside BWS.
- Thurstone, L. L. (1927). "A Law of Comparative Judgment." *Psychological Review 34*(4). Foundational work establishing that comparative judgments yield more reliable interval-scale measurements than absolute ratings.

## Configuration

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `annotation_type` | — | Must be `constant_sum` |
| `name` | — | Schema identifier (required) |
| `description` | — | Task instruction shown to annotators |
| `labels` | — | List of category names (required, minimum 2) |
| `total_points` | `100` | Total budget to distribute |
| `min_per_item` | `0` | Minimum points any single category can receive |
| `input_type` | `"number"` | Input widget: `number` (text box) or `slider` |
| `label_requirement.required` | `false` | Require exact allocation before proceeding |

### YAML Example — Number Inputs

```yaml
annotation_schemes:
  - annotation_type: constant_sum
    name: topic_allocation
    description: "Distribute 100 points across the topics present in this article. Give more points to topics that are more prominent."
    total_points: 100
    min_per_item: 0
    input_type: number
    labels:
      - Politics
      - Sports
      - Technology
      - Entertainment
      - Science
    label_requirement:
      required: true
```

### YAML Example — Slider Inputs

```yaml
annotation_schemes:
  - annotation_type: constant_sum
    name: emotion_mix
    description: "Distribute 10 points across the emotions expressed in this post."
    total_points: 10
    min_per_item: 0
    input_type: slider
    labels:
      - Joy
      - Anger
      - Sadness
      - Fear
      - Surprise
```

### Requiring Minimum Allocations

Use `min_per_item` to force annotators to consider every category:

```yaml
annotation_schemes:
  - annotation_type: constant_sum
    name: argument_components
    description: "Distribute 100 points across argument components. Every component must receive at least 5 points."
    total_points: 100
    min_per_item: 5
    labels:
      - Claim
      - Evidence
      - Warrant
      - Rebuttal
```

## Output Format

Annotations are stored as a dictionary mapping each label to its allocated value string:

```json
{
  "topic_allocation": {
    "Politics": "30",
    "Sports": "20",
    "Technology": "50",
    "Entertainment": "0",
    "Science": "0"
  }
}
```

Values are string-encoded integers. The sum of all values equals `total_points`.

## Use Cases

- **Multi-topic document labeling** — measure the proportion of content devoted to each topic
- **Resource/effort allocation** — estimate how much attention a document gives to each aspect
- **Comparative aspect rating** — evaluate which qualities (fluency, relevance, coherence) contribute most to overall quality
- **Emotion composition** — capture mixed emotional content where multiple emotions co-occur
- **Argument mining** — quantify the presence of different argument components

## Troubleshooting

**Annotators find allocation tedious for many categories:** Limit to 5–7 categories maximum when using constant sum. For larger label sets consider hierarchical multiselect or a soft label schema.

**Sum constraint causes frustration:** Make the running balance counter prominent and use the `number` input type for large totals (easier to correct) and `slider` for small totals (e.g., 10 points).

## Related Documentation

- [Soft Label](soft_label.md) — percentage-based probability distribution
- [Best-Worst Scaling](../comparison/bws.md) — comparative ranking without explicit scores
- [Slider](../schemas_and_templates.md#slider) — single continuous slider
- [Schema Gallery](../schemas_and_templates.md) — all annotation types with examples
