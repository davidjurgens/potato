"""Unit tests for span + free-text LLM-judge modes (hermetic, stub endpoint)."""

import pytest

from potato.ai.judge import (
    JudgeService, judge_mode, score_spans, _locate_spans, _coerce_feedback,
)
from potato.judge_calibration.metrics import span_prf


class StubEndpoint:
    def __init__(self, payload):
        self.payload = payload
        self.model = "stub-model"

    def query(self, prompt, model=None):
        self.last_prompt = prompt
        return self.payload


def _service(payload):
    svc = JudgeService({})
    svc._endpoint = StubEndpoint(payload)
    svc._endpoint_initialized = True
    return svc


# ---- mode routing ----

def test_judge_mode_routing():
    assert judge_mode({"annotation_type": "span"}) == "span"
    assert judge_mode({"annotation_type": "error_span"}) == "span"
    assert judge_mode({"annotation_type": "textbox"}) == "freetext"
    assert judge_mode({"annotation_type": "radio"}) == "categorical"
    assert judge_mode({"annotation_type": "likert"}) == "categorical"


# ---- span locating ----

def test_locate_spans_offsets_and_label_validation():
    text = "Alice met Bob in Paris."
    raw = [{"text": "Alice", "label": "PER"}, {"text": "Paris", "label": "LOC"},
           {"text": "ghost", "label": "PER"},          # not in text -> dropped
           {"text": "Bob", "label": "NOTALABEL"}]       # invalid label -> dropped
    spans = _locate_spans(text, raw, ["PER", "LOC"])
    assert spans == [
        {"start": 0, "end": 5, "text": "Alice", "label": "PER"},
        {"start": 17, "end": 22, "text": "Paris", "label": "LOC"},
    ]


def test_locate_spans_repeated_text_distinct_offsets():
    text = "go go go"
    spans = _locate_spans(text, [{"text": "go", "label": "X"}, {"text": "go", "label": "X"}], ["X"])
    assert [s["start"] for s in spans] == [0, 3]


# ---- span judging ----

def test_judge_spans_locates_and_validates():
    svc = _service({"spans": [{"text": "New York", "label": "LOC"},
                              {"text": "bogus", "label": "LOC"}],
                    "reasoning": "found a city"})
    schema = {"name": "ner", "annotation_type": "span",
              "labels": [{"name": "LOC"}, {"name": "PER"}], "description": "entities"}
    res = svc.judge_spans("i1", schema, "I love New York city")
    assert res["spans"] == [{"start": 7, "end": 15, "text": "New York", "label": "LOC"}]
    assert res["reasoning"] == "found a city"
    assert res["schema_name"] == "ner"


def test_judge_spans_no_endpoint_returns_none():
    svc = JudgeService({})  # no endpoint configured
    assert svc.judge_spans("i1", {"annotation_type": "span"}, "x") is None


# ---- span scoring ----

def test_score_spans_exact_match():
    gold = [{"start": 0, "end": 5, "label": "PER"}]
    pred = [{"start": 0, "end": 5, "label": "PER"}]
    r = score_spans(pred, gold)
    assert r["f1"] == 1.0 and r["tp"] == 1 and r["fp"] == 0 and r["fn"] == 0


def test_score_spans_partial_and_label_mismatch():
    gold = [{"start": 0, "end": 10, "label": "PER"}, {"start": 20, "end": 30, "label": "LOC"}]
    pred = [{"start": 0, "end": 10, "label": "PER"},  # match
            {"start": 20, "end": 30, "label": "PER"}]  # wrong label -> no match
    r = score_spans(pred, gold)
    assert r["tp"] == 1 and r["fp"] == 1 and r["fn"] == 1
    assert 0.0 < r["f1"] < 1.0


def test_span_prf_public_matches_score_spans():
    gold = [{"start": 0, "end": 5, "label": "A"}]
    pred = [{"start": 0, "end": 5, "label": "A"}]
    assert span_prf(pred, gold)["f1"] == 1.0


# ---- free-text judging ----

def test_judge_freetext_default_quality():
    svc = _service({"scores": {"quality": 0.85}, "reasoning": "good"})
    res = svc.judge_freetext("i1", {"name": "answer", "annotation_type": "textbox",
                                    "description": "rate the answer"}, "The answer is 42.")
    assert res["scores"]["quality"] == 0.85
    assert res["reasoning"] == "good"


def test_judge_freetext_multi_dimension_coercion():
    svc = _service({"scores": {"helpful": "true", "tone": "formal", "fluency": 5.0},
                    "reasoning": "x"})
    dims = [{"key": "helpful", "type": "boolean"},
            {"key": "tone", "type": "categorical", "labels": ["formal", "casual"]},
            {"key": "fluency", "type": "continuous"}]
    res = svc.judge_freetext("i1", {"name": "a", "annotation_type": "textbox"}, "txt", dims)
    assert res["scores"]["helpful"] is True
    assert res["scores"]["tone"] == "formal"
    assert res["scores"]["fluency"] == 1.0   # clamped from 5.0


def test_coerce_feedback_types():
    assert _coerce_feedback("yes", "boolean", None) is True
    assert _coerce_feedback("no", "boolean", None) is False
    assert _coerce_feedback(2.0, "continuous", None) == 1.0
    assert _coerce_feedback(-1, "continuous", None) == 0.0
    assert _coerce_feedback("FORMAL", "categorical", ["formal", "casual"]) == "formal"
    assert _coerce_feedback("bad", "continuous", None) is None
