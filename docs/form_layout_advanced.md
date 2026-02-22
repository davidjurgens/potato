# Form Layout Advanced Options

This guide covers advanced styling and alignment options for the annotation form layout system. For basic layout configuration, see [Form Layout](form_layout.md).

## Overview

Advanced options allow fine-grained control over:

- **Alignment**: Horizontal and vertical positioning of form content
- **Background colors**: Visual distinction between groups
- **Padding**: Spacing within forms and groups
- **Form styling**: Individual form appearance

## Styling Configuration

Add a `styling` section under `layout` for advanced visual options:

```yaml
layout:
  grid:
    columns: 3
    gap: "1rem"

  styling:
    # Grid alignment
    align_items: "start"           # Vertical alignment of forms
    content_align: "left"          # Horizontal alignment within forms

    # Group backgrounds
    group_background_odd: "#fafafa"
    group_background_even: "#f8f9fc"

    # Padding
    group_padding: "0.5rem 0.75rem"
    form_padding: "0.375rem 0.5rem"
```

## Alignment Options

### Vertical Alignment (`align_items`)

Controls how forms align vertically within grid rows:

```yaml
layout:
  styling:
    align_items: "start"    # Forms align to top (default)
```

| Value | Description |
|-------|-------------|
| `start` | Align forms to the top of the row (default) |
| `center` | Center forms vertically |
| `end` | Align forms to the bottom of the row |
| `stretch` | Stretch forms to fill row height |

### Horizontal Content Alignment (`content_align`)

Controls how content is aligned within form containers:

```yaml
layout:
  styling:
    content_align: "left"   # Content aligns to left (default)
```

| Value | Description |
|-------|-------------|
| `left` | Left-align form content (default) |
| `center` | Center form content |
| `right` | Right-align form content |

### Schema-Level Alignment Override

Individual schemas can override the global vertical alignment:

```yaml
annotation_schemes:
  - annotation_type: text
    name: notes
    layout:
      align_self: "stretch"   # Override for this form only
```

## Background Colors

### Group Background Colors

Groups use alternating background colors for visual distinction:

```yaml
layout:
  styling:
    group_background_odd: "#fafafa"    # Odd groups (1st, 3rd, etc.)
    group_background_even: "#f8f9fc"   # Even groups (2nd, 4th, etc.)
```

**Default colors:**
- Odd groups: `#fafafa` (very subtle warm gray)
- Even groups: `#f8f9fc` (very subtle cool blue-gray)

### Per-Group Background Color

Override the background color for a specific group:

```yaml
layout:
  groups:
    - id: "required"
      title: "Required Fields"
      background_color: "#fff8f0"    # Custom warm tint
      schemas:
        - "sentiment"

    - id: "optional"
      title: "Optional Fields"
      background_color: "#f0f8ff"    # Custom cool tint
      schemas:
        - "comments"
```

### Uniform Background Color

Use the same background for all groups:

```yaml
layout:
  styling:
    group_background_odd: "#f5f5f5"
    group_background_even: "#f5f5f5"   # Same as odd
```

## Padding Options

### Group Padding

Control spacing inside group containers:

```yaml
layout:
  styling:
    group_padding: "0.5rem 0.75rem"    # Default: vertical horizontal
```

Accepts CSS padding values:
- Single value: `"0.5rem"` (all sides)
- Two values: `"0.5rem 0.75rem"` (vertical horizontal)
- Four values: `"0.5rem 0.75rem 0.5rem 0.75rem"` (top right bottom left)

### Form Padding

Control spacing inside individual form containers:

```yaml
layout:
  styling:
    form_padding: "0.375rem 0.5rem"    # Default
```

### Compact Layout

For a more compact appearance with minimal spacing:

```yaml
layout:
  grid:
    gap: "0.5rem"
    row_gap: "0.5rem"

  styling:
    group_padding: "0.25rem 0.5rem"
    form_padding: "0.25rem 0.375rem"
```

### Spacious Layout

For a more relaxed appearance with extra breathing room:

```yaml
layout:
  grid:
    gap: "1.5rem"
    row_gap: "1.5rem"

  styling:
    group_padding: "1rem 1.25rem"
    form_padding: "0.75rem 1rem"
```

## Complete Example

```yaml
# config.yaml with advanced styling
annotation_task_name: "Styled Annotation Task"

layout:
  grid:
    columns: 3
    gap: "0.75rem"
    row_gap: "0.75rem"

  styling:
    # Alignment
    align_items: "start"
    content_align: "left"

    # Background colors
    group_background_odd: "#fafafa"
    group_background_even: "#f0f7ff"

    # Padding
    group_padding: "0.5rem 0.75rem"
    form_padding: "0.375rem 0.5rem"

  groups:
    - id: "classification"
      title: "Classification"
      description: "Required annotations"
      schemas:
        - "sentiment"
        - "topic"

    - id: "details"
      title: "Additional Details"
      collapsible: true
      background_color: "#f5fff5"    # Custom green tint for this group
      schemas:
        - "confidence"
        - "notes"

annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: "Sentiment"
    labels: [Positive, Negative, Neutral]

  - annotation_type: multiselect
    name: topic
    description: "Topics"
    labels: [Politics, Sports, Tech]
    layout:
      columns: 2

  - annotation_type: radio
    name: confidence
    description: "Confidence"
    labels: [High, Medium, Low]

  - annotation_type: text
    name: notes
    description: "Notes"
    layout:
      columns: 2
      align_self: "stretch"
```

## Default Values Reference

| Option | Default | Description |
|--------|---------|-------------|
| `align_items` | `"start"` | Vertical alignment of forms in grid |
| `content_align` | `"left"` | Horizontal alignment within forms |
| `group_background_odd` | `"#fafafa"` | Background color for odd groups |
| `group_background_even` | `"#f8f9fc"` | Background color for even groups |
| `group_padding` | `"0.5rem 0.75rem"` | Padding inside group containers |
| `form_padding` | `"0.375rem 0.5rem"` | Padding inside form containers |

## CSS Custom Properties

For advanced users, these CSS custom properties can be overridden via custom CSS:

```css
:root {
  --layout-columns: 2;
  --layout-gap: 1rem;
  --layout-row-gap: 0.75rem;
  --layout-align: start;
  --group-bg-odd: #fafafa;
  --group-bg-even: #f8f9fc;
  --group-padding: 0.5rem 0.75rem;
  --form-padding: 0.375rem 0.5rem;
}
```

## Related Documentation

- [Form Layout](form_layout.md) - Basic layout configuration
- [Annotation Schemas](schemas_and_templates.md) - Schema configuration
- [Configuration Reference](configuration.md) - Full config options
