"""Unit tests for the tool_contention schema (M8)."""

from potato.server_utils.schemas.tool_contention import generate_tool_contention_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "tool_contention", "name": "tc",
            "description": "Flag resource contention", "calls_key": "calls"}
    base.update(kw)
    return base


class TestToolContention:
    def test_generates_container_and_input(self):
        html, kb = generate_tool_contention_layout(_scheme())
        assert "tool-contention-container" in html and "tool-contention-input" in html
        assert kb == []

    def test_default_contention_labels(self):
        html, _ = generate_tool_contention_layout(_scheme())
        for l in ("deadlock", "circular_wait", "race_condition", "benign"):
            assert l in html

    def test_same_resource_overlap_logic(self):
        html, _ = generate_tool_contention_layout(_scheme())
        assert "computeContentions" in html and "resource !== calls[b].resource" in html

    def test_custom_labels_and_keys(self):
        html, _ = generate_tool_contention_layout(_scheme(contention_labels=["bad", "ok"], resource_key="lock"))
        assert '"contention_labels": ["bad", "ok"]' in html
        assert '"resource_key": "lock"' in html

    def test_persistence_seeds_from_hidden(self):
        html, _ = generate_tool_contention_layout(_scheme())
        assert "function restore()" in html and "JSON.parse(h.value)" in html

    def test_registered(self):
        assert "tool_contention" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "tool_contention", "name": "x", "description": "d"})
        assert "tool-contention-container" in html
