# Codebook

A **codebook** is a project's mutable, optionally nested set of codes
(labels). It is a **universal** feature — available in standard
annotation, [solo mode](../solo-mode/solo_mode.md), and QDA mode. Opt a
scheme in with `codebook: true` and its labels come from the codebook
instead of being static YAML, so codes can be added, renamed, recolored,
moved, and deleted without editing the config.

## Overview

- Codes live in the universal project database
  (`<task_dir>/project.sqlite`), not the YAML config.
- A scheme with `codebook: true` is **seeded once** from its YAML
  `labels`; thereafter the database is the source of truth.
- Codes can be nested (a code may have a parent), forming a tree.
- Every mutation is audited (`created_by` records the human username or
  the model id, so human + LLM edits in solo mode share one trail).
- All writes go through one service path; the ICL prompt set is kept in
  sync with the current codebook automatically.

## Configuration

```yaml
codebook_mode: open          # fixed | extensible | open

annotation_schemes:
- annotation_type: multiselect
  name: themes
  description: Which themes appear?
  codebook: true             # this scheme's labels come from the codebook
  labels: [access barriers, cost concerns]   # seeds the codebook once
```

| Option | Default | Description |
|--------|---------|-------------|
| `codebook_mode` (or `codebook.mode`) | `open` under qda/solo; `fixed` in standard mode | Governs annotator edit rights (see below). |
| `annotation_schemes[].codebook` | `false` | Opt this scheme into codebook-sourced labels. |

A **crowdsourcing backend force-locks `fixed`** regardless of the
requested mode — paid annotators must not reshape the shared codebook.

### Modes

| Mode | Annotators may… | Typical use |
|------|-----------------|-------------|
| `fixed` | nothing (config/CLI only) | controlled studies, crowd work |
| `extensible` | **add** codes | grounded coding with a fixed core |
| `open` | add / rename / recolor / move / delete | solo & QDA exploratory coding |

Adjudicators are privileged and may edit in any non-`fixed` mode.

## The Codebook tray

When a codebook is enabled, a **Codebook** toggle appears on the right
edge of the annotation page (below Notes). It lists the codes and, when
`codebook_mode` is `extensible`/`open`, shows an "Add a code…" composer.
New codes appear immediately; reload the page to pick them up as form
labels in the annotation scheme.

## Initialising / migrating from the CLI

```bash
potato codebook path/to/config.yaml          # seed missing codes
potato codebook path/to/config.yaml --dry-run
```

Code ids are **deterministic** (`uuid5` over project + parent + name),
so re-running is a no-op and the same config yields the same ids across
machines — important because annotations carry a parallel `code_id`.

## API

`/api/codebook` (universal; requires an authenticated session):

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/codebook` | tree + flat labels + `can_add`/`can_edit` |
| POST | `/api/codebook` | add a code (`extensible`/`open`) |
| PATCH | `/api/codebook/<id>` | rename / recolor / move (`open`) |
| DELETE | `/api/codebook/<id>` | delete a code + subtree (`open`) |

`/qda/codebook` is the QDA-scoped read view (returns `503` when QDA Mode
is not enabled).

## Example

A runnable example is in
[`examples/advanced/codebook-example/`](../../examples/advanced/codebook-example/):

```bash
python potato/flask_server.py start \
  examples/advanced/codebook-example/config.yaml -p 8000
```

## Related

- [Memos](memos.md) — universal annotator notes
- [Search](search.md) — universal FTS5 search
- [Cases](cases.md) — group instances into units of analysis
