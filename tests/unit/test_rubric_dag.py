"""Unit tests for the DAG/decision-tree rubric evaluator (D6)."""

import pytest

from potato.evaluators.rubric_dag import (
    RubricDagEvaluator, make_rubric_dag, RUBRIC_PRESETS,
)
from potato.evaluators import build_evaluator, get_supported_evaluators


class _StubJudge:
    """Returns a scripted choice per node question (matched by substring)."""

    def __init__(self, answers):
        self.answers = answers  # {question_substring: choice}
        self.calls = []

    def query(self, prompt, schema=None):
        self.calls.append(prompt)
        for frag, choice in self.answers.items():
            if frag.lower() in prompt.lower():
                return f'{{"choice": "{choice}", "reasoning": "stub"}}'
        return '{"choice": "", "reasoning": "no match"}'


DAG = {
    "key": "answer_quality",
    "root": "answers",
    "nodes": {
        "answers": {
            "question": "Does the response directly answer the question?",
            "choices": ["yes", "partially", "no"],
            "branches": {
                "yes": "grounded",
                "partially": {"score": 0.5, "label": "partial"},
                "no": {"score": 0.0, "label": "no answer"},
            },
        },
        "grounded": {
            "question": "Is the answer well-supported?",
            "choices": ["yes", "no"],
            "branches": {
                "yes": {"score": 1.0, "label": "complete"},
                "no": {"score": 0.7, "label": "unsourced"},
            },
        },
    },
}


class TestRubricDag:
    def test_full_traversal_to_top_leaf(self):
        judge = _StubJudge({"directly answer": "yes", "well-supported": "yes"})
        ev = RubricDagEvaluator(DAG, endpoint=judge)
        r = ev.evaluate(outputs="Paris is the capital of France [src].", inputs="Capital of France?")
        assert r.score == 1.0
        assert r.value == "complete"
        # path records both decision nodes for HITL inspection
        assert [p["node"] for p in r.metadata["path"]] == ["answers", "grounded"]

    def test_branch_to_intermediate_leaf(self):
        judge = _StubJudge({"directly answer": "yes", "well-supported": "no"})
        ev = RubricDagEvaluator(DAG, endpoint=judge)
        r = ev.evaluate(outputs="Paris.", inputs="Capital of France?")
        assert r.score == 0.7 and r.value == "unsourced"

    def test_early_leaf_short_circuits(self):
        judge = _StubJudge({"directly answer": "no"})
        ev = RubricDagEvaluator(DAG, endpoint=judge)
        r = ev.evaluate(outputs="The weather is nice.", inputs="Capital of France?")
        assert r.score == 0.0
        assert len(r.metadata["path"]) == 1  # stopped at the root leaf

    def test_partial_credit_leaf(self):
        judge = _StubJudge({"directly answer": "partially"})
        ev = RubricDagEvaluator(DAG, endpoint=judge)
        assert ev.evaluate(outputs="x").score == 0.5

    def test_key_from_dag(self):
        assert RubricDagEvaluator(DAG, endpoint=_StubJudge({})).key == "answer_quality"

    def test_missing_root_is_graceful(self):
        ev = RubricDagEvaluator({"root": "nope", "nodes": {}}, endpoint=_StubJudge({}))
        r = ev.evaluate(outputs="x")
        assert r.score is None and "misconfigured" in r.comment

    def test_no_endpoint_is_graceful(self):
        ev = RubricDagEvaluator(DAG, config={})  # no ai_support, no endpoint
        r = ev.evaluate(outputs="x")
        assert r.score is None and "endpoint" in r.comment

    def test_invalid_choice_handled(self):
        judge = _StubJudge({})  # returns empty choice
        ev = RubricDagEvaluator(DAG, endpoint=judge)
        r = ev.evaluate(outputs="x")
        assert r.score is None


class TestRubricLibraryAndRegistry:
    def test_preset_available(self):
        assert "answer_quality" in RUBRIC_PRESETS

    def test_make_from_preset(self):
        ev = make_rubric_dag({}, preset="answer_quality", endpoint=_StubJudge({}))
        assert ev.root == "answers"

    def test_make_unknown_preset_raises(self):
        with pytest.raises(KeyError):
            make_rubric_dag({}, preset="nope")

    def test_registered(self):
        assert "rubric_dag" in get_supported_evaluators()

    def test_build_via_registry(self):
        ev = build_evaluator("rubric_dag", {"dag": DAG, "endpoint": _StubJudge({})})
        assert isinstance(ev, RubricDagEvaluator)
