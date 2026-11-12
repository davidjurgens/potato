# Agent Annotation Task Recipes

Ready-to-run configurations for common agent-evaluation tasks, composed from
Potato's existing schemas plus the [turn-level annotation
framework](turn_level_annotation.md) and the
[multi-agent discussion display](multi_agent_discussion.md). Each recipe is a
self-contained example directory — copy it and swap in your data.

All recipes run from the repository root:

```bash
python potato/flask_server.py start examples/agent-traces/<recipe>/config.yaml -p 8000
```

## Debate Judging — `examples/agent-traces/debate-judging/`

Judge structured debates between agents.

| Concern | Schema |
|---------|--------|
| Winner verdict | `radio` (pro / con / draw) |
| Per-side scoring | two `rubric_eval` grids (evidence, rebuttal, consistency) |
| Per-turn argument strength | `likert` with `turn_level: true`, bound to the debater agents |
| Debate structure | `consensus_tracking` with `acts: [claim, rebuttal, concession, ruling]` |

## Plan-Quality Review — `examples/agent-traces/plan-review/`

Review an agent's plan **before execution** — approve, flag risks, or fix it.

| Concern | Schema |
|---------|--------|
| Plan quality | `rubric_eval` (completeness, ordering, efficiency, safety) |
| Per-step risk flags | `multiselect` with `turn_level: true` (irreversible, needs_permission, …) |
| Verdict | `radio` (approve / approve_with_edits / reject) |
| Plan correction | `trajectory_edit` (diffs + SFT/DPO export) |

## Negotiation Review — `examples/agent-traces/negotiation-review/`

Annotate agent-vs-agent negotiations for outcome and process.

| Concern | Schema |
|---------|--------|
| Move structure | `consensus_tracking` with `acts: [offer, counter_offer, accept, reject, concession]` |
| Per-turn tactics | `multiselect` with `turn_level: true` (anchoring, threat, value creation, …) |
| Outcome | `radio` (deal / no_deal) + `slider` (surplus split) + `likert` (fairness) |
| Efficiency | `radio` (value left on the table?) |

## Safety Escalation Review — `examples/agent-traces/safety-escalation/`

Rapid safety triage of agent traces.

| Concern | Schema |
|---------|--------|
| Fast triage | `triage` (Safe / Escalate / Unsure, keyboard-driven) |
| Per-turn violations | `multiselect` with `turn_level: true` (overstepped permissions, destructive action, injection followed, …) |
| Failure origin | `failure_attribution` (responsible agent + decisive step + reason) |
| Severity | `radio` (none / low / medium / high) |

## Context-Use Annotation — `examples/agent-traces/context-attribution/`

How did the agent use its available context/memory?

| Concern | Schema |
|---------|--------|
| Per-turn attribution | `context_attribution` — tag turns as used_context_correctly / hallucinated_context / ignored_context, with click-to-link to the source turn |
| Overall memory quality | `likert` |
| Worst failure | `radio` (forgot constraint / invented detail / stale state) |

The `context_attribution` schema shares its turn-tagging + cross-turn-link
machinery with `consensus_tracking`; both store
`[{"turn": i, "act": ..., "ref": j, "agent_id": ...}]`.

```yaml
instance_display:
  fields:
    - key: conversation
      type: dialogue
      display_options:
        show_turn_numbers: true

annotation_schemes:
  - annotation_type: context_attribution
    name: memory_use
    description: "How did the agent use its context?"
    turns_key: conversation
```

| Option | Default | Description |
|--------|---------|-------------|
| `turns_key` | `conversation` | Instance field that holds the list of turns |
| `acts` | `[used_context_correctly, hallucinated_context, ignored_context]` | Tags the annotator can put on a turn |
| `linked_acts` | `[used_context_correctly, hallucinated_context]` | Tags that then ask the annotator to click the source turn. A tag not listed here is stored without a `ref` |
| `hint` | A sentence explaining the three default tags | HTML shown above the turns. Change it when you change `acts` |

## Building Your Own Recipe

1. Pick a display: `dialogue`, `agent_trace`, `multi_agent_discussion`,
   `coding_trace`, `web_agent_trace`, `eval_trace`.
2. Add whole-trace schemas for outcomes (radio/likert/rubric_eval/…).
3. Add `turn_level: true` schemas for anything judged per turn, filtered by
   `speakers` / `agents` / `step_types` / `tools`.
4. Add structural schemas where needed: `consensus_tracking` (acts + links),
   `tool_call_review` (per-call verdicts), `process_reward` (PRM labels),
   `trajectory_eval` / `trajectory_edit` (error taxonomy / correction).

## Related Documentation

- [Turn-Level Annotation](turn_level_annotation.md)
- [Multi-Agent Discussion](multi_agent_discussion.md)
- [Agent Traces](agent_traces.md)
