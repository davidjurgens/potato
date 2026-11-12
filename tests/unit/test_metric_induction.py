"""Unit tests for agent-metric induction (E11)."""

import json
import pytest

from potato.server_utils.metric_induction import induce_metrics, CandidateMetric, _extract_aspect


class _StubLLM:
    """Maps comment substrings to a scripted aspect extraction."""
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = 0
    def query(self, prompt, model=None):
        self.calls += 1
        for frag, payload in self.mapping.items():
            if frag.lower() in prompt.lower():
                return json.dumps(payload)
        return json.dumps({})


MAP = {
    "too long": {"aspect": "Conciseness", "definition": "Is the response appropriately brief?", "polarity": "negative"},
    "rambled": {"aspect": "conciseness", "definition": "Brevity of the response", "polarity": "negative"},
    "wrong tool": {"aspect": "Tool selection", "definition": "Did it pick the right tool?", "polarity": "negative"},
    "great tool": {"aspect": "tool selection", "definition": "Tool choice quality", "polarity": "positive"},
    "polite": {"aspect": "Tone", "definition": "Politeness of the agent", "polarity": "positive"},
}


class TestExtractAspect:
    def test_extracts(self):
        asp = _extract_aspect(_StubLLM(MAP), "the answer was too long")
        assert asp["aspect"] == "Conciseness" and asp["polarity"] == "negative"

    def test_empty_on_no_aspect(self):
        assert _extract_aspect(_StubLLM({}), "x") is None


class TestInduceMetrics:
    def _comments(self):
        return ["the answer was too long", "the model rambled on", "it used the wrong tool",
                "great tool choice", "the agent was polite"]

    def test_groups_recurring_aspects(self):
        cands = induce_metrics(self._comments(), _StubLLM(MAP), min_support=2)
        names = {c.name.lower() for c in cands}
        # conciseness (2) and tool selection (2) recur; tone (1) is below min_support
        assert "conciseness" in names and "tool selection" in names
        assert "tone" not in names

    def test_sorted_by_support(self):
        cands = induce_metrics(self._comments(), _StubLLM(MAP), min_support=1)
        supports = [c.support for c in cands]
        assert supports == sorted(supports, reverse=True)

    def test_polarity_counts_and_examples(self):
        cands = {c.name.lower(): c for c in induce_metrics(self._comments(), _StubLLM(MAP), min_support=2)}
        tool = cands["tool selection"]
        assert tool.support == 2
        assert tool.polarity_counts.get("negative") == 1 and tool.polarity_counts.get("positive") == 1
        assert len(tool.examples) == 2

    def test_keeps_longest_definition(self):
        cands = {c.name.lower(): c for c in induce_metrics(self._comments(), _StubLLM(MAP), min_support=2)}
        # "Is the response appropriately brief?" is longer than "Brevity of the response"
        assert cands["conciseness"].definition == "Is the response appropriately brief?"

    def test_min_support_filter(self):
        cands = induce_metrics(["the agent was polite"], _StubLLM(MAP), min_support=2)
        assert cands == []

    def test_to_dict(self):
        c = induce_metrics(self._comments(), _StubLLM(MAP), min_support=2)[0]
        d = c.to_dict()
        assert "name" in d and "support" in d and "examples" in d
