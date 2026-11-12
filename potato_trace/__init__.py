"""
Potato tracing SDK — capture agent runs and send them to Potato for evaluation.

Dependency-light (stdlib + ``requests`` only at send time) and a *top-level*
package, so importing it never drags in Flask or the ML stack. Drop it into your
agent code to capture traces into Potato's trace-ingestion pipeline.

    import potato_trace
    potato_trace.configure(potato_url="http://localhost:8000", api_key="...")

    @potato_trace.traceable(run_type="tool")
    def search(query): ...

    @potato_trace.traceable
    def agent(task):
        return search(task)

    agent("find the weather")
    potato_trace.flush()   # ensure the trace is sent before a script exits

OpenTelemetry interop lives in ``potato_trace.otel_exporter`` (optional extra).
"""

from potato_trace.run_tree import Run, build_payload
from potato_trace.client import PotatoTraceClient
from potato_trace.tracer import (
    traceable,
    trace,
    configure,
    flush,
    current_run,
    set_outputs,
    add_metadata,
)

__all__ = [
    "Run",
    "build_payload",
    "PotatoTraceClient",
    "traceable",
    "trace",
    "configure",
    "flush",
    "current_run",
    "set_outputs",
    "add_metadata",
]

__version__ = "0.1.0"
