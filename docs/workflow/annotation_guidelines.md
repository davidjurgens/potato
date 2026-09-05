# Guidelines and Codebooks

Most of the examples in this repo describe their task in the one-line
`description:` on each annotation scheme. That is all a three-label demo needs,
and it is nowhere near enough for a real study: a codebook that has been through
two rounds of adjudication has definitions, inclusion and exclusion criteria,
worked examples, already-settled edge cases, and a change log.

Potato gives you four places to put annotator-facing instructions. They differ
in **when the annotator reads them**, and a well-run task uses more than one.

| Surface | Config | Read |
|---|---|---|
| Instructions **phase** | `phases.<name>.type: instructions` + `file:` | Once, before the first item |
| Collapsible **banner** | `annotation_instructions` | On every annotation screen, foldable |
| **Codebook** button | `annotation_codebook_url` | On demand, in a new tab |
| **Codebook tray + `/codebook`** | `codebook: true` on a scheme | Per label, while deciding |

Working examples:
[`examples/advanced/long-guidelines/`](https://github.com/davidjurgens/potato/tree/master/examples/advanced/long-guidelines)
covers the first three;
[`examples/advanced/codebook-sidebar/`](https://github.com/davidjurgens/potato/tree/master/examples/advanced/codebook-sidebar)
covers the fourth.

---

## 1. An instructions phase

Give the `instructions` phase an `.html` file and it is rendered as-is — tables,
ordered lists, worked examples, whatever the task needs. The annotator scrolls.

```yaml
phases:
  order:
  - guidelines
  - annotation
  guidelines:
    type: instructions
    file: surveys/instructions.html
```

Point the same phase at a `.json` file instead and you get a *survey* rather
than a document — that is how the consent phase works. A survey page can still
carry long prose by way of a `pure_display` entry:

```json
[
  {
    "name": "consent_info",
    "annotation_type": "pure_display",
    "allow_html": true,
    "description": "Consent to participate",
    "labels": ["<p>You are invited to take part in ...</p>"]
  }
]
```

!!! warning "`allow_html: true` is not optional"
    Without it, `pure_display` **escapes** its content and the annotator reads
    your raw `<p>` and `<h4>` tags. This is the single most common mistake with
    survey pages.

## 2. The collapsible banner

`annotation_instructions` renders as a `<details>` element at the top of every
annotation screen, open by default. Annotators fold it away once the task is
familiar and reopen it when they hit something odd.

```yaml
annotation_instructions: |
  <p>Rate how the message lands <strong>on the person receiving it</strong>,
  not whether you would have written it that way.</p>
  <ul>
    <li><strong>Polite</strong> &mdash; the writer visibly softens the ask.</li>
    <li><strong>Neutral</strong> &mdash; plain business, nothing that stings.</li>
    <li><strong>Impolite</strong> &mdash; sarcasm, blame, a pointed reminder.</li>
  </ul>
```

Keep this shorter than the phase page: it is the reminder, not the teaching
material. Good content here is the two or three rules that decide most items.

Markdown works too, and is usually less typing:

```yaml
annotation_instructions: |
  Rate how the message lands **on the person receiving it**, not whether you
  would have written it that way.

  - **Polite** — the writer visibly softens the ask.
  - **Neutral** — plain business, nothing that stings.
  - **Impolite** — sarcasm, blame, a pointed reminder.
```

Instructions that already contain block-level HTML are used as written; markdown
is rendered otherwise. So an existing config keeps rendering exactly as it did,
and you can mix inline HTML into markdown but not the other way around.

Either way the result passes through the project sanitizer — formatting
survives, `<script>` and event handlers do not, and character entities such as
`&mdash;` render correctly.

## 3. The Codebook button

`annotation_codebook_url` puts a **Codebook** button in the nav bar that opens
any URL in a new tab.

```yaml
media_directory: media
annotation_codebook_url: /media/codebook.html
```

A Google Doc, a wiki page or a PDF all work. Serving it from the project's own
`media/` directory (files under it are served at `/media/<path>`) means the
codebook is versioned alongside the config — which is the point of treating
annotation as a reproducible process rather than a folder of labels.

## 4. The codebook tray and `/codebook`

When your reference material is organized **per label** rather than as prose,
put it in the codebook. Any scheme with `codebook: true` sources its labels from
the project codebook and turns on two surfaces:

- the **tray**, a button on the right edge of the annotation screen that lists
  every code and links to the full document;
- the **`/codebook` page**, which renders each code's complete entry.

```yaml
codebook_mode: fixed        # read-only reference

annotation_schemes:
- annotation_type: radio
  name: politeness
  description: How polite is this workplace message?
  codebook: true
  labels: [Polite, Neutral, Impolite]
```

`codebook_mode` governs who may change it:

| Mode | Annotators may |
|---|---|
| `fixed` | nothing — consult only. Mutation endpoints return 403 |
| `extensible` | add codes, not restructure |
| `open` | add, rename, recolor, move, delete; the tray gains an inline editor |

QDA and solo mode default to `open`; a crowdsourcing backend force-locks
`fixed`. See [Codebook](../advanced/codebook.md) and
[QDA mode](../advanced/qda.md).

!!! note "Under `fixed`, the tray is navigation, not a reader"
    The tray's per-code content view is the inline "quick definition" editor,
    which is gated on edit permission. A `fixed`-mode annotator therefore sees
    code **names** plus **Open full codebook**, and reads the entries on
    `/codebook`. That is usually what you want — but do not promise annotators
    that definitions appear in the tray itself.

### Writing the entries

A YAML `labels:` list carries only *names*, so a codebook seeded from one lists
bare labels with no definitions. The content lives in typed blocks, written
through the content API:

```python
from potato.codebook.content_service import save_scope

save_scope(task_dir, project=project, scope_kind="code", scope_id=code_id,
           base_version=version, actor="seed_codebook.py",
           blocks_in=[{"block_type": "definition", "body_md": "..."},
                      {"block_type": "use_when",   "body_md": "..."},
                      {"block_type": "avoid_when", "body_md": "..."}])
```

`examples/advanced/codebook-sidebar/seed_codebook.py` is a complete, idempotent
example. The available block types are defined in `potato/codebook/blocks.py`:

| Block | Heading |
|---|---|
| `short_def` | Short definition |
| `definition` | Definition |
| `use_when` | Use when |
| `avoid_when` | Avoid when |
| `example` | Examples |
| `counter_example` | Counter-examples |
| `rationale` | Rationale |
| `background` | Background |
| `downstream_usage` | Downstream usage |
| `keywords` | Keywords |
| `notes` | Notes |
| `custom` | (carries its own heading) |

The first four are **semantic**. Editing one bumps the codebook's semantic
revision and re-flags every instance already coded with that code, because a
changed definition means those labels were made under a different rule. That
re-flagging is the feature, not a nuisance: it is the difference between a
codebook that records what you decided and one that quietly rewrites history.

## Which to use

- **Long teaching material** → instructions phase.
- **The two or three rules that settle most items** → banner.
- **The authoritative document, with a version number** → codebook button.
- **Per-label definitions with inclusion/exclusion criteria** → codebook.

Using all four is normal. They are not alternatives; they are different reading
moments.

## Related

- [Multi-Phase Workflows](surveyflow.md)
- [Training Phase](training_phase.md)
- [Codebook](../advanced/codebook.md)
- [QDA Mode](../advanced/qda.md)
