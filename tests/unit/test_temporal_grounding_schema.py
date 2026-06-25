"""Unit tests for the temporal_grounding schema (M10)."""

from potato.server_utils.schemas.temporal_grounding import generate_temporal_grounding_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "temporal_grounding", "name": "tg",
            "description": "Mark event intervals", "events_key": "events"}
    base.update(kw)
    return base


class TestTemporalGrounding:
    def test_generates_container_and_input(self):
        html, kb = generate_temporal_grounding_layout(_scheme())
        assert "temporal-grounding-container" in html and "temporal-grounding-input" in html
        assert kb == []

    def test_has_iou_and_setinout(self):
        html, _ = generate_temporal_grounding_layout(_scheme())
        assert "function iou(" in html
        assert "captureFromVideo" in html and "tg-setin" in html and "tg-setout" in html

    def test_predicted_vs_gold_bars(self):
        html, _ = generate_temporal_grounding_layout(_scheme())
        assert "tg-bar-pred" in html and "tg-bar-gold" in html

    def test_custom_keys(self):
        html, _ = generate_temporal_grounding_layout(_scheme(video_key="clip", events_key="queries", duration=120))
        assert '"video_key": "clip"' in html and '"events_key": "queries"' in html and '"duration": 120' in html

    def test_persistence_seeds_from_hidden(self):
        html, _ = generate_temporal_grounding_layout(_scheme())
        assert "function restore()" in html and "JSON.parse(h.value)" in html

    def test_registered(self):
        assert "temporal_grounding" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "temporal_grounding", "name": "x", "description": "d"})
        assert "temporal-grounding-container" in html
