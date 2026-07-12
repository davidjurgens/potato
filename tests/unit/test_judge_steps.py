"""Unit tests for JudgeService.judge_steps (per-step process-reward judging)."""

import json
import pytest

from potato.ai.judge import JudgeService, _coerce_reward, _robust_query_json


class FakeEndpoint:
    """Minimal endpoint returning a canned (optionally fenced) JSON string."""

    model = "fake"

    def __init__(self, payload, fenced=False, take_output_format=True, max_tokens=100):
        self._payload = payload
        self._fenced = fenced
        self._take_of = take_output_format
        self.max_tokens = max_tokens
        self.seen_max_tokens = None

    def parseStringToJson(self, s):
        import re
        m = re.search(r"```json(.*?)```", s, re.S)
        return json.loads(m.group(1)) if m else json.loads(s)

    def _content(self):
        body = json.dumps(self._payload)
        return f"```json\n{body}\n```" if self._fenced else body

    # Two signatures — one with output_format (openai/ollama), one without
    # (anthropic). The subclass toggles which is exposed.
    def query(self, prompt, output_format=None):
        self.seen_max_tokens = self.max_tokens
        return self._content()


class FakeAnthropicEndpoint(FakeEndpoint):
    def query(self, prompt):  # no output_format param, like anthropic_endpoint
        self.seen_max_tokens = self.max_tokens
        return self._content()


def _service_with(endpoint):
    js = JudgeService({"ai_support": {"enabled": True, "endpoint_type": "ollama"}})
    js._endpoint = endpoint
    js._endpoint_initialized = True
    return js


class TestCoerceReward:
    def test_ints_and_strings(self):
        assert _coerce_reward(1, False) == 1
        assert _coerce_reward(-1, False) == -1
        assert _coerce_reward("correct", False) == 1
        assert _coerce_reward("incorrect", False) == -1
        assert _coerce_reward(2.0, False) == 1

    def test_neutral_gated(self):
        assert _coerce_reward("neutral", True) == 0
        assert _coerce_reward(0, True) == 0
        assert _coerce_reward("neutral", False) is None
        assert _coerce_reward(0, False) is None

    def test_garbage(self):
        assert _coerce_reward("banana", False) is None
        assert _coerce_reward(None, False) is None


class TestJudgeSteps:
    def test_basic_parse(self):
        payload = {"steps": [
            {"index": 0, "reward": 1, "reasoning": "ok", "confidence": 0.9},
            {"index": 1, "reward": -1, "reasoning": "bad", "confidence": 0.6},
        ]}
        js = _service_with(FakeEndpoint(payload))
        out = js.judge_steps("i", {"description": "d", "allow_neutral": False},
                             [{"text": "a"}, {"text": "b"}])
        assert out == [
            {"index": 0, "reward": 1, "reasoning": "ok", "confidence": 0.9},
            {"index": 1, "reward": -1, "reasoning": "bad", "confidence": 0.6},
        ]

    def test_handles_fenced_json(self):
        payload = {"steps": [{"index": 0, "reward": 1}]}
        js = _service_with(FakeEndpoint(payload, fenced=True))
        out = js.judge_steps("i", {"description": "d"}, [{"text": "a"}])
        assert out[0]["reward"] == 1

    def test_out_of_range_index_dropped(self):
        payload = {"steps": [
            {"index": 0, "reward": 1},
            {"index": 9, "reward": -1},  # only 2 steps -> dropped
        ]}
        js = _service_with(FakeEndpoint(payload))
        out = js.judge_steps("i", {"description": "d"}, [{"text": "a"}, {"text": "b"}])
        assert [s["index"] for s in out] == [0]

    def test_duplicate_index_dropped(self):
        payload = {"steps": [{"index": 0, "reward": 1}, {"index": 0, "reward": -1}]}
        js = _service_with(FakeEndpoint(payload))
        out = js.judge_steps("i", {"description": "d"}, [{"text": "a"}])
        assert len(out) == 1

    def test_neutral_dropped_when_not_allowed(self):
        payload = {"steps": [{"index": 0, "reward": 0}]}
        js = _service_with(FakeEndpoint(payload))
        out = js.judge_steps("i", {"description": "d", "allow_neutral": False}, [{"text": "a"}])
        assert out == []

    def test_neutral_kept_when_allowed(self):
        payload = {"steps": [{"index": 0, "reward": 0}]}
        js = _service_with(FakeEndpoint(payload))
        out = js.judge_steps("i", {"description": "d", "allow_neutral": True}, [{"text": "a"}])
        assert out[0]["reward"] == 0

    def test_max_tokens_raised_then_restored(self):
        payload = {"steps": [{"index": 0, "reward": 1}]}
        ep = FakeEndpoint(payload, max_tokens=100)
        js = _service_with(ep)
        js.judge_steps("i", {"description": "d"}, [{"text": "a"}] * 3)
        assert ep.seen_max_tokens >= 512  # raised during the call
        assert ep.max_tokens == 100        # restored afterwards

    def test_anthropic_signature_without_output_format(self):
        payload = {"steps": [{"index": 0, "reward": 1}]}
        js = _service_with(FakeAnthropicEndpoint(payload))
        out = js.judge_steps("i", {"description": "d"}, [{"text": "a"}])
        assert out[0]["reward"] == 1

    def test_no_endpoint_returns_none(self):
        js = JudgeService({})
        js._endpoint = None
        js._endpoint_initialized = True
        assert js.judge_steps("i", {"description": "d"}, [{"text": "a"}]) is None

    def test_empty_steps_returns_none(self):
        js = _service_with(FakeEndpoint({"steps": []}))
        assert js.judge_steps("i", {"description": "d"}, []) is None

    def test_confidence_clamped(self):
        payload = {"steps": [{"index": 0, "reward": 1, "confidence": 5.0}]}
        js = _service_with(FakeEndpoint(payload))
        out = js.judge_steps("i", {"description": "d"}, [{"text": "a"}])
        assert out[0]["confidence"] == 1.0


class TestRobustQueryJson:
    def test_prefers_parse_string_to_json(self):
        ep = FakeEndpoint({"steps": []}, fenced=True)
        out = _robust_query_json(ep, "prompt")
        assert out == {"steps": []}
