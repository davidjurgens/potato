# Math Rendering and Grading

Potato can render LaTeX math in item text with [KaTeX](https://katex.org)
(MIT licence, vendored, no network access needed). It is off by default, so a
project whose text contains dollar signs looks the same after an upgrade.

This page covers:

- turning rendering on and choosing delimiters,
- what is and is not rendered, and how span annotation interacts with it,
- grading typed math answers against a key,
- step-level grading of worked solutions and proofs.

## Turning it on

```yaml
math:
  enabled: true
```

That renders `$...$` and `\(...\)` inline, and `$$...$$` and `\[...\]` as
display math, in:

- the item text (`#text-content`) when the project has no `instance_display`
  and no text-selection scheme (see [Span annotation](#span-annotation)),
- every `instance_display` field that is not a span target: `text`, `html`,
  `dialogue`, `agent_trace`, `cot_trace` and the other text displays,
- the steps of [`process_reward`](../../agent-evaluation/process_supervision.md)
  and [`trajectory_eval`](../../agent-evaluation/trajectory_eval.md), including
  `thought` text,
- [cloze](cloze.md) passages.

Code (`<pre>`, `<code>`), form controls and buttons are never rendered. To keep
math source visible in some other element of a custom layout, put
`data-math="off"` on it.

## Options

| Key | Default | Meaning |
|---|---|---|
| `math.enabled` | `false` | Render math |
| `math.delimiters` | `["$$", "$", "\\(", "\\["]` | Which delimiters start math. Any subset of the four |
| `math.fields` | all fields | `instance_display` field keys to render. Span-target fields are skipped whether listed or not |
| `math.macros` | `{}` | Macros available in every expression, for example `{"\\R": "\\mathbb{R}"}` |

```yaml
math:
  enabled: true
  delimiters: ["$$", "\\(", "\\["]     # no single $: the data has prices in it
  fields: [problem, solution]
  macros:
    "\\R": "\\mathbb{R}"
    "\\E": "\\mathbb{E}"
```

`potato validate` rejects an unknown key, a delimiter outside the four, a
`fields` entry that is not an `instance_display` key, and a macro name that is
not a backslash followed by letters.

## Dollar signs

- `\$` is a literal dollar sign, inside or outside math.
- A single `$` follows pandoc's rule: the opening `$` must be followed by a
  non-space character, and the closing `$` must follow a non-space character
  and must not be followed by a digit. The first unescaped `$` after an opener
  decides: if it cannot close, the opener is a plain dollar sign. So
  `$5 and $10` stays text, and in `costs $5 and $x$` only `x` is math.
- Inline `$...$` does not cross a blank line.
- A dataset with many unescaped prices can drop `"$"` from `delimiters` and
  use `\(...\)` for inline math.

In JSON data files the backslash itself is escaped: `"\\$3"`, `"$\\frac{1}{2}$"`.

## Span annotation

Span targets are never rendered. A field with `span_target: true`, and in the
single-text layout the item text of a project with a `span`, `span_link`,
`coreference`, `error_span`, `event_annotation`, `extractive_qa` or
`text_edit` scheme, show the LaTeX source. Span offsets count the source
characters, the same as with rendering off: in `We know $a^2+b^2=c^2$`, the
math is 13 code points at offsets 8 to 21. A span drawn over part of a
formula keeps meaning the same characters when the data is exported or
re-imported.

The loader logs a warning naming each field left as source. To show annotators
the rendered form next to the text they mark, add a second, non-target field:

```yaml
instance_display:
  fields:
    - key: solution
      type: text
      label: "Solution (rendered)"
    - key: solution_source        # a copy of the same text
      type: text
      label: "Mark errors here"
      span_target: true
annotation_schemes:
  - annotation_type: span
    name: errors
    description: "Highlight the wrong part"
    labels: [error]
```

## Security

Rendering runs in the browser on the HTML the server has already sanitized.
KaTeX is called with `trust: false`, so `\href`, `\url`, `\includegraphics`,
`\htmlClass`, `\htmlId`, `\htmlStyle` and `\htmlData` produce no link, image,
class or attribute. HTML typed inside math (`$<img onerror=...>$`) is shown as
characters. `strict` is on: input KaTeX reports as non-LaTeX is shown as
source with a dotted underline and the parser message in its tooltip, except
for Unicode letters in math, missing glyph metrics and `\\` in display math,
which are accepted. `maxExpand` is 500 and `maxSize` 20em.

KaTeX 0.18.11 is vendored under `potato/static/vendor/katex-0.18.11/` (the
script, the stylesheet and the woff2 fonts) and is loaded only on pages of a
project with `math.enabled: true`.

## Grading math answers

To score typed answers, use a [cloze](cloze.md) blank with `scoring: numeric`
or `scoring: latex`. The key stays on the server.

```yaml
- annotation_type: cloze
  name: final_answer
  description: "Enter the final answer."
  source_field: answer_prompt       # item field, e.g. "The value of $S$ is [[]]."
  answer_field: answer_key          # item field, e.g. "1/2"
  scoring: numeric
  tolerance: 0.0005                 # optional, absolute
```

`numeric` accepts `0.5`, `1/2`, `\frac{1}{2}`, `\dfrac12`, `5e-1` and `.5` for
a key of `1/2`. `latex` compares LaTeX text with spacing, delimiters and
`\left`/`\right` removed. Neither mode does algebra; list every accepted form
with `|`. Scores appear in the CSV/TSV export as `<scheme>.blank_<n>_correct`
and `<scheme>.score`. See [Cloze: Math answers](cloze.md#math-answers).

Gold standards and training questions compare text answers as lower-cased
strings and do not use these modes. For a gold-standard math item, ask for a
choice (`radio`) between candidate answers, or score the cloze blank in the
export.

## Step-level proof grading

[`process_reward`](../../agent-evaluation/process_supervision.md) shows each
step of a solution with Valid/Invalid buttons. With math on, the step text is
rendered. `mode: first_error` matches PRM800K-style labelling: the grader
clicks the first wrong step, and the steps after it are marked wrong.

```yaml
math:
  enabled: true

instance_display:
  fields:
    - key: problem
      type: text
      label: "Problem"

annotation_schemes:
  - annotation_type: process_reward
    name: step_grades
    description: "Mark the first incorrect step."
    steps_key: steps                # a list of strings, or of objects
    mode: first_error               # or per_step, with allow_neutral: true
    reward_labels: {correct: "Valid", incorrect: "Invalid"}
```

Item data:

```json
{"id": "p1",
 "problem": "Evaluate $\\int_0^1 x e^{x}\\,dx$.",
 "steps": ["Integrate by parts with $u = x$, $dv = e^{x}\\,dx$.",
           "So the value is $e - (e - 1) = -1$."]}
```

For an error taxonomy per step (error type, severity, rationale), use
[`trajectory_eval`](../../agent-evaluation/trajectory_eval.md) instead; its
step text and thoughts are rendered the same way. To rate steps inside a
`cot_trace` display, set `inline_with_trace: true` on `process_reward`; the
trace field is rendered as a display field.

## Example

```bash
python potato/flask_server.py start examples/text/math-proof-grading/config.yaml -p 8000
```

Four worked solutions with step grading, an overall verdict, and a cloze blank
for the correct final answer scored with `numeric`. One item uses `\$` for
prices.

## Troubleshooting

**Math shows as source.** Check `math.enabled: true`, and that the field is not
a span target (the startup log names skipped fields). A red, dotted-underlined
expression failed to parse; hover it for KaTeX's message.

**Prices turned into math.** Escape them (`\$5`) or remove `"$"` from
`math.delimiters`.

**An expression is cut off on a phone.** Display math scrolls sideways inside
its own box; inline math does not wrap inside a formula. Use display math for
long expressions.

**Math in `<pre>` or `<code>`.** It is not rendered, by design: code often
contains dollar signs.

## Related

- [Cloze](cloze.md)
- [Process supervision](../../agent-evaluation/process_supervision.md)
- [Trajectory evaluation](../../agent-evaluation/trajectory_eval.md)
- [Instance display](../instance_display.md)
- [Span annotation](text_annotation.md)
