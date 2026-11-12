# Three-Pane Agent Trace Evaluation (`eval_trace`)

The `eval_trace` display takes a single agent trace and splits it into three
synchronized side-by-side panes:

> **Reasoning** | **Function Calls** | **Final Answer**

The evaluator reads what the agent thought, what it did, and what it produced
without scrolling between them, which is what makes a stream of incoming traces
judgeable at the rate they arrive.

Unlike [`agent_trace`](agent_traces.md) (which stacks an interleaved trace
vertically in a single column) or [`pairwise`](../annotation-types/instance_display.md#pairwise-display)
(which compares two separate traces), `eval_trace` decomposes **one** interleaved
trace into its three semantic components.

## Quick start

```bash
python potato/flask_server.py start examples/agent-traces/continuous-eval/config.yaml -p 8000
```

See `examples/agent-traces/continuous-eval/` for the full runnable project,
including the directory-watch variant (`config-watch.yaml`).

## Configuration

```yaml
instance_display:
  layout:
    direction: vertical      # task header above the (internally horizontal) panes
    gap: 12px
  fields:
    - key: task_description
      type: text
      label: "Task"

    - key: trace             # the field holding the agent trace
      type: eval_trace
      label: "Agent Trace"
      display_options:
        pane_labels: ["Reasoning", "Function Calls", "Final Answer"]
        show_step_numbers: true
        collapse_long_outputs: true
        max_output_lines: 12
        link_steps: true
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `pane_labels` | `["Reasoning", "Function Calls", "Final Answer"]` | Headers for the three panes (list of 3 strings; padded with defaults if fewer). |
| `show_step_numbers` | `true` | Show `#N` step numbers on reasoning/call cards. |
| `collapse_long_outputs` | `true` | Collapse tool results longer than `max_output_lines` into an expandable block. |
| `max_output_lines` | `20` | Line threshold for collapsing results. |
| `link_steps` | `true` | Enable cross-pane highlighting: clicking a card highlights the linked cards in the other panes. |
| `compact` | `false` | Tighter padding/spacing. |

## Data format

`eval_trace` accepts the same trace formats as `agent_trace`. The most common is
a list of `{speaker, text}` steps:

```json
{
  "id": "eval_001",
  "task_description": "Find a vegan lasagna recipe.",
  "trace": [
    {"speaker": "Agent (Thought)",      "text": "I'll search for a highly-rated recipe."},
    {"speaker": "Agent (Action)",       "text": "web_search(query='vegan lasagna')"},
    {"speaker": "Environment",          "text": "10 results found..."},
    {"speaker": "Agent (Final Answer)", "text": "Here's a great recipe: ..."}
  ]
}
```

The `thought/action/observation` (one dict expands to up to three steps) and
`step_type/content` formats are also supported.

### How steps map to panes

| Step (type inferred from speaker/label) | Pane |
|---|---|
| `Thought` / reasoning / planning / `system` | **Reasoning** |
| `Action` / tool / function / call | **Function Calls** (the adjacent `Environment`/result nests under the call as `↳`) |
| `Final Answer` / `send_message` / `respond` / `finish` — or the last action if none match | **Final Answer** |

To set an explicit final answer, end the trace with a step whose speaker matches
an answer pattern (e.g. `"Agent (Final Answer)"`), or a `send_message(...)` action.

### Step linking

Steps are grouped into logical cycles: a thought (or thoughts) plus the calls it
triggers share a `data-step-index`. With `link_steps: true`, clicking any card
highlights every card sharing that index across the panes, so you can trace a
thought to the action it produced.

## Continuous evaluation

Pair `eval_trace` with any of Potato's runtime ingestion transports so traces are
evaluated as they arrive:

- **Webhook + SSE** — `trace_ingestion: {enabled: true}` exposes
  `POST /api/traces/webhook` and notifies annotators via `GET /api/traces/stream`.
- **Langfuse polling** — add a `langfuse` source under `trace_ingestion.sources`
  (see below).
- **Directory watch** — `data_directory` + `watch_data_directory: true` ingests
  dropped `.json`/`.jsonl` files.

Runtime-added traces are immediately assignable to annotators (dynamic sources
default the per-user quota to unlimited). See
`examples/agent-traces/continuous-eval/README.md` for curl examples.

### Langfuse polling

```yaml
trace_ingestion:
  enabled: true
  sources:
    - type: langfuse
      api_url: https://cloud.langfuse.com
      public_key: pk-lf-...
      secret_key: sk-lf-...
      poll_interval: 30      # seconds between polls
      lookback_hours: 24     # how far back the first poll reaches
      settle_seconds: 30     # wait this long after a run finishes
      max_trace_seconds: 3600  # the longest a run may take
```

Each Langfuse trace becomes one item, `langfuse_<trace id>`. Its steps are the
trace's observations in start order, without the root span, which stands for
the whole run; the root's input and output go in the item's metadata.

Langfuse's SDKs send a step when it ends, so while a run is going Langfuse
holds its finished steps and nothing else. The root span ends last, so the
poller takes a trace once its root has arrived and `settle_seconds` have
passed since it ended. A trace whose root never arrives (a crashed run) is
taken after `max_trace_seconds`, with what it has, and marked
`complete: false` in its metadata. Each poll reads back over the last
`max_trace_seconds`, because a long call appears only when it ends, carrying
its start time; a busy project with a long bound fetches more per poll. A
trace already in the project is not added again after a restart.

The poller reads Langfuse v4's Observations API
(`GET /api/public/v2/observations`). Self-hosted Langfuse v4 refuses the
older traces API, and Langfuse Cloud removes it on 2026-11-16. Against an
older server without the v2 endpoint, the poller falls back to the traces API
and reads each new trace in full.

Traces that came from Langfuse or LangSmith can have the annotators' merged
answer sent back to them as a score or feedback; see
[Trace Score Write-Back](trace_writeback.md).

## Notes & limitations

- `eval_trace` pairs naturally with annotation schemes (e.g. `reasoning_quality`,
  `tool_use_correctness`, `answer_helpfulness`) as in the example.
- **Span annotation is supported.** Set `span_target: true` on the field and add a
  `span` scheme — the whole three-pane view becomes one span target, so an
  evaluator can highlight any text across the panes (a flawed reasoning step, a
  wrong tool argument, a bad final answer) and label it. Spans restore by offset
  against the rendered panes (so they survive navigation), via the shared
  multi-field span pipeline.

  ```yaml
  instance_display:
    fields:
      - key: trace
        type: eval_trace
        span_target: true      # enable span highlighting across the panes
  annotation_schemes:
    - annotation_type: span
      name: error_spans
      labels: [reasoning_error, tool_error, answer_error]
  ```

## Related

- [Agent Traces](agent_traces.md) — vertical step-card display and evaluation patterns
- [Coding Agent Annotation](coding_agent_annotation.md) — diff/terminal/file-tree trace display
- [Instance Display](../annotation-types/instance_display.md) — display-field configuration reference
- [LangChain Integration](../integrations/langchain_integration.md) — webhook ingestion
