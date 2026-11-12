# Long Guidelines

Most examples in this repo describe the task in the one-line `description:` on
each annotation scheme, which is all a three-label demo needs. A real codebook
does not fit there.

Potato gives you three separate places to put annotator-facing instructions.
They differ in **when the annotator reads them**, and a well-run task uses all
three:

| Surface | Config key | When it is read |
|---|---|---|
| Instructions **phase** | `phases.<name>.type: instructions` + `file:` | Once, before the first item |
| Collapsible **banner** | `annotation_instructions` | On every annotation screen, foldable |
| **Codebook** button | `annotation_codebook_url` | On demand, in a new tab |

## Run

```bash
python potato/flask_server.py start examples/advanced/long-guidelines/config.yaml -p 8000
```

Open http://localhost:8000, register/sign in, and you will land on the
guidelines page first.

## What to look at

1. **The guidelines page.** The first phase points at
   `surveys/instructions.html`, which is rendered as-is — tables, ordered
   lists, worked examples. Write as much as the task needs; the annotator
   scrolls. Point the same phase at a `.json` file instead and you get a survey
   rather than a document (that is how the consent phase works).

2. **The Instructions banner** at the top of the annotation screen. It is a
   `<details>` element, open by default; annotators fold it away once the task
   is familiar and reopen it when they hit something odd. Keep it to the rules
   that decide most items — it is the reminder, not the teaching material.

3. **The Codebook button** in the nav bar, which opens `media/codebook.html`
   in a new tab. This is the authoritative document: label definitions with
   inclusion and exclusion criteria, the rules that resolve disagreements,
   already-adjudicated edge cases, and a change log. Any URL works here — a
   Google Doc, a wiki page, a PDF — but shipping it in `media/` means the
   codebook is versioned with the config, which is the whole point of treating
   annotation as a reproducible process.

## Notes

- `annotation_instructions` HTML goes through the project sanitizer: formatting
  survives, `<script>` and event handlers do not. Character entities such as
  `&mdash;` render correctly.
- Files under `media/` are served at `/media/<path>`, resolved against
  `media_directory` relative to the config's directory.
- If your codebook is really a **per-label** reference — a definition, inclusion
  and exclusion criteria, and examples for each code — put it in the codebook
  sidebar instead, where it sits next to the labels themselves. See
  [`examples/advanced/codebook-sidebar/`](../codebook-sidebar/).

## Related

- [`examples/advanced/codebook-sidebar/`](../codebook-sidebar/) — per-label
  reference in a sidebar
- [`examples/advanced/codebook-example/`](../codebook-example/) — an
  annotator-editable codebook
- [`examples/advanced/all-phases-example/`](../all-phases-example/) — every
  phase type
