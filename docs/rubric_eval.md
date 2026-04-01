# Multi-Criteria Rubric Evaluation

The Rubric Evaluation schema provides a structured grid for rating items on multiple criteria simultaneously. This is the essential schema for LLM evaluation — enabling MT-Bench-style multi-dimensional scoring with configurable criteria and scale points.

## When to Use Rubric Eval

- **LLM output evaluation**: Rate responses on helpfulness, accuracy, safety, clarity
- **Multi-dimensional quality assessment**: Any task requiring evaluation across several axes
- **Structured grading rubrics**: Academic or professional evaluation criteria
- **Model comparison studies**: Systematic evaluation of model outputs

## Configuration

```yaml
annotation_schemes:
  - annotation_type: rubric_eval
    name: response_quality
    description: "Evaluate this response on each criterion"
    scale_points: 5
    scale_labels: ["Poor", "Below Average", "Average", "Good", "Excellent"]
    criteria:
      - name: helpfulness
        description: "Does the response answer the question?"
      - name: accuracy
        description: "Is the information factually correct?"
      - name: clarity
        description: "Is the response well-written and easy to understand?"
      - name: safety
        description: "Does the response avoid harmful content?"
    show_overall: true
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `scale_points` | integer | `5` | Number of rating scale points |
| `scale_labels` | list | `["Poor", "Below Average", "Average", "Good", "Excellent"]` | Labels for each scale point |
| `criteria` | list | (required) | List of criteria with `name` and optional `description` |
| `show_overall` | boolean | `false` | Whether to include an "Overall" summary row |

### Criteria Format

Each criterion is a dictionary:

```yaml
criteria:
  - name: helpfulness        # Required: criterion identifier
    description: "..."       # Optional: shown as hint text below the name
```

## Data Format

```json
{
  "response_quality": {
    "helpfulness": "4",
    "accuracy": "5",
    "clarity": "3",
    "safety": "5",
    "overall": "4"
  }
}
```

## UI Description

- Table grid layout: rows = criteria, columns = scale points
- Radio buttons at each cell intersection
- Criterion name and description in the left column
- Scale labels in the header row with numeric values
- Optional "Overall" row at the bottom (highlighted)
- Hover highlighting for rows

## Rubric Eval vs Multirate vs Semantic Differential

| Feature | Rubric Eval | Multirate | Semantic Differential |
|---------|-------------|-----------|----------------------|
| Layout | Table grid | Items × options matrix | Bipolar scale rows |
| Best for | Quality criteria | Rating multiple items | Connotative meaning |
| Scale | Unipolar (1-N) | Unipolar options | Bipolar (negative-positive) |
| Items | Fixed criteria | Data-driven items | Fixed adjective pairs |

## Example

```bash
python potato/flask_server.py start examples/classification/rubric-eval/config.yaml -p 8000
```

## Related

- [Multirate](schemas_and_templates.md) — Rate multiple items on a scale
- [Semantic Differential](semantic_differential.md) — Bipolar adjective scales
- [Confidence](confidence_annotation.md) — Meta-annotation for rating confidence
- [Choosing Annotation Types](choosing_annotation_types.md)
