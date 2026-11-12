"""Unit tests for the eval→improve loop: export + reflective proposal (E12)."""

import json
import pytest

from potato.server_utils.prompt_optimization import (
    export_for_optimization, reflective_proposal, PromptDiff,
)


EXAMPLES = [
    {"inputs": {"q": "2+2"}, "reference_outputs": "4"},
    {"inputs": {"q": "cap of France"}, "reference_outputs": "Paris"},
]


class TestExport:
    def test_dspy_format(self):
        out = export_for_optimization(EXAMPLES, prompt="Answer concisely.", fmt="dspy")
        assert out["format"] == "dspy" and out["n"] == 2
        assert out["signature_instructions"] == "Answer concisely."
        assert out["trainset"][0]["expected"] == "4"

    def test_gepa_format(self):
        out = export_for_optimization(EXAMPLES, prompt="P", fmt="gepa")
        assert out["format"] == "gepa" and out["seed_prompt"] == "P"
        assert "objective" in out

    def test_unknown_format_raises(self):
        with pytest.raises(ValueError):
            export_for_optimization(EXAMPLES, fmt="bogus")


class _StubLLM:
    def __init__(self, proposed="Answer in one word.", rationale="be terse"):
        self.proposed, self.rationale = proposed, rationale
    def query(self, prompt, model=None):
        return json.dumps({"proposed_prompt": self.proposed, "rationale": self.rationale})


class TestReflectiveProposal:
    def _failures(self):
        return [{"inputs": {"q": "2+2"}, "expected": "4", "got": "The answer is four.",
                 "reason": "too verbose"}]

    def test_proposes_pending_diff(self):
        diff = reflective_proposal("Answer the question.", self._failures(), _StubLLM())
        assert isinstance(diff, PromptDiff)
        assert diff.approved is None          # pending human review
        assert diff.changed is True
        assert diff.proposed_prompt == "Answer in one word."
        assert diff.based_on_failures == 1

    def test_approve_reject(self):
        diff = reflective_proposal("p", self._failures(), _StubLLM())
        assert diff.approve("looks good").approved is True
        assert diff.reject("nope").approved is False

    def test_no_failures_returns_none(self):
        assert reflective_proposal("p", [], _StubLLM()) is None

    def test_no_prompt_returns_none(self):
        assert reflective_proposal("", self._failures(), _StubLLM()) is None

    def test_empty_proposal_returns_none(self):
        assert reflective_proposal("p", self._failures(), _StubLLM(proposed="")) is None

    def test_unchanged_flag(self):
        diff = reflective_proposal("Answer in one word.", self._failures(),
                                   _StubLLM(proposed="Answer in one word."))
        assert diff.changed is False

    def test_to_dict(self):
        d = reflective_proposal("p", self._failures(), _StubLLM()).to_dict()
        assert "proposed_prompt" in d and "approved" in d and "changed" in d
