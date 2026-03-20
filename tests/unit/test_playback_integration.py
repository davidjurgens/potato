"""
Unit tests for playback integration in WebAgentTraceDisplay.

Tests that auto_playback and playback_step_delay display options are
correctly reflected in the rendered HTML data attributes, and that
the default (no playback) produces no such attributes.
"""

import pytest

from potato.server_utils.displays.web_agent_trace_display import WebAgentTraceDisplay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_step(step_index=0, action_type="click", screenshot_url="s.png"):
    return {
        "step_index": step_index,
        "action_type": action_type,
        "screenshot_url": screenshot_url,
        "thought": "",
        "observation": "",
        "timestamp": step_index,
        "coordinates": {"x": 100, "y": 200},
        "viewport": {"width": 1280, "height": 720},
    }


def _make_trace(steps=None, task_description="Test task", site="example.com"):
    if steps is None:
        steps = [_make_step()]
    return {"task_description": task_description, "site": site, "steps": steps}


def _field_config(key="trace", display_options=None):
    cfg = {"key": key}
    if display_options:
        cfg["display_options"] = display_options
    return cfg


# ---------------------------------------------------------------------------
# Default rendering (no playback)
# ---------------------------------------------------------------------------

class TestNoPlayback:
    """Tests that the default rendering does not include playback attributes."""

    def test_no_auto_playback_attribute_by_default(self):
        """With default options, data-auto-playback attribute is absent."""
        display = WebAgentTraceDisplay()
        result = display.render(_field_config(), _make_trace())
        assert 'data-auto-playback' not in result

    def test_no_playback_delay_attribute_by_default(self):
        """With default options, data-playback-step-delay attribute is absent."""
        display = WebAgentTraceDisplay()
        result = display.render(_field_config(), _make_trace())
        assert 'data-playback-step-delay' not in result

    def test_default_auto_playback_option_is_false(self):
        """The default value for auto_playback in optional_fields is False."""
        assert WebAgentTraceDisplay.optional_fields["auto_playback"] is False

    def test_default_playback_delay_option_is_2(self):
        """The default value for playback_step_delay in optional_fields is 2.0."""
        assert WebAgentTraceDisplay.optional_fields["playback_step_delay"] == 2.0

    def test_explicit_false_produces_no_playback_attrs(self):
        """Explicitly setting auto_playback=False also produces no playback attributes."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(display_options={"auto_playback": False})
        result = display.render(cfg, _make_trace())
        assert 'data-auto-playback' not in result
        assert 'data-playback-step-delay' not in result

    def test_viewer_container_still_present_without_playback(self):
        """web-agent-viewer container is always rendered, even without playback."""
        display = WebAgentTraceDisplay()
        result = display.render(_field_config(), _make_trace())
        assert 'class="web-agent-viewer"' in result


# ---------------------------------------------------------------------------
# auto_playback enabled
# ---------------------------------------------------------------------------

class TestAutoPlaybackEnabled:
    """Tests that auto_playback=True adds the correct data attributes."""

    def test_auto_playback_true_adds_attribute(self):
        """auto_playback=True produces data-auto-playback='true' in output."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(display_options={"auto_playback": True})
        result = display.render(cfg, _make_trace())
        assert 'data-auto-playback="true"' in result

    def test_auto_playback_true_adds_delay_attribute(self):
        """auto_playback=True also emits the playback-step-delay attribute."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(display_options={"auto_playback": True})
        result = display.render(cfg, _make_trace())
        assert 'data-playback-step-delay=' in result

    def test_auto_playback_uses_default_delay(self):
        """When auto_playback=True without explicit delay, default 2.0 is used."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(display_options={"auto_playback": True})
        result = display.render(cfg, _make_trace())
        assert 'data-playback-step-delay="2.0"' in result

    def test_playback_attributes_on_viewer_container(self):
        """Playback attributes are added to the web-agent-viewer div."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(display_options={"auto_playback": True})
        result = display.render(cfg, _make_trace())
        # Both attributes should appear on the same div line
        viewer_line_idx = result.index('class="web-agent-viewer"')
        # Scan for playback attrs in the same tag segment
        tag_end = result.index('>', viewer_line_idx)
        tag_segment = result[viewer_line_idx:tag_end]
        assert 'data-auto-playback="true"' in tag_segment

    def test_auto_playback_attribute_value_is_string_true(self):
        """The attribute value is the string 'true', not a Python bool."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(display_options={"auto_playback": True})
        result = display.render(cfg, _make_trace())
        # String "true" in data attr, not "True" (Python) or 1
        assert 'data-auto-playback="true"' in result
        assert 'data-auto-playback="True"' not in result


# ---------------------------------------------------------------------------
# playback_step_delay
# ---------------------------------------------------------------------------

class TestPlaybackStepDelay:
    """Tests that playback_step_delay is reflected correctly in data attributes."""

    def test_custom_delay_reflected_when_playback_enabled(self):
        """Custom delay value appears in data attribute when auto_playback=True."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(
            display_options={"auto_playback": True, "playback_step_delay": 3.5}
        )
        result = display.render(cfg, _make_trace())
        assert 'data-playback-step-delay="3.5"' in result

    def test_integer_delay_reflected_correctly(self):
        """Integer delay value (e.g. 1) is output as its string representation."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(
            display_options={"auto_playback": True, "playback_step_delay": 1}
        )
        result = display.render(cfg, _make_trace())
        assert 'data-playback-step-delay="1"' in result

    def test_zero_delay_reflected(self):
        """Zero delay is a valid value and should appear in the attribute."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(
            display_options={"auto_playback": True, "playback_step_delay": 0}
        )
        result = display.render(cfg, _make_trace())
        assert 'data-playback-step-delay="0"' in result

    def test_large_delay_reflected(self):
        """Large delay values (e.g. 30) are reflected without truncation."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(
            display_options={"auto_playback": True, "playback_step_delay": 30}
        )
        result = display.render(cfg, _make_trace())
        assert 'data-playback-step-delay="30"' in result

    def test_delay_without_playback_not_in_output(self):
        """Setting delay without auto_playback produces no data attributes."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(
            display_options={"auto_playback": False, "playback_step_delay": 5.0}
        )
        result = display.render(cfg, _make_trace())
        assert 'data-auto-playback' not in result
        assert 'data-playback-step-delay' not in result

    def test_default_delay_is_2_0(self):
        """When auto_playback=True and no explicit delay, default 2.0 is used."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(display_options={"auto_playback": True})
        result = display.render(cfg, _make_trace())
        assert 'data-playback-step-delay="2.0"' in result

    def test_custom_delay_does_not_produce_default_delay(self):
        """Custom delay replaces the default value, not appended."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(
            display_options={"auto_playback": True, "playback_step_delay": 1.0}
        )
        result = display.render(cfg, _make_trace())
        assert 'data-playback-step-delay="1.0"' in result
        assert 'data-playback-step-delay="2.0"' not in result


# ---------------------------------------------------------------------------
# Combined attribute verification
# ---------------------------------------------------------------------------

class TestPlaybackAttributeCombinations:
    """Integration-style tests combining multiple playback-related options."""

    def test_both_attributes_present_when_playback_enabled(self):
        """Both data-auto-playback and data-playback-step-delay appear together."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(
            display_options={"auto_playback": True, "playback_step_delay": 2.5}
        )
        result = display.render(cfg, _make_trace())
        assert 'data-auto-playback="true"' in result
        assert 'data-playback-step-delay="2.5"' in result

    def test_neither_attribute_present_when_playback_disabled(self):
        """Neither attribute appears when auto_playback is False."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(
            display_options={"auto_playback": False, "playback_step_delay": 2.5}
        )
        result = display.render(cfg, _make_trace())
        assert 'data-auto-playback' not in result
        assert 'data-playback-step-delay' not in result

    def test_other_options_not_affected_by_playback(self):
        """Enabling playback does not affect other display options."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(
            display_options={
                "auto_playback": True,
                "playback_step_delay": 1.0,
                "show_filmstrip": True,
                "show_thought": True,
            }
        )
        result = display.render(cfg, _make_trace())
        # Filmstrip and thought panel should still be rendered
        assert 'class="filmstrip"' in result

    def test_playback_with_multi_step_trace(self):
        """Playback attributes work correctly with multi-step traces."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(display_options={"auto_playback": True})
        steps = [_make_step(i) for i in range(5)]
        result = display.render(cfg, _make_trace(steps=steps))
        assert 'data-auto-playback="true"' in result
        assert 'data-playback-step-delay="2.0"' in result
        assert "Step 1 of 5" in result

    def test_playback_with_no_data_returns_placeholder(self):
        """Even with playback enabled, None data returns placeholder (no crash)."""
        display = WebAgentTraceDisplay()
        cfg = _field_config(display_options={"auto_playback": True})
        result = display.render(cfg, None)
        assert "No trace data provided" in result
        # Playback attributes are never added for placeholder output
        assert 'data-auto-playback' not in result
