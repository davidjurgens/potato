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

## Related documentation

- [Failure-Mode Taxonomy (MAST)](failure_taxonomy.md) — tag *how* it failed
- [Agent Traces](agent_traces.md) — the trace display
- [Trajectory Evaluation](trajectory_eval.md) — per-step error annotation
