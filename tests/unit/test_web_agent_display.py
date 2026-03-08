"""
Unit tests for WebAgentTraceDisplay rendering.

Tests the web agent trace display type, which renders interactive
step-by-step viewers for web agent browsing traces with SVG overlays,
filmstrip navigation, and step details.
"""

import html
import json

import pytest

from potato.server_utils.displays.web_agent_trace_display import (
    WebAgentTraceDisplay,
    ACTION_TYPE_COLORS,
    DEFAULT_ACTION_COLOR,
)


def _make_step(
    step_index=0,
    action_type="click",
    screenshot_url="screenshots/step_000.png",
    coordinates=None,
    mouse_path=None,
    thought="",
    observation="",
    timestamp="",
    viewport=None,
    element=None,
    typed_text="",
    scroll_direction="",
):
    """Create a step dict with sensible defaults."""
    step = {
        "step_index": step_index,
        "action_type": action_type,
        "screenshot_url": screenshot_url,
        "thought": thought,
        "observation": observation,
        "timestamp": timestamp,
    }
    if coordinates is not None:
        step["coordinates"] = coordinates
    else:
        step["coordinates"] = {"x": 100, "y": 200}
    if mouse_path is not None:
        step["mouse_path"] = mouse_path
    if viewport is not None:
        step["viewport"] = viewport
    else:
        step["viewport"] = {"width": 1280, "height": 720}
    if element is not None:
        step["element"] = element
    if typed_text:
        step["typed_text"] = typed_text
    if scroll_direction:
        step["scroll_direction"] = scroll_direction
    return step


def _make_trace_data(steps=None, task_description="Test task", site="example.com"):
    """Create a trace data dict with sensible defaults."""
    if steps is None:
        steps = [_make_step()]
    return {
        "task_description": task_description,
        "site": site,
        "steps": steps,
    }


def _make_field_config(key="trace_field"):
    """Create a minimal field_config dict."""
    return {"key": key}


class TestWebAgentTraceDisplay:
    """Unit tests for web agent trace display rendering."""

    def test_display_type_is_web_agent_trace(self):
        """Display name attribute should be 'web_agent_trace'."""
        display = WebAgentTraceDisplay()
        assert display.name == "web_agent_trace"

    def test_render_basic_trace(self):
        """render() with valid trace data returns non-empty HTML string."""
        display = WebAgentTraceDisplay()
        data = _make_trace_data()
        result = display.render(_make_field_config(), data)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_contains_viewer_container(self):
        """HTML output should contain a container with class 'web-agent-viewer'."""
        display = WebAgentTraceDisplay()
        data = _make_trace_data()
        result = display.render(_make_field_config(), data)

        assert 'class="web-agent-viewer"' in result

    def test_render_contains_data_steps_attribute(self):
        """HTML output should contain a data-steps attribute with JSON-encoded steps."""
        display = WebAgentTraceDisplay()
        step = _make_step(action_type="click", coordinates={"x": 50, "y": 75})
        data = _make_trace_data(steps=[step])
        result = display.render(_make_field_config(), data)

        assert "data-steps=" in result

        # Extract the JSON from data-steps attribute and verify it is valid
        # The steps are HTML-escaped in the attribute value
        idx_start = result.index('data-steps="') + len('data-steps="')
        idx_end = result.index('"', idx_start)
        steps_escaped = result[idx_start:idx_end]
        steps_json = html.unescape(steps_escaped)
        parsed = json.loads(steps_json)

        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["action_type"] == "click"

    def test_render_empty_steps(self):
        """render() with empty steps list returns valid HTML without crashing."""
        display = WebAgentTraceDisplay()
        data = {"task_description": "Test", "steps": []}
        result = display.render(_make_field_config(), data)

        # With empty steps, _normalize_steps returns [], causing a placeholder
        assert isinstance(result, str)
        assert len(result) > 0
        assert "No trace steps found" in result

    def test_render_missing_steps_key(self):
        """render() with data missing 'steps' key handles gracefully."""
        display = WebAgentTraceDisplay()
        data = {"task_description": "Test"}
        result = display.render(_make_field_config(), data)

        assert isinstance(result, str)
        assert "No trace steps found" in result

    def test_normalize_steps_basic(self):
        """_normalize_steps() preserves valid step structure."""
        display = WebAgentTraceDisplay()
        step = _make_step(
            step_index=3,
            action_type="click",
            screenshot_url="img.png",
            coordinates={"x": 10, "y": 20},
            thought="thinking",
            observation="saw it",
        )
        data = {"steps": [step]}
        normalized = display._normalize_steps(data)

        assert len(normalized) == 1
        s = normalized[0]
        assert s["step_index"] == 3
        assert s["action_type"] == "click"
        assert s["screenshot_url"] == "img.png"
        assert s["coordinates"] == {"x": 10, "y": 20}
        assert s["thought"] == "thinking"
        assert s["observation"] == "saw it"

    def test_normalize_steps_fills_defaults(self):
        """Missing optional fields in steps get default values."""
        display = WebAgentTraceDisplay()
        # Minimal step with only action_type
        data = {"steps": [{"action_type": "click"}]}
        normalized = display._normalize_steps(data)

        assert len(normalized) == 1
        s = normalized[0]
        # step_index defaults to enumeration index
        assert s["step_index"] == 0
        assert s["screenshot_url"] == ""
        assert s["action_type"] == "click"
        assert s["element"] == {}
        assert s["coordinates"] == {}
        assert s["mouse_path"] == []
        assert s["thought"] == ""
        assert s["observation"] == ""
        assert s["timestamp"] == ""
        assert s["viewport"] == {"width": 1280, "height": 720}
        assert s["typed_text"] == ""

    def test_normalize_steps_zero_coordinates(self):
        """Step with coordinates {'x': 0, 'y': 0} preserves zeros (not treated as falsy)."""
        display = WebAgentTraceDisplay()
        step = {"action_type": "click", "coordinates": {"x": 0, "y": 0}}
        data = {"steps": [step]}
        normalized = display._normalize_steps(data)

        assert len(normalized) == 1
        assert normalized[0]["coordinates"] == {"x": 0, "y": 0}

    def test_render_filmstrip(self):
        """HTML output should contain filmstrip elements when show_filmstrip is True."""
        display = WebAgentTraceDisplay()
        steps = [
            _make_step(step_index=0, screenshot_url="s0.png"),
            _make_step(step_index=1, screenshot_url="s1.png"),
        ]
        data = _make_trace_data(steps=steps)
        result = display.render(_make_field_config(), data)

        assert 'class="filmstrip"' in result
        assert "filmstrip-thumb" in result
        assert "filmstrip-active" in result
        # The first thumbnail should be active, second should not
        assert 'data-step="0"' in result
        assert 'data-step="1"' in result

    def test_render_step_details(self):
        """HTML output should contain step detail sections with action type badge."""
        display = WebAgentTraceDisplay()
        step = _make_step(action_type="scroll", thought="scrolling down")
        data = _make_trace_data(steps=[step])
        result = display.render(_make_field_config(), data)

        assert "step-details-content" in result
        assert "action-badge" in result
        assert "SCROLL" in result

    def test_render_overlay_controls(self):
        """HTML output should contain overlay toggle controls."""
        display = WebAgentTraceDisplay()
        data = _make_trace_data()
        result = display.render(_make_field_config(), data)

        assert 'class="overlay-controls"' in result
        assert 'class="overlay-toggle"' in result
        assert 'data-overlay="click"' in result
        assert 'data-overlay="bbox"' in result
        assert 'data-overlay="path"' in result
        assert 'data-overlay="scroll"' in result

    def test_render_with_task_description(self):
        """Task description should appear in rendered HTML."""
        display = WebAgentTraceDisplay()
        data = _make_trace_data(task_description="Find a blue sweater under $50")
        result = display.render(_make_field_config(), data)

        assert "Find a blue sweater under $50" in result
        assert 'class="web-agent-task"' in result

    def test_render_multiple_action_types(self):
        """Steps with click, type, and scroll action types all render correctly."""
        display = WebAgentTraceDisplay()
        steps = [
            _make_step(step_index=0, action_type="click"),
            _make_step(step_index=1, action_type="type", typed_text="hello"),
            _make_step(step_index=2, action_type="scroll"),
        ]
        data = _make_trace_data(steps=steps)
        result = display.render(_make_field_config(), data)

        # The first step is rendered as static HTML; confirm its type appears
        assert "CLICK" in result
        # All three steps should be serialized in data-steps JSON
        idx_start = result.index('data-steps="') + len('data-steps="')
        idx_end = result.index('"', idx_start)
        steps_escaped = result[idx_start:idx_end]
        steps_json = html.unescape(steps_escaped)
        parsed = json.loads(steps_json)

        assert len(parsed) == 3
        assert parsed[0]["action_type"] == "click"
        assert parsed[1]["action_type"] == "type"
        assert parsed[2]["action_type"] == "scroll"

    def test_render_escapes_html_in_text(self):
        """HTML special chars in step text fields are escaped to prevent XSS."""
        display = WebAgentTraceDisplay()
        xss_payload = '<script>alert("xss")</script>'
        step = _make_step(
            thought=xss_payload,
            observation=xss_payload,
        )
        data = _make_trace_data(
            steps=[step],
            task_description=xss_payload,
        )
        result = display.render(_make_field_config(), data)

        # Raw script tag should NOT appear in output
        assert "<script>" not in result
        # Escaped version should be present
        assert html.escape(xss_payload) in result or "&lt;script&gt;" in result


class TestWebAgentTraceDisplayEdgeCases:
    """Additional edge case tests for WebAgentTraceDisplay."""

    def test_render_none_data(self):
        """render() with None data returns placeholder HTML."""
        display = WebAgentTraceDisplay()
        result = display.render(_make_field_config(), None)

        assert isinstance(result, str)
        assert "No trace data provided" in result

    def test_render_empty_dict(self):
        """render() with empty dict returns placeholder HTML.

        An empty dict is falsy in Python, so render() returns the
        'No trace data provided' placeholder before reaching step normalization.
        """
        display = WebAgentTraceDisplay()
        result = display.render(_make_field_config(), {})

        assert isinstance(result, str)
        assert "No trace data provided" in result

    def test_render_data_as_list_of_steps(self):
        """render() accepts a list of steps directly (no dict wrapper)."""
        display = WebAgentTraceDisplay()
        steps = [_make_step()]
        result = display.render(_make_field_config(), steps)

        assert 'class="web-agent-viewer"' in result

    def test_normalize_steps_skips_non_dict_items(self):
        """_normalize_steps() skips items in steps list that are not dicts."""
        display = WebAgentTraceDisplay()
        data = {"steps": [_make_step(), "not_a_dict", 42, None, _make_step(step_index=1)]}
        normalized = display._normalize_steps(data)

        assert len(normalized) == 2

    def test_render_site_info(self):
        """Site information should appear in rendered HTML when provided."""
        display = WebAgentTraceDisplay()
        data = _make_trace_data(site="amazon.com")
        result = display.render(_make_field_config(), data)

        assert "amazon.com" in result
        assert 'class="web-agent-site"' in result

    def test_render_step_with_element_info(self):
        """Element info (tag, text) should appear in step details."""
        display = WebAgentTraceDisplay()
        step = _make_step(element={"tag": "button", "text": "Submit"})
        data = _make_trace_data(steps=[step])
        result = display.render(_make_field_config(), data)

        assert "button" in result
        assert "Submit" in result
        assert "step-element" in result

    def test_render_step_with_timestamp(self):
        """Timestamp should appear in step details when present."""
        display = WebAgentTraceDisplay()
        step = _make_step(timestamp=3.5)
        data = _make_trace_data(steps=[step])
        result = display.render(_make_field_config(), data)

        assert "t=3.5s" in result
        assert "step-timestamp" in result

    def test_render_step_navigation_buttons(self):
        """Navigation buttons (prev/next) should be present."""
        display = WebAgentTraceDisplay()
        steps = [_make_step(step_index=0), _make_step(step_index=1)]
        data = _make_trace_data(steps=steps)
        result = display.render(_make_field_config(), data)

        assert "step-prev" in result
        assert "step-next" in result
        assert "Step 1 of 2" in result

    def test_render_single_step_next_disabled(self):
        """With only one step, the Next button should be disabled."""
        display = WebAgentTraceDisplay()
        data = _make_trace_data(steps=[_make_step()])
        result = display.render(_make_field_config(), data)

        # Both prev and next should be disabled when there's only 1 step
        # prev is always disabled on first render
        assert 'class="step-prev" disabled' in result

    def test_action_type_colors_mapping(self):
        """ACTION_TYPE_COLORS should have entries for standard action types."""
        expected_types = ["click", "type", "scroll", "hover", "select", "navigate", "wait", "done"]
        for action_type in expected_types:
            assert action_type in ACTION_TYPE_COLORS
            color = ACTION_TYPE_COLORS[action_type]
            assert "bg" in color
            assert "border" in color
            assert "badge" in color

    def test_default_action_color_has_required_keys(self):
        """DEFAULT_ACTION_COLOR should have bg, border, and badge keys."""
        assert "bg" in DEFAULT_ACTION_COLOR
        assert "border" in DEFAULT_ACTION_COLOR
        assert "badge" in DEFAULT_ACTION_COLOR

    def test_field_key_escaped_in_output(self):
        """Field key containing special chars should be HTML-escaped in output."""
        display = WebAgentTraceDisplay()
        data = _make_trace_data()
        config = _make_field_config(key='test"key<>&')
        result = display.render(config, data)

        # The raw unescaped key should NOT appear
        assert 'data-field-key="test"key' not in result
        # The escaped version should be there
        assert html.escape('test"key<>&', quote=True) in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
