# Coming from Argilla

`potato import -f argilla` turns an Argilla 2.x dataset into a runnable Potato
project: questions become annotation schemes, responses become each annotator's
saved work, suggestions become pre-annotations, and the guidelines go into the
project README.

## Export from Argilla

Either of Argilla's own exports works:

```python
dataset.to_disk("my_dataset")          # a folder
dataset.to_hub("my-org/my-feedback")   # a Hugging Face dataset
```

They differ in one way that matters. A `to_disk` folder records each response's
value and annotator but not its status, so a discarded or draft response cannot
be told from a submitted one, and all of them are imported (the import warns).
A `to_hub` dataset keeps the status, and only submitted responses are imported.

## Import

```bash
# A to_disk folder
python -m potato.importers -i my_dataset -o my-project --keep-annotators

# A to_hub dataset, straight from the Hub (needs huggingface_hub and datasets)
python -m potato.importers -f argilla --hf-dataset my-org/my-feedback \
    -o my-project --keep-annotators

python potato/flask_server.py start my-project/config.yaml -p 8000
```

`--keep-annotators` writes each annotator's responses as their saved work, so
`/admin/iaa` reports agreement between them straight away (the import sets
`max_annotations_per_item` to the source study's overlap, so finished items count
as complete). Argilla 2.x reports
no agreement statistic of its own. Without the flag, only the suggestions come
across. The `--keep-annotators` section of the [Import CLI](../tools/import_cli.md)
explains what the flag does to the project's login settings.

## Argilla settings and their Potato equivalents

| Argilla | Potato | Notes |
|---|---|---|
| `LabelQuestion` | `radio` | |
| `MultiLabelQuestion` | `multiselect` | |
| `RatingQuestion` | `likert` | When the scale is 1 to N. A 0–10 or sparse scale becomes a horizontal `radio`, which keeps every value exactly |
| `TextQuestion` | `text` | Multi-line |
| `SpanQuestion` | `span` | On the field the question names |
| `required: true` | `label_requirement: {required: true}` | |
| `TextField`, `ImageField` | Shown on the page | With more than one field, all are shown with `instance_display`, and a span question's field is marked as the span target |
| `ChatField` | Shown as text | One message per line, prefixed with its role |
| Record metadata | Kept in the data file | |
| Response `user_id` | A Potato username | `argilla_` plus the first eight characters of the id. The README maps each back |
| Suggestions | Pre-annotations | The `agent` and `score` are kept in the data file's `prediction_sources` column |
| Guidelines | The project README | |

## Not imported

Each is reported in the import's output and in the project README:

- `RankingQuestion`, with its responses
- Discarded and draft responses (from `to_hub` only; see above)
- Vectors

## Related

- [Bringing a Project Into Potato](migrating-into-potato.md)
- [Coming from Label Studio](coming-from-label-studio.md)
- [Inter-Annotator Agreement](../workflow/quality_control.md)
