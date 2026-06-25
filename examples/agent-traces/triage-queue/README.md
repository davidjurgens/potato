# Signal-Based Triage Queue

Review the worst agent traces **first**. Each trace in `data/triage-queue-example.json`
carries a production signal (`status`, `feedback`, `score`); the `triage` block in
`config.yaml` turns those into a queue priority, and `assignment_strategy: priority`
serves the highest-priority items first.

## Run

```bash
python potato/flask_server.py start examples/agent-traces/triage-queue/config.yaml \
  -p 8000 --debug --debug-phase annotation
```

The first item served is `trace_002` (an agent error), not `trace_001`, because the
queue is ordered by signal. A banner above the form explains why: **"Prioritized for
review · Agent errored."**

## The ranked queue (admin)

```bash
curl -H "X-API-Key: <admin-key>" "localhost:8000/admin/triage-queue?format=html"
```

shows every remaining item ranked by priority, with the reason that flagged it.

## How the signal maps to priority

| Rule              | Condition              | Priority |
|-------------------|------------------------|----------|
| Agent errored     | `status == error`      | 100      |
| Negative feedback | `feedback == thumbs_down` | 80    |
| Low quality score | `score < 0.5`          | 60       |
| (no match)        | —                      | 0        |

Highest matching rule wins. Omit `rules` entirely to use the turnkey defaults
(error / negative feedback / low score). For runtime-ingested traces (webhook /
Langfuse) the same scorer runs as each trace arrives.

See [docs/agent-evaluation/triage_queue.md](../../../docs/agent-evaluation/triage_queue.md).
