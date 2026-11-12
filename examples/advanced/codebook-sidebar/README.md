# Codebook Sidebar

A long, **per-label** codebook — definition, inclusion criteria, exclusion
criteria, worked examples, counter-examples — reachable from a sidebar on the
annotation screen, so an annotator can look up the code they are hesitating over
without hunting for a document.

This is the third way to give annotators instructions in Potato. The other two
are in [`examples/advanced/long-guidelines/`](../long-guidelines/): an
instructions **phase** (read once, up front) and the collapsible
`annotation_instructions` **banner** (a reminder on every screen). Use the
sidebar when the reference material is organized *by label* rather than as
prose.

## Run

```bash
# seed the codebook entries once, then start the server
python examples/advanced/codebook-sidebar/seed_codebook.py
python potato/flask_server.py start examples/advanced/codebook-sidebar/config.yaml -p 8000
```

Open http://localhost:8000, register/sign in, then click the **🏷 Codebook**
button on the right edge of the annotation screen.

## Two surfaces, and which does what

Be precise about this, because they are easy to conflate:

| Surface | What it is |
|---|---|
| The **tray** (🏷 Codebook, right edge of the annotation screen) | A navigation panel: every code, plus **Open full codebook** |
| The **`/codebook` page** | The reader: each code's full entry, with a revision counter |

Under `codebook_mode: fixed` the tray shows code **names only**. The tray's
per-code content view is the inline "quick definition" editor, and that is gated
on edit permission — so a fixed-mode annotator gets the list and the link, and
reads the entries on `/codebook`. Switch to `open` and the same rows gain an
inline editor.

## What to look at

- On `/codebook`, every label has a full entry: a one-line gloss, a definition,
  **Use when** and **Avoid when** criteria, an example and a counter-example,
  keywords, and — for Neutral — a note recording *why* the criterion is worded
  the way it is.
- `codebook_mode: fixed` makes the whole thing **read-only**. The "Add a code"
  composer and the rename/recolor/delete controls are hidden and the mutation
  endpoints return 403. That is what a codebook with an approved version number
  wants: annotators consult it, they do not edit it mid-study.
- Change `codebook_mode` to `extensible` (annotators may add codes) or `open`
  (annotators may restructure) to see the tray gain its editing affordances.
  [`examples/advanced/codebook-example/`](../codebook-example/) is the `open`
  case.
- The header shows `content rev N`, which increments on every semantic edit.
  Editing a `definition`, `use_when` or `avoid_when` block re-flags the instances
  already coded with that code — a changed definition means the earlier labels
  were made under a different rule.

## How the content gets there

`codebook: true` on a scheme sources its labels from the project codebook, and
seeds that codebook from the YAML `labels:` on first run. **A label list carries
only names** — so a codebook seeded that way lists three bare labels with no
definitions, which is not a codebook anyone would open twice.

The entries are typed content blocks, and `seed_codebook.py` writes them:

```python
save_scope(task_dir, project=project, scope_kind="code", scope_id=code_id,
           base_version=version, actor="seed_codebook.py",
           blocks_in=[{"block_type": "definition", "body_md": "..."},
                      {"block_type": "use_when",   "body_md": "..."},
                      {"block_type": "avoid_when", "body_md": "..."}])
```

The available block types are defined in `potato/codebook/blocks.py`:
`short_def`, `definition`, `use_when`, `avoid_when`, `example`,
`counter_example`, `rationale`, `background`, `downstream_usage`, `keywords`,
`notes`, and `custom`. The first four are *semantic*: editing one bumps the
codebook's semantic revision and re-flags the instances coded with it, because
a changed definition means earlier labels were made under a different rule.

The script is idempotent — re-run it after editing `ENTRIES`.

## Related

- [`examples/advanced/long-guidelines/`](../long-guidelines/) — instructions
  phase, collapsible banner, and an external codebook document
- [`examples/advanced/codebook-example/`](../codebook-example/) — annotator-editable codebook
- [`examples/advanced/codebook-invivo-example/`](../codebook-invivo-example/) — coding in vivo
- [`docs/advanced/codebook.md`](../../../docs/advanced/codebook.md)
