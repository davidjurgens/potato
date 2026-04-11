# Visual Analog Scale (VAS)

The Visual Analog Scale is a continuous measurement instrument where annotators click or drag a marker along a plain line between two endpoints. Unlike Likert scales or discrete sliders, VAS has no tick marks or discrete bins, returning a precise floating-point value.

## When to Use VAS

- **Fine-grained magnitude estimation**: When you need more precision than a 5- or 7-point scale
- **Clinical or psychological assessments**: Pain intensity, mood, satisfaction
- **Minimizing anchoring bias**: No visible gradations means annotators rely on their internal sense of magnitude
- **Continuous constructs**: Similarity, intensity, quality ratings

## Configuration

```yaml
annotation_schemes:
  - annotation_type: vas
    name: pain_level
    description: "Rate the intensity of pain described"
    left_label: "No pain"          # Label for the left endpoint
    right_label: "Worst imaginable" # Label for the right endpoint
    min_value: 0                    # Minimum value (default: 0)
    max_value: 100                  # Maximum value (default: 100)
    show_value: false               # Show numeric value after selection (default: false)
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `left_label` | string | `""` | Label displayed at the left endpoint |
| `right_label` | string | `""` | Label displayed at the right endpoint |
| `min_value` | number | `0` | Minimum value of the scale |
| `max_value` | number | `100` | Maximum value of the scale |
| `show_value` | boolean | `false` | Whether to display the numeric value after selection |

## Data Format

The annotation is stored as a float string:

```json
{"pain_level": "67.3"}
```

## VAS vs Slider vs Likert

| Feature | VAS | Slider | Likert |
|---------|-----|--------|--------|
| Visual | Plain line, endpoints only | Track with tick marks | Discrete buttons |
| Values | Continuous float | Discrete steps | Integer points |
| Numeric display | Hidden by default | Shown | Point labels |
| Best for | Magnitude estimation | Bounded numeric input | Categorical judgment |

## Example

Run the example:

```bash
python potato/flask_server.py start examples/classification/vas/config.yaml -p 8000
```

## Related

- [Slider](../schemas_and_templates.md) — Discrete slider with visible steps
- [Likert](../schemas_and_templates.md) — Discrete point scale with labels
- [Choosing Annotation Types](../choosing_annotation_types.md) — Guide to selecting the right schema
