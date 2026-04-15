"""
Unit tests for LiveCodingAgentDisplay.

Covers the dual-mode display:
- Live mode (no data): renders start form + viewer UI with optional
  controls and instruction input
- Review mode (data present): delegates to CodingTraceDisplay

The display has zero dedicated unit test coverage prior to this file;
rendering failures would silently break the annotation UI for users
trying to annotate coding agent sessions.
"""

import pytest

from potato.server_utils.displays.live_coding_agent_display import (
    LiveCodingAgentDisplay,
)


class TestLiveCodingAgentDisplayLiveMode:
    """Tests for live-mode rendering (no trace data present)."""

    @pytest.fixture
    def display(self):
        return LiveCodingAgentDisplay()

    @pytest.fixture
    def field_config(self):
        return {"key": "structured_turns", "display_options": {}}

    def test_class_attributes(self, display):
        assert display.name == "live_coding_agent"
        assert "key" in display.required_fields
        assert display.supports_span_target is False

    def test_live_mode_none_data_renders_start_form(self, display, field_config):
        html = display.render(field_config, None)
        assert 'class="live-coding-agent-viewer"' in html
        assert 'class="lca-start-form"' in html
        assert 'Start Coding Agent' in html
        assert 'data-action="start"' in html

    def test_live_mode_empty_list_renders_start_form(self, display, field_config):
        """Empty list is treated as 'no session yet' → live mode, not delegated."""
        html = display.render(field_config, [])
        assert 'class="lca-start-form"' in html
        assert 'Start Coding Agent' in html

    def test_live_mode_empty_dict_renders_start_form(self, display, field_config):
        """Dict without structured_turns key falls through to live mode."""
        html = display.render(field_config, {})
        assert 'class="lca-start-form"' in html

    def test_live_mode_dict_with_empty_structured_turns_renders_start_form(
        self, display, field_config
    ):
        """A dict with structured_turns=[] should NOT delegate — falsy value."""
        html = display.render(field_config, {"structured_turns": []})
        assert 'class="lca-start-form"' in html

    def test_live_mode_default_options_include_controls(self, display, field_config):
        html = display.render(field_config, None)
        # show_controls defaults to True
        assert 'data-action="pause"' in html
        assert 'data-action="resume"' in html
        assert 'data-action="stop"' in html

    def test_live_mode_default_options_include_instructions_input(
        self, display, field_config
    ):
        html = display.render(field_config, None)
        # allow_instructions defaults to True
        assert 'class="lca-instruction-input"' in html
        assert 'data-action="instruct"' in html

    def test_live_mode_disable_controls(self, display):
        field_config = {
            "key": "structured_turns",
            "display_options": {"show_controls": False},
        }
        html = LiveCodingAgentDisplay().render(field_config, None)
        assert 'data-action="pause"' not in html
        assert 'data-action="stop"' not in html
        # Instruction input should still appear (separate flag)
        assert 'class="lca-instruction-input"' in html

    def test_live_mode_disable_instructions(self, display):
        field_config = {
            "key": "structured_turns",
            "display_options": {"allow_instructions": False},
        }
        html = LiveCodingAgentDisplay().render(field_config, None)
        assert 'class="lca-instruction-input"' not in html
        assert 'data-action="instruct"' not in html
        # Controls should still appear
        assert 'data-action="pause"' in html

    def test_live_mode_disable_both(self, display):
        field_config = {
            "key": "structured_turns",
            "display_options": {
                "show_controls": False,
                "allow_instructions": False,
            },
        }
        html = LiveCodingAgentDisplay().render(field_config, None)
        assert 'data-action="pause"' not in html
        assert 'data-action="stop"' not in html
        assert 'class="lca-instruction-input"' not in html
        # But the core session container is still there
        assert 'class="lca-session"' in html

    def test_live_mode_status_and_turn_counter_elements_present(
        self, display, field_config
    ):
        html = display.render(field_config, None)
        assert 'lca-status-' in html
        assert 'lca-counter-' in html
        assert 'lca-turns-' in html
        assert 'coding-trace-display' in html  # shared class with review mode

    def test_live_mode_thinking_indicator_starts_hidden(self, display, field_config):
        html = display.render(field_config, None)
        assert 'lca-thinking' in html
        assert 'style="display:none"' in html

    def test_live_mode_uses_field_key_in_ids(self, display):
        field_config = {"key": "my_custom_field", "display_options": {}}
        html = LiveCodingAgentDisplay().render(field_config, None)
        assert 'id="lca-viewer-my_custom_field"' in html
        assert 'id="lca-start-my_custom_field"' in html
        assert 'id="lca-task-my_custom_field"' in html
        assert 'data-field-key="my_custom_field"' in html

    # --- Security: field_key HTML escaping ---

    def test_live_mode_field_key_escapes_quotes(self, display):
        """A malicious field_key with quotes must not break out of attributes."""
        field_config = {"key": 'evil"onload="alert(1)', "display_options": {}}
        html = LiveCodingAgentDisplay().render(field_config, None)
        assert 'onload="alert(1)' not in html
        # The escaped form should appear instead
        assert '&quot;' in html or "&#x27;" in html or "&#34;" in html

    def test_live_mode_field_key_escapes_angle_brackets(self, display):
        field_config = {"key": "<script>alert(1)</script>", "display_options": {}}
        html = LiveCodingAgentDisplay().render(field_config, None)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_live_mode_missing_field_key_renders_empty_id(self, display):
        """Missing key shouldn't crash — falls back to empty string."""
        field_config = {"display_options": {}}
        html = LiveCodingAgentDisplay().render(field_config, None)
        assert 'class="live-coding-agent-viewer"' in html


class TestLiveCodingAgentDisplayReviewMode:
    """Tests for review-mode delegation to CodingTraceDisplay."""

    @pytest.fixture
    def display(self):
        return LiveCodingAgentDisplay()

    @pytest.fixture
    def field_config(self):
        return {"key": "structured_turns", "display_options": {}}

    def test_review_mode_list_delegates_to_coding_trace(self, display, field_config):
        """A non-empty list should be rendered by CodingTraceDisplay, not live mode."""
        turns = [
            {
                "role": "user",
                "content": "Fix the bug in main.py",
                "tool_calls": [],
            }
        ]
        html = display.render(field_config, turns)
        # Live-mode markers must NOT be present
        assert 'class="lca-start-form"' not in html
        assert 'Start Coding Agent' not in html
        # CodingTraceDisplay output markers
        assert 'ct-turn-user' in html
        assert 'Fix the bug in main.py' in html

    def test_review_mode_dict_with_structured_turns_delegates(
        self, display, field_config
    ):
        turns = [
            {
                "role": "user",
                "content": "Refactor the auth module",
                "tool_calls": [],
            }
        ]
        html = display.render(field_config, {"structured_turns": turns})
        assert 'class="lca-start-form"' not in html
        assert 'Refactor the auth module' in html

    def test_review_mode_dict_missing_structured_turns_falls_through(
        self, display, field_config
    ):
        """Dict without structured_turns key should render live mode, not crash."""
        html = display.render(field_config, {"other_key": "some data"})
        assert 'class="lca-start-form"' in html

    def test_review_mode_delegation_reuses_coding_trace_instance(self, display):
        """LCA should hold a single CodingTraceDisplay instance, not create one per render."""
        first = display._coding_trace_display
        # Render twice
        display.render({"key": "x", "display_options": {}}, [
            {"role": "user", "content": "one", "tool_calls": []}
        ])
        display.render({"key": "y", "display_options": {}}, [
            {"role": "user", "content": "two", "tool_calls": []}
        ])
        assert display._coding_trace_display is first


class TestLiveCodingAgentDisplayInterface:
    """Conformance to BaseDisplay interface contracts."""

    def test_has_inline_label_returns_false(self):
        display = LiveCodingAgentDisplay()
        assert display.has_inline_label({"key": "x"}) is False

    def test_get_css_classes_returns_list(self):
        display = LiveCodingAgentDisplay()
        classes = display.get_css_classes({"key": "x"})
        assert isinstance(classes, list)

    def test_does_not_support_span_target(self):
        """LCA must not advertise span target support — its output is a live viewer."""
        assert LiveCodingAgentDisplay.supports_span_target is False
