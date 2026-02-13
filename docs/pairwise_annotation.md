# Pairwise Comparison Annotation

The pairwise annotation schema allows annotators to compare two items side by side and indicate their preference. It supports two modes:

1. **Binary Mode**: Click on the preferred tile (A or B), with optional tie button
2. **Scale Mode**: Use a slider to rate how much one option is preferred over the other

## Use Cases

- Comparing model outputs (which response is better?)
- Preference learning for RLHF training data
- Quality comparison of translations, summaries, etc.
- A/B testing analysis
- Sentiment or intimacy comparisons

## Configuration

### Binary Mode (Default)

Binary mode displays two clickable tiles. Annotators click on their preferred option.

```yaml
annotation_schemes:
  - annotation_type: pairwise
    name: preference
    description: "Which response is better?"
    mode: binary  # Optional, default is "binary"

    # Data source - key in instance data containing items to compare
    items_key: "responses"  # Expects a list with 2+ items

    # Display options
    show_labels: true         # Show A/B labels (default: true)
    labels:                   # Custom labels (default: ["A", "B"])
      - "Response A"
      - "Response B"

    # Tie option (opt-in)
    allow_tie: true           # Show "No preference" button
    tie_label: "No preference"  # Custom tie button text

    # Keyboard shortcuts
    sequential_key_binding: true  # Enable 1/2/0 shortcuts (default: true)

    # Validation
    label_requirement:
      required: true  # Require selection before proceeding
```

### Scale Mode

Scale mode displays a slider between two items, allowing annotators to indicate the degree of preference.

```yaml
annotation_schemes:
  - annotation_type: pairwise
    name: preference_scale
    description: "Rate how much better A is than B"
    mode: scale

    items_key: "responses"

    # Display labels for the two items
    labels:
      - "Response A"
      - "Response B"

    # Scale configuration
    scale:
      min: -3           # Negative = prefer left item (A)
      max: 3            # Positive = prefer right item (B)
      step: 1           # Slider step increment
      default: 0        # Initial slider position

      # Endpoint labels
      labels:
        min: "A is much better"
        max: "B is much better"
        center: "Equal"

    label_requirement:
      required: true
```

## Data Format

The schema expects instance data with a list of items to compare:

```json
{"id": "1", "responses": ["Response A text", "Response B text"]}
{"id": "2", "responses": ["First option here", "Second option here"]}
```

The `items_key` configuration specifies which field contains the items to compare. The field should contain a list with at least 2 items.

## Output Format

### Binary Mode Output

When annotator selects option A:
```json
{
  "preference": {
    "selection": "A"
  }
}
```

When annotator selects tie:
```json
{
  "preference": {
    "selection": "tie"
  }
}
```

### Scale Mode Output

The scale value indicates degree of preference:
- **Negative values**: Left item (A) is preferred
- **Zero**: No preference / Equal
- **Positive values**: Right item (B) is preferred

```json
{
  "preference_scale": {
    "scale_value": "-2"
  }
}
```

## Keyboard Shortcuts

In binary mode with `sequential_key_binding: true`:
- **1**: Select option A
- **2**: Select option B
- **0**: Select tie/no preference (if `allow_tie: true`)

Scale mode does not have keyboard shortcuts (uses slider interaction).

## Styling

The pairwise annotation uses CSS variables from the theme system:
- `--primary`: Selected tile border and accent color
- `--border`: Default tile border color
- `--card`: Tile background color
- `--muted`: Tie button background

### Custom Styling

Add custom CSS to your `site_dir/static/custom.css`:

```css
/* Make tiles taller */
.pairwise-tile {
  min-height: 200px;
}

/* Change selected tile highlight */
.pairwise-tile.selected {
  border-color: #10b981;
  background-color: rgba(16, 185, 129, 0.1);
}
```

## Examples

### Basic Binary Comparison

```yaml
annotation_schemes:
  - annotation_type: pairwise
    name: quality
    description: "Which text is higher quality?"
    labels: ["Text A", "Text B"]
    allow_tie: true
```

### Preference Scale with Custom Range

```yaml
annotation_schemes:
  - annotation_type: pairwise
    name: sentiment_comparison
    description: "Compare the sentiment of these two statements"
    mode: scale
    labels: ["Statement A", "Statement B"]
    scale:
      min: -5
      max: 5
      step: 1
      labels:
        min: "A is much more positive"
        max: "B is much more positive"
        center: "Equal sentiment"
```

### Multiple Pairwise Comparisons

You can include multiple pairwise schemas to compare on different dimensions:

```yaml
annotation_schemes:
  - annotation_type: pairwise
    name: fluency
    description: "Which response is more fluent?"
    labels: ["Response A", "Response B"]

  - annotation_type: pairwise
    name: relevance
    description: "Which response is more relevant?"
    labels: ["Response A", "Response B"]

  - annotation_type: pairwise
    name: overall
    description: "Which response is better overall?"
    labels: ["Response A", "Response B"]
    allow_tie: true
```

## Running the Example

```bash
# Binary mode example
python potato/flask_server.py start project-hub/simple_examples/simple-pairwise-comparison/config.yaml -p 8000

# Scale mode example
python potato/flask_server.py start project-hub/simple_examples/simple-pairwise-scale/config.yaml -p 8002
```

Then navigate to `http://localhost:8000` and register/login to start annotating.

## Related Documentation

- [Annotation Schemas](schemas_and_templates.md) - Overview of all annotation types
- [List as Text Display](configuration.md#list-as-text) - Display lists with prefixes
- [Display Types](configuration.md#display-types) - Different ways to display content
