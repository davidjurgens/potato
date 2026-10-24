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

## Related

- [Bringing a project into Potato](migrating-into-potato.md)
- [Import CLI](../tools/import_cli.md)
- [Display logic](../configuration/conditional_logic.md)
