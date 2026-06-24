# Trace Analytics & Regression Alerts

Aggregate the operational metrics your ingested agent traces already carry — token
usage, latency, error status, and (when pricing is configured) cost — into totals,
per-model breakdowns, and latency percentiles, and **flag regressions** between a
recent window and a baseline.

Potato sits *offline* in the human-in-the-loop path, so this **flags** problems for
review; it never blocks a live request.

## Viewing analytics

With the eval-datasets feature enabled, the analytics endpoint aggregates over every
runtime-ingested trace:

```bash
# JSON (totals, per-model, latency percentiles)
curl localhost:8000/admin/eval/analytics -H "X-API-Key: <admin-key>"

# HTML dashboard
open "localhost:8000/admin/eval/analytics?format=html"

# Flag regressions of the latest 100 traces vs the rest
curl "localhost:8000/admin/eval/analytics?recent=100" -H "X-API-Key: <admin-key>"
```

The dashboard shows trace count, total tokens, total cost, error rate, average and
p95 latency, a per-model table, and any regression alerts.

## Metric extraction

Extraction is tolerant of the many shapes traces arrive in. For each trace it looks
for `model`, token usage (`usage.prompt_tokens` / `completion_tokens` / `total_tokens`
and common aliases), `latency_ms`, `cost`, and a `status`/`outcome` (error detection),
using dotted paths with a converter `metadata_table` fallback. Total tokens are
derived from prompt + completion when a total isn't recorded.

## Cost from pricing

If a trace doesn't record cost but you provide a per-model price table, cost is
computed from token counts:

```yaml
analytics:
  pricing:
    gpt-4o:    {in: 2.5,  out: 10.0}   # $ per 1K prompt / completion tokens
    claude-sonnet-4-6: {in: 3.0, out: 15.0}
    default:   {in: 0.0,  out: 0.0}
  thresholds:
    cost_per_trace: 0.5    # alert if recent cost/trace is ≥ 50% over baseline
    avg_latency_ms: 0.3    # alert if avg latency is ≥ 30% over baseline
    error_rate: 0.05       # alert if error rate rises ≥ 5 percentage points
```

## Regression alerts

`?recent=N` splits traces into a recent window (last N) and a baseline (the rest)
and compares them. Each alert carries a metric, severity (medium/high), the baseline
and recent values, and a message — e.g. *"Error rate up 50.0 points"* or *"Cost per
trace up 100%"*. Thresholds are configurable (above). The same alerts can be wired to
[automation rules](automation_rules.md) (`notify` / `fire_webhook`).

## Related documentation

- [Tracing SDK](../integrations/tracing_sdk.md) — capture traces (with token usage)
- [Automation Rules](automation_rules.md) — route/alert on incoming traces
- [Datasets & Experiments](datasets_and_experiments.md) — curate flagged traces
