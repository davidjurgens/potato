# SDK Capture

Instrument your agent with the **`potato_trace`** SDK so its runs are captured
and sent to Potato for evaluation — Potato sits in the runtime path instead of
only receiving offline dumps.

## Run

1. Start a Potato server that receives traces:

   ```bash
   python potato/flask_server.py start examples/agent-traces/sdk-capture/config.yaml -p 8000
   ```

2. Run the traced agent, pointing it at the server. `potato_trace` is a
   top-level package in this repo, so either `pip install -e .` first, or put
   the repo root on `PYTHONPATH`:

   ```bash
   PYTHONPATH=. POTATO_TRACE_URL=http://localhost:8000 \
     python examples/agent-traces/sdk-capture/agent.py
   ```

3. Open the Potato UI — each agent run arrives as an item to evaluate.

## How it works

`agent.py` decorates functions with `@potato_trace.traceable`. Nested calls form
a run tree; when the outermost call returns, the whole tree is POSTed to
`/api/traces/webhook` in the background. `potato_trace.flush()` waits for sends
to finish before the script exits.

```python
import potato_trace
potato_trace.configure(potato_url="http://localhost:8000")

@potato_trace.traceable(run_type="tool")
def search(q): ...

@potato_trace.traceable
def agent(task):
    return search(task)
```

See the [Tracing SDK guide](../../../docs/integrations/tracing_sdk.md) for OpenTelemetry
interop and token-usage capture.
