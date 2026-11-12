# Automation Loop

The **production → eval flywheel**: ingested traces are matched by
[automation rules](../../../docs/agent-evaluation/automation_rules.md) that route
them to the annotation queue, curate them into eval datasets, and notify
annotators — automatically, as they arrive.

## Run

```bash
python potato/flask_server.py start examples/agent-traces/automation-loop/config.yaml -p 8000
```

Push a trace (an errored run matches the `route-errors` rule):

```bash
curl -X POST http://localhost:8000/api/traces/webhook -H "Content-Type: application/json" \
  -d '{"id":"run-1","task_description":"buy milk","status":"error","steps":[{"action_type":"click"}]}'
```

Then open the admin dashboard → **Automation** (`/admin/automation`) to see the
rules that fired and their action outcomes.

## What the rules do

- **`curate-ingested`** — every ingested trace → added to the `incoming-traces`
  dataset + an annotator notification.
- **`route-errors`** — errored runs → high-priority queue (`add_to_queue`) + added
  to the `errors-to-fix` dataset.

Rules use the shared condition grammar (`when`), a deterministic `sample_rate`,
and a list of `actions`. See the
[Automation Rules guide](../../../docs/agent-evaluation/automation_rules.md).
