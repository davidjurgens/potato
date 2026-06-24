"""Unit tests for persona-driven multi-turn simulation (D8)."""

import json
import pytest

from potato.simulator.persona_simulator import (
    Persona, PERSONA_LIBRARY, ConversationGolden, ConversationResult,
    simulate_conversation, pass_hat_k,
)


class _ScriptedLLM:
    """User-turn replies are scripted; the success judge returns a fixed verdict."""

    def __init__(self, user_turns, success=True, reason="ok"):
        self.user_turns = list(user_turns)
        self.success = success
        self.reason = reason
        self.calls = 0

    def query(self, prompt, fmt=None):
        # The success-judge prompt asks for JSON with "success".
        if "Respond as JSON" in prompt and "success" in prompt:
            return json.dumps({"success": self.success, "reason": self.reason})
        # Otherwise it's a user-turn request.
        self.calls += 1
        return self.user_turns.pop(0) if self.user_turns else "DONE"


def _echo_agent(history):
    return f"Agent reply to: {history[-1]['content'][:30]}"


class TestPersonaLibrary:
    def test_library_has_diverse_personas(self):
        assert {"cooperative", "terse", "impatient", "info_withholding"} <= set(PERSONA_LIBRARY)

    def test_system_prompt_carries_goal_and_done_protocol(self):
        p = PERSONA_LIBRARY["terse"]
        sp = p.system_prompt()
        assert p.goal in sp and "DONE" in sp


class TestSimulateConversation:
    def test_runs_until_user_done(self):
        llm = _ScriptedLLM(user_turns=["Can you confirm?", "DONE"])
        golden = ConversationGolden(scenario="I need to book a flight.",
                                    expected_outcome="A flight is booked.", max_turns=6)
        r = simulate_conversation("cooperative", _echo_agent, golden, llm=llm)
        assert r.ended_by == "user_done"
        assert r.success is True
        assert r.turns[0] == {"role": "user", "content": "I need to book a flight."}
        # turns alternate user/assistant
        assert any(t["role"] == "assistant" for t in r.turns)

    def test_respects_max_turns(self):
        llm = _ScriptedLLM(user_turns=["more", "more", "more", "more", "more", "more", "more"])
        golden = ConversationGolden(scenario="hi", expected_outcome="done", max_turns=3)
        r = simulate_conversation("impatient", _echo_agent, golden, llm=llm)
        assert r.ended_by == "max_turns"
        assert r.n_turns <= 3 + 1

    def test_failure_verdict(self):
        llm = _ScriptedLLM(user_turns=["DONE"], success=False, reason="never booked")
        golden = ConversationGolden(scenario="book it", expected_outcome="booked")
        r = simulate_conversation("cooperative", _echo_agent, golden, llm=llm)
        assert r.success is False and "never booked" in r.reason

    def test_agent_exception_is_contained(self):
        def bad_agent(history):
            raise RuntimeError("boom")
        llm = _ScriptedLLM(user_turns=["DONE"], success=False)
        r = simulate_conversation("cooperative", bad_agent,
                                  ConversationGolden(scenario="x", expected_outcome="y"), llm=llm)
        assert any("agent error" in t["content"] for t in r.turns)

    def test_no_llm_graceful(self):
        r = simulate_conversation("cooperative", _echo_agent,
                                  ConversationGolden(scenario="x", expected_outcome="y"), config={})
        assert r.success is None and "no LLM" in r.reason


class TestPassHatK:
    def test_all_pass(self):
        def make_llm():
            return _ScriptedLLM(user_turns=["DONE"], success=True)
        # pass_hat_k builds its own conversations; inject a fresh-scripted llm each call
        # by using a stub that always says DONE then judges success.
        llm = _ScriptedLLM(user_turns=["DONE"] * 30, success=True)
        out = pass_hat_k("cooperative", _echo_agent,
                         ConversationGolden(scenario="x", expected_outcome="y"), k=3, llm=llm)
        assert out["k"] == 3 and out["passes"] == 3 and out["pass_hat_k"] == 1.0

    def test_partial_reliability(self):
        # alternate success via a custom llm whose verdict flips per call
        class FlakyLLM(_ScriptedLLM):
            def __init__(self):
                super().__init__(user_turns=["DONE"] * 30)
                self._judge_calls = 0
            def query(self, prompt, fmt=None):
                if "Respond as JSON" in prompt and "success" in prompt:
                    self._judge_calls += 1
                    return json.dumps({"success": self._judge_calls % 2 == 1, "reason": "flaky"})
                return "DONE"
        out = pass_hat_k("terse", _echo_agent,
                         ConversationGolden(scenario="x", expected_outcome="y"), k=4, llm=FlakyLLM())
        assert 0.0 < out["pass_hat_k"] < 1.0
