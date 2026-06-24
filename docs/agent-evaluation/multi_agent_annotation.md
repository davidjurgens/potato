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
