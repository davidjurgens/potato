# Text Input / Rationale Annotation

The `text` schema is a free-text box for open-ended responses. Attached to another schema, it becomes the place an annotator justifies the answer they just gave.

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
| `min_chars` | integer | `0` | Minimum number of characters in each box. Text below this number blocks navigation. See [Minimum Length](#minimum-length-min_chars). |
| `show_char_count` | boolean | `false` | Show a character counter below the input |
| `collapsible` | boolean | `false` | Start collapsed, expand on click |
| `target_schema` | string | `""` | Name of the schema this is a rationale for (visual grouping) |
| `allow_paste` | boolean | `true` | Whether pasting is allowed |
| `labels` | list | `["text_box"]` | Multiple textboxes with different labels |

## Features

### Character Counter

When `show_char_count: true` or `min_chars` is set, a character counter shows below each box. The counter updates while the annotator types. This is true on annotation pages and on phase pages (for example, prestudy and poststudy surveys). The counter counts the text without spaces at the start and at the end. The counter is red while the count is below `min_chars`.

### Minimum Length (`min_chars`)

When `min_chars` is set, Potato does not accept text that is shorter than `min_chars`:

1. The page blocks **Next** (and **Submit** on a phase page).
2. The required-fields error shows the question and the count, for example "Define populism (12 of 200 characters)".
3. The server refuses the same answer. A direct request cannot skip the check.

Potato counts the text without spaces at the start and at the end.

Each box gets its own check. With `labels`, every box must have `min_chars` characters. The error then also names the box, for example "Contra: 3 of 200 characters".

An empty box is different for optional and required questions:

| Question | Empty box | Text below `min_chars` |
|---|---|---|
| Optional (no `label_requirement`) | Accepted | Blocked |
| Required (`label_requirement: {required: true}`) | Blocked | Blocked |

A question that `display_logic` hides does not block navigation.

```yaml
annotation_schemes:
  - annotation_type: text
    name: definition
    description: "Define populism in your own words."
    label_requirement: {required: true}
    min_chars: 200
    textarea: {on: true, rows: 6}
```

The counter text and the error text come from `ui_language`. With `ui_language: de`, the counter shows "12 / mind. 200 Zeichen" and the error shows "12 von 200 Zeichen". To change the text, set these keys:

| Key | English default |
|---|---|
| `text_char_count` | `{count} characters` |
| `text_char_count_min` | `{count}/{min} min characters` |
| `text_too_short` | `{count} of {min} characters` |

`{count}` is the current count. `{min}` is the value of `min_chars`. Keep both placeholders in a translation.

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

- [Confidence Annotation](../measurement/confidence_annotation.md) — Pair annotations with a confidence rating
- [Choosing Annotation Types](../choosing_annotation_types.md) — Guide to selecting the right schema
