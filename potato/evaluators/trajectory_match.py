"""
Deterministic trajectory-match evaluator.

Compares an agent's tool-call sequence to a reference, mirroring the semantics
of LangChain's ``agentevals.create_trajectory_match_evaluator``:

    mode = strict     identical tool calls, same order
    mode = unordered  same multiset of tool calls, any order
    mode = subset     agent called only tools that appear in the reference
    mode = superset   agent called at least the reference tools (extras allowed)

Tool-argument comparison is independently configurable:

    tool_args_match_mode = exact    arg dicts must be equal
    tool_args_match_mode = ignore   only the tool name matters
    tool_args_match_mode = subset   agent args are a subset of reference args
    tool_args_match_mode = superset agent args are a superset of reference args

Per-tool overrides (``tool_args_match_overrides={"search": "ignore"}``) let one
tool match loosely while others stay strict.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from potato.evaluators.base import Evaluator, EvaluationResult
from potato.evaluators.trajectory import ToolCall, extract_tool_calls

_VALID_MODES = {"strict", "unordered", "subset", "superset"}
_VALID_ARG_MODES = {"exact", "ignore", "subset", "superset"}


def _args_match(out_args: Dict[str, Any], ref_args: Dict[str, Any], mode: str) -> bool:
    if mode == "ignore":
        return True
    if mode == "exact":
        return out_args == ref_args
    if mode == "subset":
        # every key/value the agent passed must appear in the reference
        return all(k in ref_args and ref_args[k] == v for k, v in out_args.items())
    if mode == "superset":
        # every reference key/value must appear in the agent's args
        return all(k in out_args and out_args[k] == v for k, v in ref_args.items())
    raise ValueError(f"Unknown tool_args_match_mode: {mode}")


class TrajectoryMatchEvaluator(Evaluator):
    def __init__(
        self,
        mode: str = "strict",
        tool_args_match_mode: str = "exact",
        tool_args_match_overrides: Optional[Dict[str, str]] = None,
        key: str = "trajectory_match",
    ):
        if mode not in _VALID_MODES:
            raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")
        if tool_args_match_mode not in _VALID_ARG_MODES:
            raise ValueError(
                f"tool_args_match_mode must be one of {_VALID_ARG_MODES}, "
                f"got {tool_args_match_mode!r}"
            )
        self.mode = mode
        self.tool_args_match_mode = tool_args_match_mode
        self.tool_args_match_overrides = tool_args_match_overrides or {}
        self.key = key

    def _arg_mode_for(self, tool_name: str) -> str:
        return self.tool_args_match_overrides.get(tool_name, self.tool_args_match_mode)

    def _call_matches(self, out: ToolCall, ref: ToolCall) -> bool:
        if out.name != ref.name:
            return False
        return _args_match(out.args, ref.args, self._arg_mode_for(ref.name))

    def _match_strict(self, out: List[ToolCall], ref: List[ToolCall]) -> bool:
        if len(out) != len(ref):
            return False
        return all(self._call_matches(o, r) for o, r in zip(out, ref))

    def _greedy_consume(self, calls: List[ToolCall], target: ToolCall) -> bool:
        """Remove one call from ``calls`` that matches ``target``; True if found."""
        for i, c in enumerate(calls):
            if self._call_matches(c, target):
                calls.pop(i)
                return True
        return False

    def _match_unordered(self, out: List[ToolCall], ref: List[ToolCall]) -> bool:
        if len(out) != len(ref):
            return False
        remaining = list(out)
        return all(self._greedy_consume(remaining, r) for r in ref)

    def _match_subset(self, out: List[ToolCall], ref: List[ToolCall]) -> bool:
        # every agent call must be matchable against some reference call
        remaining = list(ref)
        return all(self._greedy_consume(remaining, o) for o in out)

    def _match_superset(self, out: List[ToolCall], ref: List[ToolCall]) -> bool:
        # every reference call must be matchable against some agent call
        remaining = list(out)
        return all(self._greedy_consume(remaining, r) for r in ref)

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

        dispatch = {
            "strict": self._match_strict,
            "unordered": self._match_unordered,
            "subset": self._match_subset,
            "superset": self._match_superset,
        }
        matched = dispatch[self.mode](out_calls, ref_calls)

        comment = (
            f"{self.mode} match "
            f"({'pass' if matched else 'fail'}): "
            f"{len(out_calls)} agent tool call(s) vs {len(ref_calls)} reference"
        )
        return EvaluationResult(
            key=self.key,
            score=1.0 if matched else 0.0,
            value=matched,
            comment=comment,
            metadata={
                "mode": self.mode,
                "tool_args_match_mode": self.tool_args_match_mode,
                "agent_tools": [c.name for c in out_calls],
                "reference_tools": [c.name for c in ref_calls],
            },
        )
