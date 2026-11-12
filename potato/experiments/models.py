"""
Data model for experiments.

An Experiment is one run of a set of evaluators against a specific dataset
version, producing per-example results and aggregate scores. Experiments are
immutable records; the comparison view diffs aggregate scores across them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ExperimentResult:
    """Evaluator results for a single example."""

    example_id: str
    outputs: Any = None
    scores: Dict[str, Optional[float]] = field(default_factory=dict)  # evaluator key -> score
    results: List[Dict[str, Any]] = field(default_factory=list)       # full EvaluationResult dicts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "example_id": self.example_id,
            "outputs": self.outputs,
            "scores": self.scores,
            "results": self.results,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExperimentResult":
        return cls(
            example_id=d.get("example_id", ""),
            outputs=d.get("outputs"),
            scores=d.get("scores", {}) or {},
            results=d.get("results", []) or [],
        )


@dataclass
class Experiment:
    """One evaluation run over a dataset version."""

    id: str
    dataset_name: str
    dataset_version: str
    created_at: str = ""
    name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)  # model/prompt/git-sha etc.
    aggregate_scores: Dict[str, float] = field(default_factory=dict)
    example_count: int = 0
    results: List[ExperimentResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "dataset_name": self.dataset_name,
            "dataset_version": self.dataset_version,
            "created_at": self.created_at,
            "name": self.name,
            "metadata": self.metadata,
            "aggregate_scores": self.aggregate_scores,
            "example_count": self.example_count,
            "results": [r.to_dict() for r in self.results],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Experiment":
        return cls(
            id=d["id"],
            dataset_name=d.get("dataset_name", ""),
            dataset_version=d.get("dataset_version", ""),
            created_at=d.get("created_at", ""),
            name=d.get("name", ""),
            metadata=d.get("metadata", {}) or {},
            aggregate_scores=d.get("aggregate_scores", {}) or {},
            example_count=int(d.get("example_count", 0)),
            results=[ExperimentResult.from_dict(r) for r in d.get("results", [])],
        )
