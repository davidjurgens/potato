# Annotation Form Layout System

This guide explains how to configure the layout of annotation forms using the `layout` configuration section. The layout system provides control over how annotation schemas are arranged on the page.

## Overview

The form layout system allows you to:

- **Configure grid columns**: Control how many columns forms are arranged in
- **Control column spanning**: Make forms span multiple columns
- **Group schemas**: Organize related schemas under collapsible headers
- **Order forms**: Explicitly control the order of forms
- **Set responsive breakpoints**: Customize mobile/tablet behavior

Advanced styling options (colors, padding, alignment) are covered in the [Advanced Styling Options](#advanced-styling-options) section below.

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

## Advanced Styling Options

Advanced options allow fine-grained control over:

- **Alignment**: Horizontal and vertical positioning of form content
- **Background colors**: Visual distinction between groups
- **Padding**: Spacing within forms and groups
- **Form styling**: Individual form appearance

### Styling Configuration

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

### Alignment Options

#### Vertical Alignment (`align_items`)

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

#### Horizontal Content Alignment (`content_align`)

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

#### Schema-Level Alignment Override

Individual schemas can override the global vertical alignment:

```yaml
annotation_schemes:
  - annotation_type: text
    name: notes
    layout:
      align_self: "stretch"   # Override for this form only
```

### Background Colors

#### Group Background Colors

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

#### Per-Group Background Color

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

#### Uniform Background Color

Use the same background for all groups:

```yaml
layout:
  styling:
    group_background_odd: "#f5f5f5"
    group_background_even: "#f5f5f5"   # Same as odd
```

### Padding Options

#### Group Padding

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

#### Form Padding

Control spacing inside individual form containers:

```yaml
layout:
  styling:
    form_padding: "0.375rem 0.5rem"    # Default
```

#### Compact Layout

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

#### Spacious Layout

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

### Complete Advanced Styling Example

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

### Default Values Reference

| Option | Default | Description |
|--------|---------|-------------|
| `align_items` | `"start"` | Vertical alignment of forms in grid |
| `content_align` | `"left"` | Horizontal alignment within forms |
| `group_background_odd` | `"#fafafa"` | Background color for odd groups |
| `group_background_even` | `"#f8f9fc"` | Background color for even groups |
| `group_padding` | `"0.5rem 0.75rem"` | Padding inside group containers |
| `form_padding` | `"0.375rem 0.5rem"` | Padding inside form containers |

### CSS Custom Properties

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

- [Annotation Schemas](../annotation-types/schemas_and_templates.md) - Schema configuration
- [Configuration Reference](configuration.md) - Full config options
