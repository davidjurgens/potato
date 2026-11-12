# Labeling engine CLI, REST API, MCP tools and SDK

The server, the command line, the REST API, the MCP tools and the Python SDK
all drive the same engine over the same `engine.sqlite` in the task
directory. You can start a study from the command line, serve the human
requests with the server, and certify from a notebook.

Only one process drives a study at a time. A running server's planner holds
the study's writer lock; while it does, `potato label run`, `potato label
certify` and `Study.run()` refuse and say so (certify through the server
instead: `POST /api/engine/v1/certify` or the admin page). Two drivers would
draw two calibration samples and certify against each other's labels. The
lock is released when its holder exits; a holder killed on the same machine
is taken over at once, and one elsewhere after two minutes without a
heartbeat. Read-only commands (`status`, `certificate`, `calls`, `export`)
work at any time.

## Command line

```bash
potato label <command> <config.yaml> [options]
```

| Command | What it does |
|---|---|
| `run` | Label every item with the cascade, draw the blind calibration sample, certify, resolve. `--until predicted` (default) stops after one pass; `--until met` keeps going until every contract is met or the engine is waiting on people. `--max-items N`, `--budget-usd X` (overrides `budgets.model_usd` for this run), `--max-ticks N` (default 20), `--json`. A killed run resumes where it stopped without repeating model calls. Exits with status 1, naming the source, when a source's last run failed or every answer it gave was an error, or when no source can label a scheme a contract names. |
| `status` | Items, predictions, requests by purpose, contracts, spend, items with no label yet, and a line for each source with errors or a failed or paused run. `--json`. |
| `certify` | Test every contract on new cert labels and new predictions. When only dev labels changed, the stored result comes back with a note; `--retest` tests the rule dev now picks, at the next look (see [Looks](contracts.md#looks)). `--json`. |
| `certificate` | The quality certificate. `--format md` (default), `html` or `json`; `--out FILE`. |
| `export` | Labels with provenance, the certificate (JSON, Markdown, HTML), a dataset card and the call log, into `--out DIR` (default `<output_annotation_dir>/labeling_engine`). |
| `calls` | The model-call audit log as JSON lines. `--out FILE`. |
| `distill` | Train a model on the labels so far and put it first in the cascade. |
| `optimize` | Score every subset of the cascade on dev labels and report the cheapest that keeps coverage; when no subset keeps any coverage, it recommends none. `--prompts N` also asks an LLM tier for N paraphrases of its prompt and scores each on the dev items (model calls, logged and budgeted, stored under their own source versions; the current prompt is scored from its stored predictions). The cascade and the certificate are not changed. |
| `migrate-config` | Write a copy of the config with a `labeling_engine` block equivalent to its older AI keys. `--out FILE`. See [Migration](migration.md). |

### Files written by `export`

| File | Contents |
|---|---|
| `labels.jsonl`, `labels.csv` | One row per item and scheme, labeled or not: `id`, `schema`, `label`, `label_origin` (`auto`, `human`, `adjudicated`, ...), `status` (`accepted`, `accepted_uncertified` under `threshold_legacy`, `pending`, `pending_recert`), `source`, `model`, `source_version`, `confidence`, `contract_version`, `request_ids`. A machine label whose source has changed since it was accepted reads `pending_recert` until the next pass re-certifies it. |
| `certificate.json`, `.md`, `.html` | The certificate |
| `README.md` | A dataset card (Hugging Face front matter) built from the certificate |
| `model_calls.jsonl` | Every model call: model, hashes of prompt and reply, tokens, latency, cost, cache hits, redaction categories |

The regular exporters (`python -m potato.export`, the admin export) export
people's annotations. When the engine is on, CSV, Parquet and Hugging Face exports add
two columns saying which engine request each annotation answered:
`engine_purpose` (for example `calibration`) and `engine_request` (JSON with
the purpose, inclusion probability, visibility, split and request id). Use
these to separate the blind random sample from verify answers.

## REST API

All routes are under `/api/engine/v1` and return JSON. Authenticate with the
admin key (`X-API-Key` header) or an admin session. Reads need the
admin-dashboard permission; `certify` and `plan` need assignment management;
the certificate needs export permission.

| Method and path | Returns |
|---|---|
| `GET /status` | Items, predictions, requests, call totals, budgets, and each scheme's cascade, contracts and resolved-label counts |
| `GET /schemes/<name>/contracts` | The latest result of each contract on the scheme, marked `stale` if the cascade changed |
| `GET /schemes/<name>/risk_coverage` | For each threshold of the last tier: share accepted, observed error and the guaranteed upper bound, on cert labels |
| `GET /schemes/<name>/reliability` | Reliability bins, ECE and Brier score per tier, on calibration labels |
| `GET /schemes/<name>/drift` | The audit monitor per selective-risk contract |
| `GET /schemes/<name>/optimize` | The cheaper-cascade report, scored on dev labels |
| `GET /requests` | Request counts by purpose and status, and the requests themselves. Filters: `purpose`, `status` (repeat the parameter or separate values with commas), `schema`, `limit` (max 1000) |
| `GET /calls` | The call log, newest first, and totals by source. `limit` (max 500), `offset` |
| `GET /certificate` | The certificate. `format=json` (default), `md` or `html`; `save=1` also stores it |
| `GET /crowd` | The planner's last crowd plan (dry run unless live spend is on) |
| `POST /certify` | Test every contract now. `?retest=1` (or `{"retest": true}`) also tests a rule that only dev labels changed |
| `POST /plan` | Run one planner pass now |

The routes answer 404 when the engine is off for the study, and 400 with a
JSON error for a parameter that is not valid (a `limit` that is not a number,
an unknown `purpose` or `status`, a `format` other than `json`, `md` or
`html`).

## MCP tools

The MCP server exposes five engine tools, with the same permissions as the
REST routes: `engine_status`, `engine_requests`, `engine_run` (one planner
pass), `engine_certify` (with `retest`) and `engine_certificate` (`json`, `md`
or `html`). Granting them while the engine is off is a validation warning.
Through `potato mcp connect`, a refused call (a missing permission, a bad
parameter) comes back as a tool error. See
[MCP server](../tools/mcp_server.md).

## Python

```python
from potato.labeling_engine.sdk import Study

study = Study("examples/labeling-engine/text-certified-sentiment/config.yaml")
study.run()                                   # label, sample, certify, resolve
for req in study.requests(status="open")[:5]:
    study.label(req.item_id, req.schema, "positive", user="me",
                request_id=req.id)
study.certify()
print(study.certificate(fmt="md"))
study.export("out/")
```

| Method | Does |
|---|---|
| `Study(config_path)` | Load the config and items |
| `run(until="predicted", max_ticks=20)` | As `potato label run`; takes the writer lock |
| `label(item_id, scheme, value, user, request_id=None)` | Record a person's label. It closes `request_id`, or else a request this person holds on the item; otherwise it is kept as an organic label, which never certifies. A second label from the same person on the same item updates their first |
| `status()` | As `GET /status` |
| `requests(status=None, purpose=None, ...)` | The ledger |
| `certify(retest=False)` | As `potato label certify` |
| `certificate(fmt="json")` | `json`, `md` or `html` |
| `export(out_dir)` | As `potato label export` |

## Related documentation

- [Overview](overview.md)
- [Configuration](configuration.md)
- [Contracts](contracts.md)
