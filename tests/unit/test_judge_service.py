"""
Unit tests for the LLM-as-judge service (potato/ai/judge.py).

No network: the AI endpoint is mocked.
"""

from unittest.mock import patch, MagicMock

import pytest

from potato.ai.judge import (
    JudgeService,
    JudgePrediction,
    extract_labels,
    compute_prompt_version,
    _fuzzy_match_label,
)


RADIO = {"annotation_type": "radio", "name": "verdict",
         "description": "Did the agent succeed?",
         "labels": [{"name": "success"}, {"name": "failure"}]}


class TestHelpers:
    def test_extract_labels_radio(self):
        assert extract_labels(RADIO) == ["success", "failure"]

    def test_extract_labels_likert(self):
        assert extract_labels({"annotation_type": "likert", "name": "q", "size": 4}) == ["1", "2", "3", "4"]

    def test_extract_labels_str_list(self):
        assert extract_labels({"annotation_type": "select", "name": "s", "labels": ["a", "b"]}) == ["a", "b"]

    def test_prompt_version_stable_and_sensitive(self):
        a = compute_prompt_version("rubric x", "verdict", False)
        b = compute_prompt_version("rubric x", "verdict", False)
        c = compute_prompt_version("rubric y", "verdict", False)
        d = compute_prompt_version("rubric x", "verdict", True)
        assert a == b
        assert a != c  # rubric change → new version
        assert a != d  # few-shot toggle → new version

    def test_fuzzy_match(self):
        assert _fuzzy_match_label("Success", ["success", "failure"]) == "success"
        assert _fuzzy_match_label("success.", ["success", "failure"]) == "success"  # trailing punct
        assert _fuzzy_match_label("zzz", ["success", "failure"]) is None


class TestPromptBuilding:
    def test_prompt_contains_rubric_labels_and_instructions(self):
        svc = JudgeService({"judge_alignment": {"schemas": {"verdict": {"rubric": "Strict success only."}}}})
        prompt = svc.build_prompt(RADIO, "Agent did the thing.")
        assert "impartial judge" in prompt
        assert "Allowed labels: success, failure" in prompt
        assert "Strict success only." in prompt
        assert "Agent did the thing." in prompt
        assert "JSON" in prompt

    def test_rubric_falls_back_to_description(self):
        svc = JudgeService({})
        assert svc.get_rubric(RADIO) == "Did the agent succeed?"

    def test_few_shot_examples_rendered(self):
        svc = JudgeService({})
        prompt = svc.build_prompt(RADIO, "target",
                                  few_shot_examples=[{"text": "gave up", "label": "failure"}])
        assert "Examples" in prompt
        assert "gave up" in prompt and "failure" in prompt


def _svc_with_endpoint(response_obj):
    ep = MagicMock()
    ep.model = "fake-model"
    ep.query.return_value = response_obj
    svc = JudgeService({"ai_support": {"enabled": True, "endpoint_type": "x", "ai_config": {}}})
    return svc, ep


class _Resp:
    def __init__(self, d):
        self._d = d
    def model_dump(self):
        return self._d


class TestJudging:
    def test_valid_verdict(self):
        svc, ep = _svc_with_endpoint(_Resp({"label": "success", "confidence": 0.9, "reasoning": "done"}))
        with patch("potato.ai.ai_endpoint.AIEndpointFactory.create_endpoint", return_value=ep):
            pred = svc.judge_instance("t1", RADIO, "text")
        assert isinstance(pred, JudgePrediction)
        assert pred.predicted_label == "success"
        assert pred.confidence == 0.9
        assert pred.model_name == "fake-model"
        assert pred.prompt_version.startswith("v_")

    def test_confidence_clamped(self):
        svc, ep = _svc_with_endpoint(_Resp({"label": "success", "confidence": 5.0, "reasoning": ""}))
        with patch("potato.ai.ai_endpoint.AIEndpointFactory.create_endpoint", return_value=ep):
            pred = svc.judge_instance("t1", RADIO, "text")
        assert pred.confidence == 1.0

    def test_invalid_label_fuzzy_matched(self):
        svc, ep = _svc_with_endpoint(_Resp({"label": "SUCCESS!", "confidence": 0.7, "reasoning": ""}))
        with patch("potato.ai.ai_endpoint.AIEndpointFactory.create_endpoint", return_value=ep):
            pred = svc.judge_instance("t1", RADIO, "text")
        assert pred.predicted_label == "success"

    def test_unmatchable_label_returns_none(self):
        svc, ep = _svc_with_endpoint(_Resp({"label": "banana", "confidence": 0.7, "reasoning": ""}))
        with patch("potato.ai.ai_endpoint.AIEndpointFactory.create_endpoint", return_value=ep):
            pred = svc.judge_instance("t1", RADIO, "text")
        assert pred is None

    def test_string_json_response_parsed(self):
        svc, ep = _svc_with_endpoint('{"label": "failure", "confidence": 0.6, "reasoning": "nope"}')
        with patch("potato.ai.ai_endpoint.AIEndpointFactory.create_endpoint", return_value=ep):
            pred = svc.judge_instance("t1", RADIO, "text")
        assert pred.predicted_label == "failure" and pred.confidence == 0.6

    def test_endpoint_none_returns_none(self):
        svc = JudgeService({})  # no ai_support → no endpoint
        with patch("potato.ai.ai_endpoint.AIEndpointFactory.create_endpoint", return_value=None):
            assert svc.judge_instance("t1", RADIO, "text") is None

    def test_query_exception_returns_none(self):
        ep = MagicMock(); ep.model = "m"; ep.query.side_effect = RuntimeError("boom")
        svc = JudgeService({"ai_support": {"enabled": True, "endpoint_type": "x", "ai_config": {}}})
        with patch("potato.ai.ai_endpoint.AIEndpointFactory.create_endpoint", return_value=ep):
            assert svc.judge_instance("t1", RADIO, "text") is None

    def test_explicit_prompt_version_used(self):
        svc, ep = _svc_with_endpoint(_Resp({"label": "success", "confidence": 0.9}))
        with patch("potato.ai.ai_endpoint.AIEndpointFactory.create_endpoint", return_value=ep):
            pred = svc.judge_instance("t1", RADIO, "text", prompt_version="v_custom")
        assert pred.prompt_version == "v_custom"


class TestSerialization:
    def test_roundtrip(self):
        p = JudgePrediction("i", "s", "success", 0.8, "r", "m", "v_1", ["e1"])
        assert JudgePrediction.from_dict(p.to_dict()).to_dict() == p.to_dict()
