# Memos

Memos are free-text notes an annotator can attach to an instance, or to a
text selection within an instance. They are a **universal** feature —
available in standard annotation, [solo mode](../solo-mode/solo_mode.md), and QDA mode
— useful for flagging ambiguous cases, recording rationale, and building
an audit trail.

## Overview

- Each memo belongs to its author and is attached to one instance.
- A memo can be **instance-level** or anchored to a **text selection**
  (character offsets), shown with a `quote` badge.
- Memos persist immediately and survive navigating away and back.
- Memos are stored in the universal project database
  (`<task_dir>/project.sqlite`), not in the annotation JSON files.

## Configuration

```yaml
annotation_ui:
  memos: true            # enable the Notes sidebar
  visibility: private    # default visibility for new memos: private | shared
```

| Option | Default | Description |
|--------|---------|-------------|
| `annotation_ui.memos` | off in standard mode; **on** when `qda_mode.enabled` or `solo_mode.enabled` | Shows the Notes sidebar and enables `/api/memos`. |
| `annotation_ui.visibility` | `private` | Default visibility selected in the composer. |

When disabled the `/api/memos` endpoints return `503` and no sidebar
toggle is shown — the standard annotation page is unchanged.

## Visibility model

| Visibility | Author | Admin / adjudicator | Other annotators |
|------------|:------:|:-------------------:|:----------------:|
| `private`  | ✅ | ✅ (always) | ❌ |
| `shared`   | ✅ | ✅ (always) | ✅ |

- Admins/adjudicators can **always** read every memo regardless of
  visibility (oversight/QC).
- Only the **author** may edit a memo's body or visibility.
- The **author or an admin/adjudicator** may delete a memo (moderation).

> **Bias caution.** Setting memos to `shared` lets annotators read each
> other's notes during labeling, which can anchor judgments and inflate
> apparent agreement. For inter-annotator-agreement studies, prefer
> `private` (the default). Use `shared` for collaborative qualitative
> coding where shared context is desirable.

## Using the sidebar

1. Click the **Notes** toggle on the right edge of the annotation page.
2. Type a note. Optionally select text in the instance first and tick
   "Attach to selected text" to anchor the memo to that span.
3. Choose a visibility and click **Add note**.
4. Your own memos show **Edit** / **Delete** actions.

## Exporting memos

The [`quotation_report`](../data-export/export_formats.md) exporter can include
memos for audit trails and qualitative deliverables:

```bash
python -m potato.export --config config.yaml \
  --format quotation_report --output ./out/ \
  --option include_memos=true
```

Memo rows appear with `schema = "(memo)"`, `code = <visibility>`,
`text = <memo body>`, and offsets from the memo anchor when span-anchored.

## Example

A runnable example is in `examples/advanced/memos-example/`:

```bash
python potato/flask_server.py start examples/advanced/memos-example/config.yaml -p 8000
```

## Related

- [QDA Mode](qda.md) — turns memos on alongside the codebook, cases & search
- [Solo Mode](../solo-mode/solo_mode.md)
- [Quality Control](../workflow/quality_control.md)
- [Data Export](../data-export/export_formats.md)
