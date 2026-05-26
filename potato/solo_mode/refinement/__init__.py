"""
Refinement Framework

Pluggable strategies for improving annotation prompts based on
human-LLM disagreements. Every strategy uses a validation-gated
apply step to prevent regressions.

Available strategies (all have `RefinementStrategy` as base class):

- validated_focused_edit: prompt rule edits with validation gate
  (recommended for small optimizer models)
- principle_icl: add validated ICL examples instead of rules
  (recommended for subjective tasks and small optimizers)
- hybrid_dual_track: try prompt edit first, fall back to ICL on failure
  (recommended default)
- append: legacy append-only refinement, no validation (for ablation)

Config:
    solo_mode.refinement_loop.strategy: "validated_focused_edit" | "principle_icl" | ...
    solo_mode.refinement_loop.strategy_config: {...}  # strategy-specific overrides
"""

from .base import (
    RefinementStrategy,
    RefinementCandidate,
    RefinementResult,
    CandidateKind,
)
from .validation import ValidationSplit, CandidateEvaluator
from .icl_library import ICLLibrary
from .registry import get_strategy, list_strategies, register_strategy

__all__ = [
    "RefinementStrategy",
    "RefinementCandidate",
    "RefinementResult",
    "CandidateKind",
    "ValidationSplit",
    "CandidateEvaluator",
    "ICLLibrary",
    "get_strategy",
    "list_strategies",
    "register_strategy",
]
