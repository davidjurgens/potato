# Memos

Memos are free-text notes an annotator can attach to an instance, to a text
selection within an instance, or to a shape drawn on an image. Anyone who can
read a note can reply to it, and a note can be raised as an issue that stays
open until someone resolves it. They are a **universal** feature —
available in standard annotation, [solo mode](../solo-mode/solo_mode.md), and QDA mode
— useful for flagging ambiguous cases, recording rationale, and building
an audit trail.

## Overview

- Each memo belongs to its author and is attached to one instance.
- A memo can be **instance-level**, anchored to a **text selection**
  (character offsets, shown with a `quote` badge), or anchored to a **drawn
  shape** (shown with the shape's label, for example `car box`).
- Notes form **threads**: replies sit under the note they answer.
- A note can be an **issue**, open or resolved, optionally assigned to
  someone.
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
  Deleting a thread's first note deletes its replies.
- A reply takes its thread's visibility, and follows it if the first note's
  visibility changes: anyone who can read the first note can read and reply
  to the whole thread.

## Threads and issues

| Action | Who may do it |
|---|---|
| Reply | Anyone who can read the thread |
| Resolve or reopen an issue | The issue's author, its assignee, or an adjudicator |
| Assign an issue | The issue's author or an adjudicator |

Assigning an issue lets the assignee read and reply to its thread, even when
it is private, so they can work on it; clearing the assignment takes that
back. For a memo you cannot read, every action answers 404, the same as for
a memo that does not exist.

An issue records who resolved it and when. The admin dashboard's overview
shows how many issues are open and how many are resolved, and
`GET /admin/api/memo_issues?status=open` lists them, private ones included.

### Issues assigned to you

The Notes tab counts the open issues assigned to you on any item, for example
`Notes · 2 assigned to you`, so an assignment shows even with the panel
closed. The panel lists them at the top. An issue on an item in your own queue
has a **Go to item** link; one on an item you are not assigned says so. The
links are left out when `jumping_to_id_disabled` is set.

To hear about assignments outside Potato, subscribe a
[webhook](../integrations/webhooks.md) to `memo.issue_assigned`. It fires when
an issue gets an assignee, when it is raised or later, and carries the memo
id, the item id, the assignee, who assigned it and the status. The note's text
is not sent, because an issue can be private.

### Issues on an image region

Select a shape on an image annotation canvas, then open the Notes panel: the
composer offers **Attach to the selected shape**. Clicking the shape's badge
on the note selects that shape on the canvas again.

Shapes have no stored id, so the note records the shape as it was drawn (its
scheme, type, label and normalised coordinates) and finds it again by
position. If the shape has since been moved or deleted, the panel says so.

> **Bias caution.** Setting memos to `shared` lets annotators read each
> other's notes during labeling, which can anchor judgments and inflate
> apparent agreement. For inter-annotator-agreement studies, prefer
> `private` (the default). Use `shared` for collaborative qualitative
> coding where shared context is desirable.

## Using the sidebar

1. Click the **Notes** toggle on the right edge of the annotation page.
2. Type a note. Optionally select text in the instance first and tick
   "Attach to selected text", or select a shape on the image and tick
   "Attach to the selected shape".
3. Tick **Raise as an issue to resolve** to make it an issue, and optionally
   name who should resolve it.
4. Choose a visibility and click **Add note**.
5. Each note shows the actions you may take: **Reply** on every thread,
   **Resolve** / **Reopen** and **Assign** on issues where you are allowed,
   and **Edit** / **Delete** on your own notes.

## API

| Request | Does |
|---|---|
| `GET /api/memos?instance_id=…` | Notes and replies on an instance, each with `can_edit`, `can_delete`, `can_resolve` and `can_assign` for you |
| `POST /api/memos` | A note: `instance_id`, `body`, `visibility`, `anchor`, and `issue: true` with an optional `assignee` |
| `POST /api/memos/<id>/reply` | A reply: `body` |
| `PATCH /api/memos/<id>` | Any of `body`, `visibility`, `status` (`open` or `resolved`), `assignee` (empty to clear) |
| `GET /api/memos/issues?status=open&assignee=me` | Issues across the project that you can see. Each issue on an item in your queue has `position`, its 0-based place there |

## Exporting memos

The [`quotation_report`](../data-export/export_formats.md) exporter can include
memos for audit trails and qualitative deliverables:

```bash
python -m potato.export --config config.yaml \
  --format quotation_report --output ./out/ \
  --option include_memos=true
```

Memo rows appear with `schema` set to `(memo)`, `(memo reply)`, or
`(issue: open)` / `(issue: resolved)`, `code = <visibility>` (a reply
reports its thread's), `text = <memo body>`, and offsets from the memo anchor
when span-anchored.

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
