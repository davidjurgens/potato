"""
Lazy adapter for the MIT-licensed ``agentevals`` package.

We reuse ``agentevals`` for the things it does best -- notably LangGraph
graph-trajectory evaluation -- rather than reimplementing them. The package is
an *optional* dependency: importing this module never imports ``agentevals``;
the probe runs only when an adapter function is called.

If ``agentevals`` is not installed, ``is_available()`` returns False and the
factory functions raise an informative ImportError.
"""

from __future__ import annotations

from importlib.util import find_spec
from typing import Any

from potato.evaluators.base import Evaluator, EvaluationResult


def is_available() -> bool:
    """True if the ``agentevals`` package can be imported (no import performed)."""
    return find_spec("agentevals") is not None


def _require():
    if not is_available():
        raise ImportError(
            "This evaluator requires the optional 'agentevals' package. "
            "Install it with: pip install agentevals"
        )


class _AgentEvalsWrapper(Evaluator):
    """Wraps an agentevals evaluator callable into Potato's Evaluator contract."""

    def __init__(self, fn: Any, key: str):
        self._fn = fn
        self.key = key

    def evaluate(self, *, outputs=None, reference_outputs=None, inputs=None, **kwargs) -> EvaluationResult:
        result = self._fn(outputs=outputs, reference_outputs=reference_outputs, **kwargs)
        # agentevals returns {"key", "score", "comment", ...} or a list thereof
        if isinstance(result, list):
            result = result[0] if result else {}
        score = result.get("score") if isinstance(result, dict) else None
        if isinstance(score, bool):
            score = 1.0 if score else 0.0
        return EvaluationResult(
            key=result.get("key", self.key) if isinstance(result, dict) else self.key,
            score=score,
            value=result.get("score") if isinstance(result, dict) else result,
            comment=result.get("comment", "") if isinstance(result, dict) else "",
            metadata={"source": "agentevals"},
        )


def graph_trajectory_llm_judge(**agentevals_kwargs: Any) -> Evaluator:
    """Wrap ``agentevals.graph_trajectory.create_graph_trajectory_llm_as_judge``."""
    _require()
    from agentevals.graph_trajectory.llm import create_graph_trajectory_llm_as_judge
    fn = create_graph_trajectory_llm_as_judge(**agentevals_kwargs)
    return _AgentEvalsWrapper(fn, key="graph_trajectory_accuracy")


def graph_trajectory_strict_match(**agentevals_kwargs: Any) -> Evaluator:
    """Wrap ``agentevals.graph_trajectory.strict.graph_trajectory_strict_match``."""
    _require()
    from agentevals.graph_trajectory.strict import graph_trajectory_strict_match as fn
    return _AgentEvalsWrapper(fn, key="graph_trajectory_strict_match")
