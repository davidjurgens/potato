"""Unit tests for the agent-as-judge evaluator (D12)."""

import json
import pytest

from potato.evaluators.agent_as_judge import AgentAsJudgeEvaluator
from potato.evaluators import build_evaluator, get_supported_evaluators


class _StubJudge:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def query(self, prompt, model=None):
        self.prompts.append(prompt)
        return json.dumps(self.payload)


TRAJ = [
    {"role": "assistant", "content": "Search flights DTW->SFO"},
    {"role": "tool", "content": "Found AS22 $371 refundable"},
    {"role": "assistant", "content": "Booked AS22, emailed itinerary"},
]
REQS = ["Flight is under $400", "Flight is refundable", "Itinerary emailed to user"]


class TestAgentAsJudge:
    def test_per_requirement_score(self):
        payload = {"verdicts": [
            {"requirement": REQS[0], "satisfied": True, "evidence": "step 2: $371"},
            {"requirement": REQS[1], "satisfied": True, "evidence": "step 2: refundable"},
            {"requirement": REQS[2], "satisfied": False, "evidence": "no email step"},
        ], "reasoning": "2 of 3"}
        ev = AgentAsJudgeEvaluator(endpoint=_StubJudge(payload), requirements=REQS)
        r = ev.evaluate(inputs={"question": "Book a flight"}, outputs=TRAJ)
        assert r.score == pytest.approx(2 / 3, abs=1e-6)
        assert r.metadata["satisfied"] == 2 and r.metadata["total"] == 3
        assert r.metadata["spot_check_units"] == 3
        assert len(r.metadata["verdicts"]) == 3
        assert r.metadata["verdicts"][0]["evidence"]

    def test_all_satisfied(self):
        payload = {"verdicts": [{"requirement": r, "satisfied": True, "evidence": "ok"} for r in REQS]}
        ev = AgentAsJudgeEvaluator(endpoint=_StubJudge(payload), requirements=REQS)
        assert ev.evaluate(inputs="task", outputs=TRAJ).score == 1.0

    def test_requirements_from_inputs(self):
        payload = {"verdicts": [{"requirement": "x", "satisfied": True}]}
        ev = AgentAsJudgeEvaluator(endpoint=_StubJudge(payload))
        r = ev.evaluate(inputs={"question": "t", "requirements": ["only one"]}, outputs=TRAJ)
        assert r.score == 1.0

    def test_no_requirements(self):
        ev = AgentAsJudgeEvaluator(endpoint=_StubJudge({}))
        r = ev.evaluate(inputs="task", outputs=TRAJ)
        assert r.score is None and "requirement" in r.comment

    def test_no_verdicts_returned(self):
        ev = AgentAsJudgeEvaluator(endpoint=_StubJudge({"verdicts": []}), requirements=REQS)
        assert ev.evaluate(inputs="t", outputs=TRAJ).score is None

    def test_no_endpoint_graceful(self):
        ev = AgentAsJudgeEvaluator(config={}, requirements=REQS)
        assert ev.evaluate(inputs="t", outputs=TRAJ).score is None

    def test_trajectory_in_prompt(self):
        stub = _StubJudge({"verdicts": [{"requirement": "r", "satisfied": True}]})
        AgentAsJudgeEvaluator(endpoint=stub, requirements=["r"]).evaluate(
            inputs="Book a flight", outputs=TRAJ)
        assert "Booked AS22" in stub.prompts[0]  # intermediate steps are inspected


class TestRegistry:
    def test_registered(self):
        assert "agent_as_judge" in get_supported_evaluators()

    def test_build_via_registry(self):
        ev = build_evaluator("agent_as_judge", {"endpoint": _StubJudge({"verdicts": []}),
                                                "requirements": REQS})
        assert isinstance(ev, AgentAsJudgeEvaluator)
