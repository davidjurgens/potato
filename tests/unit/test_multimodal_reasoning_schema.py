"""Unit tests for the multimodal_reasoning schema (M15)."""

from potato.server_utils.schemas.multimodal_reasoning import generate_multimodal_reasoning_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "multimodal_reasoning", "name": "mmr",
            "description": "Rate each reasoning step", "steps_key": "steps"}
    base.update(kw)
    return base


class TestMultimodalReasoning:
    def test_generates_container_and_input(self):
        html, kb = generate_multimodal_reasoning_layout(_scheme())
        assert "mmr-container" in html and "mmr-input" in html
        assert kb == []

    def test_default_verdicts(self):
        html, _ = generate_multimodal_reasoning_layout(_scheme())
        for v in ("coherent", "incoherent", "visual_hallucination", "uncertain"):
            assert v in html

    def test_renders_typed_blocks(self):
        html, _ = generate_multimodal_reasoning_layout(_scheme())
        for cls in ("mmr-image", "mmr-tool", "mmr-action", "mmr-text"):
            assert cls in html
        assert "typeOf" in html and "blockHtml" in html

    def test_custom_verdicts(self):
        html, _ = generate_multimodal_reasoning_layout(_scheme(verdict_options=["ok", "bad"]))
        assert '"verdict_options": ["ok", "bad"]' in html

    def test_restore_by_index(self):
        html, _ = generate_multimodal_reasoning_layout(_scheme())
        assert "byIndex" in html and "JSON.parse(h.value)" in html

    def test_registered(self):
        assert "multimodal_reasoning" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "multimodal_reasoning", "name": "x", "description": "d"})
        assert "mmr-container" in html
