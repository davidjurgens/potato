# Coming from ODK and KoboToolbox

Potato reads XLSForm, the spreadsheet format behind ODK, KoboToolbox,
SurveyCTO and Ona, and turns a form into survey pages. Use it to reuse a
field questionnaire's demographics or screening questions in an online
annotation or rating study.

## Import

```bash
potato import -i household_survey.xlsx -o my-study/
python potato/flask_server.py start my-study/config.yaml -p 8000
```

For a form with several label columns (`label::English`, `label::French`),
`--survey-language French` picks one; otherwise the form's
`default_language` is used.

## Form structure

ODK shows one question per screen unless a group asks for more. Potato puts
a page's questions together, so the import uses the form's own grouping:

- each `begin_group` with `appearance: field-list` (or `table-list`) is one
  page;
- the questions between such groups share a page;
- another group's `relevant` is applied to every question inside it, and its
  label becomes a heading.

## Types and their Potato equivalents

| XLSForm | Potato |
|---|---|
| `select_one` | `radio` (`appearance: minimal` as a dropdown, `likert` horizontal) |
| `select_multiple` | `multiselect` |
| `rank` | `ranking` |
| `integer`, `decimal` | `number` |
| `range` | `slider` (`parameters: start= end= step=`) |
| `text` | `text` (`appearance: multiline` as a text box) |
| `note` | `pure_display` |
| `or_other` | An "Other" option with a text field |
| `required` | `label_requirement: {required: true}` |
| `relevant` | `display_logic` |
| `parameters: randomize=true` | `randomize_order` |

`relevant` expressions with `selected()`, `not()`, `count-selected()`,
`string-length()`, `regex()` and comparisons are translated.

## Not imported

Geopoints and other location types, date and time, photos, audio, video,
barcodes and files; `calculate` and `hidden` fields and logic that uses
them; repeats (their questions are imported once); `constraint`,
`choice_filter`, `default`, `read_only` and conditional `required`; and
external choice lists. Each is listed in `IMPORT_REPORT.md`. An `.xls` file
needs the `xlrd` package; otherwise save it as `.xlsx`.

## Related

- [Importing surveys](../tools/survey_import.md)
- [Display logic](../configuration/conditional_logic.md)
