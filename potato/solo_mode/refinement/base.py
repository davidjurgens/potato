"""
Base classes for refinement strategies.

A refinement strategy takes (confusion patterns, current prompt, train/val
disagreements) and proposes candidates (either prompt edits or ICL examples).
The framework scores each candidate on the validation split and applies only
those that beat the baseline.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class CandidateKind(Enum):
    """What kind of change a candidate represents."""
    PROMPT_EDIT = "prompt_edit"   # Replaces the guidelines section
    ICL_EXAMPLE = "icl_example"   # Adds an example to the ICL library
    PRINCIPLE = "principle"       # Adds a principle as text in the prompt


@dataclass
class RefinementCandidate:
    """A single candidate change proposed by a strategy.

    Each candidate can be evaluated independently on the validation set.
    """
    kind: CandidateKind
    # For PROMPT_EDIT: the complete guidelines text that will replace the section
    # For ICL_EXAMPLE: a dict with {instance_id, text, label, principle}
    # For PRINCIPLE: the principle text
    payload: Any
    # Source pattern this candidate addresses (for logging)
    target_pattern: Optional[str] = None
    # The strategy that proposed it
    proposed_by: str = ""
    # Rationale (for audit trail and user review)
    rationale: str = ""


@dataclass
class RefinementResult:
    """The outcome of a refinement cycle."""
    success: bool
    strategy: str
    applied_candidate: Optional[RefinementCandidate] = None
    all_candidates: List[RefinementCandidate] = field(default_factory=list)
    val_baseline_accuracy: float = 0.0
    val_candidate_accuracies: Dict[int, float] = field(default_factory=dict)  # candidate_index -> acc
    val_sample_ids: List[str] = field(default_factory=list)
    train_sample_size: int = 0
    val_sample_size: int = 0
    # If dry-run, applied_candidate is None but all_candidates is populated
    dry_run: bool = False
    # Reason for no-apply
    failure_reason: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "strategy": self.strategy,
            "applied_candidate": self._candidate_to_dict(self.applied_candidate) if self.applied_candidate else None,
            "all_candidates": [self._candidate_to_dict(c) for c in self.all_candidates],
            "val_baseline_accuracy": self.val_baseline_accuracy,
            "val_candidate_accuracies": {str(k): v for k, v in self.val_candidate_accuracies.items()},
            "val_sample_ids": self.val_sample_ids,
            "train_sample_size": self.train_sample_size,
            "val_sample_size": self.val_sample_size,
            "dry_run": self.dry_run,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
        }

    @staticmethod
    def _candidate_to_dict(c: Optional[RefinementCandidate]) -> Optional[Dict]:
        if c is None:
            return None
        return {
            "kind": c.kind.value,
            "payload": c.payload,
            "target_pattern": c.target_pattern,
            "proposed_by": c.proposed_by,
            "rationale": c.rationale,
        }


class RefinementStrategy(ABC):
    """Abstract base class for refinement strategies.

    Subclasses implement `propose_candidates()`. The framework handles:
      - splitting disagreements into train/val
      - evaluating candidates on val set via CandidateEvaluator
      - applying only candidates that beat the baseline
      - tracking failure counters and dry-run logging

    Subclasses should set:
      NAME: str registry key
      RECOMMENDED_OPTIMIZER_TIER: "small" | "medium" | "large"
      BEST_FOR: list of tags (["binary", "subjective", "many_labels", ...])
      DESCRIPTION: one-line description shown to practitioners
    """

    NAME: str = "abstract"
    RECOMMENDED_OPTIMIZER_TIER: str = "small"
    BEST_FOR: List[str] = []
    DESCRIPTION: str = ""

    def __init__(self, manager: Any, solo_config: Any):
        """
        Args:
            manager: SoloModeManager instance (for accessing predictions, analyzer, etc.)
            solo_config: SoloModeConfig
        """
        self.manager = manager
        self.solo_config = solo_config

    @abstractmethod
    def propose_candidates(
        self,
        patterns: List[Any],
        current_prompt: str,
        train_comparisons: List[Dict[str, Any]],
    ) -> List[RefinementCandidate]:
        """Generate candidate refinements based on training disagreements.

        Args:
            patterns: ConfusionPattern list (already filtered to train split)
            current_prompt: the current annotation prompt text
            train_comparisons: list of comparison dicts (human_label, llm_label, etc.)
                               sliced to train split

        Returns:
            List of RefinementCandidate objects (may be empty)
        """
        ...

    def supports_kind(self, kind: CandidateKind) -> bool:
        """Whether this strategy can produce candidates of a given kind.

        Default: supports all kinds. Override to restrict.
        """
        return True
