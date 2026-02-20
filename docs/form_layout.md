# Annotation Form Layout System

This guide explains how to configure the layout of annotation forms using the `layout` configuration section. The layout system provides control over how annotation schemas are arranged on the page.

## Overview

The form layout system allows you to:

- **Configure grid columns**: Control how many columns forms are arranged in
- **Control column spanning**: Make forms span multiple columns
- **Group schemas**: Organize related schemas under collapsible headers
- **Order forms**: Explicitly control the order of forms
- **Set responsive breakpoints**: Customize mobile/tablet behavior

For advanced styling options (colors, padding, alignment), see [Form Layout Advanced Options](form_layout_advanced.md).

## Basic Configuration

Add a `layout` section to your config file:

```yaml
layout:
  grid:
    columns: 2              # Number of columns (1-6, default: 2)
    gap: "1rem"             # Gap between items (CSS value)
```

## Grid Settings

Configure the overall grid layout:

```yaml
layout:
  grid:
    columns: 3              # 1-6 columns (default: 2)
    gap: "1rem"             # Gap between items (default: "1rem")
    row_gap: "0.75rem"      # Optional separate row gap
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `columns` | integer | 2 | Number of grid columns (1-6) |
| `gap` | string | "1rem" | Gap between grid items (CSS value) |
| `row_gap` | string | same as gap | Vertical gap between rows |

## Schema Grouping

Organize related schemas under visual groups with optional headers:

```yaml
layout:
  groups:
    - id: "primary"
      title: "Primary Classification"
      description: "Required annotations"
      collapsible: false
      schemas:
        - "sentiment"
        - "intent"

    - id: "secondary"
      title: "Additional Details"
      collapsible: true
      collapsed_default: false
      schemas:
        - "confidence"
        - "comments"
```

**Group options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | string | *required* | Unique identifier for the group |
| `schemas` | list | *required* | Schema names to include |
| `title` | string | none | Header title displayed above the group |
| `description` | string | none | Description text below the title |
| `collapsible` | boolean | false | Whether group can be collapsed |
| `collapsed_default` | boolean | false | Start in collapsed state |

## Explicit Ordering

Override the default config file order:

```yaml
layout:
  order:
    - "sentiment"
    - "intent"
    - "confidence"
    - "comments"
```

Forms are displayed in this order. Forms not listed appear after the ordered forms.

## Responsive Breakpoints

Customize when the layout collapses for smaller screens:

```yaml
layout:
  breakpoints:
    mobile: 480             # Collapse to 1 column below this width
    tablet: 768             # Reduce column spans below this width
```

**Default behavior:**
- Below mobile breakpoint (480px): All forms become single-column
- Between mobile and tablet (481-768px): Large spans (3-6) reduce to span 2

## Schema-Level Layout

Each annotation scheme can specify its own layout properties:

```yaml
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: "Sentiment"
    labels: [positive, neutral, negative]
    layout:
      columns: 1            # Column span (1-6, default: 1)
      rows: 1               # Row span (1-4, default: 1)
      order: 1              # Explicit order position
      min_width: "200px"    # Minimum width (CSS value)
      max_width: "400px"    # Maximum width (CSS value)
```

### Column Spanning

Make a form span multiple columns:

```yaml
- annotation_type: text
  name: comments
  description: "Comments"
  layout:
    columns: 2              # Span 2 columns of the grid
```

**Example: 3-column grid with mixed spans**

```yaml
layout:
  grid:
    columns: 3

annotation_schemes:
  # Takes 1 of 3 columns
  - name: sentiment
    layout:
      columns: 1

  # Takes 2 of 3 columns (same row)
  - name: topics
    layout:
      columns: 2

  # Takes all 3 columns (next row)
  - name: notes
    layout:
      columns: 3
```

### Row Spanning

Make a form span multiple rows (useful for tall content):

```yaml
- annotation_type: multiselect
  name: categories
  labels: [...]
  layout:
    rows: 2                 # Span 2 rows vertically
```

### Width Constraints

Set minimum and maximum widths:

```yaml
- annotation_type: likert
  name: rating
  layout:
    min_width: "300px"      # Prevent too-narrow rendering
    max_width: "500px"      # Limit maximum stretch
```

## Complete Example

```yaml
# config.yaml
annotation_task_name: "Multi-Aspect Annotation"

layout:
  grid:
    columns: 3
    gap: "1rem"

  groups:
    - id: "classification"
      title: "Classification"
      schemas:
        - "sentiment"
        - "topic"

    - id: "details"
      title: "Details"
      collapsible: true
      schemas:
        - "intensity"
        - "notes"

annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: "Sentiment"
    labels: [Positive, Negative, Neutral]

  - annotation_type: multiselect
    name: topic
    description: "Topics"
    labels: [Politics, Sports, Tech, Business]
    layout:
      columns: 2

  - annotation_type: likert
    name: intensity
    description: "Intensity"
    min_label: "Weak"
    max_label: "Strong"
    size: 5
    layout:
      columns: 2
      min_width: "300px"

  - annotation_type: text
    name: notes
    description: "Notes"
    layout:
      columns: 3
```

## Backward Compatibility

Existing configurations without a `layout` section continue to work exactly as before:

- Default 2-column grid layout
- Forms span 1 column by default
- Standard responsive behavior at 768px

## Troubleshooting

### Forms not arranging correctly

1. Check that `columns` values don't exceed `grid.columns`
2. Verify schema names in groups match `annotation_schemes`
3. Check browser console for JavaScript errors

### Groups not showing

1. Ensure group `id` values are unique
2. Check that `schemas` array contains valid schema names
3. Verify the layout config is properly indented in YAML

### Responsive issues

1. Test at different viewport widths
2. Check custom breakpoint values are reasonable
3. Verify CSS is loading correctly

## Related Documentation

- [Form Layout Advanced Options](form_layout_advanced.md) - Styling and alignment options
- [Annotation Schemas](schemas_and_templates.md) - Schema configuration
- [Configuration Reference](configuration.md) - Full config options
