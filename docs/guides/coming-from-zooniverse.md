# Coming from Zooniverse

`potato import` reads a Zooniverse project's exports and builds a Potato
project from them: the workflow's tasks become annotation schemes, the
subjects become items, and the volunteers' classifications can come across
as their saved work. Use it to run a workflow privately (unpublished data,
a lab team, paid annotators) or to compute agreement on an existing
project's classifications with Potato's tools.

## Export from Zooniverse

From the project's **Lab → Data Exports**:

- **Request new workflow export**: the workflow's tasks (CSV);
- **Request new classification export**: the classifications (CSV);
- **Request new subject export**: the subjects, with the media URLs (CSV).

Put the three files in one folder. The workflow alone (CSV, or the API's
JSON) is enough to import the questions without items.

## Import

```bash
potato import -i zooniverse-exports/ -o my-project --keep-annotators
python potato/flask_server.py start my-project/config.yaml -p 8000
```

The files are recognised by their columns, not their names. One workflow
version is imported: by default the most recent major version the
classifications use (`--workflow-id` and `--workflow-version` choose
another). Minor versions differ only in wording and are all accepted.

## Tasks and their Potato schemes

| Zooniverse task | Potato |
|---|---|
| Question (single answer) | `radio` |
| Question (multiple answers), shortcut | `multiselect` |
| Text | `text` |
| Slider | `slider` |
| Dropdown (simple) | `select` |
| Drawing: point, rectangle, polygon, line, circle/ellipse, freehand | `image_annotation` with the landmark, bbox, polygon, polyline, ellipse and freeform tools |
| Highlighter | `span` (when the subject's text is in its metadata) |
| Combo | Its tasks, each as above |
| Branching (`next` on an answer) | `display_logic` on the tasks reached through that answer |

Zooniverse shows tasks one after another; Potato shows them on one page and
reveals each one when the answers that lead to it are given. A task reached
by several paths is shown when any of them is taken.

Drawing marks are converted to Potato's coordinates using the image size
Zooniverse recorded with each classification, or the subject's metadata.

## Not imported

Survey tasks (species identification with follow-up questions), drawing
sub-task questions, transcription, data-visualisation and crop tasks, tools
other than those above, dropdowns with several or conditional lists, and
classifications covering several subjects. Each is counted in the output.
Volunteers who were not logged in appear as `anon_<id>`, so one person may
show up as several.

## Aggregating classifications

The `consensus` export does the job of Zooniverse's aggregation reducers on a
Potato project, whether the classifications came from Zooniverse or from your
own annotators. Import with `--keep-annotators` so each volunteer's
classifications are their own, then export:

```bash
potato import -i zooniverse-exports/ -o my-project --keep-annotators
python -m potato.export -c my-project/config.yaml -f consensus -o consensus_out
```

| Zooniverse reducer | Potato output |
|---|---|
| `question_reducer`, `question_consensus_reducer` | `consensus_votes.csv` (count and fraction per answer) and `consensus_questions.csv` (top answer, its fraction, ties, status) |
| `slider_reducer` | `consensus_numeric.csv` (n, mean, median, sd, min, max) |
| `point_reducer_dbscan` | `consensus_points.csv` (cluster centre, size, annotators, spread, variances) |
| `rectangle_reducer` / `shape_reducer_dbscan` | `consensus_boxes.csv` (median box, support, IoU), grouped differently: see [Boxes](../data-export/consensus_aggregation.md#boxes) |

Point clustering is DBSCAN with the same rule for core points as
`point_reducer_dbscan`, so with `eps_unit: pixels` and the same `eps` and
`min_samples` it gives the same clusters and centres. Pixel distances need the
image size; the importer writes `image_width` and `image_height` on each item
from the size Zooniverse recorded with its classifications.

Set the parameters in the project config:

```yaml
consensus_aggregation:
  agreement_threshold: 0.8
  min_classifiers: 3
  points:
    eps: 5
    eps_unit: pixels
    min_samples: 3
  boxes:
    iou_threshold: 0.5
```

Some differences from a Zooniverse project:

- Zooniverse retires a subject after a number of classifications (the
  workflow's retirement criteria). The export's `retired` / `needs_review`
  flag reports agreement on each question and does not change assignment.
  The imported config sets `max_annotations_per_item` to the most
  classifications any subject received.
- A volunteer who answered a drawing task without drawing anything is not
  counted among that task's classifiers, since the importer does not keep an
  empty drawing.
- Volunteers who were not logged in may appear as several annotators (see
  [Not imported](#not-imported)), which raises `n_classifiers`.
- Polygons, lines, ellipses and freehand shapes are imported but not
  aggregated; survey and transcription tasks are not imported.

`examples/image/zooniverse-aggregation/` is a small imported workflow with
five volunteers to try it on. The [Consensus aggregation](../data-export/consensus_aggregation.md)
page has every option and column.

## Related

- [Bringing a project into Potato](migrating-into-potato.md)
- [Import CLI](../tools/import_cli.md)
- [Display logic](../configuration/conditional_logic.md)
- [Consensus aggregation](../data-export/consensus_aggregation.md)
