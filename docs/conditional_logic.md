# Conditional Schema Branching (Display Logic)

Conditional schema branching allows you to show or hide annotation schemas based on user responses to other schemas. This is useful for:

- Follow-up questions when specific answers are selected
- Branching survey-style annotation flows
- Requiring additional details only when relevant
- Creating cleaner interfaces by hiding irrelevant options

## Quick Start

Add a `display_logic` block to any annotation scheme:

```yaml
annotation_schemes:
  # Primary question - always visible
  - annotation_type: radio
    name: contains_pii
    description: "Does this text contain PII?"
    labels:
      - name: "Yes"
      - name: "No"

  # Follow-up - only shown when "Yes" is selected above
  - annotation_type: text
    name: pii_explanation
    description: "Describe the PII found:"
    display_logic:
      show_when:
        - schema: contains_pii
          operator: equals
          value: "Yes"
```

## Configuration Reference

### Basic Structure

```yaml
display_logic:
  show_when:
    - schema: <schema_name>      # Name of the schema to watch
      operator: <operator>       # Comparison operator
      value: <value>             # Value(s) to compare against
      case_sensitive: false      # Optional, default: false
  logic: all                     # Optional: 'all' (AND) or 'any' (OR)
```

### Supported Operators

#### Value Comparison

| Operator | Description | Example |
|----------|-------------|---------|
| `equals` | Exact value match | `value: "Yes"` or `value: ["Yes", "Maybe"]` |
| `not_equals` | Value doesn't match | `value: "No"` |

#### Collection Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `contains` | List/text contains value | `value: "keyword"` |
| `not_contains` | Doesn't contain | `value: "spam"` |

#### Regex Matching

| Operator | Description | Example |
|----------|-------------|---------|
| `matches` | Regex pattern match | `value: "^[A-Z]{2}\\d{4}$"` |

#### Numeric Comparison (for sliders, number inputs)

| Operator | Description | Example |
|----------|-------------|---------|
| `gt` | Greater than | `value: 5` |
| `gte` | Greater than or equal | `value: 5` |
| `lt` | Less than | `value: 5` |
| `lte` | Less than or equal | `value: 5` |
| `in_range` | Within range (inclusive) | `value: [3, 7]` |
| `not_in_range` | Outside range | `value: [3, 7]` |

#### Emptiness Checks

| Operator | Description | Example |
|----------|-------------|---------|
| `empty` | Field is empty/not set | (no value needed) |
| `not_empty` | Field has a value | (no value needed) |

#### Text Length

| Operator | Description | Example |
|----------|-------------|---------|
| `length_gt` | Text length > value | `value: 50` |
| `length_lt` | Text length < value | `value: 10` |
| `length_in_range` | Length within range | `value: [10, 100]` |

## Examples

### 1. Single Condition

Show a text box when "Other" is selected:

```yaml
- annotation_type: multiselect
  name: categories
  description: "Select categories:"
  labels: [Category A, Category B, Other]

- annotation_type: text
  name: other_category
  description: "Describe the other category:"
  display_logic:
    show_when:
      - schema: categories
        operator: contains
        value: "Other"
```

### 2. Multiple Values (OR within condition)

Show when ANY of the specified values is selected:

```yaml
display_logic:
  show_when:
    - schema: rating
      operator: equals
      value: ["Bad", "Very Bad", "Terrible"]  # Matches any of these
```

### 3. Multiple Conditions with AND Logic

Show only when ALL conditions are met:

```yaml
display_logic:
  show_when:
    - schema: sentiment
      operator: equals
      value: "Negative"
    - schema: confidence
      operator: gte
      value: 7
  logic: all  # Both conditions must be true (default)
```

### 4. Multiple Conditions with OR Logic

Show when ANY condition is met:

```yaml
display_logic:
  show_when:
    - schema: urgent
      operator: equals
      value: "Yes"
    - schema: priority
      operator: in_range
      value: [8, 10]
  logic: any  # Either condition can be true
```

### 5. Numeric Range Branching

Show different questions based on slider value:

```yaml
# Low score follow-up
- annotation_type: text
  name: improvement_suggestions
  description: "What could be improved?"
  display_logic:
    show_when:
      - schema: quality_score
        operator: in_range
        value: [1, 3]

# High score follow-up
- annotation_type: text
  name: positive_feedback
  description: "What worked well?"
  display_logic:
    show_when:
      - schema: quality_score
        operator: in_range
        value: [8, 10]
```

### 6. Text Length Trigger

Show when the user provides a detailed response:

```yaml
- annotation_type: text
  name: initial_feedback
  description: "Brief feedback:"

- annotation_type: radio
  name: wants_detailed_review
  description: "Would you like a detailed review of your feedback?"
  labels: [Yes, No]
  display_logic:
    show_when:
      - schema: initial_feedback
        operator: length_gt
        value: 50
```

### 7. Regex Matching

Show a follow-up for specific patterns:

```yaml
display_logic:
  show_when:
    - schema: user_input
      operator: matches
      value: "error|exception|bug"
      case_sensitive: false
```

### 8. Chained Conditions (Multi-level Branching)

```yaml
annotation_schemes:
  # Level 1
  - annotation_type: radio
    name: main_category
    description: "Select main category:"
    labels: [Product, Service, General]

  # Level 2 - appears for "Product" selection
  - annotation_type: radio
    name: product_type
    description: "Product type:"
    labels: [Hardware, Software, Other]
    display_logic:
      show_when:
        - schema: main_category
          operator: equals
          value: "Product"

  # Level 3 - appears for "Software" product type
  - annotation_type: multiselect
    name: software_issues
    description: "Software issue types:"
    labels: [Bug, Feature Request, Performance, UI/UX]
    display_logic:
      show_when:
        - schema: product_type
          operator: equals
          value: "Software"
```

## Behavior Details

### Initial Visibility

Schemas with `display_logic` are **hidden by default** when the page loads. They become visible only when their conditions are met.

### Value Preservation

When a schema becomes hidden because its conditions are no longer met, the annotation values are **preserved** (not cleared). This allows users to change their primary answer and return to the same state without re-entering data.

### Stale Annotations

In the output, annotations for hidden schemas are tracked separately as "stale" to indicate they may no longer be relevant to the current selections.

### Smooth Animations

Show/hide transitions use smooth CSS animations (300ms). Users who prefer reduced motion will see instant transitions.

### Validation

- Schemas that are hidden are excluded from required field validation
- The configuration is validated at startup to detect:
  - Invalid operators
  - Missing referenced schemas
  - Circular dependencies

## Troubleshooting

### Schema Not Showing

1. **Check the schema name**: The `schema` field in conditions must exactly match the `name` of another schema.
2. **Check the value**: String comparisons are case-insensitive by default. Set `case_sensitive: true` if needed.
3. **Check the operator**: Use `contains` for multiselect (checking if a value is in the list of selected items), use `equals` for radio/select.
4. **Browser console**: Open browser developer tools and look for `[DisplayLogic]` messages.

### Circular Dependency Error

```
Display logic validation errors:
  - Circular dependency detected: schema_a -> schema_b -> schema_a
```

This means schema_a depends on schema_b AND schema_b depends on schema_a. Remove one of the dependencies to fix this.

### Debugging

Enable debug mode in your browser console:

```javascript
displayLogicManager.enableDebug();
```

This will log all condition evaluations to help diagnose issues.

## Complete Example

See the full example project at:
`project-hub/simple_examples/simple-conditional-logic/`

Run it with:
```bash
python potato/flask_server.py start project-hub/simple_examples/simple-conditional-logic/config.yaml -p 8000
```

## Technical Notes

### Files Involved

- `potato/server_utils/display_logic.py` - Core validation and evaluation logic
- `potato/static/display-logic.js` - Frontend condition evaluation
- `potato/static/display-logic.css` - Show/hide animations
- `potato/server_utils/schemas/registry.py` - Wraps schema HTML with display_logic attributes

### Performance

- Conditions are only evaluated when a relevant schema changes (not on every keystroke)
- Large forms with many conditional schemas perform well due to efficient dependency tracking
