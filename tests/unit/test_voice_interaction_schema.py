"""Unit tests for the voice_interaction schema (M9)."""

from potato.server_utils.schemas.voice_interaction import generate_voice_interaction_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "voice_interaction", "name": "voice",
            "description": "Annotate turn-taking", "turns_key": "turns"}
    base.update(kw)
    return base


class TestVoiceInteraction:
    def test_generates_container_and_input(self):
        html, kb = generate_voice_interaction_layout(_scheme())
        assert "voice-interaction-container" in html
        assert "voice-interaction-input" in html
        assert kb == []

    def test_dual_track_timeline_and_overlap_logic(self):
        html, _ = generate_voice_interaction_layout(_scheme())
        assert "vi-lane-user" in html and "vi-lane-agent" in html
        assert "computeOverlaps" in html

    def test_default_overlap_labels(self):
        html, _ = generate_voice_interaction_layout(_scheme())
        for l in ("agent_should_respond", "agent_should_resume", "backchannel", "uncertain"):
            assert l in html

    def test_custom_labels_and_speakers(self):
        html, _ = generate_voice_interaction_layout(
            _scheme(overlap_labels=["interrupt", "ok"], user_speakers=["Caller"]))
        assert '"overlap_labels": ["interrupt", "ok"]' in html
        assert '"caller"' in html  # lowercased

    def test_persistence_seeds_from_hidden(self):
        html, _ = generate_voice_interaction_layout(_scheme())
        assert "function restore()" in html and "JSON.parse(h.value)" in html

    def test_registered(self):
        assert "voice_interaction" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "voice_interaction", "name": "x", "description": "d"})
        assert "voice-interaction-container" in html
