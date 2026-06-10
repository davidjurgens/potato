"""
Tests for the eval_trace display type (three-pane reasoning | function calls |
final answer) and the shared trace normalizer it relies on.
"""

import re

import pytest

from potato.server_utils.displays.eval_trace_display import (
    EvalTraceDisplay,
    _tool_name,
)
from potato.server_utils.displays.registry import display_registry
from potato.server_utils.displays._trace_normalize import normalize_steps


def _strip_style(html: str) -> str:
    """Remove the <style> block so section assertions don't match CSS rules
    (the CSS contains class names like .eval-pane-calls and .eval-step-num)."""
    return re.sub(r"<style>.*?</style>", "", html, flags=re.DOTALL)


# A representative interleaved trace in the common speaker/text format.
TRACE = [
    {"speaker": "Agent (Thought)", "text": "I need to find a recipe"},
    {"speaker": "Agent (Action)", "text": "web_search(query='lasagna')"},
    {"speaker": "Environment", "text": "10 results found\nresult1\nresult2"},
    {"speaker": "Agent (Thought)", "text": "The first looks best, read it"},
    {"speaker": "Agent (Action)", "text": "fetch(url='site.com')"},
    {"speaker": "Environment", "text": "Recipe text"},
    {"speaker": "Agent (Final Answer)", "text": "Here is the recipe: ..."},
]


class TestRegistration:
    def setup_method(self):
        self.display = EvalTraceDisplay()

    def test_registered(self):
        assert display_registry.is_registered("eval_trace")

    def test_in_supported_types(self):
        assert "eval_trace" in display_registry.get_supported_types()

    def test_does_not_support_span_target(self):
        assert self.display.supports_span_target is False
        assert display_registry.type_supports_span_target("eval_trace") is False

    def test_render_via_registry(self):
        html = display_registry.render("eval_trace", {"key": "trace"}, TRACE)
        assert "eval-trace-display" in html


class TestEmptyAndMalformed:
    def setup_method(self):
        self.display = EvalTraceDisplay()

    def test_render_none(self):
        html = self.display.render({"key": "t"}, None)
        assert "No trace data" in html

    def test_render_empty_list(self):
        html = self.display.render({"key": "t"}, [])
        assert "No trace" in html

    def test_render_single_string(self):
        # A bare string normalizes to one observation -> appears in calls pane,
        # and (being the last/only step) is not an action, so no answer.
        html = self.display.render({"key": "t"}, "just some text")
        assert "eval-trace-display" in html
        assert "just some text" in html

    def test_render_malformed_steps_do_not_crash(self):
        data = [{"unknown_key": "x"}, 42, None, {"speaker": "Agent (Thought)", "text": "ok"}]
        html = self.display.render({"key": "t"}, data)
        assert "eval-trace-display" in html
        assert "ok" in html


class TestPaneBucketing:
    def setup_method(self):
        self.display = EvalTraceDisplay()
        self.html = self.display.render({"key": "trace"}, TRACE)

    def test_three_panes_present(self):
        assert "eval-pane-reasoning" in self.html
        assert "eval-pane-calls" in self.html
        assert "eval-pane-answer" in self.html

    def test_default_pane_labels(self):
        assert "Reasoning" in self.html
        assert "Function Calls" in self.html
        assert "Final Answer" in self.html

    def test_thoughts_in_reasoning(self):
        assert "I need to find a recipe" in self.html
        assert "The first looks best" in self.html

    def test_calls_in_calls_pane(self):
        assert "web_search" in self.html
        assert "fetch" in self.html
        assert "eval-tool-badge" in self.html

    def test_observation_nested_as_result(self):
        assert "10 results found" in self.html
        assert "eval-result" in self.html

    def test_final_answer_in_answer_pane(self):
        # The answer step text must appear inside the answer card.
        body = _strip_style(self.html)
        answer_section = body.split("eval-pane-answer", 1)[1]
        assert "Here is the recipe" in answer_section

    def test_answer_excluded_from_calls(self):
        # The final answer should not also render as a function call.
        body = _strip_style(self.html)
        calls_section = body.split("eval-pane-calls", 1)[1].split("eval-pane-answer", 1)[0]
        assert "Here is the recipe" not in calls_section


class TestAnswerDetection:
    def setup_method(self):
        self.display = EvalTraceDisplay()

    def test_explicit_final_answer_speaker(self):
        idx = self.display._find_answer_step(normalize_steps(TRACE))
        steps = normalize_steps(TRACE)
        assert steps[idx]["text"].startswith("Here is the recipe")

    def test_send_message_tool_is_answer(self):
        trace = [
            {"speaker": "Agent (Thought)", "text": "plan"},
            {"speaker": "Agent (Action)", "text": "search(q='x')"},
            {"speaker": "Agent (Action)", "text": "send_message(text='done')"},
        ]
        steps = normalize_steps(trace)
        idx = self.display._find_answer_step(steps)
        assert "send_message" in steps[idx]["text"]

    def test_fallback_to_last_action(self):
        trace = [
            {"speaker": "Agent (Thought)", "text": "plan"},
            {"speaker": "Agent (Action)", "text": "compute(x=1)"},
            {"speaker": "Agent (Action)", "text": "compute(x=2)"},
        ]
        steps = normalize_steps(trace)
        idx = self.display._find_answer_step(steps)
        assert steps[idx]["text"] == "compute(x=2)"

    def test_no_actions_no_answer(self):
        trace = [{"speaker": "Agent (Thought)", "text": "only thinking"}]
        steps = normalize_steps(trace)
        assert self.display._find_answer_step(steps) is None
        html = self.display.render({"key": "t"}, trace)
        assert "No final answer" in html


class TestStepLinking:
    def setup_method(self):
        self.display = EvalTraceDisplay()

    def test_step_index_emitted_and_consistent(self):
        body = _strip_style(self.display.render({"key": "trace"}, TRACE))
        # Group 0 = first thought + web_search; group 1 = second thought + fetch.
        assert 'data-step-index="0"' in body
        assert 'data-step-index="1"' in body
        # index 0 should appear in both reasoning and calls panes (linkable)
        reasoning = body.split("eval-pane-reasoning", 1)[1].split("eval-pane-calls", 1)[0]
        calls = body.split("eval-pane-calls", 1)[1].split("eval-pane-answer", 1)[0]
        assert 'data-step-index="0"' in reasoning
        assert 'data-step-index="0"' in calls

    def test_link_steps_false_omits_indices_and_js(self):
        html = self.display.render(
            {"key": "trace", "display_options": {"link_steps": False}}, TRACE
        )
        assert "data-step-index" not in html
        assert "evalBound" not in html  # JS not emitted

    def test_link_js_present_by_default(self):
        html = self.display.render({"key": "trace"}, TRACE)
        assert "evalBound" in html

    def test_linkable_cards_are_accessible_buttons(self):
        body = _strip_style(self.display.render({"key": "trace"}, TRACE))
        assert 'role="button"' in body
        assert 'aria-pressed="false"' in body
        assert "aria-label=" in body

    def test_no_button_role_when_link_disabled(self):
        # Strip the <style> block — the CSS contains `.eval-card[role="button"]`.
        body = _strip_style(
            self.display.render(
                {"key": "trace", "display_options": {"link_steps": False}}, TRACE
            )
        )
        assert 'role="button"' not in body
        assert "tabindex" not in body


class TestOptions:
    def setup_method(self):
        self.display = EvalTraceDisplay()

    def test_custom_pane_labels(self):
        html = self.display.render(
            {"key": "t", "display_options": {"pane_labels": ["Think", "Do", "Say"]}},
            TRACE,
        )
        assert "Think" in html and "Do" in html and "Say" in html

    def test_pane_labels_padded_when_too_few(self):
        labels = self.display._resolve_pane_labels(["Only One"])
        assert len(labels) == 3
        assert labels[0] == "Only One"
        assert labels[1] == "Function Calls"

    def test_pane_labels_non_list_falls_back(self):
        labels = self.display._resolve_pane_labels("not a list")
        assert labels == ["Reasoning", "Function Calls", "Final Answer"]

    def test_show_step_numbers_toggle(self):
        on = self.display.render({"key": "t", "display_options": {"show_step_numbers": True}}, TRACE)
        off = self.display.render({"key": "t", "display_options": {"show_step_numbers": False}}, TRACE)
        # Check the rendered span, not the always-present CSS rule.
        assert '<span class="eval-step-num">' in on
        assert '<span class="eval-step-num">' not in off

    def test_collapse_long_output(self):
        long_obs = "\n".join(f"line {i}" for i in range(50))
        trace = [
            {"speaker": "Agent (Action)", "text": "run()"},
            {"speaker": "Environment", "text": long_obs},
        ]
        html = self.display.render(
            {"key": "t", "display_options": {"collapse_long_outputs": True, "max_output_lines": 10}},
            trace,
        )
        assert "<details" in html  # collapsed into an expandable block
        assert "expand" in html


class TestEscaping:
    def setup_method(self):
        self.display = EvalTraceDisplay()

    def test_step_text_escaped(self):
        trace = [{"speaker": "Agent (Thought)", "text": "<script>alert('x')</script>"}]
        html = self.display.render({"key": "t"}, trace)
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_speaker_escaped(self):
        trace = [{"speaker": "<img src=x onerror=alert(1)>", "text": "hi"}]
        html = self.display.render({"key": "t"}, trace)
        assert "<img src=x" not in html

    def test_tool_name_and_args_escaped(self):
        trace = [{"speaker": "Agent (Action)", "text": "<b>evil</b>(x='<i>y</i>')"}]
        html = self.display.render({"key": "t"}, trace)
        assert "<b>evil</b>" not in html
        assert "&lt;b&gt;evil&lt;/b&gt;" in html

    def test_pane_label_escaped(self):
        html = self.display.render(
            {"key": "t", "display_options": {"pane_labels": ["<x>", "B", "C"]}}, TRACE
        )
        assert "<x>" not in html
        assert "&lt;x&gt;" in html


class TestValidation:
    def setup_method(self):
        self.display = EvalTraceDisplay()

    def test_valid_config_passes(self):
        errors = self.display.validate_config({"key": "trace", "type": "eval_trace"})
        assert errors == []

    def test_bad_pane_labels_reports_error(self):
        errors = self.display.validate_config(
            {"key": "trace", "display_options": {"pane_labels": "oops"}}
        )
        assert any("pane_labels" in e for e in errors)

    def test_span_target_warns(self):
        # eval_trace does not support span targets; setting one should error.
        errors = self.display.validate_config({"key": "trace", "span_target": True})
        assert any("span_target" in e for e in errors)


class TestHelpers:
    def test_tool_name_extraction(self):
        assert _tool_name("web_search(query='x')") == "web_search"
        assert _tool_name("finish") == "finish"
        assert _tool_name("  spaced (a=1)") == "spaced"


class TestThoughtActionObservationFormat:
    """Format 2: one dict expands to thought/action/observation steps."""

    def setup_method(self):
        self.display = EvalTraceDisplay()

    def test_expanded_format_buckets_correctly(self):
        trace = [
            {
                "thought": "I will search",
                "action": {"tool": "search", "params": {"q": "cats"}},
                "observation": "found 3",
            }
        ]
        html = self.display.render({"key": "t"}, trace)
        assert "I will search" in html           # reasoning
        assert "search" in html                   # calls
        assert "found 3" in html                   # result
        # the single action is also the last action -> becomes the answer
        assert "eval-pane-answer" in html


class TestStepTypeContentFormat:
    """Format 3: explicit step_type/content."""

    def setup_method(self):
        self.display = EvalTraceDisplay()

    def test_step_type_buckets(self):
        trace = [
            {"step_type": "thought", "content": "thinking hard"},
            {"step_type": "action", "content": "do_thing(x=1)"},
        ]
        html = self.display.render({"key": "t"}, trace)
        assert "thinking hard" in html
        assert "do_thing" in html
