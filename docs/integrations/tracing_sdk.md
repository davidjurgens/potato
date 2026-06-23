# Tracing SDK (`potato_trace`)

`potato_trace` is a lightweight, dependency-light SDK that captures your agent's
runs and ships them to Potato's [trace-ingestion](../agent-evaluation/agent_traces.md)
pipeline — so Potato sits in the runtime path and you evaluate real runs as they
happen, instead of only importing offline dumps.

It is a **top-level package** (importing it never pulls in Flask or the ML
stack) and uses only the standard library plus `requests` at send time.

## Install

`potato_trace` ships with Potato:

```bash
pip install -e .        # from the repo, makes `potato_trace` importable anywhere
# or, running from the repo without installing:
PYTHONPATH=. python your_agent.py
```

## Quick start

```python
import potato_trace

potato_trace.configure(
    potato_url="http://localhost:8000",   # or env POTATO_TRACE_URL
    api_key="",                            # or env POTATO_TRACE_API_KEY
    project_name="my-agent",
)

@potato_trace.traceable(run_type="tool")
def search(query):
    return run_search(query)

@potato_trace.traceable(run_type="llm")
def summarize(text):
    potato_trace.add_metadata(prompt_tokens=120, completion_tokens=40)
    return call_llm(text)

@potato_trace.traceable           # the outermost call is the trace root
def agent(task):
    return summarize(search(task))

agent("weather in NYC")
potato_trace.flush()              # ensure sends finish before a short script exits
```

Nested `@traceable` calls form a **run tree**; when the root returns, the whole
tree is POSTed to `/api/traces/webhook` in a background thread (tracing never
blocks or crashes your agent). If no `potato_url` is configured, tracing is a
safe no-op.

## API

| Symbol | Purpose |
|--------|---------|
| `configure(potato_url=, api_key=, project_name=)` | Set the global client |
| `@traceable` / `@traceable(run_type=, name=, tags=)` | Trace a function (sync or async). `run_type`: `chain` (default), `llm`, `tool`, `retriever` |
| `trace(name, run_type=...)` | Context-manager form: `with trace("step"): ...` |
| `set_outputs({...})` | Set/merge outputs on the current run |
| `add_metadata(**kw)` | Attach extra metadata (e.g. token usage) to the current run |
| `current_run()` | The `Run` currently executing (or `None`) |
| `flush(timeout=30)` | Wait for pending background sends |
| `PotatoTraceClient(...)` | Construct a client explicitly (advanced) |

## OpenTelemetry interop (optional)

If your stack emits OpenTelemetry spans (GenAI semantic conventions), export them
to Potato directly. `opentelemetry-sdk` is an optional extra:

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from potato_trace.otel_exporter import build_exporter

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(build_exporter(project_name="my-agent")))
```

`build_exporter()` maps spans (using `gen_ai.*` attributes where present —
prompt, completion, token usage, model) to Potato run trees and submits them.
`potato_trace.otel_exporter.is_available()` reports whether `opentelemetry` is
installed.

## Payload format

The SDK emits the LangSmith-format run payload (`{"runs": [...], "project_name"}`)
that Potato's webhook already normalizes — so no server-side configuration is
needed beyond enabling trace ingestion:

```yaml
trace_ingestion:
  enabled: true
  api_key: ""    # set a key in production; the SDK sends it as a Bearer token
```

## Related

- [Agent trace annotation](../agent-evaluation/agent_traces.md)
- [Datasets & Experiments](../agent-evaluation/datasets_and_experiments.md)
- [LangChain callback](langchain_integration.md) — the framework-specific alternative
- Example: `examples/agent-traces/sdk-capture/`
