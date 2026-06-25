# Search Example

Demonstrates **universal FTS5 search**. Read-only admin search is always
available; this example also turns on **annotator search-and-claim**
(`search.annotator_claim: true`), which is compatible here because the
project uses `fixed_order` assignment with no overlap, QC, or crowd
backend (the startup guard would refuse to boot otherwise).

```bash
python potato/flask_server.py start \
  examples/advanced/search-example/config.yaml -p 8000
```

## What to try

- **Admin search** (read-only), using the `admin_api_key` from the config:

  ```bash
  curl -H "X-API-Key: search-example-key" \
    "http://localhost:8000/admin/api/search?q=export"
  ```

- **Annotator Find panel** (left edge): search the corpus and **Claim** a
  matching instance into your queue. `max_annotations_per_user: 2` keeps
  the corpus from being fully pre-assigned, so claiming is meaningful.

Queries are prefix + AND matches (e.g. `bus line` needs both `bus*` and
`line*`); see the query-syntax notes in the doc.

See [docs/advanced/search.md](../../../docs/advanced/search.md).
