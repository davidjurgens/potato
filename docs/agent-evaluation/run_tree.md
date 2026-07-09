# Sub-Agent Run Tree

Orchestrator-style agents delegate to sub-agents and tools, producing traces
with real *hierarchy* — a root run spawning researcher/writer/booking runs,
each spawning tool calls. A flat step list hides that structure. The **run
tree** preserves it and renders it as an interactive sidebar next to the
`agent_trace` display: click a run to filter the step list to the turns that
run (and its sub-runs) produced.

## Where the run tree comes from

Trace converters preserve hierarchy automatically:

- **LangChain/LangSmith** (`langchain` format): nested `child_runs` become
  tree nodes; every conversation turn is tagged with the run that produced it.
- **OpenTelemetry** (`otel` format): `parent_span_id` links become the tree;
  spans are classified as `llm` / `tool` / `chain` from their attributes.
- **potato_trace SDK**: `Run.parent_run_id` serializes into the LangSmith
  payload shape, so SDK-captured traces carry hierarchy end to end.

You can also provide it directly in your data. The canonical shape is a flat
list of nodes under a top-level `run_tree` key, with turns carrying `run_id`:

```json
{
  "id": "trace-1",
  "conversation": [
    {"speaker": "Agent (Thought)", "text": "Delegating research…", "run_id": "run-orchestrator"},
    {"speaker": "Agent (Action)", "text": "search(q)", "run_id": "run-search-1"}
  ],
  "run_tree": [
    {"id": "run-orchestrator", "parent_id": null, "name": "orchestrator",
     "run_type": "chain", "status": "success", "turn_range": [0, 8]},
    {"id": "run-search-1", "parent_id": "run-orchestrator", "name": "search",
     "run_type": "tool", "status": "error", "turn_range": [1, 1]}
  ]
}
```

`turn_range` is the inclusive `[start, end]` range of conversation indexes the
run covers; `status` (`success`/`error`) renders as a colored dot.

## Display

The sidebar appears automatically on `agent_trace` fields whenever the item
carries a `run_tree` (opt out with `show_run_tree: false`):

```yaml
instance_display:
  fields:
    - key: conversation
      type: agent_trace
      display_options:
        show_run_tree: true    # default when run_tree data is present
```

Interactions:

- **Click a run** — steps produced by that run *and its descendants* stay
  highlighted, everything else dims, and the view scrolls to the first
  matching step.
- **Click again** — clears the filter.
- Nodes show a run-type badge (`chain`/`llm`/`tool`/`retriever`), the
  error/success dot, and their step range.

## Binding annotations to sub-agents

[Turn-level schemes](turn_level_annotation.md) can target specific runs with
the `runs` binding filter — e.g. rate delegation quality only on the
researcher sub-agent's turns:

```yaml
annotation_schemes:
  - annotation_type: likert
    name: delegation_quality
    description: "Sub-agent delegation quality"
    size: 5
    turn_level: true
    turn_binding:
      field: conversation
      runs: [run-researcher, run-writer]
```

`runs` matches each turn's `run_id` and ANDs with the other filters
(`speakers`, `agents`, `step_types`, `tools`, `turn_range`).

## Example

`examples/agent-traces/sub-agent-tree/` has two synthetic orchestrator traces
(a clean delegation and a failed-tool recovery case):

```bash
python potato/flask_server.py start examples/agent-traces/sub-agent-tree/config.yaml -p 8000
```

## Related

- [Turn-Level Annotation](turn_level_annotation.md) — the `runs` binding filter
- [Agent Traces](agent_traces.md) — the `agent_trace` display
- [Agent Traces](agent_traces.md) — live ingestion / webhook / SDK capture
