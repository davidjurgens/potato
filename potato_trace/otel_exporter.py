"""
OpenTelemetry interop (optional extra).

Maps OTel spans (OpenTelemetry GenAI semantic conventions where present) to
Potato run trees and ships them via ``PotatoTraceClient``. ``opentelemetry`` is
an OPTIONAL dependency: importing this module probes for it lazily and
``build_exporter`` raises an informative error if it's missing.

    from potato_trace.otel_exporter import build_exporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(build_exporter()))
"""

from __future__ import annotations

from importlib.util import find_spec
from typing import Any, List, Optional

from potato_trace.run_tree import Run


def is_available() -> bool:
    """True if ``opentelemetry`` can be imported (no import performed)."""
    return find_spec("opentelemetry") is not None


def _hex(n: Optional[int]) -> Optional[str]:
    return format(n, "x") if n else None


def _run_type_for(span: Any) -> str:
    attrs = dict(getattr(span, "attributes", {}) or {})
    name = (getattr(span, "name", "") or "").lower()
    if any(k.startswith("gen_ai") for k in attrs) or "llm" in name or "chat" in name:
        return "llm"
    if "tool" in name or attrs.get("tool.name") or "execute_tool" in name:
        return "tool"
    if "retriev" in name or "search" in name:
        return "retriever"
    return "chain"


def span_to_run(span: Any) -> Run:
    """Map one OTel span to a Potato Run (GenAI conventions where present)."""
    attrs = dict(getattr(span, "attributes", {}) or {})
    ctx = getattr(span, "context", None) or getattr(span, "get_span_context", lambda: None)()
    span_id = _hex(getattr(ctx, "span_id", None)) if ctx else None
    parent = getattr(span, "parent", None)
    parent_id = _hex(getattr(parent, "span_id", None)) if parent else None

    prompt = attrs.get("gen_ai.prompt") or attrs.get("input") or attrs.get("llm.prompts")
    completion = attrs.get("gen_ai.completion") or attrs.get("output") or attrs.get("llm.output")

    start = getattr(span, "start_time", None)
    end = getattr(span, "end_time", None)
    latency = (end - start) / 1e9 if (start and end) else None

    status_obj = getattr(span, "status", None)
    is_error = bool(getattr(getattr(status_obj, "status_code", None), "name", "") == "ERROR")

    extra = {}
    for k in ("gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
              "gen_ai.usage.total_tokens", "gen_ai.request.model", "gen_ai.system"):
        if k in attrs:
            extra[k] = attrs[k]

    return Run(
        name=getattr(span, "name", "span"),
        run_type=_run_type_for(span),
        id=span_id or Run(name="x").id,
        parent_run_id=parent_id,
        inputs={"input": prompt} if prompt is not None else {},
        outputs={"output": completion} if completion is not None else {},
        status="error" if is_error else "success",
        latency=latency,
        extra=extra,
    )


def build_exporter(client: Any = None, project_name: str = ""):
    """Build a SpanExporter that ships spans to Potato. Requires opentelemetry."""
    if not is_available():
        raise ImportError(
            "potato_trace.otel_exporter requires the optional 'opentelemetry-sdk' "
            "package. Install it with: pip install opentelemetry-sdk"
        )
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    from potato_trace.client import PotatoTraceClient
    _client = client or PotatoTraceClient()

    class PotatoSpanExporter(SpanExporter):
        def export(self, spans) -> "SpanExportResult":
            # Group spans into per-trace run trees.
            by_trace = {}
            for span in spans:
                ctx = getattr(span, "context", None)
                trace_id = _hex(getattr(ctx, "trace_id", None)) if ctx else "otel"
                by_trace.setdefault(trace_id, []).append(span)
            for trace_id, group in by_trace.items():
                runs: List[Run] = [span_to_run(s) for s in group]
                child_ids = {r.parent_run_id for r in runs}
                roots = [r for r in runs if r.parent_run_id is None
                         or r.parent_run_id not in {x.id for x in runs}]
                root_id = roots[0].id if roots else (runs[0].id if runs else None)
                _client.submit(runs, root_id, project_name)
            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            _client.flush()

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            _client.flush(timeout=timeout_millis / 1000.0)
            return True

    return PotatoSpanExporter()
