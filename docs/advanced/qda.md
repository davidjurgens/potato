# QDA Mode

**QDA Mode** turns Potato into a qualitative data analysis workspace. It
composes Potato's universal qualitative-coding features — the
[codebook](codebook.md), [memos](memos.md), [cases](cases.md), and
full-text [search](search.md) — into one coherent, single-coder
workflow tuned for reading and coding a whole corpus (interview
transcripts, open-ended survey responses, field notes, documents).

Each of those features also works on its own in standard annotation and
in [solo mode](../solo-mode/solo_mode.md). QDA Mode is the switch that
turns them on together with sensible defaults, so you don't have to wire
each one up by hand.

## What "QDA Mode" changes

Setting `qda_mode.enabled: true` is a single-coder posture (one analyst
over the entire corpus, no inter-annotator sampling to protect). On that
basis it flips the universal features to their qualitative defaults:

| Feature | Standard default | Under `qda_mode.enabled: true` |
|---------|------------------|--------------------------------|
| [Codebook](codebook.md) mode | `fixed` | **`open`** — add / rename / recolor / move / delete codes while coding (opt a scheme in with `codebook: true`) |
| [Memos](memos.md) sidebar | off | **on** (unless `annotation_ui.memos: false`) |
| [Cases](cases.md) | off | **on** + auto-detect (unless `cases.enabled: false`) |
| Admin [search](search.md) | on (universal) | on |
| Annotator search-and-claim | off | allowed — opt in with `search.annotator_claim: true` |
| In-vivo coding key | `i` | `i` (active for any `span` + `codebook: true` scheme) |

A **crowdsourcing backend force-locks the codebook to `fixed`** even
under QDA Mode — paid annotators must not reshape the shared codebook.

Every default above can be overridden explicitly; QDA Mode only changes
the *starting point*.

## Quick start

```yaml
annotation_task_name: My Qualitative Study
task_dir: .
output_annotation_dir: annotation_output/
data_files:
- data/interviews.json
item_properties:
  id_key: id
  text_key: text

qda_mode:
  enabled: true            # compose codebook + memos + cases + search

codebook_invivo_key: i     # mint a code from a text selection (span schemes)

cases:                     # group excerpts into units of analysis
  enabled: true
  key: participant_id
  attributes: [condition]

search:                    # let the coder jump to any matching excerpt
  enabled: true
  annotator_claim: true

annotation_schemes:
- annotation_type: span    # span + codebook = in-vivo coding
  name: codes
  description: Highlight a passage and apply (or mint, via `i`) a code
  codebook: true
  labels: [access barriers, cost concerns, provider trust]
```

The `cases`, `search`, and `annotation_ui.memos` blocks are optional —
QDA Mode already turns cases and memos on. Write them only to tune the
defaults (e.g. choose the `cases.key`, or enable `annotator_claim`).

A complete runnable example lives in
[`examples/advanced/qda-mode-example/`](../../examples/advanced/qda-mode-example/):

```bash
python potato/flask_server.py start \
  examples/advanced/qda-mode-example/config.yaml -p 8000
```

## Configuration

```yaml
qda_mode:
  enabled: true
  memos:
    enabled: true                 # QDA-Mode memo defaults
    show_sidebar_by_default: true
  codebook:
    enabled: true
    mode: open                    # open | extensible | fixed
```

| Option | Default | Description |
|--------|---------|-------------|
| `qda_mode.enabled` | `false` | Master switch. Initialises QDA Mode and applies the qualitative defaults above. |
| `qda_mode.memos.enabled` | `true` | QDA-Mode memo default. (Memo storage is universal — see [Memos](memos.md).) |
| `qda_mode.memos.show_sidebar_by_default` | `true` | Whether the Notes sidebar starts open. |
| `qda_mode.codebook.enabled` | `true` | Whether the codebook is active. |
| `qda_mode.codebook.mode` | `open` | Annotator edit rights — `open` / `extensible` / `fixed` (see [Codebook modes](codebook.md#modes)). Equivalent to top-level `codebook_mode`. |

Unknown `qda_mode.*` keys are preserved (not rejected) so you can write
forward-compatible YAML for features that land in later phases.

## Endpoints

QDA Mode mounts a small blueprint at `/qda` (it never collides with the
universal `/api/*` namespace):

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/qda/status` | Always `200`. Reports whether QDA Mode is enabled and the resolved memo/codebook config — use it to confirm the mode is wired correctly. |
| GET | `/qda/codebook` | QDA-scoped read view: the project codebook tree, flat labels, and cases. Returns `503` when QDA Mode is not enabled. |

The full codebook CRUD, memos, cases, and search APIs live in their own
universal namespaces — see the linked feature docs.

## How the pieces fit together

- **Codebook** is the shared, mutable set of codes. Opt a scheme into it
  with `codebook: true`; under QDA Mode you can grow and reorganise it
  while coding.
- **In-vivo coding** (a `span` scheme that is also `codebook: true`) lets
  you mint a code straight from a highlighted passage — press
  `codebook_invivo_key` (default `i`). The composer surfaces
  near-duplicate codes so you reuse instead of fragmenting.
- **Memos** capture analytic notes on an instance or a specific text
  selection, private to you or shared with the team.
- **Cases** group excerpts into units of analysis (a participant, a
  document) and lift case-level attributes (e.g. `condition`) so the
  admin **code crosstab** can tabulate codes by participant-level
  variables.
- **Search** (FTS5) lets you find any excerpt by text; with
  `annotator_claim: true` you can pull a match into your queue.

## Exporting your coding

Two exporters turn coded data into qualitative-research deliverables:

- **`codebook`** — one row per code (hierarchy, description, colour, use
  count).
- **`quotation_report`** — one row per coded span (the quote, its
  character offsets, instance, and coder); add `include_memos=true` to
  append memo rows too.

```bash
python -m potato.export config.yaml --format quotation_report \
  --option include_memos=true -o quotations.csv
```

See [Export formats](../data-export/export_formats.md) for the column
reference.

## Related

- [Codebook](codebook.md) — the mutable code set + in-vivo coding
- [Memos](memos.md) — analytic notes
- [Cases](cases.md) — units of analysis + attributes
- [Search](search.md) — FTS5 full-text search and claim
- [Solo mode](../solo-mode/solo_mode.md) — single-annotator deployments
