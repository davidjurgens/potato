# Linguistic Fieldwork: Glossing with FLEx and Toolbox

This guide covers checking and correcting interlinear glosses in Potato when
the analysis already lives in FieldWorks Language Explorer (FLEx) or Toolbox.
You import the texts, annotators review every sentence in an
[`interlinear_gloss`](../annotation-types/text/interlinear_gloss.md) scheme,
and you export the corrected glosses back to the same format.

## Import

```bash
# A FLEx interlinear export (FLExText)
potato import -i stories.flextext -o glossing-project/

# A Toolbox or Shoebox text database
potato import -i texts.txt -f toolbox -o glossing-project/
```

`-i` can also be a directory of `.flextext` files, or of Toolbox files
(`.txt`, `.sfm`, `.db`, `.tbx`, `.toolbox`). The format is detected from the
content: a FLExText file has `<interlinear-text>` elements, and a Toolbox
file has `\ref` records with a text line and a morpheme or gloss line. Pass
`-f flextext` or `-f toolbox` to choose explicitly.

A FLExText file that cannot be read is left out with the reason: it is
binary or not UTF-8 text, it is not well-formed XML (the parser's message
and line are shown), or it defines XML entities, which uploaded files may
not. If no file could be read, the error lists those reasons.

Each FLEx phrase or Toolbox record becomes one item. The existing analysis is
written into the item's own fields (`words`, `morphemes`, `glosses`,
`translation`, and `pos` when the source has parts of speech), and the
generated scheme reads them as its starting point. Nothing counts as a
person's answer until an annotator presses Next or edits the item, so an
export before review contains only the sentences someone has checked.

### FLExText fields read

| FLExText | Potato |
|---|---|
| `interlinear-text` title | `text_title` field, used again on export |
| `paragraph`, `phrase` `segnum` | `paragraph`, `phrase` fields |
| word `txt` | a word; `punct` words are kept in the sentence text but not glossed |
| morph `txt` (or `cf` when `txt` is missing) and `type` | the segmentation; `-` or `=` comes from the form's own marks, or from the type (`enclitic`, `proclitic` give `=`) |
| morph `gls` | the gloss of that morpheme; spaces become `.` |
| word `pos`, or the stem's `msa` | the `pos` tier |
| phrase `gls` | the free translation |
| vernacular and analysis `language` | the scheme's `language` and `metalanguage` |

### Toolbox records and markers

Records start at `\ref`. The interlinear lines are read by column, as Toolbox
writes them: a morpheme belongs to the word it starts under, and a gloss to the
morpheme it starts under. Hand-edited files are often not aligned, so two
readings by order are tried first. Morphemes are grouped into words by their
own marks (`-ler` and `=de` attach to the morpheme before, `un-` to the one
after) when that gives one group per word. Glosses are paired with morphemes
in order when there is one gloss per morpheme. Other markers in a record,
such as `\nt`, are kept in the item's `sfm_extra` field and written back on
export.

| Role | Markers read (first one a record uses) |
|---|---|
| record | `\ref` |
| text | `\tx`, `\t` |
| morphemes | `\mb`, `\m` |
| gloss | `\ge`, `\g` |
| part of speech | `\ps`, `\p` |
| free translation | `\ft`, `\f` |

Projects that use other marker names can set them when calling the importer
from Python:

```python
from pathlib import Path
from potato.importers import projects
from potato.importers.projects.writer import write_project

result = projects.IMPORTERS["toolbox"].parse_path(
    Path("texts.txt"), {"markers": {"gloss": "gle", "translation": ["fte", "ft"]}})
write_project(result, "glossing-project", source="texts.txt")
```

`potato import` itself uses the markers in the table.

## Review

```bash
python potato/flask_server.py start glossing-project/config.yaml -p 8000
```

Annotators see each sentence with the imported analysis in place. Any word
whose segmentation and gloss do not line up is marked when the page opens,
so errors already in the source are visible on the first review. See the
[scheme page](../annotation-types/text/interlinear_gloss.md) for what is
checked and the keyboard controls.

## Export

```bash
python -m potato.export --config glossing-project/config.yaml --format flextext --output out/
python -m potato.export --config glossing-project/config.yaml --format toolbox --output out/
python -m potato.export --config glossing-project/config.yaml --format igt --output out/
```

- `flextext` writes `<annotator>.flextext`, one per annotator, grouped into
  the texts and paragraphs the import recorded. Morph types are worked out
  from the boundaries: the first morpheme with a lowercase (lexical) gloss is
  the stem, morphemes before it are prefixes or proclitics, and those after
  it suffixes or enclitics.
- `toolbox` writes `<annotator>.txt` with column-aligned lines and the
  original `\ref` values.
- `igt` writes `igt.txt` (three aligned lines and the translation per
  example) and `igt.tex` for the gb4e LaTeX package.

Re-importing an exported file gives the same words, segmentations, glosses,
translations and parts of speech. What does not survive the trip:

- FLEx GUIDs and lexicon links. The export has no lexicon.
- FLEx punctuation words. They stay in the item's sentence text but are not
  written back as `punct` words.
- The morph type of a morpheme that is neither the stem nor next to a marked
  boundary, such as a second root in a compound.
- Tiers other than `pos` in FLExText. In Toolbox they are written as extra
  lines named after the tier. A tier whose values are single words stays
  aligned with the words, as written. An aligned line separates its cells
  with spaces, so a tier with a value of several words is written in full
  instead, one `\tier word: value` line per word, and comes back in
  `sfm_extra` rather than as a tier. A line break inside a value becomes a
  space, because a line that starts with a backslash begins a new field.

## Leipzig conventions

The checks follow the Leipzig Glossing Rules by Bernard Comrie, Martin
Haspelmath and Balthasar Bickel
(<https://www.eva.mpg.de/lingua/resources/glossing-rules.php>). The points
that matter for this scheme:

- The example line and the gloss line are aligned word by word, left-aligned
  in columns.
- Within a word, `-` separates affixes and `=` separates clitics. The gloss
  has the same separators in the same places, so morpheme and gloss can be
  paired by counting.
- When one morpheme stands for several meanings (case and number together,
  or a multi-word English gloss), join them with a period: `NOM.SG`,
  `put.in.bag`. A period is not a boundary and is not counted.
- Person and number may be written together without a period: `3SG`.
- Grammatical categories are written as abbreviations in capitals and printed
  in small caps. The rules list standard abbreviations (`ACC`, `ERG`, `PL`,
  `PST`, and so on); add any others a project uses to its own list.
- An infix is set off with angle brackets in both lines, and its gloss goes
  next to the stem's gloss rather than in the same position.
- The free translation goes on its own line in quotation marks.

## Related

- [Interlinear gloss scheme](../annotation-types/text/interlinear_gloss.md)
- [Migrating into Potato](migrating-into-potato.md)
- [Working with transcripts](working_with_transcripts.md)
