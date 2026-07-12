"""Unit tests for the cot_trace long-CoT display."""

import pytest

from potato.server_utils.displays.cot_trace_display import CotTraceDisplay
from potato.server_utils.displays.registry import display_registry


SEGMENTED = [
    {"index": 0, "text": "First I plan the approach.", "type": "thought"},
    {"index": 1, "text": "compute(x) returns 2x.", "type": "action"},
    {"index": 2, "text": "The result is 0.", "type": "observation"},
]


class TestCotTraceDisplay:
    def setup_method(self):
        self.d = CotTraceDisplay()

    def test_registered(self):
        assert "cot_trace" in display_registry.get_supported_types()

    def test_renders_segmented_steps(self):
        html = self.d.render({"key": "cot_steps"}, SEGMENTED)
        assert html.count('data-turn-index=') == 3
        assert "cot-trace-display" in html

    def test_turn_index_matches_step_index(self):
        html = self.d.render({"key": "cot_steps"}, SEGMENTED)
        for i in range(3):
            assert f'data-turn-index="{i}"' in html
            assert f'data-step-index="{i}"' in html

    def test_sticky_header_and_rail(self):
        html = self.d.render({"key": "cot_steps"}, SEGMENTED)
        assert "cot-trace-header" in html
        assert "position: sticky" in html
        assert "cot-trace-rail" in html
        assert "cot-jump-next" in html

    def test_rail_can_be_disabled(self):
        # The rail <nav> is omitted; the (harmless) rail CSS may remain.
        with_rail = self.d.render({"key": "cot_steps"}, SEGMENTED)
        assert '<nav class="cot-trace-rail"' in with_rail
        without = self.d.render(
            {"key": "cot_steps", "display_options": {"show_rail": False}}, SEGMENTED)
        # The rail <nav> and its dot buttons are gone (rail CSS may remain).
        assert '<nav class="cot-trace-rail"' not in without
        assert '<button type="button" class="cot-rail-dot"' not in without

    def test_long_step_is_clamped(self):
        long_steps = [{"index": 0, "text": "x\n" * 40, "type": "thought"}]
        html = self.d.render({"key": "cot_steps"}, long_steps)
        assert "cot-step-text clamped" in html
        assert "cot-step-expand" in html

    def test_placeholder_when_empty(self):
        assert "No reasoning" in self.d.render({"key": "cot_steps"}, [])
        assert "No reasoning" in self.d.render({"key": "cot_steps"}, None)

    def test_fallback_dialogue_format(self):
        data = [{"speaker": "Agent", "text": "hi"}, {"speaker": "Env", "text": "ok"}]
        html = self.d.render({"key": "conv"}, data)
        assert html.count('data-turn-index=') == 2

    def test_step_type_badges(self):
        html = self.d.render({"key": "cot_steps"}, SEGMENTED)
        assert "badge-thought" in html
        assert "badge-action" in html

    def test_html_escaped(self):
        data = [{"index": 0, "text": "<script>alert(1)</script>", "type": "thought"}]
        html = self.d.render({"key": "cot_steps"}, data)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_registry_render_smoke(self):
        out = display_registry.render(
            "cot_trace", {"key": "cot_steps", "type": "cot_trace"}, SEGMENTED)
        assert "cot-trace-display" in out
