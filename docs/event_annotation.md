# Event Annotation

Event annotation enables the creation of N-ary event structures for information extraction tasks. Events consist of:

- **Trigger span**: The word or phrase that indicates the event (e.g., "attacked", "hired", "traveled")
- **Argument spans**: Entity spans with typed semantic roles (e.g., attacker, target, weapon)

This annotation type is commonly used for:
- Information extraction (IE)
- Event detection and extraction
- Semantic role labeling
- Knowledge graph construction

## Configuration

Event annotation requires a span annotation schema to be defined first, which provides the entity spans that can be used as triggers and arguments.

### Basic Configuration

```yaml
annotation_schemes:
  # Step 1: Define entity spans
  - annotation_type: span
    name: entities
    description: "Label entities in the text"
    labels:
      - name: PERSON
        color: "#3b82f6"
      - name: ORGANIZATION
        color: "#10b981"
      - name: LOCATION
        color: "#f59e0b"
      - name: WEAPON
        color: "#ef4444"
      - name: EVENT_TRIGGER
        color: "#8b5cf6"
        tooltip: "Words indicating events"

  # Step 2: Define event types and arguments
  - annotation_type: event_annotation
    name: events
    description: "Annotate events with triggers and arguments"
    span_schema: entities  # Reference to span schema
    event_types:
      - type: "ATTACK"
        color: "#dc2626"
        trigger_labels: ["EVENT_TRIGGER"]
        arguments:
          - role: "attacker"
            entity_types: ["PERSON", "ORGANIZATION"]
            required: true
          - role: "target"
            entity_types: ["PERSON", "ORGANIZATION", "LOCATION"]
            required: true
          - role: "weapon"
            entity_types: ["WEAPON"]
            required: false
```

### Configuration Options

#### Event Types

Each event type defines:

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `type` | string | Yes | Event type name (e.g., "ATTACK", "HIRE") |
| `color` | string | No | Color for visualization (default: auto-assigned) |
| `trigger_labels` | list | No | Span labels allowed as triggers (empty = any span) |
| `arguments` | list | Yes | List of argument definitions |

#### Arguments

Each argument defines:

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `role` | string | Yes | Semantic role name (e.g., "attacker", "target") |
| `entity_types` | list | No | Span labels allowed for this role (empty = any span) |
| `required` | boolean | No | Whether this argument must be filled (default: false) |

#### Visual Display

```yaml
visual_display:
  enabled: true           # Show arc visualization (default: true)
  arc_position: above     # Position of arcs: "above" (default)
  show_labels: true       # Show role labels on arcs (default: true)
```

## Usage Workflow

1. **Create entity spans**: First, annotate entity spans using the span annotation tool (click and drag to select text, then choose a label).

2. **Select event type**: Click on an event type button (e.g., "ATTACK") to enter event creation mode.

3. **Select trigger**: Click on a span to set it as the event trigger. If `trigger_labels` is configured, only spans with matching labels can be selected.

4. **Assign arguments**: For each argument role, click the role button to activate it, then click on a span to assign it to that role. Required arguments must be filled before the event can be created.

5. **Create event**: Once all required arguments are filled, click "Create Event" to save the event.

6. **View events**: Created events appear in the "Existing Events" section with their triggers and arguments listed.

## Data Format

### Input

Event annotation works with any text-based data format:

```json
[
  {
    "id": "event_1",
    "text": "John attacked the building with a rifle."
  }
]
```

### Output

Events are stored with the following structure:

```json
{
  "event_annotations": [
    {
      "id": "event_abc123",
      "schema": "events",
      "event_type": "ATTACK",
      "trigger_span_id": "span_xyz789",
      "arguments": [
        {"role": "attacker", "span_id": "span_def456"},
        {"role": "target", "span_id": "span_ghi012"},
        {"role": "weapon", "span_id": "span_jkl345"}
      ],
      "properties": {
        "color": "#dc2626",
        "trigger_text": "attacked",
        "trigger_label": "EVENT_TRIGGER"
      }
    }
  ]
}
```

## Complete Example

See the `simple-event-annotation` example in the project hub:

```bash
python potato/flask_server.py start examples/span/event-annotation/config.yaml -p 8000 --debug --debug-phase annotation
```

This example demonstrates:
- Entity span annotation (PERSON, ORGANIZATION, LOCATION, WEAPON, EVENT_TRIGGER)
- Three event types (ATTACK, HIRE, TRAVEL)
- Required and optional arguments
- Entity type constraints on arguments
- Visual arc display

## Tips

### Defining Event Types

1. **Use descriptive type names**: Choose clear, unambiguous event type names that reflect the semantic meaning (e.g., "ATTACK" rather than "TYPE_1").

2. **Constrain triggers appropriately**: Use `trigger_labels` to limit which spans can be triggers. For verb-based events, create a dedicated "EVENT_TRIGGER" label.

3. **Balance required vs optional arguments**: Mark core arguments as required, but allow optional arguments for additional context that may not always be present.

### Entity Type Constraints

Use `entity_types` to enforce semantic constraints:
- An "attacker" should typically be a PERSON or ORGANIZATION
- A "weapon" should be labeled as WEAPON
- This helps annotators avoid errors and ensures consistent annotations

### Visual Display

The arc visualization shows:
- A **hub** (filled circle) at the trigger position
- **Spokes** (arrows) connecting to each argument
- **Role labels** on each spoke
- Events are color-coded by type

Multiple events are stacked vertically to avoid overlap.

## Related Documentation

- [Span Annotation](span_annotation.md) - Required for defining entity spans
- [Span Link](span_linking.md) - Alternative for binary relationships
- [Coreference Annotation](coreference_annotation.md) - For entity coreference
