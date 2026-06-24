# Multi-Agent Team Annotation

Annotating multi-agent systems needs more than a flat per-turn transcript — you
need to attribute outcomes to **which agent**, **which step**, and **which handoff**.
This page covers Potato's multi-agent-specific annotation surfaces (the M-series),
which build on the [agent trace](agent_traces.md) and [MAST taxonomy](failure_taxonomy.md).

## Failure attribution (`failure_attribution`)

Capture the **(responsible agent, decisive step, reason)** triple that the
failure-attribution literature needs (Zhang et al., *"Which Agent Causes Task
Failures and When?"*, ICML 2025; the Who&When dataset). The agent dropdown and step
picker are **populated from the trace's own turns** at render time, so the annotator
chooses from what actually happened.

```yaml
annotation_schemes:
  - annotation_type: failure_attribution
    name: attribution
    description: "If it failed: which agent, which step, and why?"
    steps_key: steps        # field in the instance data holding the turn list
    agent_key: agent        # which field of each turn names the agent
    # agents: [Planner, Coder, Reviewer]   # optional static list instead of deriving from the trace
```

Stored as `{"responsible_agent", "decisive_step", "reason"}`. Pair it with the
[agent trace display](agent_traces.md) so annotators see the interactions while
attributing the failure. A runnable example is at
`examples/agent-traces/failure-attribution/`:

```bash
python potato/flask_server.py start examples/agent-traces/failure-attribution/config.yaml -p 8000
```

## MAST tagging at step granularity (recipe)

You don't need a new schema to bind the [MAST taxonomy](failure_taxonomy.md) to the
exact step (and therefore the acting agent) where a failure occurred — configure the
existing per-step [`trajectory_eval`](trajectory_eval.md) schema with the 14 MAST
modes as its `error_types`, grouped by the three MAST categories. Annotators then tag
each turn with the precise failure mode instead of labeling the trace as a whole.
Pair it with `failure_attribution` (responsible agent) and `handoff_review`
(inter-agent edges) for full coverage.

```yaml
annotation_schemes:
  - annotation_type: trajectory_eval
    name: mast_steps
    description: "Tag each step with the MAST failure mode(s) it exhibits."
    steps_key: steps
    step_text_key: content
    error_types:
      - name: "Specification & System Design"
        subtypes: ["1.1 Disobey task specification", "1.2 Disobey role specification", "1.3 Step repetition", "1.4 Loss of conversation history", "1.5 Unaware of termination conditions"]
      - name: "Inter-Agent Misalignment"
        subtypes: ["2.1 Conversation reset", "2.2 Fail to ask for clarification", "2.3 Task derailment", "2.4 Information withholding", "2.5 Ignored other agent's input", "2.6 Reasoning-action mismatch"]
      - name: "Task Verification & Termination"
        subtypes: ["3.1 Premature termination", "3.2 No or incomplete verification", "3.3 Incorrect verification"]
```

Runnable example: `examples/agent-traces/mast-step-tagging/`.

## Interaction graph (`agent_interaction_graph`)

Render the whole run as a directed **interaction graph** — nodes are the agents,
edges are the message/handoff transitions between them (thicker = more frequent) —
and let the annotator mark the **critical path** (click a node) and flag
**problematic edges** (click an edge to cycle normal → critical → problematic). No
open competitor offers a clickable agent-interaction graph (cf. AgentGraph,
AAAI 2026). The graph is laid out automatically from the trace, so it needs no
precomputed coordinates.

```yaml
annotation_schemes:
  - annotation_type: agent_interaction_graph
    name: graph
    description: "Mark the critical path and flag any problematic handoffs."
    steps_key: steps
    agent_key: agent
```

Stored as `{"critical_nodes": [...], "edges": {"A->B": "problematic", ...}}`. Every
node and edge is keyboard-focusable and activates on Enter/Space, and a live text
summary lists critical nodes and flagged edges so meaning is never conveyed by color
alone (WCAG). Example: `examples/agent-traces/interaction-graph/`.

## Handoff review (`handoff_review`)

Treat every **handoff** — one agent passing control to another — as a first-class
object to annotate. Wherever the acting agent changes between consecutive turns,
Potato emits a handoff card `A → B`; the annotator flags inter-agent misalignment
and rates the handoff quality. Grounded in MAST's inter-agent failure modes, LACP
(Zhang et al., 2510.13821) and the "Echoing" phenomenon (2511.09710).

```yaml
annotation_schemes:
  - annotation_type: handoff_review
    name: handoffs
    description: "For each handoff: flag any misalignment and rate the quality."
    steps_key: steps
    agent_key: agent
    flags: [info_loss, dropped_constraint, garbling, goal_drift]   # customizable
    quality_scale: 5
```

Stored as a list of `{index, step, from, to, flags, quality}`. Handoffs are derived
from the trace at render time (no manual setup). Example:
`examples/agent-traces/handoff-review/`.

## Per-agent + per-team scorecard (`agent_scorecard`)

Score a run on **two levels at once** (MultiAgentBench, Zhou et al., ACL 2025,
2503.01935): each agent gets per-dimension scores (role fidelity, contribution,
coordination), the team gets shared-dimension scores, and optional milestones are
checked off. Agent rows are derived from the trace's own turns, so the matrix matches
who actually participated.

```yaml
annotation_schemes:
  - annotation_type: agent_scorecard
    name: scorecard
    description: "Score each agent, the team, and which milestones were reached."
    steps_key: steps
    agent_key: agent
    scale: 5
    agent_dimensions: [role fidelity, contribution, coordination]
    team_dimensions: [coordination, communication, efficiency]
    milestones: [plan produced, task delegated correctly, result verified]   # optional
```

Stored as `{"agents": {name: {dim: score}}, "team": {dim: score}, "milestones": {name: bool}}`.
Example: `examples/agent-traces/agent-scorecard/`.

## Tool / resource-contention timeline (`tool_contention`)

Visualize concurrent tool/resource use across agents on a multi-lane timeline (one
lane per agent) and flag concurrency failures — deadlock, circular wait, race
conditions, shared-resource collisions (DPBench, 2602.13255). **Contention regions**
where two calls touch the *same* resource at overlapping times are highlighted
across the lanes and listed for classification.

```yaml
annotation_schemes:
  - annotation_type: tool_contention
    name: contention
    description: "Classify each shared-resource contention region."
    calls_key: calls          # list of {agent, tool, start, end, resource}
    agent_key: agent
    resource_key: resource
    contention_labels: [deadlock, circular_wait, race_condition, benign]
```

Contentions are computed at render time (same `resource`, overlapping interval).
Stored as `{"contentions": {idx: label}}`. Example:
`examples/agent-traces/tool-contention/`.

## Tool-call review (`tool_call_review`)

Judge each **tool / function call** in a trace individually: was the right tool
chosen, were the arguments correct, was the ordering right? (mirrors BFCL v4 /
MCPMark). Tool calls are extracted from the trace steps at render time — each step's
`tool_calls`/`tool_call`/`action` becomes a card showing the tool name and
pretty-printed arguments, with a per-call verdict and notes.

```yaml
annotation_schemes:
  - annotation_type: tool_call_review
    name: tool_review
    description: "Judge each tool call: right tool? correct arguments?"
    steps_key: steps
    # verdict_options: [correct, wrong_tool, wrong_args, wrong_order]   # customizable
```

Stored as a list of `{index, step, tool, verdict, notes}`. Example:
`examples/agent-traces/tool-call-review/`.

## Related documentation

- [Failure-Mode Taxonomy (MAST)](failure_taxonomy.md) — tag *how* it failed
- [Agent Traces](agent_traces.md) — the trace display
- [Trajectory Evaluation](trajectory_eval.md) — per-step error annotation
