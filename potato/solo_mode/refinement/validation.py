"""
Validation infrastructure for refinement strategies.

- ValidationSplit: deterministically splits disagreements into train/val
- CandidateEvaluator: labels val instances with a candidate prompt/ICL
  and returns accuracy against human labels
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SplitResult:
    train: List[Dict[str, Any]]
    val: List[Dict[str, Any]]
    seed: int


class ValidationSplit:
    """Split human-LLM comparison records into train/val deterministically.

    Split is seeded by prompt_version so it's stable within a version
    (a refinement cycle can re-run without the split changing) but
    different across versions (preventing val leakage across cycles).

    Only disagreements (agrees=False) are split, because the refinement
    process works on disagreements. Agreements stay in the train side as
    useful context but aren't needed for eval.
    """

    def __init__(self, val_ratio: float = 0.3, min_val: int = 5, min_train: int = 5):
        """
        Args:
            val_ratio: fraction of disagreements held out for validation
            min_val: minimum val size; if fewer disagreements exist, returns empty val
            min_train: minimum train size; if fewer, returns empty train
        """
        self.val_ratio = val_ratio
        self.min_val = min_val
        self.min_train = min_train

    def split(
        self,
        comparisons: List[Dict[str, Any]],
        prompt_version: int,
    ) -> SplitResult:
        """Split comparisons into train/val.

        Args:
            comparisons: list of {instance_id, human_label, llm_label, agrees, ...}
            prompt_version: used to seed the split deterministically

        Returns:
            SplitResult with train and val lists; either can be empty if not
            enough disagreements are available.
        """
        # Only disagreements go to val; agreements stay in train
        disagreements = [c for c in comparisons if not c.get('agrees')]
        agreements = [c for c in comparisons if c.get('agrees')]

        if len(disagreements) < (self.min_val + self.min_train):
            logger.info(
                f"[ValidationSplit] Only {len(disagreements)} disagreements available; "
                f"need at least {self.min_val + self.min_train}. Returning empty splits."
            )
            return SplitResult(train=[], val=[], seed=prompt_version)

        rng = random.Random(f"val_split_v{prompt_version}")
        shuffled = list(disagreements)
        rng.shuffle(shuffled)

        val_size = max(self.min_val, int(len(shuffled) * self.val_ratio))
        val = shuffled[:val_size]
        train_disagreements = shuffled[val_size:]

        # Combine train disagreements with agreements (useful context for
        # rule generation — but agreements aren't used for scoring)
        train = train_disagreements + agreements

        logger.info(
            f"[ValidationSplit] v{prompt_version}: "
            f"{len(train_disagreements)} train disagreements, "
            f"{len(val)} val disagreements, "
            f"{len(agreements)} agreements in train context"
        )

        return SplitResult(train=train, val=val, seed=prompt_version)


@dataclass
class EvalResult:
    accuracy: float
    correct_count: int
    total: int
    per_instance: List[Dict[str, Any]]  # {instance_id, predicted, human, correct}


class CandidateEvaluator:
    """Evaluate a candidate (prompt edit or ICL example) on a validation set.

    Uses a single labeling call per instance (no sampling diversity for speed).
    Compares predicted label against the human label already recorded.
    """

    def __init__(
        self,
        label_fn: Callable[[str, str, str], Optional[str]],
        get_text_fn: Callable[[str], str],
    ):
        """
        Args:
            label_fn: callable(instance_id, text, prompt) -> predicted_label or None
            get_text_fn: callable(instance_id) -> text string
        """
        self.label_fn = label_fn
        self.get_text_fn = get_text_fn

    def evaluate(
        self,
        candidate_prompt: str,
        val_comparisons: List[Dict[str, Any]],
        sample_size: Optional[int] = None,
    ) -> EvalResult:
        """Label each val instance with the candidate prompt, compute accuracy.

        Args:
            candidate_prompt: the full prompt text to evaluate
            val_comparisons: list of comparison dicts with human_label
            sample_size: if set, randomly sample this many from val_comparisons

        Returns:
            EvalResult with accuracy and per-instance breakdown
        """
        if sample_size and len(val_comparisons) > sample_size:
            val_comparisons = random.sample(val_comparisons, sample_size)

        correct = 0
        per_instance = []
        for comp in val_comparisons:
            iid = comp['instance_id']
            human_label = comp.get('human_label')
            if human_label is None:
                continue
            try:
                text = self.get_text_fn(iid)
                predicted = self.label_fn(iid, text, candidate_prompt)
            except Exception as e:
                logger.warning(f"[CandidateEval] Failed to label {iid}: {e}")
                predicted = None

            is_correct = (
                predicted is not None
                and str(predicted) == str(human_label)
            )
            if is_correct:
                correct += 1
            per_instance.append({
                'instance_id': iid,
                'predicted': predicted,
                'human': human_label,
                'correct': is_correct,
            })

        total = len(per_instance)
        accuracy = correct / total if total > 0 else 0.0

        return EvalResult(
            accuracy=accuracy,
            correct_count=correct,
            total=total,
            per_instance=per_instance,
        )
