# Cases

A **case** groups instances that belong to the same unit of analysis —
an interview participant, a survey respondent, a document set. Cases are
a **universal** feature, with QDA mode auto-detecting them from the item
data. The code crosstab can then tabulate codes by case-level metadata
that does not live on each instance.

## Overview

- Cases, their attributes, and instance membership live in the universal
  project database (`<task_dir>/project.sqlite`).
- One instance belongs to at most one case.
- Auto-detection runs at server start and is idempotent.
- Case **attributes** (e.g. `condition`, `age`) are lifted from the item
  data so the crosstab can group codes by participant-level metadata.

## Configuration

```yaml
cases:
  enabled: true              # on by default under qda_mode
  key: participant_id        # item field to group on
  auto_detect: true          # scan the data at startup
  attributes:                # item fields to lift onto the case
  - condition
```

| Option | Default | Description |
|--------|---------|-------------|
| `cases.enabled` | off in standard mode; **on** when `qda_mode.enabled` | Enables cases + `/api/cases`. |
| `cases.key` | first present of `case_id`, `participant_id`, `respondent_id` | Item field whose value names the case. |
| `cases.auto_detect` | `true` | Group instances into cases at server start. |
| `cases.attributes` | `[]` | Item fields copied onto the case for crosstabs. |

When disabled the `/api/cases` endpoints return `503`.

## Crosstab integration

The admin **code crosstab** (`/admin/api/code_crosstab`) uses the
requested attribute from the instance data, and **falls back to the
case-level attribute** when the instance has no such field. This lets
you tabulate codes by participant-level variables (e.g. study
`condition`) even though that variable is recorded once per participant,
not on every excerpt.

## API

`/api/cases` (requires an authenticated session):

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/cases` | list cases with their attributes |
| GET | `/api/cases/instance/<id>` | the case (and attributes) for an instance |

## Example

A runnable example is in
[`examples/advanced/cases-example/`](../../examples/advanced/cases-example/):

```bash
python potato/flask_server.py start \
  examples/advanced/cases-example/config.yaml -p 8000
```

## Related

- [Codebook](codebook.md) — universal mutable code set
- [Memos](memos.md) — universal annotator notes
