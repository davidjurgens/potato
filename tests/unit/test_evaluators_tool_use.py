"""Unit tests for tool-use and tool-call-accuracy evaluators."""

import pytest

from potato.evaluators import ToolUseEvaluator, ToolCallAccuracyEvaluator


def _calls(*specs):
    return [
        {"role": "assistant", "tool_calls": [{"function": {"name": n, "arguments": a}}]}
        for n, a in specs
    ]


def test_tool_use_found():
    out = _calls(("search", {"q": "x"}), ("submit", {"id": 1}))
    r = ToolUseEvaluator(expected_tool="submit").evaluate(outputs=out)
    assert r.score == 1.0 and r.value is True


def test_tool_use_not_found():
    out = _calls(("search", {"q": "x"}))
    r = ToolUseEvaluator(expected_tool="submit").evaluate(outputs=out)
    assert r.score == 0.0


def test_tool_use_with_expected_args():
    out = _calls(("submit", {"id": 1, "extra": "y"}))
    r = ToolUseEvaluator(expected_tool="submit", expected_args={"id": 1}).evaluate(outputs=out)
    assert r.score == 1.0  # expected arg present among actual args


def test_tool_use_expected_args_mismatch():
    out = _calls(("submit", {"id": 2}))
    r = ToolUseEvaluator(expected_tool="submit", expected_args={"id": 1}).evaluate(outputs=out)
    assert r.score == 0.0


def test_tool_call_accuracy_partial():
    out = _calls(("a", {}), ("b", {}))
    ref = _calls(("a", {}), ("b", {}), ("c", {}))
    r = ToolCallAccuracyEvaluator().evaluate(outputs=out, reference_outputs=ref)
    assert r.score == pytest.approx(2 / 3)
    assert r.value == "2/3"


def test_tool_call_accuracy_no_reference_returns_none():
    r = ToolCallAccuracyEvaluator().evaluate(outputs=_calls(("a", {})), reference_outputs=[])
    assert r.score is None


def test_tool_call_accuracy_exact_args():
    out = _calls(("a", {"x": 1}))
    ref = _calls(("a", {"x": 2}))
    r = ToolCallAccuracyEvaluator(args_match_mode="exact").evaluate(
        outputs=out, reference_outputs=ref)
    assert r.score == 0.0
