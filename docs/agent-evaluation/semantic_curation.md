# Semantic Curation (Catalog)

Find *what to review* by **similarity**, not just rules or uncertainty. An
embedding index over your items powers similarity search ("find traces like this
failure") and **dynamic slices** — saved semantic + metadata filters that
auto-include new matching traces and curate into [datasets](datasets_and_experiments.md).
This is the LabelBox-Catalog-style discovery layer; it complements
[triage](triage_queue.md) (signal rules) and active learning (model uncertainty).

## Enabling

```yaml
curation:
  enabled: true
  model_name: all-MiniLM-L6-v2   # any sentence-transformers model
  embed_on_ingest: false          # set true to index runtime-ingested traces on arrival
  text_key: task_description      # which field to embed (defaults to the item text)
```

Embeddings are **lazy** — `sentence-transformers` is imported only when you build
the index, never at startup (so boot stays fast). Install it with
`pip install sentence-transformers`, or wire a custom embedder. When enabled, the
admin dashboard shows a **Catalog** link.

## Build the index

The index is built on demand (or incrementally on ingest with `embed_on_ingest`):

```bash
curl -X POST localhost:8000/admin/catalog/api/build -H "X-API-Key: <key>"
# {"indexed": 1234}
```

## Similarity search

Search by free-text query or by an **anchor instance** (find neighbours of a
known example). Results are ranked by cosine similarity, with an adjustable
threshold.

```bash
curl -X POST localhost:8000/admin/catalog/api/search -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"query": "tool call failed", "top_k": 10, "threshold": 0.3}'
# or: {"anchor_id": "trace-42", ...}   (excludes the anchor itself)
```

## Dynamic slices

A **slice** is a saved filter that resolves *on demand* against the current
index — so traces ingested after you saved it are automatically included if they
match. A slice combines (optional) semantic neighborhood with a metadata filter
(the shared [condition grammar](automation_rules.md)):

```bash
curl -X POST localhost:8000/admin/catalog/api/slices -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"name": "tool-errors", "query": "tool call failed", "threshold": 0.3,
       "metadata_filter": [{"field": "metadata.outcome", "equals": "error"}]}'

curl localhost:8000/admin/catalog/api/slices/tool-errors/resolve -H "X-API-Key: <key>"
# {"count": 17, "instance_ids": [...]}
```

### Curate a slice into a dataset

```bash
curl -X POST localhost:8000/admin/catalog/api/slices/tool-errors/to_dataset \
  -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"dataset": "tool-errors-to-fix", "include_annotations": false}'
```

The resolved instances become examples in the named [dataset](datasets_and_experiments.md),
ready for annotation, experiments, or SFT/DPO export.

## API summary

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/admin/catalog/api/build` | Build the embedding index over current items |
| POST | `/admin/catalog/api/search` | `{query\|anchor_id, top_k, threshold}` |
| GET/POST | `/admin/catalog/api/slices` | List / create slices |
| GET | `/admin/catalog/api/slices/<n>/resolve` | Resolve a slice → instance ids |
| DELETE | `/admin/catalog/api/slices/<n>` | Delete a slice |
| POST | `/admin/catalog/api/slices/<n>/to_dataset` | Curate a slice into a dataset |

## Example

`examples/agent-traces/semantic-curation/` is a runnable demo.

## Related

- [Datasets & Experiments](datasets_and_experiments.md) — slice curation target
- [Automation Rules](automation_rules.md) — rule-based routing (shares the condition grammar)
- [Triage Queue](triage_queue.md) — signal-based prioritization
