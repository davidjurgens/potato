"""
Unit tests for LiveAgentDisplay.

Tests cover:
- Render with empty/None data → live mode UI elements present
- Render with populated trace data (dict with steps) → delegates to review mode
- display_options overrides applied correctly
- HTML structure: start form, status bar, controls, filmstrip, overlay controls
- Conditional sections (show_controls=False, show_filmstrip=False, etc.)
- field_key is safely HTML-escaped
- Data attributes encoded in the container
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from potato.server_utils.displays.live_agent_display import LiveAgentDisplay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render(field_config, data):
    """Convenience: instantiate display and render."""
    display = LiveAgentDisplay()
    return display.render(field_config, data)


# ---------------------------------------------------------------------------
# Live mode — triggered when data is empty/None
# ---------------------------------------------------------------------------

class TestLiveModeEmpty:
    def test_none_data_renders_live_mode(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-viewer" in html

    def test_empty_dict_renders_live_mode(self):
        html = _render({"key": "agent_trace"}, {})
        assert "live-agent-viewer" in html

    def test_empty_string_renders_live_mode(self):
        html = _render({"key": "agent_trace"}, "")
        assert "live-agent-viewer" in html

    def test_dict_without_steps_renders_live_mode(self):
        """A dict that has keys but no 'steps' is live mode, not review mode."""
        html = _render({"key": "agent_trace"}, {"task_description": "Do something"})
        assert "live-agent-viewer" in html

    def test_dict_with_empty_steps_renders_live_mode(self):
        """steps=[] is falsy, so live mode applies."""
        html = _render({"key": "agent_trace"}, {"steps": []})
        assert "live-agent-viewer" in html

    # --- start form ---

    def test_start_form_present(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-start-form" in html

    def test_start_form_contains_start_button(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-start-btn" in html
        assert "Start Agent" in html

    def test_start_form_task_input_present(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-task-input" in html

    def test_start_form_url_input_present(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-url-input" in html

    def test_start_form_prefilled_from_data(self):
        data = {"task_description": "Buy milk", "start_url": "https://shop.example.com"}
        html = _render({"key": "trace"}, data)
        assert "Buy milk" in html
        assert "https://shop.example.com" in html

    def test_start_form_prefilled_url_fallback_to_url_key(self):
        data = {"url": "https://fallback.example.com"}
        html = _render({"key": "trace"}, data)
        assert "https://fallback.example.com" in html

    # --- status bar ---

    def test_status_bar_present(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-status" in html

    def test_status_indicator_starts_idle(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-status-indicator idle" in html

    def test_status_text_ready(self):
        html = _render({"key": "agent_trace"}, None)
        assert "Ready" in html

    def test_step_counter_starts_at_zero(self):
        html = _render({"key": "agent_trace"}, None)
        assert "Step 0" in html

    # --- main viewer (hidden until session starts) ---

    def test_main_panel_present_but_hidden(self):
        html = _render({"key": "agent_trace"}, None)
        assert 'class="live-agent-main"' in html
        assert 'style="display: none;"' in html

    def test_screenshot_panel_present(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-screenshot-panel" in html

    def test_thought_panel_present_by_default(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-thought-panel" in html
        assert "Agent Thinking" in html

    def test_step_details_panel_present(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-step-details" in html

    # --- controls ---

    def test_controls_present_by_default(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-controls" in html
        assert "live-agent-pause-btn" in html
        assert "live-agent-stop-btn" in html

    def test_takeover_button_present_by_default(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-takeover-btn" in html
        assert "Take Over" in html

    def test_instruction_input_present_by_default(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-instruction-input" in html
        assert "live-agent-instruct-btn" in html

    # --- filmstrip ---

    def test_filmstrip_present_by_default(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-filmstrip" in html

    # --- overlay controls ---

    def test_overlay_controls_present_by_default(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-overlay-controls" in html
        assert "live-agent-overlay-toggle" in html

    # --- container attributes ---

    def test_field_key_encoded_in_container(self):
        html = _render({"key": "my_trace_field"}, None)
        assert 'data-field-key="my_trace_field"' in html

    def test_config_json_encoded_in_container(self):
        html = _render({"key": "agent_trace"}, None)
        # The data-config attribute should be present
        assert "data-config=" in html

    def test_config_json_contains_expected_keys(self):
        html = _render({"key": "agent_trace"}, None)
        # The JSON is HTML-escaped and embedded in a data attribute
        # Unescape and parse to verify
        import html as html_module
        start = html.index('data-config="') + len('data-config="')
        end = html.index('"', start)
        raw_json = html_module.unescape(html[start:end])
        config = json.loads(raw_json)
        assert "show_overlays" in config
        assert "show_filmstrip" in config
        assert "show_controls" in config
        assert "allow_takeover" in config
        assert "allow_instructions" in config

    # --- CSS is included ---

    def test_css_is_included(self):
        html = _render({"key": "agent_trace"}, None)
        assert "<style>" in html
        assert ".live-agent-viewer" in html

    def test_svg_overlay_layer_present(self):
        html = _render({"key": "agent_trace"}, None)
        assert "live-agent-overlay-layer" in html


# ---------------------------------------------------------------------------
# Helpers for option tests
# ---------------------------------------------------------------------------

def _html_body(field_config, data):
    """Return only the HTML portion of the render output (after the <style> block).

    The <style> block always contains CSS class-name strings like
    '.live-agent-controls { ... }' regardless of display options.
    To test that conditional HTML elements are absent we must inspect
    the HTML body only.
    """
    rendered = _render(field_config, data)
    style_end = rendered.index("</style>") + len("</style>")
    return rendered[style_end:]


# ---------------------------------------------------------------------------
# Display options override tests
# ---------------------------------------------------------------------------

class TestDisplayOptions:
    def test_show_controls_false_hides_controls(self):
        body = _html_body(
            {"key": "agent_trace", "display_options": {"show_controls": False}},
            None,
        )
        assert "live-agent-controls" not in body
        assert "live-agent-pause-btn" not in body

    def test_show_thought_false_hides_thought_panel(self):
        body = _html_body(
            {"key": "agent_trace", "display_options": {"show_thought": False}},
            None,
        )
        assert "live-agent-thought-panel" not in body

    def test_show_filmstrip_false_hides_filmstrip(self):
        body = _html_body(
            {"key": "agent_trace", "display_options": {"show_filmstrip": False}},
            None,
        )
        assert "live-agent-filmstrip" not in body

    def test_show_overlays_false_hides_overlay_controls(self):
        body = _html_body(
            {"key": "agent_trace", "display_options": {"show_overlays": False}},
            None,
        )
        assert "live-agent-overlay-controls" not in body

    def test_allow_takeover_false_hides_takeover_button(self):
        body = _html_body(
            {"key": "agent_trace", "display_options": {"allow_takeover": False}},
            None,
        )
        assert "live-agent-takeover-btn" not in body

    def test_allow_instructions_false_hides_instruction_input(self):
        body = _html_body(
            {"key": "agent_trace", "display_options": {"allow_instructions": False}},
            None,
        )
        assert "live-agent-instruction-input" not in body

    def test_custom_screenshot_max_width_applied_to_css(self):
        html = _render(
            {"key": "agent_trace", "display_options": {"screenshot_max_width": 1200}},
            None,
        )
        assert "1200px" in html

    def test_custom_screenshot_max_height_applied_to_css(self):
        html = _render(
            {"key": "agent_trace", "display_options": {"screenshot_max_height": 800}},
            None,
        )
        assert "800px" in html

    def test_custom_filmstrip_size_applied_to_css(self):
        html = _render(
            {"key": "agent_trace", "display_options": {"filmstrip_size": 120}},
            None,
        )
        assert "120px" in html

    def test_config_json_reflects_option_overrides(self):
        import html as html_module
        rendered = _render(
            {
                "key": "trace",
                "display_options": {
                    "show_controls": False,
                    "allow_takeover": False,
                    "show_filmstrip": False,
                },
            },
            None,
        )
        start = rendered.index('data-config="') + len('data-config="')
        end = rendered.index('"', start)
        raw_json = html_module.unescape(rendered[start:end])
        config = json.loads(raw_json)
        assert config["show_controls"] is False
        assert config["allow_takeover"] is False
        assert config["show_filmstrip"] is False

    def test_all_controls_off_leaves_side_panel_structure(self):
        """Disabling optional sections still leaves the core side panel."""
        html = _render(
            {
                "key": "agent_trace",
                "display_options": {
                    "show_controls": False,
                    "show_thought": False,
                },
            },
            None,
        )
        assert "live-agent-side-panel" in html
        assert "live-agent-step-details" in html

    def test_defaults_applied_when_no_display_options(self):
        """No display_options key → all defaults are used."""
        display = LiveAgentDisplay()
        options = display.get_display_options({"key": "trace"})

        assert options["show_overlays"] is True
        assert options["show_filmstrip"] is True
        assert options["show_thought"] is True
        assert options["show_controls"] is True
        assert options["allow_takeover"] is True
        assert options["allow_instructions"] is True
        assert options["screenshot_max_width"] == 900
        assert options["screenshot_max_height"] == 650
        assert options["filmstrip_size"] == 80


# ---------------------------------------------------------------------------
# Review mode — triggered when data has non-empty 'steps'
# ---------------------------------------------------------------------------

class TestReviewMode:
    # WebAgentTraceDisplay is imported locally inside _render_review_mode via
    # "from .web_agent_trace_display import WebAgentTraceDisplay", so the
    # correct patch target is the class in its source module.
    _PATCH_TARGET = "potato.server_utils.displays.web_agent_trace_display.WebAgentTraceDisplay"

    def test_populated_trace_delegates_to_web_agent_trace_display(self):
        """When data has steps, render() calls WebAgentTraceDisplay.render()."""
        trace_data = {
            "steps": [
                {
                    "step_index": 0,
                    "screenshot_url": "screenshots/step_000.png",
                    "action_type": "click",
                    "thought": "I see a button",
                    "observation": "Clicked successfully",
                    "timestamp": 1.0,
                }
            ],
            "task_description": "Find the login page",
        }

        sentinel_html = "<div>review-mode-sentinel</div>"
        with patch(self._PATCH_TARGET) as MockTraceDisplay:
            mock_instance = MagicMock()
            mock_instance.render.return_value = sentinel_html
            MockTraceDisplay.return_value = mock_instance

            result = _render({"key": "agent_trace"}, trace_data)

        assert result == sentinel_html
        MockTraceDisplay.assert_called_once()
        mock_instance.render.assert_called_once_with({"key": "agent_trace"}, trace_data)

    def test_review_mode_does_not_include_live_ui_elements(self):
        """Review mode output (from WebAgentTraceDisplay) should not contain live-only elements."""
        trace_data = {"steps": [{"step_index": 0, "action_type": "click"}]}

        with patch(self._PATCH_TARGET) as MockTraceDisplay:
            mock_instance = MagicMock()
            mock_instance.render.return_value = "<div>trace viewer</div>"
            MockTraceDisplay.return_value = mock_instance

            result = _render({"key": "trace"}, trace_data)

        # The live-mode viewer container must not appear in delegated output
        assert "live-agent-start-form" not in result

    def test_live_mode_not_triggered_when_steps_present(self):
        """Steps present → no start-form (live mode) in the output."""
        trace_data = {"steps": [{"step_index": 0}]}

        with patch(self._PATCH_TARGET) as MockTraceDisplay:
            mock_instance = MagicMock()
            mock_instance.render.return_value = "<div>review</div>"
            MockTraceDisplay.return_value = mock_instance

            result = _render({"key": "trace"}, trace_data)

        assert "live-agent-start-form" not in result


# ---------------------------------------------------------------------------
# HTML safety
# ---------------------------------------------------------------------------

class TestHTMLSafety:
    def test_field_key_with_special_chars_is_escaped(self):
        """Special characters in field_key must be HTML-escaped (check HTML body)."""
        rendered = _render({"key": 'trace"><script>alert(1)</script>'}, None)
        style_end = rendered.index("</style>") + len("</style>")
        body = rendered[style_end:]
        assert "<script>alert(1)</script>" not in body

    def test_task_description_with_html_is_escaped(self):
        """Raw HTML in task_description must not appear unescaped in the body."""
        data = {"task_description": '<b>inject</b>', "start_url": ""}
        rendered = _render({"key": "trace"}, data)
        style_end = rendered.index("</style>") + len("</style>")
        body = rendered[style_end:]
        # The literal tags must not appear as live HTML
        assert "<b>inject</b>" not in body
        # But the escaped content should be present
        assert "inject" in body

    def test_start_url_with_html_is_escaped(self):
        """The injected closing quote + tag must not appear unescaped."""
        data = {"start_url": 'https://example.com"><img src=x onerror=alert(1)>'}
        rendered = _render({"key": "trace"}, data)
        style_end = rendered.index("</style>") + len("</style>")
        body = rendered[style_end:]
        # The raw injection sequence that would break out of the attribute must not be present
        assert '"><img' not in body
        # The URL itself must appear (safely escaped)
        assert "https://example.com" in body


# ---------------------------------------------------------------------------
# Display metadata / class-level attributes
# ---------------------------------------------------------------------------

class TestDisplayMetadata:
    def test_name_attribute(self):
        assert LiveAgentDisplay.name == "live_agent"

    def test_required_fields(self):
        assert "key" in LiveAgentDisplay.required_fields

    def test_supports_span_target_is_false(self):
        assert LiveAgentDisplay.supports_span_target is False

    def test_optional_fields_has_expected_keys(self):
        opts = LiveAgentDisplay.optional_fields
        assert "show_overlays" in opts
        assert "show_filmstrip" in opts
        assert "show_thought" in opts
        assert "show_controls" in opts
        assert "allow_takeover" in opts
        assert "allow_instructions" in opts
        assert "screenshot_max_width" in opts
        assert "screenshot_max_height" in opts
        assert "filmstrip_size" in opts

    def test_description_is_nonempty(self):
        assert LiveAgentDisplay.description

    def test_validate_config_passes_with_key(self):
        display = LiveAgentDisplay()
        errors = display.validate_config({"key": "trace"})
        assert errors == []

    def test_validate_config_fails_without_key(self):
        display = LiveAgentDisplay()
        errors = display.validate_config({})
        assert any("key" in e for e in errors)
