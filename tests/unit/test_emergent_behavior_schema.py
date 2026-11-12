"""Unit tests for the emergent_behavior schema (M7)."""

from potato.server_utils.schemas.emergent_behavior import generate_emergent_behavior_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "emergent_behavior", "name": "eb",
            "description": "Tag emergent behaviors", "steps_key": "steps"}
    base.update(kw)
    return base


class TestEmergentBehavior:
    def test_generates_container_and_input(self):
        html, kb = generate_emergent_behavior_layout(_scheme())
        assert "emergent-behavior-container" in html and "emergent-behavior-input" in html
        assert kb == []

    def test_default_behaviors(self):
        html, _ = generate_emergent_behavior_layout(_scheme())
        for b in ("collusion", "groupthink", "cascading_error", "role_drift"):
            assert b in html

    def test_turn_set_model(self):
        html, _ = generate_emergent_behavior_layout(_scheme())
        # turns are tracked as a per-behavior set of turn indices.
        assert "STATE[b].turns" in html and "eb-cb" in html

    def test_custom_behaviors(self):
        html, _ = generate_emergent_behavior_layout(_scheme(behaviors=["echo_chamber"]))
        assert '"behaviors": ["echo_chamber"]' in html

    def test_persistence_seeds_from_hidden(self):
        html, _ = generate_emergent_behavior_layout(_scheme())
        assert "function restore()" in html and "JSON.parse(h.value)" in html

    def test_registered(self):
        assert "emergent_behavior" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "emergent_behavior", "name": "x", "description": "d"})
        assert "emergent-behavior-container" in html
