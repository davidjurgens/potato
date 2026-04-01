# Text Input / Rationale Annotation

The `text` schema provides free-text input for open-ended responses. With the enhanced rationale features, it can also serve as a justification companion to any other annotation schema.

## Basic Usage

```yaml
annotation_schemes:
  - annotation_type: text
    name: comments
    description: "Any additional comments?"
    multiline: true
    rows: 3
```

## Rationale / Justification Pattern

Pair a text schema with any primary annotation to collect explanations:

```yaml
annotation_schemes:
  - annotation_type: radio
    name: toxicity
    labels: ["Toxic", "Not toxic"]
    description: "Is this text toxic?"

  - annotation_type: text
    name: toxicity_rationale
    description: "Why did you choose this label?"
    target_schema: toxicity           # Visual grouping with the schema above
    placeholder: "Explain your reasoning..."
    min_chars: 10                     # Minimum 10 characters required
    show_char_count: true             # Show character counter
    collapsible: true                 # Start collapsed to reduce clutter
    multiline: true
    rows: 3
```

## Enhanced Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `multiline` | boolean | `false` | Use a textarea instead of a single-line input |
| `rows` | integer | `3` | Number of rows for the textarea |
| `cols` | integer | `40` | Number of columns for the textarea |
| `placeholder` | string | `""` | Placeholder text shown when the input is empty |
| `min_chars` | integer | `0` | Minimum character count required |
| `show_char_count` | boolean | `false` | Show a character counter below the input |
| `collapsible` | boolean | `false` | Start collapsed, expand on click |
| `target_schema` | string | `""` | Name of the schema this is a rationale for (visual grouping) |
| `allow_paste` | boolean | `true` | Whether pasting is allowed |
| `labels` | list | `["text_box"]` | Multiple textboxes with different labels |

## Features

### Character Counter

When `show_char_count: true` or `min_chars` is set, a character counter appears below the input. It shows the current character count and turns red when below the minimum.

### Collapsible

When `collapsible: true`, the text input starts collapsed and only shows the description as a clickable header. Click to expand and type. Useful for optional justifications that should not overwhelm the primary annotation.

### Target Schema Grouping

When `target_schema` is set, the text input renders with reduced top margin, visually grouping it with the preceding schema. This makes it clear that the text input is a companion annotation.

## Data Format

```json
{"toxicity_rationale": {"text_box": "I chose 'Toxic' because the text contains a slur targeting..."}}
```

For multiple labeled textboxes:
```json
{"comments": {"pro": "Good writing style", "con": "Factual errors in paragraph 2"}}
```

## Related

- [Confidence Annotation](confidence_annotation.md) — Pair annotations with a confidence rating
- [Choosing Annotation Types](choosing_annotation_types.md) — Guide to selecting the right schema
