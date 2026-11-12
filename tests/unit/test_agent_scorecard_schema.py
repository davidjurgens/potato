"""Unit tests for the agent_scorecard schema (M5)."""

from potato.server_utils.schemas.agent_scorecard import generate_agent_scorecard_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "agent_scorecard", "name": "scores",
            "description": "Score each agent and the team", "steps_key": "steps"}
    base.update(kw)
    return base


class TestAgentScorecard:
    def test_generates_container_and_input(self):
        html, kb = generate_agent_scorecard_layout(_scheme())
        assert "agent-scorecard-container" in html
        assert "agent-scorecard-input" in html
        assert kb == []

    def test_default_dimensions(self):
        html, _ = generate_agent_scorecard_layout(_scheme())
        for d in ("role fidelity", "contribution", "coordination", "communication", "efficiency"):
            assert d in html

    def test_custom_dimensions_and_scale(self):
        html, _ = generate_agent_scorecard_layout(
            _scheme(agent_dimensions=["accuracy"], team_dimensions=["synergy"], scale=7))
        assert '"agent_dimensions": ["accuracy"]' in html
        assert '"team_dimensions": ["synergy"]' in html
        assert '"scale": 7' in html

    def test_milestones_block_present_when_configured(self):
        html, _ = generate_agent_scorecard_layout(_scheme(milestones=["plan made", "code passed"]))
        assert '"milestones": ["plan made", "code passed"]' in html

    def test_persistence_seeds_from_hidden(self):
        html, _ = generate_agent_scorecard_layout(_scheme())
        assert "function restore()" in html and "JSON.parse(h.value)" in html

    def test_registered(self):
        assert "agent_scorecard" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "agent_scorecard", "name": "x", "description": "d"})
        assert "agent-scorecard-container" in html
