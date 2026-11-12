# Coming from Qualtrics

Potato reads a Qualtrics survey file (`.qsf`) and turns it into survey pages
around an annotation task. A study that uses Qualtrics for consent,
demographics and a screener, and something else for the labeling itself,
can run in one place: the survey, the annotation, Prolific or SONA, and one
export with both.

## Export from Qualtrics

**Survey → Tools → Import/Export → Export Survey** downloads the `.qsf`. It
holds the questions, blocks, survey flow and logic, not the responses.

## Import

```bash
potato import -i screener.qsf -o my-study/
python potato/flask_server.py start my-study/config.yaml -p 8000
```

Each block becomes a page (a page break starts a new one), each question a
Potato question, and the display logic, branches and end-of-survey elements
become page and question rules. The study runs the survey and then a
placeholder annotation task; replace it with the real one. To add the
survey to a project you already have:

```bash
potato import -i screener.qsf --into my-study/config.yaml --prefix scr_
```

`IMPORT_REPORT.md` lists everything that did not carry over.

## Qualtrics features and their Potato equivalents

| Qualtrics | Potato |
|---|---|
| Block | A survey page in `phases.order` |
| Page break | A new page |
| Multiple choice (single / multiple / dropdown) | `radio` / `multiselect` / `select` |
| Matrix table (Likert) | `multirate` |
| Text entry, form | `text`, one `text` per form field |
| Text entry with number validation | `number` with min and max |
| Slider | `slider`, one per statement |
| Rank order, constant sum | `ranking`, `constant_sum` |
| Descriptive text | `pure_display` |
| Force response | `label_requirement: {required: true}` |
| Display logic | `display_logic` with nested `all` / `any` / `not` |
| Branch in the survey flow | `show_when` on the pages under it |
| Randomizer showing all blocks | `phases.counterbalance` |
| Randomizer assigning one embedded-data value | `conditions` (between-subjects factor) |
| End of Survey in a branch, skip to end of survey | `exit_when` (screens the participant out) |
| Choice randomization | `randomize_order` |
| Embedded data from a URL (Prolific ID) | Potato's [crowdsourcing](../deployment/crowdsourcing.md) settings capture it |

## Not imported

Loop & Merge (the block is imported once), piped text, logic on single
matrix cells, "is displayed" conditions, choice-level display logic, quotas,
web service and authenticator elements, scoring, custom validation, soft
"request response", question JavaScript, and question types with no Potato
equivalent (heat map, hot spot, file upload, signature, side-by-side,
timing). Each one is listed in the report.

## Related

- [Importing surveys](../tools/survey_import.md)
- [Experiment flow](../workflow/experiment_flow.md)
- [Display logic](../configuration/conditional_logic.md)
