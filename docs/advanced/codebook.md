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

### Add a code while coding

A code added from the tray is **usable immediately** on the current
instance — it is appended to the codebook-backed scheme's options
in place, no reload required. Because the annotation form template is
built once at server start, the tray re-applies any missing codes to
the form on every page load (it polls a lightweight
`/api/codebook/version` and only re-downloads the full codebook when
the revision moved), so codes added mid-session keep working across
navigation and their selections are restored.

### In-vivo coding (code from a selection)

For a scheme that is both `annotation_type: span` **and**
`codebook: true`, you can mint a code straight from the text:

1. Select the passage in the instance.
2. Press the in-vivo key (`codebook_invivo_key`, default `i`).
3. A small composer opens, pre-filled with a code name derived from
   the selection. Edit it if you like, then **Create & code**.

The code is created through the same audited path as the tray, added
to the scheme's label palette in place, and a span with that code is
laid over your selection — no reload, no losing the selection.

**Soft suggest-on-create.** As you type the name, closely matching
existing codes surface as one-click chips ("Similar existing code —
reuse instead?"). Picking one reuses that code instead of creating a
near-duplicate; the primary button then reads **Apply code**. Nothing
is blocked or silently merged — the choice is always yours. This keeps
a fast in-vivo workflow from fragmenting the codebook into
`cost` / `costs` / `cost concerns`.

| Option | Default | Description |
|--------|---------|-------------|
| `codebook_invivo_key` | `i` | Single key that opens the in-vivo composer when text is selected in a codebook-backed span scheme. Only meaningful when such a scheme exists. |

### Revision provenance & the review worklist

Every codebook change (add / rename / recolor / move / delete) bumps a
per-project `codebook_revision`, and every saved annotation is stamped
with the revision in effect. When you revisit an instance you labeled
under an older revision, a dismissible banner notes what changed
("*N codes added since you labeled this: …*", or a generic message for
non-additive changes). The tray's **Review** worklist lists exactly the
instances you labeled before later changes — only genuinely affected
instances are surfaced (an instance is listed only if its stamped
revision precedes the change) — each with a **Go** button to jump
straight there. Nothing is force-reopened; reviewing is optional.

Admins/adjudicators can see the project-wide stale set via
`GET /api/codebook/admin/stale`.

### Retroactive curation (merge / split) — admin only

A long-lived codebook accretes near-duplicate or mis-scoped codes
(more so once on-the-fly and in-vivo coding are in use). Admins and
adjudicators get a **Curate** section in the tray to fix this
**retroactively without destroying history**:

- **Merge** folds one code into another: every existing annotation
  linked to the source is re-pointed at the target (idempotent if the
  annotation already had the target), the source's links are
  *invalidated* (never deleted), and the source code is **archived**
  (it leaves the label list / ICL prompt but its row and history
  survive).
- **Split by annotator** moves just one annotator's links from a code
  to a new or existing code — the concrete fix when two coders meant
  different things by the same name. The source stays live for the
  other annotators.

Both are **append-only**: historical links are marked superseded, not
removed, so the change is fully auditable and the codebook can never
silently lose data. Affected instances are softly re-flagged so they
resurface in each annotator's **Review** worklist (dismissible, never a
hard re-label gate — same policy as ordinary revision changes).

Authorship/provenance lives in a **separate change log**, never on the
code records (those feed the ICL prompt verbatim). The collapsed
**Recent changes** list in the Curate section is the human-readable
before→after delta.

### LLM-proposed edits (propose → human confirm)

A model (e.g. in solo mode) must **not** mutate a shared codebook
autonomously. Instead it *proposes*: a queued, pending edit an admin
reviews as a plain sentence ("Merge «cost» into «cost concerns»") and
**Confirms** or **Rejects**. Confirmed proposals execute through the
same audited path as a human edit and are tagged in the change log as
model-originated; rejected ones change nothing. Producers (HTTP agents
or in-process callers) stage a proposal via
`POST /api/codebook/proposals` with `actor_kind: "model"`, or the
in-process helper `potato.codebook.propose_change(...)`. Queuing needs
no admin rights (nothing changes until confirmed); confirming/rejecting
is admin/adjudicator only.

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
| GET | `/api/codebook` | tree + labels + `revision` + `schemes` + `can_add`/`can_edit` |
| GET | `/api/codebook/version` | just `{revision}` — the cheap navigation poll |
| GET | `/api/codebook/similar?name=` | near-duplicate existing codes for soft suggest-on-create |
| GET | `/api/codebook/provenance?instance_id=` | is this instance stale for me + codes added since |
| GET | `/api/codebook/stale` | my review worklist (stale instances + nav index) |
| GET | `/api/codebook/admin/stale` | project-wide stale set (admin/adjudicator) |
| POST | `/api/codebook` | add a code (`extensible`/`open`) |
| PATCH | `/api/codebook/<id>` | rename / recolor / move (`open`) |
| DELETE | `/api/codebook/<id>` | delete a code + subtree (`open`) |
| POST | `/api/codebook/admin/merge` | fold src into dst, append-only (admin) |
| POST | `/api/codebook/admin/split` | split a code by annotator (admin) |
| GET | `/api/codebook/admin/changes` | change log for the before→after delta (admin) |
| POST | `/api/codebook/proposals` | queue a model-proposed edit (`actor_kind:"model"`) |
| GET | `/api/codebook/admin/proposals` | pending proposals (admin) |
| POST | `/api/codebook/admin/proposals/<id>/confirm` | execute a proposal (admin) |
| POST | `/api/codebook/admin/proposals/<id>/reject` | discard a proposal (admin) |

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
