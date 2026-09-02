# Threaded discussion annotation

A branching discussion annotated at every level at once. **No ConvoKit involved** —
the data is a plain hand-written thread whose turns carry `id` and `reply_to`.

```bash
python potato/flask_server.py start examples/conversation/threaded-forum/config.yaml -p 8000
```

## What it demonstrates

The `dialogue` display renders any threaded source — a forum, a GitHub review, a
mailing list, a chat log — and supports the full range of annotation on it
simultaneously:

| Level | Scheme |
|---|---|
| Whole thread | `outcome` (radio) |
| Per comment | `comment_type` (radio) |
| Per comment | `persuasiveness` (likert) |
| Per comment | `comment_note` (text, in a drawer) |
| Any text in the thread | `evidence` (span) |
| Between comments | `argument_links` (span_link) |

Nesting depth is derived from `reply_to`; nothing precomputes it. Spans and
per-comment widgets coexist on the same field — widget subtrees are excluded from
the span offset basis, so adding a rating to a comment never shifts a highlight.

See [dialogue annotation](../../../docs/annotation-types/structured/dialogue_annotation.md).
