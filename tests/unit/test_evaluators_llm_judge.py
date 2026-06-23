"""Unit tests for the LLM trajectory judge using a stub endpoint (no network)."""

from potato.evaluators import LLMTrajectoryJudge


class _StubEndpoint:
    """Mimics BaseAIEndpoint.query(prompt, Model) -> dict/json."""

    def __init__(self, payload, capture=None):
        self.payload = payload
        self.capture = capture if capture is not None else {}
        self.model = "stub-model"

    def query(self, prompt, model=None):
        self.capture["prompt"] = prompt
        return self.payload


def test_judge_pass_fail_mode():
    ep = _StubEndpoint({"pass": True, "reasoning": "looks good"})
    judge = LLMTrajectoryJudge(endpoint=ep)
    r = judge.evaluate(outputs=[{"role": "assistant", "content": "answer"}])
    assert r.score == 1.0 and r.value is True
    assert r.comment == "looks good"


def test_judge_fail():
    ep = _StubEndpoint({"pass": False, "reasoning": "wrong tool"})
    r = LLMTrajectoryJudge(endpoint=ep).evaluate(outputs="bad")
    assert r.score == 0.0


def test_judge_continuous_mode():
    ep = _StubEndpoint({"score": 0.75, "reasoning": "mostly right"})
    r = LLMTrajectoryJudge(endpoint=ep, continuous=True).evaluate(outputs="x")
    assert r.score == 0.75


def test_judge_continuous_clamps():
    ep = _StubEndpoint({"score": 5.0})
    r = LLMTrajectoryJudge(endpoint=ep, continuous=True).evaluate(outputs="x")
    assert r.score == 1.0


def test_judge_renders_tool_calls_into_prompt():
    capture = {}
    ep = _StubEndpoint({"pass": True}, capture=capture)
    judge = LLMTrajectoryJudge(endpoint=ep)
    trace = {"conversation": [{"speaker": "Agent (Action)", "text": 'get_weather({"loc": "NYC"})'}]}
    judge.evaluate(outputs=trace, inputs="what's the weather")
    assert "get_weather" in capture["prompt"]
    assert "what's the weather" in capture["prompt"]


def test_judge_no_endpoint_returns_none_score():
    # No endpoint injected and no config -> graceful None.
    r = LLMTrajectoryJudge(config={}).evaluate(outputs="x")
    assert r.score is None
