"""Unit tests for the handoff_review schema (M2)."""

from potato.server_utils.schemas.handoff_review import generate_handoff_review_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "handoff_review", "name": "handoffs",
            "description": "Review each agent handoff", "steps_key": "steps"}
    base.update(kw)
    return base


class TestHandoffReview:
    def test_generates_container_and_input(self):
        html, kb = generate_handoff_review_layout(_scheme())
        assert "handoff-review-container" in html
        assert "handoff-review-input" in html
        assert kb == []

    def test_default_flags(self):
        html, _ = generate_handoff_review_layout(_scheme())
        for f in ("info_loss", "dropped_constraint", "garbling", "goal_drift"):
            assert f in html

    def test_custom_flags(self):
        html, _ = generate_handoff_review_layout(_scheme(flags=["lost_context", "wrong_target"]))
        assert '"flags": ["lost_context", "wrong_target"]' in html

    def test_extracts_handoffs_on_agent_change(self):
        html, _ = generate_handoff_review_layout(_scheme())
        assert "extractHandoffs" in html and "a !== prev" in html

    def test_restore_by_index_not_positional(self):
        html, _ = generate_handoff_review_layout(_scheme())
        assert "byIndex" in html and "s.index !== undefined" in html

    def test_registered(self):
        assert "handoff_review" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "handoff_review", "name": "x", "description": "d"})
        assert "handoff-review-container" in html
