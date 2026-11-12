"""Unit tests for the failure_attribution schema (M1)."""

import pytest

from potato.server_utils.schemas.failure_attribution import generate_failure_attribution_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "failure_attribution", "name": "blame",
            "description": "Attribute the failure", "steps_key": "steps"}
    base.update(kw)
    return base


class TestFailureAttribution:
    def test_generates_form_and_inputs(self):
        html, kb = generate_failure_attribution_layout(_scheme())
        assert "failure-attribution-container" in html
        assert "failure-attribution-input" in html
        assert kb == []

    def test_has_agent_step_reason_fields(self):
        html, _ = generate_failure_attribution_layout(_scheme())
        assert "fa-agent" in html and "fa-step" in html and "fa-reason" in html

    def test_persistence_seeds_from_hidden_value(self):
        # The IIFE must read the hidden input value before wiring change events.
        html, _ = generate_failure_attribution_layout(_scheme())
        assert "JSON.parse(h.value)" in html
        assert "responsible_agent" in html and "decisive_step" in html

    def test_static_agents_embedded(self):
        html, _ = generate_failure_attribution_layout(_scheme(agents=["Planner", "Coder"]))
        assert "Planner" in html and "Coder" in html

    def test_registered(self):
        assert "failure_attribution" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "failure_attribution", "name": "x", "description": "d"})
        assert "failure-attribution-container" in html

    def test_custom_agent_key(self):
        html, _ = generate_failure_attribution_layout(_scheme(agent_key="role"))
        assert '"agent_key": "role"' in html
