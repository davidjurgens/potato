"""
OpenTelemetry/OTLP Converter

Converts OpenTelemetry trace exports to Potato's canonical format.

Supported input formats:

1. OTLP JSON export (nested spans):
{
    "resourceSpans": [{
        "scopeSpans": [{
            "spans": [{
                "traceId": "abc123",
                "spanId": "span1",
                "parentSpanId": "",
                "name": "LLM call",
                "startTimeUnixNano": "1700000000000000000",
                "endTimeUnixNano": "1700000001000000000",
                "attributes": [
                    {"key": "gen_ai.prompt", "value": {"stringValue": "..."}},
                    {"key": "gen_ai.completion", "value": {"stringValue": "..."}}
                ]
            }]
        }]
    }]
}

2. Flattened per-span format (from exporters like Braintrust, OpenLLMetry):
[
    {
        "trace_id": "abc123",
        "span_id": "span1",
        "parent_span_id": null,
        "name": "AgentRun",
        "start_time": "2024-01-01T00:00:00Z",
        "end_time": "2024-01-01T00:00:01Z",
        "attributes": {
            "gen_ai.prompt": "...",
            "gen_ai.completion": "...",
            "llm.token_count.prompt": 100
        }
    }
]
"""

from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class OTELConverter(BaseTraceConverter):
    """Converter for OpenTelemetry/OTLP trace exports."""

    format_name = "otel"
    description = "OpenTelemetry/OTLP trace exports (GenAI Semantic Conventions)"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}

        if self._is_otlp_format(data):
            spans = self._extract_otlp_spans(data)
        else:
            spans = data if isinstance(data, list) else [data]

        # Group spans by trace_id
        trace_groups = self._group_by_trace(spans)
        results = []

        for trace_id, trace_spans in trace_groups.items():
            results.append(self._convert_trace_group(trace_id, trace_spans, len(results)))

        return results

    def _extract_otlp_spans(self, data: Any) -> List[dict]:
        """Extract flat span list from OTLP nested format."""
        spans = []
        resource_spans = data if isinstance(data, dict) else {}
        for rs in resource_spans.get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for span in ss.get("spans", []):
                    flat = {
                        "trace_id": span.get("traceId", ""),
                        "span_id": span.get("spanId", ""),
                        "parent_span_id": span.get("parentSpanId", ""),
                        "name": span.get("name", ""),
                        "start_time_nano": span.get("startTimeUnixNano", "0"),
                        "end_time_nano": span.get("endTimeUnixNano", "0"),
                        "attributes": self._flatten_otlp_attributes(
                            span.get("attributes", [])
                        ),
                        "status": span.get("status", {}),
                    }
                    spans.append(flat)
        return spans

    def _flatten_otlp_attributes(self, attrs: list) -> dict:
        """Convert OTLP attribute list to flat dict."""
        result = {}
        for attr in attrs:
            if not isinstance(attr, dict):
                continue
            key = attr.get("key", "")
            value = attr.get("value", {})
            if isinstance(value, dict):
                # Extract the typed value
                for vtype in ("stringValue", "intValue", "doubleValue", "boolValue"):
                    if vtype in value:
                        result[key] = value[vtype]
                        break
                if "arrayValue" in value:
                    result[key] = [
                        v.get("stringValue", str(v))
                        for v in value["arrayValue"].get("values", [])
                    ]
            else:
                result[key] = value
        return result

    def _group_by_trace(self, spans: List[dict]) -> Dict[str, List[dict]]:
        """Group spans by trace_id, preserving order."""
        groups: Dict[str, List[dict]] = {}
        for span in spans:
            if not isinstance(span, dict):
                continue
            trace_id = span.get("trace_id", span.get("traceId", ""))
            if not trace_id:
                trace_id = f"trace_{len(groups)}"
            if trace_id not in groups:
                groups[trace_id] = []
            groups[trace_id].append(span)
        return groups

    def _convert_trace_group(self, trace_id: str, spans: List[dict],
                             index: int) -> CanonicalTrace:
        """Convert a group of spans belonging to the same trace."""
        # Sort by start time
        spans.sort(key=lambda s: self._get_start_time(s))

        conversation = []
        task_description = ""
        total_tokens = 0
        model = ""

        # Find root span (no parent)
        root_span = None
        for span in spans:
            parent = span.get("parent_span_id", span.get("parentSpanId", ""))
            if not parent:
                root_span = span
                break

        if root_span:
            task_description = root_span.get("name", "")

        for span in spans:
            attrs = span.get("attributes", {})
            span_name = span.get("name", "")

            # GenAI Semantic Conventions
            prompt = attrs.get("gen_ai.prompt", attrs.get("gen_ai.request.prompt", ""))
            completion = attrs.get("gen_ai.completion", attrs.get("gen_ai.response.completion", ""))
            span_model = attrs.get("gen_ai.request.model", attrs.get("llm.model", ""))

            if span_model and not model:
                model = str(span_model)

            # Token counting
            for token_key in ("llm.token_count.prompt", "llm.token_count.completion",
                              "gen_ai.usage.prompt_tokens", "gen_ai.usage.completion_tokens",
                              "llm.usage.total_tokens"):
                val = attrs.get(token_key)
                if val:
                    try:
                        total_tokens += int(val)
                    except (ValueError, TypeError):
                        pass

            # Build conversation turns
            if prompt:
                conversation.append({
                    "speaker": "User",
                    "text": str(prompt)
                })

            if completion:
                conversation.append({
                    "speaker": "Agent",
                    "text": str(completion)
                })

            # Tool spans
            tool_name = attrs.get("tool.name", "")
            tool_input = attrs.get("tool.input", "")
            tool_output = attrs.get("tool.output", "")

            if tool_name or (not prompt and not completion and tool_input):
                if tool_input:
                    conversation.append({
                        "speaker": "Agent (Action)",
                        "text": f"{tool_name or span_name}({tool_input})" if tool_name or span_name else str(tool_input)
                    })
                if tool_output:
                    conversation.append({
                        "speaker": "Environment",
                        "text": str(tool_output)
                    })

            # If span has no GenAI attributes but has a meaningful name,
            # and is not root, add as a system event
            if not prompt and not completion and not tool_name and not tool_input:
                if span != root_span and span_name:
                    duration = self._compute_duration(span)
                    if duration:
                        conversation.append({
                            "speaker": f"System ({span_name})",
                            "text": f"Duration: {duration}"
                        })

        # Build metadata table
        metadata_table = [
            {"Property": "Spans", "Value": str(len(spans))}
        ]
        if model:
            metadata_table.append({"Property": "Model", "Value": model})
        if total_tokens:
            metadata_table.append({"Property": "Total Tokens", "Value": str(total_tokens)})

        return CanonicalTrace(
            id=trace_id,
            task_description=task_description or f"OTEL Trace {trace_id[:16]}",
            conversation=conversation,
            agent_name=model,
            metadata_table=metadata_table,
        )

    def _get_start_time(self, span: dict) -> int:
        """Get start time as integer for sorting."""
        # Try nano timestamp first (OTLP format)
        nano = span.get("start_time_nano", "0")
        try:
            return int(nano)
        except (ValueError, TypeError):
            pass
        # Try ISO timestamp
        start = span.get("start_time", "")
        if start:
            return hash(start)  # Consistent ordering for ISO strings
        return 0

    def _compute_duration(self, span: dict) -> str:
        """Compute human-readable duration from span timestamps."""
        try:
            start = int(span.get("start_time_nano", "0"))
            end = int(span.get("end_time_nano", "0"))
            if start and end and end > start:
                duration_ms = (end - start) / 1_000_000
                if duration_ms < 1000:
                    return f"{duration_ms:.0f}ms"
                return f"{duration_ms / 1000:.2f}s"
        except (ValueError, TypeError):
            pass
        return ""

    def _is_otlp_format(self, data: Any) -> bool:
        """Check if data is in OTLP nested format."""
        return isinstance(data, dict) and "resourceSpans" in data

    def detect(self, data: Any) -> bool:
        # OTLP nested format
        if isinstance(data, dict) and "resourceSpans" in data:
            return True

        # Flattened per-span format
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False

        # Must have trace_id + span_id (distinguishes from other formats)
        has_trace_id = "trace_id" in first or "traceId" in first
        has_span_id = "span_id" in first or "spanId" in first
        return has_trace_id and has_span_id
