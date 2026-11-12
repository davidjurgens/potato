"""Unit tests for trajectory normalization and the trajectory-match evaluator."""

import pytest

from potato.evaluators import (
    TrajectoryMatchEvaluator,
    normalize_trajectory,
    extract_tool_calls,
)


# ---- normalization across input shapes --------------------------------------

def test_normalize_openai_messages_with_tool_calls():
    messages = [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": "checking", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"location": "NYC"}'}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "Sunny"},
    ]
    calls = extract_tool_calls(messages)
    assert [c.name for c in calls] == ["get_weather"]
    assert calls[0].args == {"location": "NYC"}


def test_normalize_canonical_conversation_action_turns():
    # The shape every trace_converter importer produces.
    trace = {
        "id": "t1",
        "conversation": [
            {"speaker": "User", "text": "weather?"},
            {"speaker": "Agent (Action)", "text": 'get_weather({"location": "NYC"})'},
            {"speaker": "Environment", "text": "Sunny"},
        ],
    }
    calls = extract_tool_calls(trace)
    assert len(calls) == 1
    assert calls[0].name == "get_weather"
    assert calls[0].args == {"location": "NYC"}


def test_normalize_action_turn_non_json_args():
    trace = {"conversation": [{"speaker": "Agent (Action)", "text": "search(raw query)"}]}
    calls = extract_tool_calls(trace)
    assert calls[0].name == "search"
    assert calls[0].args == {"_raw": "raw query"}


def test_normalize_bare_string_and_none():
    assert len(normalize_trajectory("hello")) == 1
    assert normalize_trajectory(None) == []


# ---- helpers -----------------------------------------------------------------

def _calls(*specs):
    """Build OpenAI-style messages from (name, args) specs."""
    return [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": n, "arguments": a}}]}
        for n, a in specs
    ]


# ---- strict mode -------------------------------------------------------------

def test_strict_match_pass():
    out = _calls(("a", {}), ("b", {"x": 1}))
    ref = _calls(("a", {}), ("b", {"x": 1}))
    r = TrajectoryMatchEvaluator(mode="strict").evaluate(outputs=out, reference_outputs=ref)
    assert r.score == 1.0 and r.value is True


def test_strict_match_order_matters():
    out = _calls(("b", {}), ("a", {}))
    ref = _calls(("a", {}), ("b", {}))
    r = TrajectoryMatchEvaluator(mode="strict").evaluate(outputs=out, reference_outputs=ref)
    assert r.score == 0.0


def test_strict_match_arg_mismatch_fails_exact():
    out = _calls(("a", {"x": 1}))
    ref = _calls(("a", {"x": 2}))
    r = TrajectoryMatchEvaluator(mode="strict", tool_args_match_mode="exact").evaluate(
        outputs=out, reference_outputs=ref)
    assert r.score == 0.0


# ---- unordered mode ----------------------------------------------------------

def test_unordered_match_ignores_order():
    out = _calls(("b", {}), ("a", {}))
    ref = _calls(("a", {}), ("b", {}))
    r = TrajectoryMatchEvaluator(mode="unordered").evaluate(outputs=out, reference_outputs=ref)
    assert r.score == 1.0


def test_unordered_requires_same_count():
    out = _calls(("a", {}))
    ref = _calls(("a", {}), ("b", {}))
    r = TrajectoryMatchEvaluator(mode="unordered").evaluate(outputs=out, reference_outputs=ref)
    assert r.score == 0.0


# ---- subset / superset -------------------------------------------------------

def test_subset_agent_uses_only_reference_tools():
    out = _calls(("a", {}))
    ref = _calls(("a", {}), ("b", {}))
    r = TrajectoryMatchEvaluator(mode="subset").evaluate(outputs=out, reference_outputs=ref)
    assert r.score == 1.0  # agent's calls ⊆ reference


def test_subset_fails_on_extra_tool():
    out = _calls(("a", {}), ("c", {}))
    ref = _calls(("a", {}), ("b", {}))
    r = TrajectoryMatchEvaluator(mode="subset").evaluate(outputs=out, reference_outputs=ref)
    assert r.score == 0.0  # 'c' not in reference


def test_superset_allows_extra_tools():
    out = _calls(("a", {}), ("b", {}), ("c", {}))
    ref = _calls(("a", {}), ("b", {}))
    r = TrajectoryMatchEvaluator(mode="superset").evaluate(outputs=out, reference_outputs=ref)
    assert r.score == 1.0  # all reference tools present, extras OK


def test_superset_fails_when_missing_reference_tool():
    out = _calls(("a", {}))
    ref = _calls(("a", {}), ("b", {}))
    r = TrajectoryMatchEvaluator(mode="superset").evaluate(outputs=out, reference_outputs=ref)
    assert r.score == 0.0


# ---- arg match modes ---------------------------------------------------------

def test_arg_mode_ignore():
    out = _calls(("a", {"x": 1}))
    ref = _calls(("a", {"x": 999}))
    r = TrajectoryMatchEvaluator(mode="strict", tool_args_match_mode="ignore").evaluate(
        outputs=out, reference_outputs=ref)
    assert r.score == 1.0


def test_arg_mode_subset():
    out = _calls(("a", {"x": 1}))
    ref = _calls(("a", {"x": 1, "y": 2}))
    r = TrajectoryMatchEvaluator(mode="strict", tool_args_match_mode="subset").evaluate(
        outputs=out, reference_outputs=ref)
    assert r.score == 1.0  # agent args ⊆ reference args


def test_arg_mode_superset():
    out = _calls(("a", {"x": 1, "y": 2}))
    ref = _calls(("a", {"x": 1}))
    r = TrajectoryMatchEvaluator(mode="strict", tool_args_match_mode="superset").evaluate(
        outputs=out, reference_outputs=ref)
    assert r.score == 1.0  # reference args ⊆ agent args


def test_per_tool_arg_override():
    out = _calls(("search", {"q": "foo"}), ("submit", {"id": 1}))
    ref = _calls(("search", {"q": "bar"}), ("submit", {"id": 1}))
    ev = TrajectoryMatchEvaluator(
        mode="strict",
        tool_args_match_mode="exact",
        tool_args_match_overrides={"search": "ignore"},
    )
    r = ev.evaluate(outputs=out, reference_outputs=ref)
    assert r.score == 1.0  # search args ignored, submit args exact-match


# ---- validation --------------------------------------------------------------

def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        TrajectoryMatchEvaluator(mode="bogus")


def test_invalid_arg_mode_raises():
    with pytest.raises(ValueError):
        TrajectoryMatchEvaluator(tool_args_match_mode="bogus")
