# Turn-Level Annotation

Turn-level annotation lets you apply an annotation scheme *per turn* (or per
step) of a conversation or agent trace, instead of once per instance. Any
supported scheme can be bound to a declarative filter — by speaker, agent,
step type, tool name, or turn range — and its widget is rendered inline
inside every matching turn.

This is the general-purpose successor to the dialogue display's
`per_turn_ratings` option: it works on multiple display types, supports more
widget types than numeric scales, and stores values under stable turn ids.

## Quick Start

```yaml
annotation_schemes:
  - annotation_type: multiselect
    name: turn_errors
    description: "Errors in this turn"
    labels: [hallucination, ignored_context, contradiction]
    turn_level: true
    turn_binding:
      field: conversation        # instance_display field to attach to
      speakers: ["Assistant"]    # only Assistant turns get the widget
```

Run the complete example:

```bash
python potato/flask_server.py start examples/agent-traces/per-turn-binding/config.yaml -p 8000
```

## Supported Schema Types

`turn_level: true` is supported for compact widget types:

| Type | Turn widget |
|------|-------------|
| `radio` | chip row (single-select, click again to clear) |
| `multiselect` | chip row (multi-select) |
| `likert` | numbered scale chips with min/max labels |
| `slider` | inline range slider |
| `select` | dropdown |
| `textbox` | inline comment box |
| `number` | number input |

Complex interactive schemas (`span`, `image_annotation`, `tool_call_review`,
…) remain trace-level; configuring them with `turn_level: true` is a config
error.

## Supported Display Types

Turn slots render on turn-based displays:

- `dialogue` — slot appears under each matching turn (coexists with legacy
  `per_turn_ratings`)
- `agent_trace` — slot appears inside each matching step card
- `multi_agent_discussion` — see [Multi-Agent Discussion](multi_agent_discussion.md)

## `turn_binding` Reference

All keys are optional; omitted filters match every turn. Present filters AND
together.

```yaml
turn_binding:
  field: conversation      # instance_display field key. Omit to bind to all
                           # turn-capable fields.
  speakers: ["Assistant"]  # turn speaker must be in this list
  agents: [researcher]     # turn agent_id must be in this list (multi-agent traces)
  step_types: [action]     # normalized step type: thought | action |
                           # observation | system | error
  tools: [search, browser] # tool name of the call (from an explicit `tool`
                           # key, tool_calls, or `tool(args)` text)
  turn_range: [0, 50]      # inclusive index range over normalized turns
  placement: inline        # inline (default) — widget always visible
                           # drawer — collapsed behind an "annotate" button;
                           # use for long traces or many bound schemes
```

## Stable Turn IDs and Storage

Each per-turn value is stored under a stable turn id:

- If the turn dict carries an explicit `turn_id` (or `step_id`), that id is
  used.
- Otherwise the id is `t{index}` over the display's normalized turn sequence.

Values round-trip through the standard annotation pipeline as a single JSON
document per scheme:

```json
{"v": 1, "schema_type": "multiselect",
 "turns": {
   "t3": {"values": ["hallucination"], "speaker": "Assistant", "step_type": "thought"},
   "s9": {"value": 4, "speaker": "Agent (Action)", "step_type": "action"}
 }}
```

Each turn entry snapshots `speaker` / `step_type` (and `agent_id` when
present) at annotation time, so downstream consumers can detect drift if the
underlying trace data is later edited.

Single-value widgets store `value`; `multiselect` stores `values` (a list).

## Export

Use `potato.server_utils.turn_annotations.flatten_turn_annotation` to flatten
a stored blob into one row per `(schema, turn_id)`:

```python
from potato.server_utils.turn_annotations import flatten_turn_annotation

rows = flatten_turn_annotation("turn_errors", stored_json)
# [{"schema": "turn_errors", "turn_id": "t3",
#   "values": ["hallucination"], "speaker": "Assistant", ...}]
```

## Caveats

- **Span targets**: turn widgets add text to the display container, so
  binding turn-level schemes onto a `span_target: true` field can misalign
  span offsets (the same caveat applies to `per_turn_ratings`). The config
  validator warns about this combination — prefer separate fields for span
  annotation and turn-level annotation.
- **Keybindings** are not assigned to turn-level schemes (the widget repeats
  once per turn, so a single key cannot address a specific turn).
- **Required-field validation** does not apply to turn-level schemes: any
  subset of turns may be annotated.
- **If a trace is edited** after annotation (turns inserted/removed),
  index-based ids (`t{index}`) will shift. Provide explicit `turn_id` values
  in your data when traces may change.

## Relationship to Other Per-Step Features

| Feature | Use when |
|---------|----------|
| `turn_level` binding (this page) | attach standard rating/tagging/comment widgets to filtered turns of any turn display |
| `per_turn_ratings` (dialogue display option) | legacy numeric-scale-only ratings; still supported |
| `tool_call_review` schema | structured per-tool-call verdicts with argument inspection |
| `process_reward` schema | PRM-style per-step reward labels with first-error cascade |
| `trajectory_eval` schema | per-step error taxonomy + severity + rationale |

## Related Documentation

- [Agent Traces](agent_traces.md)
- [Multi-Agent Discussion](multi_agent_discussion.md)
- [Trajectory Evaluation](trajectory_evaluation.md)
