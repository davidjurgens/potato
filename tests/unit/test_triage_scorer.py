"""Unit tests for the signal-based triage scorer (potato/server_utils/triage.py)."""

import pytest

from potato.server_utils.triage import (
    TriageScorer,
    TriageScore,
    build_scorer,
    DEFAULT_RULES,
    _matches,
    _lookup,
)


# --- default rules (turnkey) ------------------------------------------------

def test_defaults_flag_error_status():
    s = TriageScorer({"enabled": True})
    score = s.score({"status": "error"})
    assert score.priority == 100
    assert score.reason == "Agent errored"


def test_defaults_flag_negative_feedback():
    s = TriageScorer({"enabled": True})
    assert s.score({"feedback": "thumbs_down"}).priority == 80


def test_defaults_flag_low_score():
    s = TriageScorer({"enabled": True})
    assert s.score({"score": 0.3}).priority == 60


def test_defaults_clean_item_is_default_priority():
    s = TriageScorer({"enabled": True})
    score = s.score({"status": "ok", "score": 0.95})
    assert score.priority == 0
    assert score.reason is None


def test_highest_matching_rule_wins():
    # error (100) + thumbs_down (80) + low score (60) -> highest is 100
    s = TriageScorer({"enabled": True})
    score = s.score({"status": "error", "feedback": "thumbs_down", "score": 0.1})
    assert score.priority == 100
    assert score.rule == "Agent errored"


# --- operators --------------------------------------------------------------

def test_equals_is_case_insensitive():
    assert _matches({"field": "status", "equals": "ERROR"}, {"status": "error"})


def test_in_operator():
    cond = {"field": "feedback", "in": ["thumbs_down", "negative"]}
    assert _matches(cond, {"feedback": "negative"})
    assert not _matches(cond, {"feedback": "thumbs_up"})


def test_numeric_comparisons():
    assert _matches({"field": "score", "lt": 0.5}, {"score": 0.4})
    assert not _matches({"field": "score", "lt": 0.5}, {"score": 0.6})
    assert _matches({"field": "score", "gte": 0.5}, {"score": 0.5})
    assert _matches({"field": "n", "gt": 3}, {"n": 5})


def test_numeric_comparison_coerces_strings():
    assert _matches({"field": "score", "lt": 0.5}, {"score": "0.2"})


def test_exists_operator():
    assert _matches({"field": "err", "exists": True}, {"err": "boom"})
    assert _matches({"field": "err", "exists": False}, {"other": 1})
    assert not _matches({"field": "err", "exists": True}, {"other": 1})


def test_contains_on_list_field():
    cond = {"field": "tags", "contains": "regression"}
    assert _matches(cond, {"tags": ["smoke", "regression"]})
    assert not _matches(cond, {"tags": ["smoke"]})


def test_contains_substring_on_string():
    assert _matches({"field": "msg", "contains": "timeout"}, {"msg": "Request TIMEOUT after 30s"})


def test_dotted_field_path():
    cond = {"field": "metadata.tags", "contains": "bad"}
    assert _matches(cond, {"metadata": {"tags": ["bad"]}})


def test_lookup_missing_path_returns_none():
    assert _lookup({"a": {"b": 1}}, "a.c") is None
    assert _lookup({"a": 1}, "a.b") is None


def test_absent_field_never_matches_value_ops():
    assert not _matches({"field": "score", "lt": 0.5}, {})


# --- signal_field -----------------------------------------------------------

def test_signal_field_used_when_no_rule_matches():
    s = TriageScorer({"enabled": True, "signal_field": "priority_hint", "rules": []})
    assert s.score({"priority_hint": 7}).priority == 7


def test_signal_field_invert():
    s = TriageScorer({"enabled": True, "signal_field": "score", "invert_signal": True, "rules": []})
    # lower score -> higher priority
    assert s.score({"score": 0.2}).priority == pytest.approx(-0.2)


def test_rules_take_precedence_over_signal_field():
    s = TriageScorer({
        "enabled": True,
        "signal_field": "score",
        "rules": [{"name": "err", "priority": 99, "when": {"field": "status", "equals": "error"}}],
    })
    assert s.score({"status": "error", "score": 0.1}).priority == 99


# --- enable / disable -------------------------------------------------------

def test_disabled_scorer_returns_default():
    s = TriageScorer({"enabled": False})
    assert s.score({"status": "error"}).priority == 0


def test_build_scorer_none_when_disabled():
    assert build_scorer({"triage": {"enabled": False}}) is None
    assert build_scorer({}) is None


def test_build_scorer_present_when_enabled():
    assert build_scorer({"triage": {"enabled": True}}) is not None


def test_custom_default_priority():
    s = TriageScorer({"enabled": True, "default_priority": -5, "rules": []})
    assert s.score({"clean": True}).priority == -5


def test_malformed_rule_is_skipped_not_raised():
    # A rule whose condition references a comparison against a non-number must
    # not blow up scoring.
    s = TriageScorer({"enabled": True, "rules": [
        {"name": "weird", "priority": 10, "when": {"field": "x", "lt": "not-a-number"}},
    ]})
    assert s.score({"x": 5}).priority == 0  # falls through to default


def test_badge_defaults_to_rule_name():
    s = TriageScorer({"enabled": True, "rules": [
        {"name": "My Rule", "priority": 5, "when": {"field": "f", "equals": "v"}},
    ]})
    assert s.score({"f": "v"}).reason == "My Rule"


def test_to_metadata_shape():
    score = TriageScore(priority=42, reason="r", rule="rl")
    md = score.to_metadata()
    assert md == {"triage_priority": 42, "triage_reason": "r", "triage_rule": "rl"}
