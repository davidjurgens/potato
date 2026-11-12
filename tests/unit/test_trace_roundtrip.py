"""
Round-trip regression tests for agent-trace import/export.

Mirrors the span/link/event serialization guards: verifies that an agent trace
survives the full import -> store(JSON) -> reload -> normalize/export pipeline
without losing state. The recurring bug class is a serializer that writes fewer
fields than the consumer reads (see test_span_serialization_roundtrip.py).

Coverage:
  A. CanonicalTrace.to_dict() fidelity + drift guard (the documented HIGH-risk
     asymmetry: to_dict() exists, no from_dict()).
  B. Per-importer round-trip: raw format -> converter -> CanonicalTrace ->
     to_dict() -> JSON dump/load -> reload, asserting the stored dict yields the
     same annotation-facing state (conversation + normalized steps) as the live
     object, and that format auto-detection is stable.
  C. normalize_trajectory() equivalence across shapes + tool-call arg fidelity.
  D. potato_trace capture SDK: Run -> build_payload -> JSON -> ingestion
     normalizer round-trip, plus safe_serialize robustness.
  E. Real example canonical trace data file survives a JSON round-trip.
"""

import json
import os

import pytest

from potato.trace_converter.base import CanonicalTrace
from potato.trace_converter.registry import converter_registry
from potato.evaluators.trajectory import (
    normalize_trajectory,
    extract_tool_calls,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _canonical_from_dict(d: dict) -> CanonicalTrace:
    """Reconstruct a CanonicalTrace from its to_dict() output.

    There is no CanonicalTrace.from_dict(); this mirrors how a stored trace is
    re-hydrated (core fields + everything else into extra_fields).
    """
    core = CanonicalTrace._CORE_FIELDS
    return CanonicalTrace(
        id=d.get("id", ""),
        task_description=d.get("task_description", ""),
        conversation=d.get("conversation", []),
        agent_name=d.get("agent_name", ""),
        metadata_table=d.get("metadata_table", []),
        screenshots=d.get("screenshots", []),
        extra_fields={k: v for k, v in d.items() if k not in core},
    )


def _json_round_trip(obj):
    return json.loads(json.dumps(obj))


def _normalized_repr(obj):
    """A comparable, JSON-able representation of normalized steps."""
    steps = normalize_trajectory(obj)
    return [
        {"role": s.role, "content": s.content,
         "tool_calls": [tc.to_dict() for tc in s.tool_calls]}
        for s in steps
    ]


# --------------------------------------------------------------------------- #
# A. CanonicalTrace serialization fidelity
# --------------------------------------------------------------------------- #

class TestCanonicalTraceSerialization:
    def _full_trace(self):
        return CanonicalTrace(
            id="trace_42",
            task_description="Book the cheapest flight JFK->LHR",
            conversation=[
                {"speaker": "User", "text": "Find me a flight"},
                {"speaker": "Agent (Thought)", "text": "I should search"},
                {"speaker": "Agent (Action)", "text": 'search_flights({"from": "JFK"})'},
                {"speaker": "Environment", "text": "Found 5 flights"},
            ],
            agent_name="ReAct-GPT4",
            metadata_table=[{"Property": "Steps", "Value": "4"}],
            screenshots=["https://example.com/s1.png"],
            extra_fields={"gold_labels": {"quality": "good"}, "source": "unit-test"},
        )

    def test_to_dict_preserves_all_populated_fields(self):
        t = self._full_trace()
        d = _json_round_trip(t.to_dict())
        r = _canonical_from_dict(d)
        assert r.id == t.id
        assert r.task_description == t.task_description
        assert r.conversation == t.conversation
        assert r.agent_name == t.agent_name
        assert r.metadata_table == t.metadata_table
        assert r.screenshots == t.screenshots
        # extra fields are flattened to the top level and must round-trip
        assert r.extra_fields == t.extra_fields

    def test_extra_fields_flattened_not_nested(self):
        d = self._full_trace().to_dict()
        # extra fields live at the top level (not under an "extra_fields" key)
        assert "extra_fields" not in d
        assert d["gold_labels"] == {"quality": "good"}
        assert d["source"] == "unit-test"

    def test_extra_fields_cannot_clobber_core_fields(self):
        t = CanonicalTrace(
            id="real_id",
            task_description="real task",
            conversation=[{"speaker": "User", "text": "hi"}],
            extra_fields={"id": "HACKED", "task_description": "HACKED",
                          "conversation": [], "harmless": 1},
        )
        d = t.to_dict()
        assert d["id"] == "real_id"
        assert d["task_description"] == "real task"
        assert d["conversation"] == [{"speaker": "User", "text": "hi"}]
        assert d["harmless"] == 1

    def test_empty_optionals_omitted_but_reload_defaults_match(self):
        # to_dict() omits empty agent_name/metadata_table/screenshots; reloading
        # must restore the same (empty) defaults so state is unchanged.
        t = CanonicalTrace(id="t", task_description="task",
                           conversation=[{"speaker": "User", "text": "x"}])
        d = t.to_dict()
        assert "agent_name" not in d
        assert "metadata_table" not in d
        assert "screenshots" not in d
        r = _canonical_from_dict(_json_round_trip(d))
        assert r.agent_name == ""
        assert r.metadata_table == []
        assert r.screenshots == []
        assert r.conversation == t.conversation

    def test_drift_guard_all_dataclass_fields_round_trip(self):
        """If a new CanonicalTrace field is added but not handled by to_dict(),
        this fails. Update _full_trace() + this list when adding fields."""
        from dataclasses import fields
        expected = {"id", "task_description", "conversation", "agent_name",
                    "metadata_table", "screenshots", "extra_fields"}
        actual = {f.name for f in fields(CanonicalTrace)}
        assert actual == expected, (
            f"CanonicalTrace fields changed: {actual ^ expected}. "
            "Update to_dict(), _canonical_from_dict(), and the round-trip tests."
        )


# --------------------------------------------------------------------------- #
# B. Per-importer round-trip (raw -> canonical -> JSON -> reload)
# --------------------------------------------------------------------------- #

# (format_name, raw_input) pairs. Each raw_input must be detect()-able as its
# named format and convert to >=1 CanonicalTrace.
CONVERTER_SAMPLES = {
    "react": {
        "id": "r1",
        "task": "Book a flight",
        "agent": "ReAct-GPT4",
        "steps": [
            {"thought": "I should search", "action": 'search({"q": "JFK->LHR"})',
             "observation": "Found 5 flights"},
            {"thought": "Pick cheapest", "action": "book(flight=3)",
             "observation": "Booked"},
        ],
        "metadata": {"tokens": 2340},
    },
    "langchain": {
        "id": "lc1",
        "name": "AgentExecutor",
        "run_type": "chain",
        "inputs": {"input": "Book a flight"},
        "outputs": {"output": "Booked BA117"},
        "child_runs": [
            {"name": "ChatOpenAI", "run_type": "llm",
             "inputs": {}, "outputs": {"generations": [{"text": "I need to search"}]}},
            {"name": "search_flights", "run_type": "tool",
             "inputs": {"query": "JFK to LHR"}, "outputs": {"output": "Found 5 flights"}},
        ],
    },
    "openai": {
        "id": "oai1",
        "messages": [
            {"role": "user", "content": "Book a flight"},
            {"role": "assistant", "content": "Searching", "tool_calls": [
                {"function": {"name": "search", "arguments": '{"q": "JFK"}'}}]},
            {"role": "tool", "content": "Found 5 flights"},
        ],
    },
    "anthropic": {
        # tool name is deliberately NOT a coding tool, so this routes to the
        # anthropic converter rather than claude_code (which claims coding tools).
        "id": "ant1",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Book a flight"}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Searching"},
                {"type": "tool_use", "name": "book_flight", "input": {"q": "JFK"}},
            ]},
        ],
    },
    "langfuse": {
        "id": "lf1",
        "name": "agent-run",
        "observations": [
            {"type": "GENERATION", "name": "llm", "input": "Book a flight",
             "output": "I should search"},
            {"type": "SPAN", "name": "search", "input": {"q": "JFK"},
             "output": "Found 5 flights"},
        ],
    },
    "multi_agent": {
        "id": "ma1",
        "agents": ["planner", "executor"],
        "steps": [
            {"agent": "planner", "thought": "Plan it", "action": "delegate"},
            {"agent": "executor", "action": "search(q='JFK')", "observation": "Found"},
        ],
    },
}


class TestConverterRoundTrip:
    @pytest.mark.parametrize("fmt", sorted(CONVERTER_SAMPLES.keys()))
    def test_detect_routes_to_correct_format(self, fmt):
        raw = CONVERTER_SAMPLES[fmt]
        detected = converter_registry.detect_format(raw)
        # Auto-detection must route each sample to its intended converter --
        # misrouting (e.g. an OpenAI trace detected as Anthropic) silently
        # corrupts imported state.
        assert detected == fmt, f"{fmt} sample auto-detected as {detected!r}"
        # Re-detecting the same input must give the same answer (no flakiness).
        assert converter_registry.detect_format(raw) == detected

    @pytest.mark.parametrize("fmt", sorted(CONVERTER_SAMPLES.keys()))
    def test_import_store_reload_preserves_state(self, fmt):
        raw = CONVERTER_SAMPLES[fmt]
        traces = converter_registry.convert(fmt, raw)
        assert traces, f"{fmt} produced no traces"
        trace = traces[0]

        # to_dict() must be JSON-serializable (it becomes a stored item).
        d = trace.to_dict()
        stored = _json_round_trip(d)

        # Core identity survives storage.
        assert stored["id"] == trace.id
        assert stored["task_description"] == trace.task_description

        # Conversation is preserved byte-for-byte through JSON.
        assert stored["conversation"] == trace.conversation
        # Conversation turns are well-formed {speaker, text} dicts.
        assert isinstance(stored["conversation"], list)
        for turn in stored["conversation"]:
            assert set(turn.keys()) >= {"speaker", "text"}

        # The stored dict normalizes to the SAME annotation-facing steps as the
        # live object -- this is the real "state works after reload" guarantee.
        assert _normalized_repr(trace) == _normalized_repr(stored)

    @pytest.mark.parametrize("fmt", sorted(CONVERTER_SAMPLES.keys()))
    def test_normalized_steps_nonempty(self, fmt):
        raw = CONVERTER_SAMPLES[fmt]
        trace = converter_registry.convert(fmt, raw)[0]
        steps = normalize_trajectory(trace.to_dict())
        assert len(steps) >= 1, f"{fmt} normalized to zero steps"

    def test_all_registered_converters_have_a_sample(self):
        """Coverage guard: every registered converter should have a round-trip
        sample here, or be explicitly acknowledged as untested."""
        registered = set(converter_registry.get_supported_formats())
        # Formats deliberately not sampled here (covered by other tests / niche
        # input shapes). Keep this list SMALL and intentional.
        acknowledged = {
            "atif", "webarena", "web_agent", "swebench",
            "swe_agent_trajectory", "aider", "otel", "mcp", "claude_code",
        }
        tested = set(CONVERTER_SAMPLES.keys())
        missing = registered - tested - acknowledged
        assert not missing, (
            f"Converters with no round-trip coverage: {sorted(missing)}. "
            "Add a sample to CONVERTER_SAMPLES or acknowledge it explicitly."
        )


# --------------------------------------------------------------------------- #
# C. normalize_trajectory equivalence + tool-call fidelity
# --------------------------------------------------------------------------- #

class TestNormalizeEquivalence:
    def test_object_and_dict_paths_match(self):
        t = converter_registry.convert("react", CONVERTER_SAMPLES["react"])[0]
        # CanonicalTrace object path vs its to_dict() (stored) path.
        assert _normalized_repr(t) == _normalized_repr(t.to_dict())

    def test_flattened_action_tool_call_args_survive(self):
        # An "Agent (Action)" turn with a JSON arg blob must parse into a
        # ToolCall whose args round-trip through normalization.
        trace = CanonicalTrace(
            id="x", task_description="t",
            conversation=[
                {"speaker": "Agent (Action)",
                 "text": 'search_flights({"from": "JFK", "to": "LHR", "n": 3})'},
            ],
        )
        calls = extract_tool_calls(trace.to_dict())
        assert len(calls) == 1
        assert calls[0].name == "search_flights"
        assert calls[0].args == {"from": "JFK", "to": "LHR", "n": 3}

    def test_openai_messages_and_canonical_yield_tool_calls(self):
        oai = converter_registry.convert("openai", CONVERTER_SAMPLES["openai"])[0]
        calls = extract_tool_calls(oai.to_dict())
        names = [c.name for c in calls]
        assert "search" in names
        # the JSON string arguments were parsed into a dict
        search = next(c for c in calls if c.name == "search")
        assert search.args == {"q": "JFK"}

    def test_bare_string_and_list_shapes(self):
        assert _normalized_repr("just an answer") == [
            {"role": "assistant", "content": "just an answer", "tool_calls": []}
        ]
        assert normalize_trajectory(None) == []
        assert normalize_trajectory([]) == []


# --------------------------------------------------------------------------- #
# D. potato_trace capture SDK -> ingestion round-trip
# --------------------------------------------------------------------------- #

class TestCaptureSDKRoundTrip:
    def test_run_payload_json_round_trip(self):
        from potato_trace.run_tree import Run, build_payload

        root = Run(name="agent", run_type="chain", id="root",
                   inputs={"input": "Book a flight"},
                   outputs={"output": "Booked"}, status="success", latency=1.5,
                   tags=["prod"])
        child = Run(name="search", run_type="tool", id="c1", parent_run_id="root",
                    inputs={"q": "JFK"}, outputs={"output": "Found 5"},
                    status="success", extra={"tokens": 10})
        payload = build_payload([child, root], root_id="root",
                                project_name="proj")
        reloaded = _json_round_trip(payload)

        assert reloaded["project_name"] == "proj"
        assert [r["id"] for r in reloaded["runs"]][0] == "root"  # root first
        run_map = {r["id"]: r for r in reloaded["runs"]}
        assert run_map["root"]["inputs"] == {"input": "Book a flight"}
        assert run_map["c1"]["parent_run_id"] == "root"
        assert run_map["c1"]["extra"] == {"tokens": 10}
        for r in reloaded["runs"]:
            assert {"id", "run_type", "name", "inputs", "outputs", "status"} <= set(r)

    def test_sdk_payload_ingests_to_steps(self):
        # The SDK emits a LangSmith-format payload; the ingestion normalizer must
        # turn it back into a usable trace with one step per run.
        from potato_trace.run_tree import Run, build_payload
        from potato.trace_ingestion.webhook_receiver import WebhookReceiver

        root = Run(name="agent", run_type="chain", id="root",
                   inputs={"input": "Book a flight"},
                   outputs={"output": "Booked"}, status="success")
        child = Run(name="search", run_type="tool", id="c1", parent_run_id="root",
                    inputs={"input": "JFK"}, outputs={"output": "Found 5"},
                    status="success")
        payload = _json_round_trip(build_payload([root, child], "root", "proj"))

        normalized = WebhookReceiver().process_webhook(payload, format_hint="auto")
        assert normalized is not None
        assert normalized["id"].startswith("langsmith_")
        assert len(normalized["steps"]) == 2
        assert normalized["steps"][1]["observation"] == "Found 5"

    def test_safe_serialize_handles_non_json_object(self):
        from potato_trace.run_tree import Run

        class Weird:
            def __repr__(self):
                return "Weird(1)"

        run = Run(name="x", inputs={"obj": Weird(), "ok": 5})
        payload = run.to_payload()
        # Non-JSON object is stringified; the payload stays JSON-serializable.
        assert payload["inputs"]["ok"] == 5
        assert payload["inputs"]["obj"] == "Weird(1)"
        _json_round_trip(payload)  # must not raise


# --------------------------------------------------------------------------- #
# E. Real example canonical trace data survives a JSON round-trip
# --------------------------------------------------------------------------- #

_EXAMPLE_TRACE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "examples", "agent-traces", "agent-trace-evaluation", "data",
    "agent-traces.json",
)


@pytest.mark.skipif(
    not os.path.exists(_EXAMPLE_TRACE_FILE),
    reason="example trace data file not present",
)
class TestExampleDataRoundTrip:
    def _load(self):
        records = []
        with open(_EXAMPLE_TRACE_FILE) as f:
            content = f.read().strip()
        # Support both a JSON array and JSONL.
        try:
            parsed = json.loads(content)
            records = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            for line in content.splitlines():
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def test_every_record_normalizes_and_round_trips(self):
        records = self._load()
        assert records, "no example trace records loaded"
        for rec in records:
            assert "conversation" in rec
            # JSON round-trip is stable (idempotent).
            assert _json_round_trip(rec) == rec
            # Loaded record normalizes to >=1 step.
            steps = normalize_trajectory(rec)
            assert len(steps) >= 1

            # Re-hydrating as a CanonicalTrace and re-serializing preserves the
            # conversation (the annotation-facing state).
            trace = _canonical_from_dict(rec)
            assert trace.conversation == rec["conversation"]
            assert _normalized_repr(trace) == _normalized_repr(rec)
