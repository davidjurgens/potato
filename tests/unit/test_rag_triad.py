"""Unit tests for the RAG triad reference-free evaluators (D10)."""

import json
import pytest

from potato.evaluators.rag_triad import (
    ContextRelevanceEvaluator, GroundednessEvaluator, AnswerRelevanceEvaluator, rag_triad,
)
from potato.evaluators import build_evaluator, get_supported_evaluators


class _StubJudge:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def query(self, prompt, model=None):
        self.prompts.append(prompt)
        return json.dumps(self.payload)


class TestContextRelevance:
    def test_score_clamped_and_returned(self):
        ev = ContextRelevanceEvaluator(endpoint=_StubJudge({"score": 0.9, "reasoning": "ok"}))
        r = ev.evaluate(outputs="ans", inputs={"question": "q", "context": "ctx"})
        assert r.key == "context_relevance" and r.score == 0.9

    def test_no_context(self):
        ev = ContextRelevanceEvaluator(endpoint=_StubJudge({"score": 1.0}))
        r = ev.evaluate(outputs="ans", inputs={"question": "q"})
        assert r.score is None and "context" in r.comment

    def test_context_via_kwarg(self):
        ev = ContextRelevanceEvaluator(endpoint=_StubJudge({"score": 0.5}))
        r = ev.evaluate(outputs="ans", inputs="plain question", context="some ctx")
        assert r.score == 0.5


class TestAnswerRelevance:
    def test_basic(self):
        ev = AnswerRelevanceEvaluator(endpoint=_StubJudge({"score": 0.8, "reasoning": "addresses it"}))
        r = ev.evaluate(outputs="Paris", inputs={"question": "Capital of France?"})
        assert r.key == "answer_relevance" and r.score == 0.8


class TestGroundedness:
    def test_claim_decomposition_fraction(self):
        payload = {"claims": [
            {"claim": "Paris is the capital", "supported": True},
            {"claim": "It has 50M people", "supported": False},
        ], "reasoning": "1 of 2"}
        ev = GroundednessEvaluator(endpoint=_StubJudge(payload))
        r = ev.evaluate(outputs="Paris is the capital; it has 50M people.",
                        inputs={"question": "?", "context": "Paris is the capital of France."})
        assert r.score == 0.5
        assert r.metadata["supported"] == 1 and r.metadata["total"] == 2
        assert len(r.metadata["claims"]) == 2

    def test_all_supported(self):
        payload = {"claims": [{"claim": "x", "supported": True}], "reasoning": "ok"}
        ev = GroundednessEvaluator(endpoint=_StubJudge(payload))
        r = ev.evaluate(outputs="x", inputs={"context": "x is true"})
        assert r.score == 1.0

    def test_no_claims(self):
        ev = GroundednessEvaluator(endpoint=_StubJudge({"claims": []}))
        r = ev.evaluate(outputs="x", inputs={"context": "ctx"})
        assert r.score is None

    def test_no_context(self):
        ev = GroundednessEvaluator(endpoint=_StubJudge({"claims": [{"claim": "x", "supported": True}]}))
        r = ev.evaluate(outputs="x", inputs={"question": "q"})
        assert r.score is None and "context" in r.comment


class TestRegistryAndHelper:
    def test_all_registered(self):
        supported = get_supported_evaluators()
        for name in ("context_relevance", "groundedness", "answer_relevance"):
            assert name in supported

    def test_build_via_registry(self):
        ev = build_evaluator("groundedness", {"endpoint": _StubJudge({"claims": []})})
        assert isinstance(ev, GroundednessEvaluator)

    def test_rag_triad_helper(self):
        triad = rag_triad({}, endpoint=_StubJudge({"score": 1.0}))
        assert set(triad) == {"context_relevance", "groundedness", "answer_relevance"}

    def test_no_endpoint_graceful(self):
        ev = ContextRelevanceEvaluator(config={})  # no ai_support
        r = ev.evaluate(outputs="a", inputs={"question": "q", "context": "c"})
        assert r.score is None
