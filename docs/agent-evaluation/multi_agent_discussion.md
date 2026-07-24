# Multi-Agent Discussion Annotation

Annotate conversations **between multiple agents** — debates, crew
coordination, agent-to-agent handoffs — with agent identity, message
addressees, reply threading, and discussion-structure tagging.

Potato treats multi-agent identity as first-class: converters populate
standardized `agent_id` / `addressee` / `role` keys on conversation turns,
the `multi_agent_discussion` display renders them, and turn-level bindings
and analytics can filter on them.

## Quick Start

```bash
python potato/flask_server.py start examples/agent-traces/multi-agent-discussion/config.yaml -p 8000
```

## The `multi_agent_discussion` Display

```yaml
instance_display:
  fields:
    - key: conversation
      type: multi_agent_discussion
      label: "Agent Discussion"
      display_options:
        show_turn_numbers: true
        show_legend: true        # agent chips; click to show/hide an agent
        show_addressees: true    # "→ critic" chips on directed messages
        thread_replies: true     # indent turns with reply_to under a connector
        collapse_environment: false
```

Features:

- **Agent legend** — one chip per agent with a deterministic color (hash of
  the agent id, stable across instances and sessions). Clicking a chip
  toggles that agent's turns, so an annotator can isolate one agent's
  contributions in a long discussion.
- **Per-agent color coding** — each turn gets its agent's color as border,
  avatar, and tint.
- **Addressee chips** — turns with an `addressee` key show who the message
  is directed at (populated automatically from AutoGen sender/receiver).
- **Reply threading** — turns with `reply_to` (referencing another turn's
  `turn_id`) are indented under a connector line.
- **Span annotation** — the display supports `span_target: true`.
- **Turn-level slots** — [turn-level bindings](turn_level_annotation.md)
  work here, including the `agents:` filter.

### Turn Data Format

A list of dicts; only `speaker`/`text` are required. Identity keys are the
standardized optional keys of the canonical trace format:

```json
{"speaker": "critic", "text": "I disagree because ...",
 "agent_id": "critic", "role": "critic",
 "addressee": "planner", "turn_id": "t3", "reply_to": "t1"}
```

When `agent_id` is absent, the speaker string is used as the agent identity,
so plain dialogue data renders sensibly.

## Trace Converters and Agent Identity

The multi-agent converter (`potato/trace_converter/`) populates identity keys
automatically:

| Source | agent_id | addressee | roster (`extra_fields["agents"]`) |
|--------|----------|-----------|------------------------------------|
| AutoGen | `sender` | `receiver` | all participants |
| CrewAI | step's `agent` role | — | `agents` list with goals |
| LangGraph | node name | — | all nodes |

Speaker strings are unchanged from previous releases, so existing configs and
displays keep working.

## The `consensus_tracking` Schema

Captures the *structure* of a deliberation — who proposed what, who
agreed/objected, where the decision landed:

```yaml
annotation_schemes:
  - annotation_type: consensus_tracking
    name: discussion_acts
    description: "Tag the discussion structure"
    turns_key: conversation          # instance field holding the turns
    # Optional customization:
    # acts: [proposal, agreement, disagreement, decision, concession]
    # linked_acts: [agreement, disagreement, concession]
```

Each turn card offers the configured acts. Choosing a *linked* act (e.g.
`agreement`) arms link mode — the next click on another turn records which
proposal the response refers to. Stored as:

```json
[{"turn": 4, "act": "agreement", "ref": 1, "agent_id": "critic"}]
```

For negotiation-style tasks, override the acts:

```yaml
    acts: [offer, counter_offer, accept, reject, concession]
    linked_acts: [counter_offer, accept, reject, concession]
```

## Per-Turn Ratings on Specific Agents

Combine with the turn-level framework to rate only certain agents' turns:

```yaml
  - annotation_type: likert
    name: contribution_quality
    description: "Contribution quality"
    min_label: "Off-topic"
    max_label: "Decisive"
    size: 5
    turn_level: true
    turn_binding:
      field: conversation
      agents: [planner, researcher, critic]   # skip moderator/environment
```

Stored values snapshot `agent_id`, enabling per-agent aggregation in exports.

## Related Schemas for Multi-Agent Work

| Schema | Purpose |
|--------|---------|
| `consensus_tracking` | discussion acts + cross-turn links (this page) |
| `agent_scorecard` | per-agent + per-team dimension scores with milestones |
| `failure_attribution` | responsible agent + decisive step + reason |
| `handoff_review` | agent-to-agent handoff quality + misalignment flags |
| `agent_interaction_graph` | clickable agent graph: critical path + problem edges |
| `emergent_behavior` | cross-lane tags (collusion, groupthink, cascade, role drift) |

## Related Documentation

- [Turn-Level Annotation](turn_level_annotation.md)
- [Agent Traces](agent_traces.md)
- [Multi-Agent Annotation](multi_agent_annotation.md)
