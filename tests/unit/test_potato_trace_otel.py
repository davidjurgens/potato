"""Tests for the optional OpenTelemetry exporter in potato_trace."""

import types

import pytest

from potato_trace import otel_exporter
from potato_trace.otel_exporter import span_to_run, is_available


def _fake_span(name, attributes, span_id, trace_id, parent_id=None,
               start=1_000_000_000, end=1_500_000_000, error=False):
    ctx = types.SimpleNamespace(span_id=span_id, trace_id=trace_id)
    parent = types.SimpleNamespace(span_id=parent_id) if parent_id else None
    status = types.SimpleNamespace(
        status_code=types.SimpleNamespace(name="ERROR" if error else "OK"))
    return types.SimpleNamespace(
        name=name, attributes=attributes, context=ctx, parent=parent,
        start_time=start, end_time=end, status=status)


def test_span_to_run_llm_mapping():
    span = _fake_span(
        "chat gpt-4o",
        {"gen_ai.prompt": "hello", "gen_ai.completion": "hi there",
         "gen_ai.usage.input_tokens": 3, "gen_ai.usage.output_tokens": 2,
         "gen_ai.request.model": "gpt-4o"},
        span_id=0x2, trace_id=0xABC, parent_id=0x1)
    run = span_to_run(span)
    assert run.run_type == "llm"
    assert run.inputs["input"] == "hello"
    assert run.outputs["output"] == "hi there"
    assert run.parent_run_id == "1"
    assert run.id == "2"
    assert run.latency == pytest.approx(0.5)  # (1.5e9 - 1.0e9) / 1e9
    assert run.extra["gen_ai.usage.input_tokens"] == 3


def test_span_to_run_tool_and_error():
    span = _fake_span("execute_tool search", {"tool.name": "search"},
                      span_id=0x3, trace_id=0xABC, error=True)
    run = span_to_run(span)
    assert run.run_type == "tool"
    assert run.status == "error"


def test_build_exporter_submits_tree():
    if not is_available():
        pytest.skip("opentelemetry not installed")

    class Capture:
        def __init__(self):
            self.calls = []
        def submit(self, runs, root_id, project_name=""):
            self.calls.append((runs, root_id, project_name))
        def flush(self, timeout=30.0):
            pass

    cap = Capture()
    exporter = otel_exporter.build_exporter(client=cap, project_name="otel-proj")
    spans = [
        _fake_span("agent", {}, span_id=0x1, trace_id=0xABC, parent_id=None),
        _fake_span("search", {"tool.name": "x"}, span_id=0x2, trace_id=0xABC, parent_id=0x1),
    ]
    result = exporter.export(spans)
    # SpanExportResult.SUCCESS
    assert getattr(result, "name", str(result)) in ("SUCCESS", "SpanExportResult.SUCCESS")
    assert len(cap.calls) == 1
    runs, root_id, proj = cap.calls[0]
    assert proj == "otel-proj"
    assert root_id == "1"  # the parentless span is the root
    assert {r.name for r in runs} == {"agent", "search"}
