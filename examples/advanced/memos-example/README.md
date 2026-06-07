# Memos Example

Demonstrates the **universal Memos sidebar**: free-text analytic notes
attached to an instance or to a specific text selection, with
per-memo visibility (`private` = author + admins; `shared` = peers too).

```bash
python potato/flask_server.py start \
  examples/advanced/memos-example/config.yaml -p 8000
```

## What to try

- Open the **Notes** sidebar (right edge) and add a note about the
  current instance; pick Private or Shared visibility.
- Select some text first, then add a note — the composer offers to
  **anchor** the memo to that selection (character offsets are stored).
- Navigate away and back: your notes persist (stored server-side).

This example sets `annotation_ui.visibility: private`. See the
inter-annotator bias caution before using `shared`.

See [docs/advanced/memos.md](../../../docs/advanced/memos.md).
