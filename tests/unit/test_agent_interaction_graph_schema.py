"""Unit tests for the agent_interaction_graph schema (M3)."""

from potato.server_utils.schemas.agent_interaction_graph import (
    generate_agent_interaction_graph_layout)
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "agent_interaction_graph", "name": "graph",
            "description": "Mark the critical path and flag edges", "steps_key": "steps"}
    base.update(kw)
    return base


class TestAgentInteractionGraph:
    def test_generates_container_and_input(self):
        html, kb = generate_agent_interaction_graph_layout(_scheme())
        assert "agent-graph-container" in html
        assert "agent-graph-input" in html
        assert kb == []

    def test_has_svg_canvas(self):
        html, _ = generate_agent_interaction_graph_layout(_scheme())
        assert "aig-svg" in html and "viewBox" in html

    def test_builds_graph_from_steps(self):
        html, _ = generate_agent_interaction_graph_layout(_scheme())
        assert "buildGraph" in html and "edgeMap" in html

    def test_edge_cycle_states(self):
        html, _ = generate_agent_interaction_graph_layout(_scheme())
        assert "EDGE_CYCLE" in html
        assert "critical" in html and "problematic" in html

    def test_accessibility_keyboard_and_summary(self):
        html, _ = generate_agent_interaction_graph_layout(_scheme())
        # Keyboard activation + aria-pressed + a non-color text summary.
        assert "keydown" in html and "aria-pressed" in html
        assert "renderSummary" in html and "aria-live" in html

    def test_persistence_seeds_from_hidden(self):
        html, _ = generate_agent_interaction_graph_layout(_scheme())
        assert "function restore()" in html and "JSON.parse(h.value)" in html

    def test_registered(self):
        assert "agent_interaction_graph" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "agent_interaction_graph", "name": "x", "description": "d"})
        assert "agent-graph-container" in html
