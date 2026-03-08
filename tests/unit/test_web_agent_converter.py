"""
Unit tests for WebAgentConverter format detection and conversion.

Tests the web agent converter's ability to detect and convert various
web agent trace formats (raw recording, Anthropic Computer Use, Mind2Web)
to Potato's canonical trace format.
"""

import pytest

from potato.trace_converter.converters.web_agent_converter import WebAgentConverter
from potato.trace_converter.base import CanonicalTrace


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------

def _make_raw_recording(
    trace_id="t1",
    task_description="Test task",
    site="example.com",
    steps=None,
):
    """Create a raw recording format trace."""
    if steps is None:
        steps = [
            {
                "step_index": 0,
                "action_type": "click",
                "screenshot_url": "s.png",
                "coordinates": {"x": 100, "y": 200},
                "mouse_path": [[0, 0], [100, 200]],
                "viewport": {"width": 1280, "height": 720},
                "thought": "clicking button",
                "observation": "button clicked",
            }
        ]
    return {
        "id": trace_id,
        "task_description": task_description,
        "site": site,
        "steps": steps,
    }


def _make_anthropic_cu(
    trace_id="t2",
    action="click",
    coordinate=None,
    text_input="",
    model="claude-3-opus-20240229",
):
    """Create an Anthropic Computer Use format trace."""
    if coordinate is None:
        coordinate = [100, 200]
    tool_input = {"action": action, "coordinate": coordinate}
    if text_input:
        tool_input["text"] = text_input
    return {
        "id": trace_id,
        "model": model,
        "messages": [
            {"role": "user", "content": "Find a blue sweater"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "computer",
                        "input": tool_input,
                        "id": "tool1",
                    }
                ],
            },
        ],
    }


def _make_mind2web(
    trace_id="t3",
    task="Find product",
    website="amazon.com",
    actions=None,
):
    """Create a Mind2Web format trace."""
    if actions is None:
        actions = [
            {
                "operation": "click",
                "target_html": "<button>Search</button>",
                "annotation_id": "a1",
            }
        ]
    return {
        "id": trace_id,
        "confirmed_task": task,
        "website": website,
        "actions": actions,
    }


def _make_openai_chat():
    """Create an OpenAI chat format (should NOT be detected as web agent)."""
    return {
        "id": "chatcmpl-abc",
        "object": "chat.completion",
        "model": "gpt-4",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello! How can I help?",
                }
            }
        ],
    }


def _make_webarena_plain():
    """Create a standard WebArena format WITHOUT coordinate data.

    This format should NOT be detected by the web_agent converter's
    detect(), so that a dedicated webarena converter can handle it.
    """
    return {
        "task_id": "wa_42",
        "intent": "Find the cheapest flight",
        "url": "https://example.com",
        "actions": [
            {
                "action_type": "click",
                "element_id": "btn-search",
                "thought": "clicking search",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebAgentConverter:
    """Unit tests for web agent trace converter."""

    # -------------------------------------------------------------------
    # Detection tests
    # -------------------------------------------------------------------

    def test_detect_raw_recording(self):
        """Data with mouse_path + viewport in steps should be detected."""
        converter = WebAgentConverter()
        data = _make_raw_recording()
        assert converter.detect(data) is True

    def test_detect_anthropic_computer_use(self):
        """Data with tool_use blocks containing 'computer' should be detected."""
        converter = WebAgentConverter()
        data = _make_anthropic_cu()
        assert converter.detect(data) is True

    def test_detect_mind2web(self):
        """Data with operation + target_html in actions should be detected."""
        converter = WebAgentConverter()
        data = _make_mind2web()
        assert converter.detect(data) is True

    def test_detect_false_for_openai_chat(self):
        """OpenAI chat format should NOT be detected as web agent."""
        converter = WebAgentConverter()
        data = _make_openai_chat()
        assert converter.detect(data) is False

    def test_detect_false_for_plain_text(self):
        """Plain text / non-dict data should NOT be detected."""
        converter = WebAgentConverter()
        assert converter.detect("just a string") is False
        assert converter.detect(42) is False
        assert converter.detect(None) is False

    def test_detect_does_not_steal_webarena(self):
        """Standard WebArena format (action_type + element_id, no mouse_path/coords)
        should NOT be detected by web_agent converter, leaving it for the
        dedicated webarena converter."""
        converter = WebAgentConverter()
        data = _make_webarena_plain()
        assert converter.detect(data) is False

    def test_detect_priority_over_generic(self):
        """Web agent with mouse_path IS detected even though it also has action_type."""
        converter = WebAgentConverter()
        data = _make_raw_recording()
        # The raw recording has both action_type and mouse_path
        assert "action_type" in data["steps"][0]
        assert "mouse_path" in data["steps"][0]
        assert converter.detect(data) is True

    # -------------------------------------------------------------------
    # Conversion tests
    # -------------------------------------------------------------------

    def test_convert_raw_recording_basic(self):
        """Convert raw recording format, verify CanonicalTrace output."""
        converter = WebAgentConverter()
        data = _make_raw_recording(
            trace_id="rec1",
            task_description="Click the search button",
        )
        results = converter.convert(data)

        assert len(results) == 1
        trace = results[0]
        assert isinstance(trace, CanonicalTrace)
        assert trace.id == "rec1"
        assert trace.task_description == "Click the search button"
        assert len(trace.conversation) > 0

        # Steps should be in extra_fields
        steps = trace.extra_fields.get("steps", [])
        assert len(steps) == 1
        assert steps[0]["action_type"] == "click"

    def test_convert_raw_preserves_coordinates(self):
        """Coordinates should be preserved in converted step metadata."""
        converter = WebAgentConverter()
        data = _make_raw_recording(
            steps=[
                {
                    "step_index": 0,
                    "action_type": "click",
                    "screenshot_url": "s.png",
                    "coordinates": {"x": 350, "y": 450},
                    "mouse_path": [[0, 0], [350, 450]],
                    "viewport": {"width": 1920, "height": 1080},
                }
            ]
        )
        results = converter.convert(data)

        steps = results[0].extra_fields["steps"]
        assert steps[0]["coordinates"] == {"x": 350, "y": 450}

    def test_convert_raw_preserves_mouse_path(self):
        """Mouse path data should be preserved in converted steps."""
        converter = WebAgentConverter()
        path = [[0, 0], [50, 100], [200, 300]]
        data = _make_raw_recording(
            steps=[
                {
                    "step_index": 0,
                    "action_type": "click",
                    "screenshot_url": "s.png",
                    "coordinates": {"x": 200, "y": 300},
                    "mouse_path": path,
                    "viewport": {"width": 1280, "height": 720},
                }
            ]
        )
        results = converter.convert(data)

        steps = results[0].extra_fields["steps"]
        assert steps[0]["mouse_path"] == path

    def test_convert_anthropic_cu(self):
        """Convert Anthropic Computer Use format produces valid CanonicalTrace."""
        converter = WebAgentConverter()
        data = _make_anthropic_cu(
            trace_id="cu_1",
            action="click",
            coordinate=[500, 300],
        )
        results = converter.convert(data)

        assert len(results) == 1
        trace = results[0]
        assert trace.id == "cu_1"
        # Task description should come from the first user message
        assert trace.task_description == "Find a blue sweater"

        steps = trace.extra_fields.get("steps", [])
        assert len(steps) == 1
        assert steps[0]["action_type"] == "click"
        assert steps[0]["coordinates"] == {"x": 500, "y": 300}

    def test_convert_mind2web(self):
        """Convert Mind2Web format produces valid CanonicalTrace."""
        converter = WebAgentConverter()
        data = _make_mind2web(
            trace_id="mw_1",
            task="Search for laptops",
            website="bestbuy.com",
            actions=[
                {
                    "operation": "click",
                    "target_html": "<button>Search</button>",
                    "annotation_id": "a1",
                },
                {
                    "operation": {"op": "type", "value": "laptop"},
                    "target_html": '<input id="search-box" />',
                    "annotation_id": "a2",
                },
            ],
        )
        results = converter.convert(data)

        assert len(results) == 1
        trace = results[0]
        assert trace.id == "mw_1"
        assert trace.task_description == "Search for laptops"

        steps = trace.extra_fields.get("steps", [])
        assert len(steps) == 2
        assert steps[0]["action_type"] == "click"
        assert steps[1]["action_type"] == "type"
        assert steps[1]["typed_text"] == "laptop"

    def test_convert_step_types_mapped(self):
        """Action types should be mapped correctly in normalized steps."""
        converter = WebAgentConverter()
        data = _make_raw_recording(
            steps=[
                {
                    "step_index": 0,
                    "action_type": "click",
                    "screenshot_url": "s0.png",
                    "coordinates": {"x": 10, "y": 20},
                    "mouse_path": [[0, 0]],
                    "viewport": {"width": 1280, "height": 720},
                },
                {
                    "step_index": 1,
                    "action_type": "type",
                    "screenshot_url": "s1.png",
                    "coordinates": {"x": 10, "y": 20},
                    "mouse_path": [],
                    "viewport": {"width": 1280, "height": 720},
                    "typed_text": "hello world",
                },
                {
                    "step_index": 2,
                    "action_type": "scroll",
                    "screenshot_url": "s2.png",
                    "coordinates": {},
                    "mouse_path": [],
                    "viewport": {"width": 1280, "height": 720},
                    "scroll_direction": "down",
                },
            ]
        )
        results = converter.convert(data)

        steps = results[0].extra_fields["steps"]
        assert steps[0]["action_type"] == "click"
        assert steps[1]["action_type"] == "type"
        assert steps[1]["typed_text"] == "hello world"
        assert steps[2]["action_type"] == "scroll"
        assert steps[2]["scroll_direction"] == "down"

    # -------------------------------------------------------------------
    # Edge cases
    # -------------------------------------------------------------------

    def test_convert_empty_steps(self):
        """Empty steps list should convert to a trace with 0 steps."""
        converter = WebAgentConverter()
        data = {
            "id": "empty",
            "task_description": "Nothing to do",
            "steps": [],
        }
        # This uses the generic fallback since no sub-format markers exist
        results = converter.convert(data)

        assert len(results) == 1
        steps = results[0].extra_fields.get("steps", [])
        assert len(steps) == 0

    def test_convert_missing_optional_fields(self):
        """Steps missing optional fields (thought, observation) should not crash."""
        converter = WebAgentConverter()
        data = _make_raw_recording(
            steps=[
                {
                    "step_index": 0,
                    "action_type": "click",
                    "screenshot_url": "s.png",
                    "coordinates": {"x": 1, "y": 2},
                    "mouse_path": [[0, 0]],
                    "viewport": {"width": 800, "height": 600},
                    # no thought, no observation, no timestamp, no element
                }
            ]
        )
        results = converter.convert(data)

        assert len(results) == 1
        steps = results[0].extra_fields["steps"]
        assert len(steps) == 1
        step = steps[0]
        assert step["thought"] == ""
        assert step["observation"] == ""
        assert step["timestamp"] == ""

    def test_convert_zero_coordinates(self):
        """Coordinates at (0, 0) should be preserved correctly, not treated as falsy."""
        converter = WebAgentConverter()
        data = _make_raw_recording(
            steps=[
                {
                    "step_index": 0,
                    "action_type": "click",
                    "screenshot_url": "s.png",
                    "coordinates": {"x": 0, "y": 0},
                    "mouse_path": [[0, 0]],
                    "viewport": {"width": 1280, "height": 720},
                }
            ]
        )
        results = converter.convert(data)

        steps = results[0].extra_fields["steps"]
        assert steps[0]["coordinates"]["x"] == 0
        assert steps[0]["coordinates"]["y"] == 0

    def test_convert_preserves_task_description(self):
        """Task description should flow through to the canonical trace."""
        converter = WebAgentConverter()
        desc = "Add a blue wool sweater under $50 to the shopping cart"
        data = _make_raw_recording(task_description=desc)
        results = converter.convert(data)

        assert results[0].task_description == desc

    def test_format_name(self):
        """Converter format_name should be 'web_agent'."""
        converter = WebAgentConverter()
        assert converter.format_name == "web_agent"


class TestWebAgentConverterHelpers:
    """Tests for internal helper methods of WebAgentConverter."""

    def test_normalize_step_handles_non_dict_element(self):
        """_normalize_step wraps non-dict element values in a dict."""
        converter = WebAgentConverter()
        raw = {
            "step_index": 0,
            "action_type": "click",
            "element": "button text",
        }
        step = converter._normalize_step(raw, 0)
        assert isinstance(step["element"], dict)
        assert step["element"]["text"] == "button text"

    def test_normalize_step_handles_non_dict_coordinates(self):
        """_normalize_step replaces non-dict coordinates with empty dict."""
        converter = WebAgentConverter()
        raw = {
            "step_index": 0,
            "action_type": "click",
            "coordinates": "invalid",
        }
        step = converter._normalize_step(raw, 0)
        assert step["coordinates"] == {}

    def test_normalize_step_handles_non_dict_viewport(self):
        """_normalize_step replaces non-dict viewport with default."""
        converter = WebAgentConverter()
        raw = {
            "step_index": 0,
            "action_type": "click",
            "viewport": "invalid",
        }
        step = converter._normalize_step(raw, 0)
        assert step["viewport"] == {"width": 1280, "height": 720}

    def test_normalize_step_handles_non_list_mouse_path(self):
        """_normalize_step replaces non-list mouse_path with empty list."""
        converter = WebAgentConverter()
        raw = {
            "step_index": 0,
            "action_type": "click",
            "mouse_path": "invalid",
        }
        step = converter._normalize_step(raw, 0)
        assert step["mouse_path"] == []

    def test_format_action_text_with_element(self):
        """_format_action_text includes element info when available."""
        converter = WebAgentConverter()
        action = {
            "action_type": "click",
            "element": {"text": "Submit"},
            "coordinates": {"x": 100, "y": 200},
        }
        text = converter._format_action_text(action)
        assert "click" in text
        assert "Submit" in text
        assert "100" in text

    def test_format_action_text_no_extras(self):
        """_format_action_text with no element/coords returns simple format."""
        converter = WebAgentConverter()
        action = {"action_type": "wait"}
        text = converter._format_action_text(action)
        assert text == "wait()"

    def test_extract_text_from_html(self):
        """_extract_text_from_html strips tags and returns visible text."""
        converter = WebAgentConverter()
        result = converter._extract_text_from_html("<button>Search</button>")
        assert result == "Search"

    def test_extract_tag_from_html(self):
        """_extract_tag_from_html returns the first tag name."""
        converter = WebAgentConverter()
        assert converter._extract_tag_from_html("<button>Search</button>") == "button"
        assert converter._extract_tag_from_html('<input id="q" />') == "input"
        assert converter._extract_tag_from_html("no tags here") == ""

    def test_convert_list_of_traces(self):
        """convert() handles a list of multiple traces."""
        converter = WebAgentConverter()
        data = [
            _make_raw_recording(trace_id="t1"),
            _make_raw_recording(trace_id="t2"),
        ]
        results = converter.convert(data)

        assert len(results) == 2
        assert results[0].id == "t1"
        assert results[1].id == "t2"

    def test_convert_skips_non_dict_items_in_list(self):
        """convert() skips non-dict items in input list."""
        converter = WebAgentConverter()
        data = [_make_raw_recording(trace_id="good"), "not_a_dict", 42]
        results = converter.convert(data)

        assert len(results) == 1
        assert results[0].id == "good"

    def test_to_dict_includes_extra_fields(self):
        """CanonicalTrace.to_dict() includes extra_fields like 'steps' and 'site'."""
        converter = WebAgentConverter()
        data = _make_raw_recording(trace_id="td1", site="test.com")
        results = converter.convert(data)

        trace_dict = results[0].to_dict()
        assert "steps" in trace_dict
        assert "site" in trace_dict
        assert trace_dict["site"] == "test.com"

    def test_detect_empty_list(self):
        """detect() with empty list returns False."""
        converter = WebAgentConverter()
        assert converter.detect([]) is False

    def test_detect_list_input(self):
        """detect() works when given a list of traces."""
        converter = WebAgentConverter()
        data = [_make_raw_recording()]
        assert converter.detect(data) is True

    def test_get_format_info(self):
        """get_format_info() returns correct metadata."""
        converter = WebAgentConverter()
        info = converter.get_format_info()
        assert info["format_name"] == "web_agent"
        assert ".json" in info["file_extensions"]
        assert ".jsonl" in info["file_extensions"]


class TestWebAgentConverterAnthropicCUEdgeCases:
    """Edge case tests specific to Anthropic Computer Use conversion."""

    def test_anthropic_cu_type_action(self):
        """Anthropic CU with type action preserves typed text."""
        converter = WebAgentConverter()
        data = _make_anthropic_cu(
            action="type",
            coordinate=[300, 400],
            text_input="hello world",
        )
        results = converter.convert(data)

        steps = results[0].extra_fields["steps"]
        assert len(steps) == 1
        assert steps[0]["action_type"] == "type"
        assert steps[0]["typed_text"] == "hello world"
        assert steps[0]["coordinates"] == {"x": 300, "y": 400}

    def test_anthropic_cu_model_in_metadata(self):
        """Anthropic CU converter captures model name in metadata and agent_name."""
        converter = WebAgentConverter()
        data = _make_anthropic_cu(model="claude-3-opus-20240229")
        results = converter.convert(data)

        assert results[0].agent_name == "claude-3-opus-20240229"
        metadata_values = [m["Value"] for m in results[0].metadata_table]
        assert "claude-3-opus-20240229" in metadata_values

    def test_anthropic_cu_detect_with_computer_type(self):
        """Detect Anthropic CU when block type contains 'computer'."""
        converter = WebAgentConverter()
        data = {
            "id": "t_type",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "computer_20241022",
                            "action": "click",
                            "coordinate": [100, 200],
                        }
                    ],
                }
            ],
        }
        assert converter.detect(data) is True


class TestWebAgentConverterMind2WebEdgeCases:
    """Edge case tests specific to Mind2Web conversion."""

    def test_mind2web_operation_as_dict(self):
        """Mind2Web operation field can be a dict with op and value."""
        converter = WebAgentConverter()
        data = _make_mind2web(
            actions=[
                {
                    "operation": {"op": "type", "value": "laptop"},
                    "target_html": '<input id="search" />',
                    "annotation_id": "a1",
                }
            ]
        )
        results = converter.convert(data)

        steps = results[0].extra_fields["steps"]
        assert steps[0]["action_type"] == "type"
        assert steps[0]["typed_text"] == "laptop"

    def test_mind2web_with_pos_candidates(self):
        """Mind2Web with pos_candidates extracts bbox info."""
        converter = WebAgentConverter()
        data = _make_mind2web(
            actions=[
                {
                    "operation": "click",
                    "target_html": "<button>Go</button>",
                    "pos_candidates": [
                        {"bbox": [10, 20, 100, 50], "rank": 0}
                    ],
                    "annotation_id": "a1",
                }
            ]
        )
        results = converter.convert(data)

        steps = results[0].extra_fields["steps"]
        assert steps[0]["element"].get("bbox") == [10, 20, 100, 50]

    def test_mind2web_site_in_metadata(self):
        """Mind2Web converter captures website in metadata and extra_fields."""
        converter = WebAgentConverter()
        data = _make_mind2web(website="amazon.com")
        results = converter.convert(data)

        assert results[0].extra_fields.get("site") == "amazon.com"
        metadata_values = [m["Value"] for m in results[0].metadata_table]
        assert "amazon.com" in metadata_values


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
