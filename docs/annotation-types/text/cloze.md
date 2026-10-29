# Cloze (Fill in the Blank)

A `cloze` scheme shows a passage with blanks the annotator types into. Use it
for cloze and C-tests of language proficiency, comprehension checks,
predictability norming, or checking what a reader recalls from an item.

The answer key stays on the server. It is used to score the export and is
never sent to the browser.

## One passage

```yaml
annotation_schemes:
  - annotation_type: cloze
    name: proficiency
    description: Fill in each blank with one word.
    text: "The library opens at nine and [[closes|shuts]] at six."
    scoring: case_insensitive
    label_requirement:
      required: true
```

Each `[[...]]` is a blank. The text inside is the accepted answer; separate
alternatives with `|`. `[[]]` is a blank with no key, which is recorded but
not scored.

A fixed passage suits a survey page, such as a proficiency screener in the
prestudy phase.

## A passage per item

```yaml
annotation_schemes:
  - annotation_type: cloze
    name: completion
    description: Fill in each blank with one word.
    source_field: passage
    answer_field: answers
```

```json
{"id": "p1", "text": "Passage 1",
 "passage": "Rain is expected [[]] the afternoon, so bring an [[]].",
 "answers": [["in", "during"], "umbrella"]}
```

`source_field` names the item field with the passage, blanks written as
`[[]]`. `answer_field` names a field holding a list with one entry per blank,
each a string (with `|` between alternatives) or a list. For a one-blank item
a plain string works too. Entries beyond the number of blanks are ignored,
with a warning in the server log. The answer field is removed from the page
and from the item APIs, and text typed inside `[[...]]` in an item passage is
blanked before the item reaches the page, so a key put there by mistake is
not shown either.

## Options

| Key | Default | Meaning |
|---|---|---|
| `text` | | One passage for every item. Use this or `source_field` |
| `source_field` | | Item field holding each item's passage |
| `answer_field` | | Item field holding each item's key (with `source_field` only) |
| `scoring` | `case_insensitive` | `exact`, `case_insensitive`, `normalized` (also ignores accents and punctuation), `numeric`, or `latex` (see [Math answers](#math-answers)) |
| `tolerance` | `0` | Largest absolute difference that still counts as correct, with `numeric` or `latex` scoring |
| `input_width` | `10` | Width of each blank, in characters |
| `label_requirement` | | `required: true` requires text in every blank, checked on the page and on the server |

## Data

Each blank is stored as a label of the scheme, `blank_1`, `blank_2`, ..., with
the typed text as its value. The CSV/TSV export adds, for each keyed blank,
`<scheme>.blank_<n>_correct` (1 or 0), and `<scheme>.score` and
`<scheme>.scored_blanks` for the item. A passage left blank scores 0.

Cloze answers on survey pages are exported with the other phase answers
(`export_include_phase_data: true`) and are not scored there.

## Math answers

`normalized` removes punctuation, so `-0.5` and `0.5` both become `05`. Use one
of the math modes for numbers and formulas:

- `numeric` compares values exactly. `0.5`, `1/2`, `\frac{1}{2}`,
  `\dfrac{1}{2}`, `$\tfrac12$`, `5e-1` and `.5` all match a key of `1/2`.
  Thousands separators (`1,000`) and the Unicode minus sign are accepted.
  `tolerance: 0.001` accepts `3.1416` for a key of `3.14159`. A key that is not
  a number (`x=2`) is compared with the `latex` rule instead.
- `latex` compares the LaTeX text after removing `$`/`\(`/`\[` delimiters,
  whitespace, spacing commands (`\,`, `\;`, `\quad`, ...) and
  `\left`/`\right`, and reading `\dfrac`/`\tfrac` as `\frac`. Two answers
  that are both numbers are compared by value.

Neither mode does algebra: `2x` does not match `x+x`, and `\sqrt{4}` does not
match `2`. List each accepted form, separated by `|`. A number needs one form
(`[[1/2]]` also accepts `0.5`); an equation needs every order you accept
(`[[x=2|2=x]]`).

```yaml
- annotation_type: cloze
  name: final_answer
  description: Enter the final answer.
  source_field: answer_prompt     # "The value of $S$ is [[]]."
  answer_field: answer_key        # "1/2"; never sent to the browser
  scoring: numeric
  tolerance: 0.0005
```

With [math rendering](math.md) on, math in the passage is rendered.

## Example

```bash
python potato/flask_server.py start examples/classification/cloze-test/config.yaml -p 8000
```

## Related

- [Text annotation](text_annotation.md)
- [Math rendering and grading](math.md)
- [Text edit](text_edit.md)
- [Multi-phase workflows](../../workflow/surveyflow.md)
- [Coming from jsPsych](../../guides/coming-from-jspsych.md)
