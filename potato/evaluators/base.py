"""
Core abstractions for the Potato evaluators library.

Evaluators are Flask-free and dependency-light so they can run inside the
automation engine (Phase 4), the experiment runner (Phase 2), and a user's
pytest suite (Phase 5) without importing the web server.

The single shared contract is:

    evaluator.evaluate(outputs=..., reference_outputs=..., inputs=...)
        -> EvaluationResult

so heuristic, trajectory, and LLM-judge evaluators are interchangeable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class EvaluationResult:
    """The normalized result every evaluator returns.

    Attributes:
        key: Name of the metric (e.g. "trajectory_match"). One evaluator may
            emit one key; aggregation downstream groups by key.
        score: Normalized numeric score, conventionally in [0, 1] where higher
            is better. May be None for purely categorical results.
        value: The raw/categorical value (bool, label, number) when a score is
            not the natural representation.
        comment: Human-readable explanation (judge reasoning, mismatch detail).
        metadata: Arbitrary extra detail (per-step breakdown, matched pairs).
    """

    key: str
    score: Optional[float] = None
    value: Any = None
    comment: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "score": self.score,
            "value": self.value,
            "comment": self.comment,
            "metadata": self.metadata,
        }


class Evaluator:
    """Base class for all evaluators.

    Subclasses set ``key`` and implement ``evaluate``. Instances are callable
    so they can be passed anywhere a plain function evaluator is expected.
    """

    key: str = "evaluator"

    def evaluate(
        self,
        *,
        outputs: Any = None,
        reference_outputs: Any = None,
        inputs: Any = None,
        **kwargs: Any,
    ) -> EvaluationResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def __call__(self, **kwargs: Any) -> EvaluationResult:
        return self.evaluate(**kwargs)
