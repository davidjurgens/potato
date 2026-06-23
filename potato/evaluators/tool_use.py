"""
Tool-use correctness evaluators.

``ToolUseEvaluator`` checks that a specific expected tool was invoked (optionally
with expected arguments) anywhere in the trajectory -- single-step tool-call
correctness, as opposed to the whole-sequence matching of
``TrajectoryMatchEvaluator``.

``ToolCallAccuracyEvaluator`` reports the fraction of reference tool calls the
agent reproduced (a graded, partial-credit signal rather than pass/fail).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from potato.evaluators.base import Evaluator, EvaluationResult
from potato.evaluators.trajectory import ToolCall, extract_tool_calls
from potato.evaluators.trajectory_match import _args_match, _VALID_ARG_MODES


class ToolUseEvaluator(Evaluator):
    def __init__(
        self,
        expected_tool: str,
        expected_args: Optional[Dict[str, Any]] = None,
        args_match_mode: str = "subset",
        key: Optional[str] = None,
    ):
        if args_match_mode not in _VALID_ARG_MODES:
            raise ValueError(f"args_match_mode must be one of {_VALID_ARG_MODES}")
        self.expected_tool = expected_tool
        self.expected_args = expected_args or {}
        self.args_match_mode = args_match_mode
        self.key = key or f"tool_use:{expected_tool}"

    def evaluate(
        self,
        *,
        outputs: Any = None,
        reference_outputs: Any = None,
        inputs: Any = None,
        **kwargs: Any,
    ) -> EvaluationResult:
        calls = extract_tool_calls(outputs)
        # superset semantics for the expected-args check: every expected
        # key/value must be present in the actual call.
        found = False
        for c in calls:
            if c.name != self.expected_tool:
                continue
            if not self.expected_args:
                found = True
                break
            ref = ToolCall(name=c.name, args=self.expected_args)
            if _args_match(c.args, ref.args, "superset" if self.args_match_mode == "subset" else self.args_match_mode):
                found = True
                break
        return EvaluationResult(
            key=self.key,
            score=1.0 if found else 0.0,
            value=found,
            comment=(
                f"tool '{self.expected_tool}' "
                + ("called" if found else "not called")
                + (" with expected args" if self.expected_args else "")
            ),
            metadata={"called_tools": [c.name for c in calls]},
        )


class ToolCallAccuracyEvaluator(Evaluator):
    """Fraction of reference tool calls reproduced by the agent (partial credit)."""

    def __init__(self, args_match_mode: str = "exact", key: str = "tool_call_accuracy"):
        if args_match_mode not in _VALID_ARG_MODES:
            raise ValueError(f"args_match_mode must be one of {_VALID_ARG_MODES}")
        self.args_match_mode = args_match_mode
        self.key = key

    def _matches(self, out: ToolCall, ref: ToolCall) -> bool:
        return out.name == ref.name and _args_match(out.args, ref.args, self.args_match_mode)

    def evaluate(
        self,
        *,
        outputs: Any = None,
        reference_outputs: Any = None,
        inputs: Any = None,
        **kwargs: Any,
    ) -> EvaluationResult:
        out_calls = extract_tool_calls(outputs)
        ref_calls = extract_tool_calls(reference_outputs)
        if not ref_calls:
            return EvaluationResult(
                key=self.key, score=None, value=None,
                comment="no reference tool calls to score against",
            )
        remaining: List[ToolCall] = list(out_calls)
        hits = 0
        for r in ref_calls:
            for i, o in enumerate(remaining):
                if self._matches(o, r):
                    remaining.pop(i)
                    hits += 1
                    break
        score = hits / len(ref_calls)
        return EvaluationResult(
            key=self.key,
            score=score,
            value=f"{hits}/{len(ref_calls)}",
            comment=f"reproduced {hits} of {len(ref_calls)} reference tool calls",
            metadata={
                "matched": hits,
                "reference_count": len(ref_calls),
                "agent_count": len(out_calls),
            },
        )
