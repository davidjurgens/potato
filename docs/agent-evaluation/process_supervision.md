# Process Supervision (PRM Labeling)

Step-level reward labeling for **Process Reward Model (PRM)** training data. Where
[Trajectory Evaluation](trajectory_eval.md) captures rich per-step error taxonomies,
the `process_reward` schema captures the single signal a PRM trainer needs — a
per-step reward — with a fast, low-friction interface.

Based on PRM800K (Lightman et al. 2023, *"Let's Verify Step by Step"*) and agent
process-reward research (AgentPRM, ToolRM, ToolRL, SPORT).

## Overview

The `process_reward` schema renders each step of an agent trajectory and lets the
annotator assign a reward. It has two labeling **modes** and an optional three-way
neutral state:

| Mode | Interaction | Use when |
|------|-------------|----------|
| `first_error` (default) | Click the first incorrect step; every step before it is auto-marked correct, that step and all after are auto-marked incorrect | You want fast outcome-style supervision and assume an error is unrecoverable |
| `per_step` | Rate each step independently | You want true process supervision where individual steps are judged on their own merits |

### Reward values

| Value | Meaning |
|-------|---------|
| `1` | Correct — the step helped |
| `-1` | Incorrect — the step hurt |
| `0` | **Neutral** — neither helped nor hurt (only when `allow_neutral: true`) |
| `null` | Unmarked — the annotator has not judged this step |

By default a step is correct, incorrect, or unmarked (stored as `0`). When you
enable **three-way labeling**, unmarked becomes `null` so a deliberate *neutral*
judgment (`0`) is never confused with a step that was simply skipped — matching the
PRM800K `+1 / 0 / −1` convention.

## Configuration

```yaml
annotation_schemes:
  - annotation_type: process_reward
    name: step_rewards
    description: "Label each step's reward"
    steps_key: steps            # field in instance data containing the step list
    step_text_key: action       # which field of each step to display
    mode: per_step              # "first_error" (default) or "per_step"
    allow_neutral: true         # enable the three-way +1 / 0 / -1 label
    inline_with_trace: false    # inject controls into a rendered trace (see below)
```

| Option | Default | Description |
|--------|---------|-------------|
| `steps_key` | `steps` | Field in the instance data holding the list of steps |
| `step_text_key` | `action` | Field within each step object to display as the step text |
| `mode` | `first_error` | `first_error` cascade or independent `per_step` rating |
| `allow_neutral` | `false` | Adds a **Neutral** button (`per_step` only — ignored in `first_error`) |
| `inline_with_trace` | `false` | Place the rating control beside each step of a rendered agent trace (e.g. the [three-pane eval display](eval_trace.md)) rather than in a separate card list |

> **Note:** `allow_neutral` only applies to `per_step` mode. The `first_error`
> cascade has no place for a neutral judgment, so it is forced off there.

## Three-way (neutral) labeling

PRM800K-style process supervision distinguishes three judgments:

- **Correct** (`+1`) — the step is a valid, helpful move.
- **Neutral** (`0`) — the step is benign: it neither advances nor harms the
  solution (e.g. a redundant read, a harmless restatement).
- **Incorrect** (`−1`) — the step is a mistake.

Forcing every step into correct/incorrect loses signal: many real agent steps are
genuinely neutral, and labeling them as either pole teaches the reward model the
wrong thing. Enabling `allow_neutral: true` adds an amber **Neutral** button and
keeps unmarked steps as `null`, so your exported data cleanly separates *neutral*
from *not yet labeled*.

## Export

Process-reward annotations export through the
[coding evaluation exporter](../data-export/index.md) as JSONL, one record per
annotator per instance:

```json
{"instance_id": "trace_42", "annotator": "alice", "mode": "per_step",
 "steps": [{"index": 0, "reward": 1}, {"index": 1, "reward": 0},
           {"index": 2, "reward": -1}, {"index": 3, "reward": null}]}
```

`reward: 0` is a deliberate neutral label; `reward: null` is an unmarked step your
PRM trainer can drop. This is the canonical PRM800K-style step-reward format.

## Example

A runnable example lives at `examples/agent-traces/coding-agent-prm/` — run it from
the repo root:

```bash
python potato/flask_server.py start examples/agent-traces/coding-agent-prm/config.yaml -p 8000
```

## Related documentation

- [Trajectory Evaluation](trajectory_eval.md) — richer per-step error taxonomy and severity
- [Trajectory Correction](trajectory_correction.md) — edit steps to build SFT/DPO data
- [Three-Pane Trace Eval](eval_trace.md) — the trace display `inline_with_trace` attaches to
- [Programmatic Evaluators](evaluators.md) — automatic trajectory/tool scoring
