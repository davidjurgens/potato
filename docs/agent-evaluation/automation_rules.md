# Automation Rules

The automation engine closes the **production → eval loop**: a programmable
`filter → sampling rate → actions` pipeline runs over every item entering Potato
— whether loaded from `data_files` or ingested at runtime via the
[trace webhook](agent_traces.md) / [tracing SDK](../integrations/tracing_sdk.md).
Each matching rule can route the item to the annotation queue, curate it into an
[eval dataset](datasets_and_experiments.md), run an
[evaluator](evaluators.md), fire an outbound webhook, or notify annotators.

## Enabling

```yaml
automation:
  enabled: true
  rules:
    - name: route-errors
      when: {field: status, in: [error, failed]}
      sample_rate: 1.0          # 0.0–1.0 (default 1.0 = every match)
      actions:
        - {type: add_to_queue, priority: 100, reason: "Agent errored"}
        - {type: add_to_dataset, dataset: errors-to-fix}
        - {type: run_evaluator, evaluator: trajectory_match}
        - {type: fire_webhook, url: "https://example.com/hook"}
        - {type: notify, message: "New error trace"}
```

## Rules

A rule fires for an item when **both**:

1. **`when`** matches — the shared condition grammar (same as
   [triage](triage_queue.md)): `equals`, `in`, `contains`, `exists`,
   `lt`/`lte`/`gt`/`gte`, dotted field paths (`metadata.score`). A list of
   conditions is AND-ed; an empty/absent `when` matches everything.
2. **`sample_rate`** selects it — **deterministic** sampling on a hash of
   `(item id, rule name)`, so re-processing the same item yields the same
   decision (idempotent, replay-safe). `1.0` = always, `0.0` = never.

> Common fields on an ingested trace: `metadata.source`
> (`webhook`/`langsmith`/`langfuse`), `task_description`, plus any top-level
> fields your payload includes that survive normalization.

## Actions

| Action | When it runs | Effect |
|--------|--------------|--------|
| `add_to_queue` | inline (fast) | Boost the item's triage priority so the `priority` assignment strategy surfaces it. Params: `priority`, `reason`. |
| `add_to_dataset` | inline (fast) | Append the item as an example to a dataset (created if absent). Params: `dataset`. |
| `notify` | inline (fast) | Notify connected annotators via SSE. Params: `message`. |
| `enroll_review` | inline (fast) | Enroll the item on the [review board](review_workflow.md), applying `review_workflow.routing`. No params. |
| `run_evaluator` | background worker | Score the item with an [evaluator](evaluators.md); the score is stored on the item (`metadata.automation_eval`). Params: `evaluator`, `params`. |
| `fire_webhook` | background worker | POST `{rule, item_id, item_data}` to an external URL. Params: `url`, `headers`. |
| `refresh_topics` | background worker | Re-cluster the curation index and persist the clusters as [topics](semantic_curation.md). Params: `k`, `min_indexed`, `use_llm`. |

**Fast actions** run inline in the ingestion path (cheap, in-process). **Heavy
actions** (`run_evaluator`, `fire_webhook`, `refresh_topics`) are dispatched to a
background worker so ingestion never blocks. Every action records an outcome;
failures are caught and logged as `error` outcomes — automation never breaks
ingestion.

> Ordering note: actions within a rule run in listed order, but heavy actions
> complete asynchronously, so a `fire_webhook` may finish after a later inline
> action. (Mirrors LangSmith's per-rule scheduling caveat.)

## Inspecting

The admin dashboard links to **Automation** (`/admin/automation`), showing
configured rules, activity counters, and recent action outcomes. JSON API:

| Path | Returns |
|------|---------|
| `GET /admin/automation/status` | rules + counters + per-action breakdown |
| `GET /admin/automation/outcomes?limit=N` | recent action outcomes |

## Example

`examples/agent-traces/automation-loop/` is a runnable demo:

```bash
python potato/flask_server.py start examples/agent-traces/automation-loop/config.yaml -p 8000
curl -X POST http://localhost:8000/api/traces/webhook -H "Content-Type: application/json" \
  -d '{"id":"run-1","task_description":"buy milk","status":"error","steps":[{"action_type":"click"}]}'
```

## Related

- [Datasets & Experiments](datasets_and_experiments.md) — `add_to_dataset` targets
- [Programmatic Evaluators](evaluators.md) — `run_evaluator`
- [Triage Queue](triage_queue.md) — shares the condition grammar
- [Tracing SDK](../integrations/tracing_sdk.md) / [Agent traces](agent_traces.md) — sources of incoming items
