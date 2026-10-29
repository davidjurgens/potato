# Interlinear Glossed Text

An `interlinear_gloss` scheme shows a sentence as one column per word. Each
column has the word (read-only), its morpheme segmentation, and its gloss, and
the free translation goes on a line under the columns. Use it for language
documentation, typological data, or checking glosses imported from FLEx or
Toolbox. On a narrow screen the columns wrap onto further lines, as a long
example does in print.

The page checks each word against the Leipzig Glossing Rules (Comrie,
Haspelmath & Bickel) while the annotator types. See
[Linguistic fieldwork](../../guides/linguistic-fieldwork.md) for the FLEx and
Toolbox round trip and a summary of the conventions.

## Configuration

```yaml
annotation_schemes:
  - annotation_type: interlinear_gloss
    name: igt
    description: Segment each word into morphemes and gloss every morpheme
    source_field: text            # sentence string, or a list of words
    morphemes_field: morphemes    # optional pre-filled segmentation
    gloss_field: glosses          # optional pre-filled glosses
    translation_field: translation
    tiers: [pos, notes]           # optional extra lines per word
    abbreviations: leipzig        # warn on unknown category labels
    language: la                  # BCP 47 tag of the object language
    metalanguage: en              # language of the glosses and translation
    label_requirement:
      required: true
```

A matching data row:

```json
{"id": "latin_1", "text": "Puella rosam amat.",
 "morphemes": ["puell-a", "ros-am", "ama-t"],
 "glosses": ["girl-NOM.SG", "rose-ACC.SG", "love-3SG"],
 "translation": "The girl loves the rose.",
 "pos": ["n", "n", "v"]}
```

When `source_field` holds a string, it is split on spaces and punctuation at
the edges of each word (`.` `,` `?` quotes and brackets) is dropped. Hyphens
and `=` inside a word are kept. To control the words exactly, give a list.

The pre-fill fields take a list with one entry per word, or a string with one
space-separated entry per word. A configured tier is pre-filled from an item
field with the same name when that field is a list. A word with no pre-filled
segmentation starts with the word itself in the segmentation cell, so the
annotator only types the boundaries.

## Options

| Key | Default | Meaning |
|---|---|---|
| `source_field` | `text` | Item field with the sentence (string) or the words (list) |
| `morphemes_field` | none | Item field with a segmentation per word |
| `gloss_field` | none | Item field with a gloss per word |
| `translation_field` | none | Item field with the free translation |
| `tiers` | `[]` | Extra lines per word, such as `[pos, notes]`. `word`, `morphemes` and `gloss` are reserved |
| `abbreviations` | none | `leipzig` for the standard list, a list of labels, or a mapping of label to meaning. Put `leipzig` in a list to add your own labels to the standard ones. Without it, labels are not checked |
| `language` | none | Language tag set on the word and segmentation cells (`lang` attribute), and written to FLExText |
| `metalanguage` | none | Language tag for the gloss, tier and translation cells |
| `show_translation` | `true` | Show the free translation line |
| `instructions` | none | Text shown under the question |
| `label_requirement` | none | `required: true` blocks Next until every word is segmented, glossed and aligned |

## Alignment and label checks

For each word, the segmentation and the gloss must have the same `-` (affix)
and `=` (clitic) boundaries in the same order. `ros-am` with `rose-ACC.SG` is
aligned; `rose-ACC-SG` has one boundary too many. `vir-um=que` with
`man-ACC.SG-and` has the right number of boundaries but glosses the clitic
`=que` as an affix, and is also marked.

A word is marked misaligned, with the reason under its column, when:

- the boundaries differ in number, kind or order;
- a morpheme or a gloss between two boundaries is empty (`ev--ler`, `house-`);
- a cell contains a space. Join the words of one gloss with `.`
  (`put.in.bag`), and separate morphemes with `-` or `=`.

Infixes in angle brackets (`s<um>ulat`) are counted in both lines but not
paired by position, because the infix's gloss sits beside the stem's gloss
rather than inside it.

A misaligned word has a red border, a `≠` before the word, and
`aria-invalid` on both cells. A word with only one of the two lines filled is
shown as not yet glossed. The count at the top of the widget says how many
words are misaligned. When the scheme is required, either state blocks Next.

Grammatical category labels (words in capitals and person numbers: `ACC`,
`3SG`) are shown under the gloss cell in small caps. With `abbreviations`
set, labels not in the list appear as a warning under the word, such as
"Unknown label: EVID". The warning does not block Next. The check accepts
person and number written together (`3SG`), the `N-` prefix for "non-"
(`NSG`, `NPST`), and `Ø`.

## Keyboard

| Key | Action |
|---|---|
| Tab / Shift+Tab | Next / previous cell: down a word's lines, then on to the next word |
| Enter | Same line of the next word; from the last word, the translation |
| Shift+Enter | Same line of the previous word |

## Stored answer

One hidden input holds the answer as JSON:

```json
{"words": [{"word": "Puella", "morphemes": "puell-a", "gloss": "girl-NOM.SG",
            "pos": "n", "notes": ""}, ...],
 "translation": "The girl loves the rose."}
```

An item that came with a pre-filled analysis is saved when the annotator
presses Next, even if nothing was edited, so a confirmed import is stored as
that person's answer. An item with no pre-fill is stored once the annotator
types in it.

## Export

| Format | Files | Content |
|---|---|---|
| `flextext` | `<user>.flextext` | FieldWorks interlinear XML, one file per annotator |
| `toolbox` | `<user>.txt` | Toolbox standard format with column-aligned `\tx \mb \ge \ps \ft` lines |
| `igt` | `igt.txt`, `igt.tex` | Aligned plain text (words, segmentation, gloss, translation) and gb4e LaTeX |

```bash
python -m potato.export --config config.yaml --format igt --output out/
```

`igt.tex` holds one `exe` environment with an `\ex` per stored answer, the
segmentation and gloss on a `\gll` line, and the translation on `\glt`.
Category labels are written as `\textsc{...}` in lower case, and LaTeX's
special characters are escaped. Load `gb4e` in the preamble. For scripts
other than Latin, compile with XeLaTeX or LuaLaTeX.

Words that are still misaligned are exported as stored, and the export prints
how many there were. In FLExText and Toolbox, which pair glosses with
morphemes one to one, a misaligned word's whole gloss goes on its first
morpheme.

## Agreement

`/admin/iaa` scores each line of the analysis separately, with Krippendorff's
alpha (nominal) and the pairwise percentage of agreement:

| Group | Unit | Compared |
|---|---|---|
| `segmentation` | one word | the morpheme line |
| `gloss` | one word | the whole gloss |
| `morpheme_gloss` | one morpheme | each morpheme's gloss, on words every annotator segmented the same way |
| `tier_<name>` | one word | each tier in `tiers` |

Two cells agree when their text is identical after trimming. An empty cell
counts as unanswered, so two annotators who both left a word blank do not
agree on it. `morpheme_gloss` leaves out words segmented two ways, because
their morphemes do not line up and comparing them by position would count a
segmentation difference as a gloss difference. The free translation is not
scored.

`/admin/api/agreement` does not score this type and points to `/admin/iaa`.

## Example

```bash
python potato/flask_server.py start examples/span/interlinear-gloss/config.yaml -p 8000
```

Four Latin sentences glossed for illustration. One is complete, one is blank,
one has a segmentation and no glosses, and one has a deliberate error (the
clitic `-que` glossed with `-`).

## Troubleshooting

- **"This item has no words to gloss"**: the item has no value under
  `source_field`, or it is empty. The default field is `text`.
- **Every word shows "no gloss yet"**: `gloss_field` names a field the items
  do not have, or the list is shorter than the word list.
- **The pre-fill lands on the wrong words**: a string pre-fill is split on
  spaces, so it needs exactly one entry per word. Use lists.
- **A label you use is flagged as unknown**: add it, as in
  `abbreviations: [leipzig, EVID, AOR]`.

## Related

- [Linguistic fieldwork: FLEx and Toolbox](../../guides/linguistic-fieldwork.md)
- [Text edit](text_edit.md)
- [Export formats](../../data-export/export_formats.md)
