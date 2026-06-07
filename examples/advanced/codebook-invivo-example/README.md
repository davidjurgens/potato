# Codebook In-Vivo Example

Demonstrates **in-vivo coding**: a `span` scheme that is also
`codebook: true`. Select a passage in the text, press the in-vivo key
(`codebook_invivo_key`, default **`i`**), and mint a code straight from
the selection.

```bash
python potato/flask_server.py start \
  examples/advanced/codebook-invivo-example/config.yaml -p 8000
```

## What to try

- Highlight a phrase (e.g. "the cost of insulin"), press **`i`**, and a
  composer opens pre-filled with a code name derived from the selection.
- Start typing a near-duplicate of an existing code (e.g. `cost
  concern`) — closely matching codes surface as one-click chips
  ("Similar existing code — reuse instead?"). Pick one to reuse it; the
  button then reads **Apply code** instead of **Create & code**.
- Confirm: a span with that code is laid over your selection, no reload.

See [docs/advanced/codebook.md](../../../docs/advanced/codebook.md#in-vivo-coding-code-from-a-selection).
