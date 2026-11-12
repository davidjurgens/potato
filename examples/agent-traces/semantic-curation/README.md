# Semantic Curation (Catalog)

Find *what to review* by **similarity**, not just rules: build an embedding index
over your items, search for traces like a query or example, and save **dynamic
slices** (semantic + metadata filters) that auto-include new matching traces and
curate into datasets.

## Run

```bash
pip install sentence-transformers     # real embeddings (or wire a custom embedder)
python potato/flask_server.py start examples/agent-traces/semantic-curation/config.yaml -p 8000
```

Open the admin dashboard → **Catalog**.

## Try it

1. **Build index** — embeds the loaded traces.
2. **Search** "tool call failed" → the error traces (t1, t2, t5) rank highest.
3. **Save a slice** — name `tool-errors`, query "tool call failed", threshold 0.3,
   optionally a metadata filter `{field: metadata.outcome, equals: error}`.
4. **Resolve** the slice to see matching ids; **→ Dataset** curates them into a
   dataset for annotation/eval.

## API

```bash
curl -X POST localhost:8000/admin/catalog/api/build -H "X-API-Key: <key>"
curl -X POST localhost:8000/admin/catalog/api/search -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" -d '{"query": "tool call failed", "top_k": 3}'
```

## Config

```yaml
curation:
  enabled: true
  model_name: all-MiniLM-L6-v2   # any sentence-transformers model
  embed_on_ingest: false          # set true to index runtime-ingested traces
  text_key: task_description      # which field to embed
```

See the [Semantic Curation guide](../../../docs/agent-evaluation/semantic_curation.md).
