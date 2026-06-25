# Agent Failure-Mode Taxonomy (MAST)

Tag **why** an agent trace failed using a built-in, research-backed taxonomy —
without hand-authoring the label set. The flagship preset is **MAST** (the
Multi-Agent System failure taxonomy from Cemri et al. 2025, *"Why Do Multi-Agent
LLM Systems Fail?"*): **14 failure modes across 3 categories**, empirically derived
with κ=0.88 human inter-annotator agreement.

Commercial tools *auto-detect* failure modes; Potato gives you a turnkey
**human** failure-mode annotation workflow — optionally seeded by an LLM-judge
pre-label that annotators then validate.

## Quick start

Add `taxonomy_preset: mast` to any `hierarchical_multiselect` scheme:

```yaml
annotation_schemes:
  - annotation_type: hierarchical_multiselect
    name: failure_modes
    description: "Tag every MAST failure mode this trace exhibits"
    taxonomy_preset: mast      # auto-fills the 14 modes + hover definitions
    show_search: true
```

That's it — no need to list the modes. Each mode renders with its code
(e.g. `1.1 Disobey task specification`) and an **ⓘ** marker; hovering or
keyboard-focusing it shows the mode's definition so annotators apply the modes
consistently.

A runnable example is at `examples/agent-traces/failure-taxonomy/`:

```bash
python potato/flask_server.py start examples/agent-traces/failure-taxonomy/config.yaml -p 8000
```

## The MAST taxonomy

| Category | Modes |
|----------|-------|
| **Specification & System Design** | 1.1 Disobey task specification · 1.2 Disobey role specification · 1.3 Step repetition · 1.4 Loss of conversation history · 1.5 Unaware of termination conditions |
| **Inter-Agent Misalignment** | 2.1 Conversation reset · 2.2 Fail to ask for clarification · 2.3 Task derailment · 2.4 Information withholding · 2.5 Ignored other agent's input · 2.6 Reasoning-action mismatch |
| **Task Verification & Termination** | 3.1 Premature termination · 3.2 No or incomplete verification · 3.3 Incorrect verification |

Each mode carries a one-line definition (shown as a tooltip). See
`potato/server_utils/failure_taxonomy.py` for the full text.

## Options

| Option | Description |
|--------|-------------|
| `taxonomy_preset` | Name of a built-in taxonomy (currently `mast`). Fills `taxonomy` + per-mode tooltips. |
| `taxonomy` | An explicit nested taxonomy. Wins over the preset if both are given. |
| `tooltips` | A `{label: text}` map of hover definitions. Merged over the preset's (explicit wins). |
| `show_search` | Show a search box — handy for 14+ labels. |

Because it is a normal `hierarchical_multiselect` scheme, selections export as a
comma-separated list of coded mode labels, and all the usual options
(`max_selections`, `auto_select_parent`, …) apply.

## Pairing with an LLM judge

The taxonomy is small and explicit enough for an LLM judge to apply. A common
loop:

1. An LLM proposes failure modes for each incoming trace (a pre-label).
2. Annotators **validate or correct** the proposal in the UI above.
3. [Judge Alignment](judge_alignment.md) reports judge↔human agreement (κ) per
   mode, so you can see where the judge is reliable and where humans must review.

This mirrors the MAST paper's own workflow (human κ=0.88, LLM-judge κ=0.77) and
turns failure-mode tagging into a calibrated, auditable signal.

## Adding your own taxonomy

Append to `TAXONOMY_PRESETS` in `potato/server_utils/failure_taxonomy.py`. Each
preset is an ordered `{category: [(code, name, description), ...]}` mapping; the
schema wiring (`to_hierarchical`, `to_tooltips`) does the rest.

## Related documentation

- [Trajectory Evaluation](trajectory_eval.md) — per-step error taxonomy + severity
- [Process Supervision (PRM)](process_supervision.md) — per-step reward labeling
- [Judge Alignment](judge_alignment.md) — judge↔human agreement on the tags
- [Three-Pane Trace Eval](eval_trace.md) — richer trace display
