# Discrete Choice / Conjoint Analysis

The Conjoint schema presents annotators with side-by-side product/concept profiles and asks them to choose the preferred one. Each profile is defined by attribute-level combinations. This enables estimation of attribute importance through experimental design — a methodology widely used in market research, preference elicitation, and now increasingly in LLM evaluation.

## When to Use Conjoint

- **Preference elicitation**: Which AI assistant configuration do users prefer?
- **Attribute importance estimation**: Which features matter most?
- **Product/concept testing**: Compare multi-attribute alternatives
- **Trade-off analysis**: Understand how people weigh competing attributes

## Configuration

```yaml
annotation_schemes:
  - annotation_type: conjoint
    name: model_preference
    description: "Which AI assistant would you prefer?"
    profiles_per_set: 3
    attributes:
      - name: Response Length
        levels: ["Brief (1-2 sentences)", "Medium (1 paragraph)", "Detailed (multiple paragraphs)"]
      - name: Tone
        levels: ["Formal", "Conversational", "Technical"]
      - name: Includes Examples
        levels: ["Yes", "No"]
      - name: Cites Sources
        levels: ["Yes", "No"]
    show_none_option: true
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `profiles_per_set` | integer | `3` | Number of profiles shown per choice set (2-4) |
| `attributes` | list | (required*) | List of attributes with `name` and `levels` |
| `show_none_option` | boolean | `true` | Show "None of these" option |
| `profiles_field` | string | `null` | Data field with pre-specified profiles (null = use attributes to generate) |

*Either `attributes` or `profiles_field` is required.

### Attributes Format

```yaml
attributes:
  - name: Speed           # Attribute name shown in profile cards
    levels: ["Fast", "Medium", "Slow"]  # Possible values
```

## Data Format

```json
{
  "model_preference": {
    "chosen_profile": 2,
    "profiles": [
      {"Response Length": "Brief", "Tone": "Formal", "Includes Examples": "No"},
      {"Response Length": "Detailed", "Tone": "Conversational", "Includes Examples": "Yes"},
      {"Response Length": "Medium", "Tone": "Technical", "Includes Examples": "Yes"}
    ]
  }
}
```

If "None of these" is selected:
```json
{"model_preference": {"chosen_profile": "none"}}
```

## UI Description

- Side-by-side profile cards (2-4 profiles)
- Each card shows attribute names and their levels in a clean table
- Radio button below each card for selection
- Selected card gets a highlight border
- Optional "None of these" option below the cards

## Example

```bash
python potato/flask_server.py start examples/classification/conjoint/config.yaml -p 8000
```

## Related

- [Pairwise Comparison](schemas_and_templates.md) — Compare exactly two items
- [Best-Worst Scaling](schemas_and_templates.md) — Select best and worst from a set
- [Ranking](ranking.md) — Order items by preference
- [Choosing Annotation Types](choosing_annotation_types.md)
