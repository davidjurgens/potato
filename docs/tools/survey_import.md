# Importing Surveys

`potato import` turns a questionnaire built in another tool into Potato
survey pages: the questions, the pages, and the show/hide logic, translated
into Potato's [display logic](../configuration/conditional_logic.md).

| Format | File | `-f` |
|---|---|---|
| Qualtrics | `.qsf` (Survey → Tools → Import/Export → Export Survey) | `qualtrics` |
| SurveyJS | survey JSON (what SurveyJS Creator saves) | `surveyjs` |
| LimeSurvey | `.lss` (Display/Export → Survey structure) | `limesurvey` |
| XLSForm (ODK, KoboToolbox, SurveyCTO) | `.xlsx` | `xlsform` |
| REDCap | data dictionary `.csv` (Designer → Download the current Data Dictionary), or the API metadata export | `redcap` |
| Beiwe | survey JSON, or a study settings export | `beiwe` |
| Network Canvas | a `.netcanvas` protocol file, or its `protocol.json` | `network_canvas` |

The format is detected from the file. Pass `-f` to choose it explicitly.

## Usage

A new project, with the survey before a placeholder annotation task:

```bash
potato import -i screener.qsf -o my-study/
python potato/flask_server.py start my-study/config.yaml -p 8000
```

The survey pages go in `my-study/surveys/`, one JSON file per page, and
`config.yaml` lists them in `phases.order` before an `annotation` phase with
a placeholder question and three placeholder items. Replace those with the
real task.

Into an existing project:

```bash
potato import -i exit_survey.lss --into my-study/config.yaml --survey-slot poststudy --prefix exit_
```

The pages go in `surveys/` beside that config, and a merged copy is written
as `config.with-exit_survey-exit.yaml`, with the report in
`IMPORT_REPORT.exit_survey-exit.md`. Without `--prefix` they are
`config.with-exit_survey.yaml` and `IMPORT_REPORT.exit_survey.md`. Question
and page names, and so the page files, get the prefix exactly as given. In the
two file names above, underscores, hyphens and dots at either end of it are
dropped, so `exit_` becomes `exit`. The original config is not changed. `--prefix` renames every imported question
and page; use it when question names would clash with the project's own (the
import stops on a clash). It also stops with an error if it would replace
files an earlier import wrote; remove them, or import under another prefix.

The merged copy differs from the original in more than the new pages:

- if the config does not set `export_include_phase_data`, the copy sets it
  to `true`, so the survey answers are exported; the import says so, and a
  comment at the top of the copy repeats it. Survey answers can hold
  personal data; set it to `false` to leave them out of exports.
- comments in the original are not kept, and YAML lists are rewritten in
  block style.

Importing the same file with the same prefix again is refused while the
first import's merged copy, report or pages exist, so edits made to them are
not overwritten.

| Flag | Meaning |
|---|---|
| `-o DIR` | Write a new project |
| `--into CONFIG` | Add the pages to an existing project (writes a merged copy) |
| `--survey-slot` | `prestudy` (default, before annotation) or `poststudy` |
| `--prefix` | Prefix for every imported question and page name |
| `--survey-language` | Language to take from a multilingual LimeSurvey or XLSForm survey |

## What carries over

Every format:

- question wording (HTML is reduced to text), choices, and required questions;
- pages, in order;
- show/hide logic on questions and pages, translated to `display_logic` and
  page `show_when`, including nested AND/OR/NOT;
- choice order randomization (`randomize_order`) and question order
  randomization (`randomize_questions`) where the source has them.

Answers to choice questions are stored as the option text, so the
translated logic compares against option text, not the source's codes.

Everything the importer could not translate is listed in `IMPORT_REPORT.md`
with where it was and why, and the first ten are printed. A logic rule that contains anything untranslatable is reported
whole, and the question is left always visible rather than given a partial
rule.

## Qualtrics

- **Pages**: each block is a page, and each page break inside a block starts
  another. Trash blocks are skipped.
- **Questions**: multiple choice (single, multiple, dropdown, NPS), Matrix
  Likert (as `multirate`), text entry (single line, multi-line, number
  validation as `number`, forms as one text question per field), sliders,
  rank order (`ranking`), constant sum (`constant_sum`), descriptive text
  (`pure_display`). "Other" choices with a text box get a free-text field.
- **Logic**: display logic with Qualtrics' precedence (AND before OR within a
  condition set, and between `If` / `AndIf` / `ElseIf` sets), on selected
  choices, text-entry values, slider values and selection counts.
- **Survey flow**: branches become page rules (nested branches are ANDed);
  a randomizer that shows all of its blocks becomes a counterbalance group; a
  randomizer that shows one of several embedded-data assignments to one
  field becomes a between-subjects condition (`conditions`), and logic on that
  field tests `condition.<field>`; End of Survey inside a branch, and skip
  logic to the end of the survey, become `exit_when`.
- **Reported**: Loop & Merge, piped text, matrix-cell logic, Displayed /
  NotDisplayed, choice-level display logic, quotas, web services,
  authenticators, scoring, custom validation, request-response (soft
  required), JavaScript, and the question types Potato has no equivalent for
  (heat maps, hot spots, file upload, signature, side-by-side, timing, meta
  info).

## SurveyJS

- **Elements**: text (number inputs as `number`), comment, radiogroup,
  checkbox, dropdown, tagbox, boolean, rating, ranking, matrix, multipletext
  (one text question per item), html, slider. Panels are flattened into the
  page, and the panel's `visibleIf` applies to each question in it.
- **Logic**: `visibleIf` on questions, panels and pages, including
  `anyof` / `allof` / `contains` / `empty`, `{q.length}` selection counts,
  and `and` / `or` / `!`. A `complete` trigger becomes an `exit_when` on the
  page that asks the last question it tests.
- **Reported**: `enableIf`, `requiredIf`, `choicesVisibleIf`, validators,
  default values, calculated values and expression questions, `setvalue` /
  `skip` / `runexpression` triggers, dynamic matrices and panels, file and
  signature questions, and logic that calls functions.

## LimeSurvey

- **Both file layouts**: older exports (a language column on each row) and
  exports from DBVersion 400 on (text in `*_l10ns` tables). The survey's
  base language is used unless `--survey-language` says otherwise.
- **Pages**: question groups, in order. Group relevance becomes the page's
  `show_when`.
- **Questions**: list (radio, dropdown, with comment), 5-point, yes/no,
  gender, multiple choice, the array types (as `multirate`), short and long
  text, numerical, multiple numerical and multiple short text (one question
  per subquestion), ranking, text display.
- **Logic**: ExpressionScript relevance on question codes, subquestion codes
  and SGQA names, with `is_empty()`, `count()` over a multiple-choice
  question, and `and` / `or` / `!`; and the older `conditions` table.
- **Reported**: date, equation, file upload and dual-scale questions; hidden
  questions; validation (`preg`, `em_validation`); min/max answers; array
  filters; randomization groups; quotas; assessments; piped text; and
  `if()`, `regexMatch()` and `.shown` in logic.

## XLSForm

- **Pages**: each `field-list` or `table-list` group is a page; the
  questions between such groups share a page. Another group's relevance is
  applied to every question in it, and its label is shown as a heading.
- **Questions**: `select_one` (radio; `minimal` as a dropdown), 
  `select_multiple`, `rank`, `integer`, `decimal`, `range` (slider), `text`
  (`multiline` as a text box), `note`. `or_other` adds a free-text field.
- **Logic**: `relevant` with `selected()`, `not()`, `count-selected()`,
  `string-length()`, `regex()` and comparisons.
- **Reported**: date, time, geopoint, media, barcode and file questions;
  `calculate` and `hidden` fields and logic that uses them; repeats
  (imported once); `constraint`, `choice_filter`, `default`, `read_only` and
  conditional `required`; external choice lists.
- `.xls` files need the `xlrd` package; otherwise save the form as `.xlsx`.

## REDCap

- **Pages**: one per instrument (form), in order. Section headers are
  headings on the page.
- **Fields**: text (integer and number validation as `number`), notes,
  dropdown, radio, checkbox, yes/no, true/false, slider, descriptive. A
  matrix group becomes one `multirate`, unless logic tests one of its rows,
  in which case the rows stay separate questions.
- **Logic**: branching logic on choice codes, checkbox options
  (`[field(3)] = '1'`), numbers and empty values, with `and` binding tighter
  than `or`.
- **Reported**: calculated, file and SQL fields; validation types Potato has
  no check for; action tags other than `@PLACEHOLDER` (`@HIDDEN` fields are
  left out, since REDCap never shows them to participants); piped values;
  and logic using functions, events (`[event][field]`) or form status.

## Beiwe

- **Pages**: one per survey in the export.
- **Questions**: info text, slider, radio button, checkbox, free response
  (numeric, single line, multi-line).
- **Logic**: `display_if` (and / or / not, with radio answers by position
  and checkbox answers by membership).
- **Reported**: date and time questions, audio surveys, schedules and
  timings (Potato has no survey scheduling), and partial randomization.

## Network Canvas

- **Pages**: an ego form or information stage becomes a survey page; the
  network stages for one node type become one
  [`ego_network`](../annotation-types/structured/ego_network.md) question
  (name generators, name interpreters, dyad and tie-strength censuses, and
  the sociogram), on one page.
- **Rosters**: CSV or JSON roster assets become the name generator's roster.
- **Logic**: ego skip logic becomes `show_when`; a skip to the end of the
  interview becomes `exit_when` on the page before.
- **Reported**: node and edge filter rules, alter edge forms, narrative and
  geospatial stages, date and time variables, and media items. Network
  stages for one node type share a page, so they cannot be skipped one by
  one, and a stage that came after other pages moves ahead of them; each
  move is reported. See [Coming from Network Canvas](../guides/coming-from-network-canvas.md).

## Related

- [Display logic](../configuration/conditional_logic.md)
- [Multi-phase workflows](../workflow/surveyflow.md)
- [Experiment flow](../workflow/experiment_flow.md)
- [Coming from Qualtrics](../guides/coming-from-qualtrics.md)
- [Coming from REDCap](../guides/coming-from-redcap.md)
- [Coming from ODK and KoboToolbox](../guides/coming-from-odk.md)
- [Import CLI](import_cli.md)
