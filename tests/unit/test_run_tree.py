"""
Unit tests for D6 sub-agent run-tree view.

Covers: run-tree preservation in the LangChain and OTel converters
(hierarchy nodes, run_id turn tagging, turn ranges), the agent_trace
display sidebar (nesting, descendant lists, step tagging, opt-out),
run_id passthrough in normalization, and the `runs` turn-binding filter.
"""

import pytest

from potato.server_utils.displays._trace_normalize import normalize_steps
from potato.server_utils.displays.agent_trace_display import AgentTraceDisplay
from potato.server_utils.turn_annotations import (
    build_turn_index,
    turn_matches_binding,
)
from potato.trace_converter.converters.langchain_converter import (
    LangChainConverter,
)
from potato.trace_converter.converters.otel_converter import OTELConverter


LANGCHAIN_TRACE = {
    "id": "run-root",
    "name": "AgentExecutor",
    "run_type": "chain",
    "inputs": {"input": "Book a flight"},
    "outputs": {"output": "Booked BA117"},
    "child_runs": [
        {"id": "run-llm-1", "name": "ChatOpenAI", "run_type": "llm",
         "inputs": {}, "outputs": {"generations": [{"text": "I should search flights"}]}},
        {"id": "run-sub", "name": "flight_researcher", "run_type": "chain",
         "status": "success",
         "child_runs": [
             {"id": "run-tool-1", "name": "search_flights", "run_type": "tool",
              "inputs": {"query": "JFK to LHR"},
              "outputs": {"output": "Found 5 flights"}},
         ]},
    ],
}


class TestLangChainRunTree:
    def _trace(self):
        return LangChainConverter().convert(LANGCHAIN_TRACE)[0]

    def test_run_tree_preserved(self):
        tree = self._trace().extra_fields["run_tree"]
        by_id = {n["id"]: n for n in tree}
        assert by_id["run-root"]["parent_id"] is None
        assert by_id["run-llm-1"]["parent_id"] == "run-root"
        assert by_id["run-sub"]["parent_id"] == "run-root"
        assert by_id["run-tool-1"]["parent_id"] == "run-sub"
        assert by_id["run-sub"]["status"] == "success"

    def test_turns_tagged_with_run_id(self):
        conv = self._trace().conversation
        # llm thought from run-llm-1, action+observation from run-tool-1
        assert conv[0]["run_id"] == "run-llm-1"
        assert conv[1]["run_id"] == "run-tool-1"
        assert conv[2]["run_id"] == "run-tool-1"

    def test_turn_ranges(self):
        tree = self._trace().extra_fields["run_tree"]
        by_id = {n["id"]: n for n in tree}
        assert by_id["run-root"]["turn_range"] == [0, 2]
        assert by_id["run-llm-1"]["turn_range"] == [0, 0]
        # The nested chain covers its tool's turns
        assert by_id["run-sub"]["turn_range"] == [1, 2]
        assert by_id["run-tool-1"]["turn_range"] == [1, 2]

    def test_flat_trace_has_no_run_tree(self):
        flat = {"id": "x", "name": "n", "run_type": "chain",
                "inputs": {"input": "hi"}, "outputs": {"output": "yo"},
                "child_runs": []}
        trace = LangChainConverter().convert(flat)[0]
        assert "run_tree" not in trace.extra_fields
        # to_dict must not leak an empty key either
        assert "run_tree" not in trace.to_dict()

    def test_generated_ids_when_missing(self):
        no_ids = {"id": "root", "run_type": "chain", "inputs": {},
                  "outputs": {},
                  "child_runs": [
                      {"name": "t", "run_type": "tool",
                       "inputs": {"q": 1}, "outputs": {"output": "r"}}]}
        trace = LangChainConverter().convert(no_ids)[0]
        tree = trace.extra_fields["run_tree"]
        child = [n for n in tree if n["parent_id"] == "root"][0]
        assert child["id"]  # synthesized
        assert trace.conversation[0]["run_id"] == child["id"]


OTEL_SPANS = [
    {"trace_id": "T1", "span_id": "s-root", "parent_span_id": None,
     "name": "AgentRun", "start_time": "2024-01-01T00:00:00Z",
     "attributes": {}},
    {"trace_id": "T1", "span_id": "s-llm", "parent_span_id": "s-root",
     "name": "llm-call", "start_time": "2024-01-01T00:00:01Z",
     "attributes": {"gen_ai.prompt": "plan the trip",
                    "gen_ai.completion": "I will search"}},
    {"trace_id": "T1", "span_id": "s-tool", "parent_span_id": "s-llm",
     "name": "search", "start_time": "2024-01-01T00:00:02Z",
     "attributes": {"tool.name": "search", "tool.input": "flights",
                    "tool.output": "5 results"}},
]


class TestOtelRunTree:
    def _trace(self):
        return OTELConverter().convert(OTEL_SPANS)[0]

    def test_run_tree_from_spans(self):
        tree = self._trace().extra_fields["run_tree"]
        by_id = {n["id"]: n for n in tree}
        assert by_id["s-root"]["parent_id"] is None
        assert by_id["s-llm"]["parent_id"] == "s-root"
        assert by_id["s-tool"]["parent_id"] == "s-llm"
        assert by_id["s-llm"]["run_type"] == "llm"
        assert by_id["s-tool"]["run_type"] == "tool"

    def test_turns_tagged(self):
        conv = self._trace().conversation
        tagged = {t["text"]: t.get("run_id") for t in conv}
        assert tagged["plan the trip"] == "s-llm"
        assert tagged["5 results"] == "s-tool"

    def test_orphan_parent_becomes_root(self):
        spans = [{"trace_id": "T2", "span_id": "a",
                  "parent_span_id": "not-in-export", "name": "x",
                  "attributes": {"gen_ai.prompt": "p"}},
                 {"trace_id": "T2", "span_id": "b", "parent_span_id": "a",
                  "name": "y", "attributes": {"gen_ai.completion": "c"}}]
        tree = OTELConverter().convert(spans)[0].extra_fields["run_tree"]
        by_id = {n["id"]: n for n in tree}
        assert by_id["a"]["parent_id"] is None
        assert by_id["b"]["parent_id"] == "a"

    def test_flat_spans_no_tree(self):
        spans = [{"trace_id": "T3", "span_id": "only", "parent_span_id": None,
                  "name": "x", "attributes": {"gen_ai.prompt": "p"}}]
        trace = OTELConverter().convert(spans)[0]
        assert "run_tree" not in trace.extra_fields


RUN_TREE = [
    {"id": "root", "parent_id": None, "name": "orchestrator",
     "run_type": "chain", "status": "success", "turn_range": [0, 2]},
    {"id": "sub", "parent_id": "root", "name": "researcher",
     "run_type": "chain", "status": None, "turn_range": [1, 2]},
    {"id": "tool", "parent_id": "sub", "name": "search",
     "run_type": "tool", "status": "error", "turn_range": [2, 2]},
]

STEPS = [
    {"speaker": "Agent (Thought)", "text": "plan", "run_id": "root"},
    {"speaker": "Agent (Thought)", "text": "research", "run_id": "sub"},
    {"speaker": "Agent (Action)", "text": "search(q)", "run_id": "tool"},
]


class TestRunTreeDisplay:
    def _render(self, **field_extra):
        field = {"key": "conversation", "type": "agent_trace"}
        field.update(field_extra)
        return AgentTraceDisplay().render(field, STEPS)

    def test_sidebar_renders_with_tree(self):
        html = self._render(_run_tree=RUN_TREE)
        assert 'class="run-tree"' in html
        assert "has-run-tree" in html
        assert 'data-run-id="sub"' in html
        # Descendant list lets JS filter whole subtrees
        assert 'data-run-desc="sub,tool"' in html
        assert "rt-status-error" in html
        assert "steps 1–2" in html

    def test_steps_carry_run_id(self):
        html = self._render(_run_tree=RUN_TREE)
        assert 'data-step-index="2" data-step-type="action" data-run-id="tool"' in html

    def test_no_tree_without_injection(self):
        html = self._render()
        assert 'class="run-tree"' not in html
        assert "has-run-tree" not in html

    def test_opt_out(self):
        html = self._render(_run_tree=RUN_TREE,
                            display_options={"show_run_tree": False})
        assert 'class="run-tree"' not in html


class TestRunIdBindingAndPassthrough:
    def test_normalize_passes_run_id_through(self):
        steps = normalize_steps(STEPS)
        assert [s.get("run_id") for s in steps] == ["root", "sub", "tool"]

    def test_turn_index_carries_run_id(self):
        index = build_turn_index(normalize_steps(STEPS))
        assert index[1]["run_id"] == "sub"

    def test_runs_binding_filters(self):
        turn = {"speaker": "Agent (Thought)", "text": "x", "run_id": "sub"}
        assert turn_matches_binding(turn, 0, {"runs": ["sub", "tool"]})
        assert not turn_matches_binding(turn, 0, {"runs": ["tool"]})
        assert not turn_matches_binding({"speaker": "A", "text": "x"}, 0,
                                        {"runs": ["sub"]})

    def test_runs_binding_validated_as_list(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_single_annotation_scheme)
        scheme = {"annotation_type": "radio", "name": "s", "description": "d",
                  "labels": ["x"], "turn_level": True,
                  "turn_binding": {"runs": "not-a-list"}}
        with pytest.raises(ConfigValidationError, match="runs must be a list"):
            validate_single_annotation_scheme(scheme, "t")
