"""Unit tests for the potato_trace SDK (hermetic — no network)."""

import asyncio

import pytest

import potato_trace
from potato_trace import tracer
from potato_trace.run_tree import Run, build_payload


class CaptureClient:
    """Stand-in client that records submitted run trees instead of POSTing."""

    def __init__(self):
        self.calls = []  # list of (runs, root_id, project_name)

    def submit(self, runs, root_id, project_name=""):
        self.calls.append((list(runs), root_id, project_name))

    def flush(self, timeout=30.0):
        pass


@pytest.fixture
def capture(monkeypatch):
    client = CaptureClient()
    monkeypatch.setattr(tracer, "_default_client", client)
    return client


# ---- run tree / payload ----

def test_build_payload_root_first_and_project():
    a = Run(name="root", id="r1")
    b = Run(name="child", id="r2", parent_run_id="r1")
    payload = build_payload([b, a], root_id="r1", project_name="proj")
    assert payload["runs"][0]["id"] == "r1"  # root sorted first
    assert payload["project_name"] == "proj"
    assert payload["runs"][1]["parent_run_id"] == "r1"


# ---- decorator ----

def test_nested_traceable_forms_one_tree(capture):
    @potato_trace.traceable(run_type="tool")
    def search(q):
        return f"results for {q}"

    @potato_trace.traceable
    def agent(task):
        return search(task)

    agent("weather")

    assert len(capture.calls) == 1  # one submit when the root completes
    runs, root_id, _ = capture.calls[0]
    assert len(runs) == 2
    by_name = {r.name: r for r in runs}
    assert by_name["agent"].parent_run_id is None
    assert by_name["agent"].id == root_id
    assert by_name["search"].parent_run_id == by_name["agent"].id
    assert by_name["search"].run_type == "tool"
    assert by_name["agent"].status == "success"
    assert by_name["search"].latency is not None


def test_exception_marks_error_and_still_submits(capture):
    @potato_trace.traceable
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        boom()
    assert len(capture.calls) == 1
    runs, _, _ = capture.calls[0]
    assert runs[0].status == "error"
    assert "nope" in runs[0].error


def test_async_traceable(capture):
    @potato_trace.traceable
    async def afetch(x):
        await asyncio.sleep(0)
        return x * 2

    assert asyncio.run(afetch(3)) == 6
    assert len(capture.calls) == 1
    assert capture.calls[0][0][0].outputs["output"] == 6


def test_set_outputs_and_metadata(capture):
    @potato_trace.traceable(run_type="llm")
    def call_llm(prompt):
        potato_trace.set_outputs({"output": "hello"})
        potato_trace.add_metadata(tokens=42)
        return "hello"

    call_llm("hi")
    run = capture.calls[0][0][0]
    assert run.outputs["output"] == "hello"
    assert run.extra["tokens"] == 42


def test_trace_context_manager(capture):
    with potato_trace.trace("step", run_type="chain") as run:
        run.outputs = {"output": "done"}
    assert len(capture.calls) == 1
    assert capture.calls[0][0][0].name == "step"


# ---- client enable/disable ----

def test_client_disabled_without_url():
    from potato_trace.client import PotatoTraceClient
    c = PotatoTraceClient()  # no POTATO_TRACE_URL
    assert c.enabled is False
    # submit is a safe no-op; should not raise even with runs
    c.submit([Run(name="x")], root_id=None)


def test_client_enabled_with_url():
    from potato_trace.client import PotatoTraceClient
    c = PotatoTraceClient(potato_url="http://localhost:9999")
    assert c.enabled is True
