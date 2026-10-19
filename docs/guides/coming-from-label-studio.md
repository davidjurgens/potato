# Coming from Label Studio

`potato import` turns a Label Studio project into a runnable Potato project: the
labeling interface becomes annotation schemes, each annotator's answers become
that person's saved work, and model predictions become pre-annotations.

## Export from Label Studio

1. **Export → JSON** (not JSON-MIN or CSV). This is the list of tasks with
   their `annotations` and `predictions`.
2. **Settings → Labeling Interface → Code**: copy the XML into a file, such as
   `label_config.xml`.

The XML is optional. Without it the questions are rebuilt from the answers, so
every label someone used comes across but options nobody chose do not.

## Import

```bash
python -m potato.importers -i project-export.json --ls-config label_config.xml \
    -o my-project --keep-annotators
python potato/flask_server.py start my-project/config.yaml -p 8000
```

`--keep-annotators` writes each annotator's answers as their saved work, so
`/admin/iaa` reports agreement between them straight away (the import sets
`max_annotations_per_item` to the source study's overlap, so finished items count
as complete). Without it, only the
predictions come across. The `--keep-annotators` section of the
[Import CLI](../tools/import_cli.md) explains what the flag does to the project's login settings.

## Label Studio tags and their Potato schemes

| Label Studio | Potato | Notes |
|---|---|---|
| `<Choices>` | `radio` | `multiselect` when `choice="multiple"` |
| `<Labels>` | `span` | Label colours carry over. Offsets are converted from JavaScript's UTF-16 units to code points, so spans after an emoji land where they should |
| `<RectangleLabels>` | `image_annotation`, bbox tool | Rotation is dropped and counted |
| `<PolygonLabels>` | `image_annotation`, polygon tool | |
| `<KeyPointLabels>` | `image_annotation`, landmark tool | |
| `<TextArea>` | `text` | Multi-line when `rows` is more than 1 |
| `<Rating>` | `likert` | Size from `maxRating` |
| `<Number>` | `number` | `min` and `max` carry over |
| `<Header>` before a control | The scheme's description | |
| `completed_by` | A Potato username | `ls_user_<id>`, or the email when the export has one. The README maps each back |
| Predictions | Pre-annotations | The highest-scoring prediction per task. Its `model_version` and `score` are kept in the data file's `prediction_sources` column, and on image objects as `ai_model` and `confidence` |

Image tools that point at the same `<Image>` become one `image_annotation`
scheme with several tools, which is how Potato draws them.

## Not imported

These have no equivalent in the importer yet. Each is reported in the import's
output and in the project README, with how many answers were dropped:

- `<Pairwise>`, `<Ranker>`, `<Taxonomy>`, `<BrushLabels>`, relations, and any
  other control not in the table above
- Cancelled (skipped) annotations
- Predictions other than the highest-scoring one on each task
- A second label on the same span (the first is kept)

## Related

- [Bringing a Project Into Potato](migrating-into-potato.md)
- [Coming from Argilla](coming-from-argilla.md)
- [Inter-Annotator Agreement](../workflow/quality_control.md)
