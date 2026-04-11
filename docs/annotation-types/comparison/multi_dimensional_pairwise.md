# Multi-Dimensional Pairwise Comparison

Compare two items on multiple independent dimensions, each producing a separate A/B/tie value. Based on Scale AI RLHF multi-aspect evaluation and multi-dimensional preference learning research.

## Overview

The `multi_dimension` mode for the `pairwise` annotation type displays two items side by side and provides independent A/B tile rows for each configured dimension (e.g., helpfulness, accuracy, safety).

This is distinct from:
- **Binary pairwise**: A single A/B choice
- **Scale pairwise**: A single slider between A and B
- **Rubric eval**: Scores items independently, not comparatively

## Configuration

```yaml
annotation_schemes:
  - annotation_type: pairwise
    name: agent_comparison
    description: "Compare these two agent responses"
    mode: multi_dimension
    items_key: text
    labels: ["Response A", "Response B"]
    dimensions:
      - name: helpfulness
        description: "Which response better addresses the user's request?"
        allow_tie: true
      - name: accuracy
        description: "Which response has fewer factual errors?"
        allow_tie: true
      - name: safety
        description: "Which response is safer?"
        allow_tie: true
```

### Dimension Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique identifier for this dimension |
| `description` | No | Help text shown to annotators |
| `allow_tie` | No | Show tie button for this dimension (default: false) |
| `tie_label` | No | Custom tie button text (default: "Tie") |

## Adding Justification

You can require annotators to explain their preferences with reason categories and free text:

```yaml
    justification:
      required: true
      reason_categories:
        - "More accurate"
        - "More helpful"
        - "Safer"
        - "Better formatted"
      min_rationale_chars: 20
      rationale_placeholder: "Explain your preference..."
```

The justification block works with all pairwise modes (binary, scale, multi_dimension).

## Output Format

Each dimension produces a separate annotation value:

```json
{
  "agent_comparison": {
    "helpfulness": "A",
    "accuracy": "B",
    "safety": "tie",
    "justification": "{\"reasons\": [\"More accurate\"], \"rationale\": \"Response A had correct facts...\"}"
  }
}
```

## Example

```bash
python potato/flask_server.py start examples/agent-traces/multi-dim-comparison/config.yaml -p 8000
```

## Related Documentation

- [Schemas and Templates](../schemas_and_templates.md) — gallery of all annotation types
- [Rubric Evaluation](../measurement/rubric_eval.md) — multi-criteria scoring (non-comparative)
- [Trajectory Evaluation](../../agent-evaluation/trajectory_eval.md) — per-step agent evaluation
