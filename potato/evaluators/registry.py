"""
Evaluator registry -- name -> factory mapping so evaluators can be configured
declaratively (in YAML for the experiment runner / automation engine) rather
than constructed in code.

    from potato.evaluators.registry import build_evaluator
    ev = build_evaluator("trajectory_match", {"mode": "unordered"})
    result = ev.evaluate(outputs=..., reference_outputs=...)
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from potato.evaluators.base import Evaluator
from potato.evaluators.trajectory_match import TrajectoryMatchEvaluator
from potato.evaluators.tool_use import ToolUseEvaluator, ToolCallAccuracyEvaluator
from potato.evaluators.llm_judge import LLMTrajectoryJudge
from potato.evaluators.heuristic import (
    ExactMatch,
    Contains,
    RegexMatch,
    EditDistance,
    JSONValid,
    JSONSchemaMatch,
    EmbeddingDistance,
)
from potato.evaluators.rubric_dag import RubricDagEvaluator

# name -> (factory, one-line description)
_REGISTRY: Dict[str, tuple] = {
    "trajectory_match": (TrajectoryMatchEvaluator, "Deterministic tool-call sequence match"),
    "tool_use": (ToolUseEvaluator, "A specific expected tool was invoked"),
    "tool_call_accuracy": (ToolCallAccuracyEvaluator, "Fraction of reference tool calls reproduced"),
    "llm_trajectory_judge": (LLMTrajectoryJudge, "Reference-free LLM judge of trajectory quality"),
    "rubric_dag": (RubricDagEvaluator, "Decision-tree rubric the judge traverses to a fixed leaf score"),
    "exact_match": (ExactMatch, "Output equals reference"),
    "contains": (Contains, "Output contains a substring"),
    "regex_match": (RegexMatch, "Output matches a regex"),
    "edit_distance": (EditDistance, "Normalized edit distance to reference"),
    "json_valid": (JSONValid, "Output parses as JSON"),
    "json_schema_match": (JSONSchemaMatch, "Output validates against a JSON schema"),
    "embedding_similarity": (EmbeddingDistance, "Cosine similarity of embeddings"),
}


def register_evaluator(name: str, factory: Callable[..., Evaluator], description: str = "") -> None:
    _REGISTRY[name] = (factory, description)


def build_evaluator(name: str, params: Dict[str, Any] | None = None) -> Evaluator:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown evaluator '{name}'. Available: {sorted(_REGISTRY)}")
    factory, _ = _REGISTRY[name]
    return factory(**(params or {}))


def list_evaluators() -> List[Dict[str, str]]:
    return [{"name": n, "description": d} for n, (_, d) in sorted(_REGISTRY.items())]


def get_supported_evaluators() -> List[str]:
    return sorted(_REGISTRY)
