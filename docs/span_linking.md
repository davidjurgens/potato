# Span Linking Annotation

Span linking allows annotators to create typed relationships between spans (text segments) that have already been annotated. This is useful for relation extraction tasks where you need to identify how entities relate to each other, such as "PERSON works_for ORGANIZATION" or "PERSON collaborates_with PERSON".

## Overview

The span linking feature provides:

- **Typed relationships**: Define multiple link types with different colors and constraints
- **Directed and undirected links**: Support for both directional relationships (e.g., "WORKS_FOR") and symmetric relationships (e.g., "COLLABORATES_WITH")
- **N-ary links**: Create links between multiple spans (not just pairs)
- **Visual arc display**: See relationships rendered as colored arcs above the text
- **Label constraints**: Restrict which span labels can be sources or targets for each link type

## Configuration

### Basic Setup

To use span linking, you need two annotation schemes in your configuration:

1. A `span` schema to annotate the entities
2. A `span_link` schema to annotate relationships between those entities

```yaml
annotation_schemes:
  # First, define the span schema for named entities
  - annotation_type: span
    name: entities
    description: "Highlight named entities"
    labels:
      - name: "PERSON"
        color: "#3b82f6"
      - name: "ORGANIZATION"
        color: "#22c55e"
      - name: "LOCATION"
        color: "#f59e0b"
    sequential_key_binding: true

  # Then, define the span_link schema for relationships
  - annotation_type: span_link
    name: relations
    description: "Annotate relationships between entities"
    span_schema: entities  # References the span schema above
    link_types:
      - name: "WORKS_FOR"
        directed: true
        allowed_source_labels: ["PERSON"]
        allowed_target_labels: ["ORGANIZATION"]
        color: "#dc2626"
      - name: "COLLABORATES_WITH"
        directed: false
        allowed_source_labels: ["PERSON"]
        allowed_target_labels: ["PERSON"]
        color: "#06b6d4"
```

### Configuration Options

#### Required Fields

| Field | Description |
|-------|-------------|
| `annotation_type` | Must be `"span_link"` |
| `name` | Unique identifier for the schema |
| `description` | Description shown to annotators |
| `span_schema` | Name of the span annotation schema to link (must match the `name` of a span schema) |
| `link_types` | Array of link type definitions |

#### Link Type Options

Each link type can have the following properties:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | **Required.** Name/label for the link type |
| `directed` | boolean | Whether the link is directional. Default: `false` |
| `color` | string | Hex color code for the link (e.g., `"#dc2626"`) |
| `allowed_source_labels` | array | Span labels that can be the source/first span |
| `allowed_target_labels` | array | Span labels that can be the target/last span |
| `max_spans` | integer | Maximum number of spans in this link type (for n-ary links) |

#### Visual Display Options

```yaml
visual_display:
  enabled: true        # Show arc visualization
  arc_position: "above"  # Position of arcs ("above" or "below")
  show_labels: true    # Show link type labels on arcs
```

## Usage

### Creating Spans

1. First, annotate the text by selecting span labels and highlighting text
2. Each highlighted span becomes available for linking

### Creating Links

1. Select a link type from the available options
2. Click on spans to add them to the current link (selected spans are highlighted)
3. Click "Create Link" to finalize the link
4. For directed links, the first span selected is the source and the last is the target

### Viewing Links

- Created links appear in the "Existing Links" section
- If visual display is enabled, arcs are drawn above the text connecting linked spans
- Arcs are color-coded by link type

### Deleting Links

- Click the delete button (×) next to any link in the "Existing Links" section

## Example

See the complete working example at:
- Config: `project-hub/simple_examples/simple-span-linking/config.yaml`
- Data: `project-hub/simple_examples/simple-span-linking/data.json`

To run:
```bash
cd project-hub/simple_examples
python ../../potato/flask_server.py start simple-span-linking/config.yaml -p 9001
```

## Data Format

### Input Data

Standard text data with an ID and text field:

```json
[
  {
    "id": "item_1",
    "text": "John Smith works at Google as a senior engineer."
  }
]
```

### Output Format

Annotations are saved with both span annotations and link annotations:

```json
{
  "id": "item_1",
  "text": "John Smith works at Google as a senior engineer.",
  "entities": [
    {"start": 0, "end": 10, "label": "PERSON", "text": "John Smith"},
    {"start": 20, "end": 26, "label": "ORGANIZATION", "text": "Google"}
  ],
  "relations": [
    {
      "link_type": "WORKS_FOR",
      "span_ids": ["span_abc123", "span_def456"],
      "direction": "directed"
    }
  ]
}
```

## Constraints and Validation

### Label Constraints

You can restrict which span labels can participate in each link type:

```yaml
link_types:
  - name: "WORKS_FOR"
    directed: true
    allowed_source_labels: ["PERSON"]      # Only PERSON can be source
    allowed_target_labels: ["ORGANIZATION"]  # Only ORGANIZATION can be target
```

When constraints are violated, the UI will show an error message and prevent link creation.

### N-ary Links

By default, links connect exactly 2 spans. For relationships involving more entities, use `max_spans`:

```yaml
link_types:
  - name: "MEETING"
    directed: false
    max_spans: 5  # Allow up to 5 participants
    allowed_source_labels: ["PERSON"]
    allowed_target_labels: ["PERSON"]
```

## Tips

1. **Annotate spans first**: Make sure to create span annotations before attempting to link them
2. **Use colors effectively**: Choose distinct colors for different link types to make the visualization clear
3. **Consider direction**: Use directed links when the relationship has a clear direction (e.g., "supervises", "works_for")
4. **Keyboard shortcuts**: Span labels support keyboard shortcuts (1, 2, 3...) for faster annotation
