# Session-Level Scoring

Agent interactions rarely end after one trace: a user comes back, the agent
follows up, an escalation resolves three exchanges later. **Session-level
scoring** groups every trace that shares a `session_id`/`thread_id` into a
*session* and lets annotators score the session as a whole — "did this
multi-trace interaction resolve the user's problem?" — the session/thread
annotation workflow from LangSmith and Langfuse.

Session scores live alongside (not instead of) per-trace annotation: regular
schemes still apply per trace on `/annotate`, while `session_level` schemes
are answered once per session on `/sessions`.

## Configuration

```yaml
sessions:
  enabled: true
  key: session_id        # optional — by default session_id, thread_id,
                         # then conversation_id are scanned (top-level
                         # or under item metadata)
  attributes: [user_tier]  # optional — item fields lifted onto the session

annotation_schemes:
  - annotation_type: likert
    name: session_resolution
    description: "Did the session resolve the user's problem?"
    size: 5
    session_level: true    # scored on /sessions, not per trace

  - annotation_type: radio   # regular scheme — per trace, as usual
    name: trace_quality
    description: "Quality of this trace"
    labels: [good, acceptable, poor]
```

Supported `session_level` types: `radio`, `multiselect`, `likert`, `slider`,
`select`, `textbox`, `number`. A scheme cannot be both `turn_level` and
`session_level`.

### How sessions are detected

At server start (and idempotently on re-runs) items are grouped by the first
non-empty session key found either top-level or under `metadata` — which is
where the [Langfuse poller](agent_traces.md) and the trace converters put
`session_id`. Items with no session key simply don't join any session.
Sessions are stored as *cases* in the universal cases store, under a separate
`<project>::sessions` namespace, so they coexist with QDA participant cases.

## The /sessions page

Log in and open `/sessions`:

- **Queue** (left): every detected session with trace count and your
  per-session progress (`2/3 scored`).
- **Detail** (right): the session-level questions, live cross-annotator
  aggregates (mean for numeric schemes, value counts for categorical ones),
  and the member traces with previews.

Scores save immediately on interaction; clicking a selected chip again clears
it. Each annotator scores independently — one row per
`(session, annotator, schema)`.

On the per-trace annotation form, session-level schemes render only a small
pointer note linking to `/sessions`, so annotators always know where those
questions live.

## Export

Every save rewrites `<output_annotation_dir>/session_annotations.jsonl`, one
row per (session, annotator, schema):

```json
{"session": "session-alpha", "case_id": "…", "annotator": "alice",
 "schema": "session_resolution", "value": {"value": 4},
 "updated_at": 1751979600.0, "instance_ids": ["trace-a1", "trace-a2", "trace-a3"]}
```

Admins can also pull the same rows as JSON:

```bash
curl localhost:8000/api/sessions/export -H "X-API-Key: <key>"
```

## API summary

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/sessions` | Session review page (login required) |
| GET | `/api/sessions` | Queue: sessions + trace counts + aggregates + my progress |
| GET | `/api/sessions/<case_id>` | Members, my annotations, aggregates |
| POST | `/api/sessions/<case_id>/annotate` | `{schema, value: {value: x} \| {values: [...]} \| null}` |
| GET | `/api/sessions/export` | Full dump (admin / X-API-Key) |

## Example

`examples/agent-traces/session-scoring/` is a runnable demo with three
synthetic sessions (a three-trace debugging arc, a two-trace contradiction
case, and a single-trace escalation):

```bash
python potato/flask_server.py start examples/agent-traces/session-scoring/config.yaml -p 8000
```

## Related

- [Turn-Level Annotation](turn_level_annotation.md) — the other end of the
  granularity spectrum (per turn instead of per session)
- [Agent Traces](agent_traces.md) — live ingestion; the Langfuse poller emits
  `session_id` in item metadata
- [Datasets & Experiments](datasets_and_experiments.md)
