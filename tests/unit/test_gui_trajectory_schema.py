"""Unit tests for the gui_trajectory schema (M11)."""

from potato.server_utils.schemas.gui_trajectory import generate_gui_trajectory_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "gui_trajectory", "name": "gui",
            "description": "Judge each GUI step", "steps_key": "steps"}
    base.update(kw)
    return base


class TestGuiTrajectory:
    def test_generates_container_and_input(self):
        html, kb = generate_gui_trajectory_layout(_scheme())
        assert "gui-trajectory-container" in html
        assert "gui-trajectory-input" in html
        assert kb == []

    def test_default_verdict_options(self):
        html, _ = generate_gui_trajectory_layout(_scheme())
        for v in ("correct", "wrong_element", "wrong_action", "hallucinated"):
            assert v in html

    def test_custom_verdict_and_coord_space(self):
        html, _ = generate_gui_trajectory_layout(_scheme(verdict_options=["ok", "bad"], coord_space="pixels"))
        assert '"verdict_options": ["ok", "bad"]' in html
        assert '"coord_space": "pixels"' in html

    def test_renders_screenshot_and_grounding_marker(self):
        html, _ = generate_gui_trajectory_layout(_scheme())
        assert "gt-shot" in html and "gt-marker" in html and "extractSteps" in html

    def test_restore_by_index_not_positional(self):
        html, _ = generate_gui_trajectory_layout(_scheme())
        assert "byIndex" in html and "JSON.parse(h.value)" in html

    def test_registered(self):
        assert "gui_trajectory" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "gui_trajectory", "name": "x", "description": "d"})
        assert "gui-trajectory-container" in html
