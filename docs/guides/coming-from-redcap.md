# Coming from REDCap

Potato reads a REDCap data dictionary and turns its instruments into survey
pages. Use it to put a REDCap screening or demographics instrument in front
of an annotation task, such as clinicians labeling notes or images, without
retyping the questions and branching logic.

## Export from REDCap

**Designer → Download the current Data Dictionary** gives a `.csv` with one
row per field. The API metadata export (snake_case column names) works too.
Neither file contains records.

## Import

```bash
potato import -i MyProject_DataDictionary.csv -o my-study/
python potato/flask_server.py start my-study/config.yaml -p 8000
```

Each instrument becomes a page, in the order the dictionary lists them.

## Fields and their Potato equivalents

| REDCap | Potato |
|---|---|
| Instrument (Form Name) | A survey page |
| Section header | A heading on the page |
| `text` with integer or number validation | `number` with the validation min and max |
| `text` (other validation), `notes` | `text`, a text box for notes |
| `radio`, `dropdown`, `checkbox` | `radio`, `select`, `multiselect` |
| `yesno`, `truefalse` | `radio` with Yes/No, True/False |
| `slider` | `slider` |
| `descriptive` | `pure_display` |
| Matrix group | `multirate`, or separate questions when logic tests a row |
| Required field | `label_requirement: {required: true}` |
| Branching logic | `display_logic`, choice codes mapped to the option text |
| `@PLACEHOLDER` | The text box placeholder |
| `@HIDDEN`, `@HIDDEN-SURVEY` | Left out (participants never see them) |

## Not imported

Calculated fields and logic that uses them, file and SQL fields, validation
types Potato does not check (dates, emails, phone numbers become plain text
with a format hint), other action tags, piped values, and logic that uses
functions (`datediff`, `sum`, ...), events (`[event][field]`) or form status.
REDCap's longitudinal events and repeating instruments have no Potato
equivalent. Each item is listed in `IMPORT_REPORT.md`.

## Data

Potato is not a clinical data capture system: it has no audit trail of the
kind REDCap provides for regulated studies. Keep identifiable health data
in REDCap and use Potato for the annotation and its surrounding questions.

## Related

- [Importing surveys](../tools/survey_import.md)
- [Display logic](../configuration/conditional_logic.md)
