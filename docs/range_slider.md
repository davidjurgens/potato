# Goldilocks Range / Dual-Thumb Slider

The range slider schema presents a dual-thumb slider where annotators select a minimum and maximum value on a continuous scale, defining a range rather than a single point. This is sometimes called the "Goldilocks" task: annotators mark the acceptable range of a scalar property (not too low, not too high — but somewhere in between).

## Overview

Standard sliders elicit a single point estimate. Many human judgments are more accurately described as ranges:

- A sentence is "formal enough" somewhere between 60–80 on a formality scale
- A paraphrase is acceptable if its meaning similarity is between 70–90%
- A response length is appropriate if it falls between 2–4 sentences

The dual-thumb slider captures this interval structure directly. Both thumbs are independently draggable; the selected range is highlighted between them.

## Research Basis

- Pavlick, E., & Kwiatkowski, T. (2019). "Inherent Disagreements in Human Textual Inferences." *Transactions of the Association for Computational Linguistics (TACL) 7*. Shows that annotator disagreement on inference tasks reflects genuine semantic indeterminacy that is better modeled as a range than as a point.
- Jurgens, D. (2013). "Embracing Ambiguity: A Comparison of Annotation Methodologies for Crowdsourcing Word Sense Labels." *NAACL 2013*. Demonstrates that allowing annotators to express uncertainty via ranges or soft labels improves dataset quality compared to forcing single-point choices.

## Configuration

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `annotation_type` | — | Must be `range_slider` |
| `name` | — | Schema identifier (required) |
| `description` | — | Task instruction |
| `min_value` | `0` | Minimum end of the scale |
| `max_value` | `100` | Maximum end of the scale |
| `step` | `1` | Increment between valid positions |
| `left_label` | `""` | Label displayed at the left (min) end of the track |
| `right_label` | `""` | Label displayed at the right (max) end of the track |
| `show_values` | `true` | Display the current numeric range values above the thumbs |
| `default_low` | `min_value` | Initial position of the lower thumb |
| `default_high` | `max_value` | Initial position of the upper thumb |
| `label_requirement.required` | `false` | Require range selection before proceeding |

### YAML Example — Formality Range

```yaml
annotation_schemes:
  - annotation_type: range_slider
    name: formality_range
    description: "Select the range of formality scores that would be acceptable for this text in a professional email context."
    min_value: 0
    max_value: 100
    step: 1
    left_label: "Very informal"
    right_label: "Very formal"
    show_values: true
    label_requirement:
      required: true
```

### YAML Example — Acceptable Confidence Interval

```yaml
annotation_schemes:
  - annotation_type: range_slider
    name: confidence_interval
    description: "Select the range of values you believe the correct answer falls within."
    min_value: 0
    max_value: 100
    step: 5
    left_label: "0%"
    right_label: "100%"
    show_values: true
    default_low: 25
    default_high: 75
```

### YAML Example — Sentence Length Acceptability

```yaml
annotation_schemes:
  - annotation_type: range_slider
    name: length_range
    description: "How many words is acceptable for a summary of this article? Drag both thumbs."
    min_value: 10
    max_value: 200
    step: 5
    left_label: "Too short"
    right_label: "Too long"
    show_values: true
```

## Output Format

The selected range is stored as two separate key-value pairs:

```json
{
  "formality_range": {
    "range_low": "25",
    "range_high": "75"
  }
}
```

Both values are string-encoded numbers. `range_low` is always less than or equal to `range_high`.

## Use Cases

- **Vague scalar adjective annotation** — measure acceptable range of "tall", "expensive", "fast"
- **Acceptable paraphrase similarity** — what similarity range qualifies as a valid paraphrase
- **Quality threshold elicitation** — what range of scores would a human accept as "good enough"
- **Toxicity boundary marking** — where does mildly offensive become clearly offensive
- **Summary length norms** — what length range is appropriate for a given source document
- **Temporal expression annotation** — mark the range of time a vague expression like "recently" refers to

## Troubleshooting

**Both thumbs overlap at the same position:** This is a valid degenerate case (zero-width range = point estimate). If your task requires a non-zero range, add a validation check in the instruction text but note that the schema does not enforce a minimum range width by default.

**Annotators do not move the default thumbs:** Ensure `default_low` and `default_high` are set to values that require deliberate adjustment. Setting them both to the midpoint forces annotators to actively place both thumbs.

## Related Documentation

- [Slider](schemas_and_templates.md#slider) — single-thumb continuous slider
- [Soft Label](soft_label.md) — probability distribution across categories
- [Pairwise Comparison](pairwise_annotation.md) — scale mode with single slider between two options
- [Schema Gallery](schemas_and_templates.md) — all annotation types with examples
