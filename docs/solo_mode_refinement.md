# Solo Mode: Validated Prompt Refinement

This document describes the validated refinement framework for the solo mode pipeline.

## Problem

Solo mode's refinement loop observes human-LLM disagreements and tries to improve the labeling prompt. Early versions of this loop used an **append-only** strategy that degraded per-version agreement in practice:

- **Observation**: On SST-2, per-version agreement dropped from ~85% (baseline) to ~65% after 1–2 refinement cycles.
- **Root cause**: The revision LLM writes narrow rules keyed to specific phrases in example text (e.g., `"If the text says 'get under your skin', classify as negative"`). These rules overfit to the training disagreements and hurt accuracy on unseen instances.

Recent literature on automated prompt optimization (ProTeGi EMNLP'23, COPRO/DSPy ICLR'24, Lampinen 2024) identifies the same pattern and suggests two mitigations that the framework implements:

1. **Validation gating** — score every candidate change on a held-out validation set; reject candidates that don't beat the baseline.
2. **In-Context Principles** — when rule-writing fails, add validated example demonstrations instead.

## Architecture

```
Refinement cycle triggered
          │
          ▼
ValidationSplit (70/30 of disagreements, deterministic per prompt version)
          │
          ├── train: used by strategy to propose candidates
          └── val:   held out for scoring
          │
          ▼
Strategy.propose_candidates(patterns, current_prompt, train_comparisons)
   returns list of RefinementCandidate(kind={PROMPT_EDIT | ICL_EXAMPLE | PRINCIPLE}, payload, ...)
          │
          ▼
For each candidate:
  CandidateEvaluator.evaluate(candidate_prompt, val_sample)
    → accuracy on the held-out val set
          │
          ▼
Pick best candidate if > baseline + min_val_improvement
  │
  ├── No candidate beats baseline → increment failure counter
  │       └── After max_consecutive_failures → stop loop
  │               (resumes when new disagreements trigger the refinement interval)
  │
  └── Winner found:
        ├── dry_run=true: log but don't apply
        ├── require_approval=true: queue for admin
        └── auto-apply: create new prompt version OR add to ICL library; trigger re-annotation
```

## Strategies

All strategies are registered via `@register_strategy` in `potato/solo_mode/refinement/strategies.py`. Each is tagged with `RECOMMENDED_OPTIMIZER_TIER` and `BEST_FOR` so practitioners can choose.

| Strategy | Tier | Best for | How it works |
|---|---|---|---|
| `validated_focused_edit` | small | binary, objective, few labels | Generates N prompt-rule candidates via the revision LLM, validation-gated apply. |
| `principle_icl` | small | subjective, many labels, small models | Proposes validated instances as ICL examples instead of rules. More robust against narrow-rule overfitting. |
| `hybrid_dual_track` | small | **recommended default** | Tries prompt edits first; after 2 consecutive prompt-edit failures, falls back to ICL. |
| `legacy_append` | — | ablation / comparison only | Original append-only behavior, no validation. Preserved so research baselines can be reproduced. |

For larger optimizer models (7B+), additional strategies like ProTeGi beam search and OPRO solution-history are described in the literature but not yet implemented. See `potato/solo_mode/refinement/strategies.py` docstrings for guidance on implementing new strategies.

## Configuration

Under `solo_mode.refinement_loop` in the config YAML:

```yaml
solo_mode:
  refinement_loop:
    enabled: true
    trigger_interval: 50          # fire after N new human annotations
    refinement_strategy: "hybrid_dual_track"  # see table above
    # Validation-gated framework options
    validation_split_ratio: 0.3   # fraction of disagreements held out
    eval_sample_size: 10          # val instances scored per candidate
    num_candidates: 3             # candidates generated per cycle
    min_val_size: 5               # skip cycle if insufficient val data
    max_consecutive_failures: 2   # stop loop after N failed cycles
    min_val_improvement: 0.0      # candidate must beat baseline by this much (strict = 0.0)
    # Approval workflow (optional)
    dry_run: false                # if true, log candidates but don't apply
    require_approval: false       # if true, queue for admin review
```

## HTTP API

### Listing strategies

```
GET /solo/api/refinement/strategies
```

Returns each registered strategy with its tier and description. Useful for building an admin UI with strategy selection.

### Refinement log

```
GET /solo/api/refinement/log
```

Full history of refinement cycles from the validated framework. Each entry includes:
- `applied_candidate`: the winning candidate or `null`
- `val_baseline_accuracy`: how the current prompt scored on val
- `val_candidate_accuracies`: how each candidate scored
- `failure_reason`: if no candidate was applied
- `dry_run`: whether this was a logging-only cycle

### Approval workflow

```
GET  /solo/api/refinement/pending        # list candidates awaiting approval
POST /solo/api/refinement/approve {index} # apply candidate; triggers re-annotation
POST /solo/api/refinement/reject {index}  # discard candidate
```

Admin workflows can embed this in a "review" page similar to the existing edge case rule review. Each pending entry shows the baseline accuracy, candidate accuracies, and the proposed change.

## When refinement makes things worse

If per-version agreement is dropping after refinement, check:

1. **Is `min_val_improvement` set to `0.0` (strict)?** Lowering it to negative values lets worse candidates through.
2. **Is `eval_sample_size` big enough?** 10 is the minimum for reliable signal. On noisy/subjective datasets (hate speech), 20+ is better.
3. **Check the refinement log.** If most candidates score near-baseline, the optimizer model may be too small. Consider switching `principle_icl` (which avoids rule writing) or using a larger revision model.
4. **If `hybrid_dual_track` keeps failing on prompt edits**, the failure counter will naturally route future cycles to ICL-only. Check the log for `proposed_by: principle_icl` entries.
5. **Dry-run mode (`dry_run: true`)** lets you see what WOULD be applied without committing. Useful for evaluating a new strategy on your data before trusting it.

## References

- Pryzant et al. "Automatic Prompt Optimization with Gradient Descent and Beam Search" (EMNLP 2023) — the ProTeGi technique of textual gradients + beam search validated on minibatches.
- Khattab et al. "DSPy: Compiling Declarative Language Model Calls" (ICLR 2024) — the COPRO hill-climbing optimizer that popularized validation-gated prompt refinement.
- Lampinen et al. "In-Context Principle Learning" (2024) — the principle-extraction pattern underlying `principle_icl`.
- Yuksekgonul et al. "TextGrad" (Nature 2024) — component-level textual feedback, considered for future implementation.

## Extending the framework

To add a new strategy:

1. Subclass `RefinementStrategy` in `potato/solo_mode/refinement/strategies.py` (or a new module).
2. Set `NAME`, `RECOMMENDED_OPTIMIZER_TIER`, `BEST_FOR`, `DESCRIPTION`.
3. Implement `propose_candidates()` returning a list of `RefinementCandidate` objects.
4. Apply `@register_strategy` decorator.
5. The framework handles validation, failure counting, application, and approval.

Each candidate has a `kind`:
- `PROMPT_EDIT`: payload `{"new_prompt_text": "...", "rules": [...]}`
- `ICL_EXAMPLE`: payload `{"instance_id": "...", "text": "...", "label": "...", "principle": "..."}`
- `PRINCIPLE`: payload is the principle string (appended to prompt)

The manager's `_build_eval_prompt_for_candidate` and `_apply_refinement_candidate` handle each kind.
