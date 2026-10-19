# FiftyOne Annotation Backend

[FiftyOne](https://github.com/voxel51/fiftyone) can send a view of a dataset to
an external annotation tool and load the labels back. Potato is one of those
tools. A view sent to Potato can be labeled by several people. Loading it back
gives each sample one merged label, each person's own labels if you ask for
them, and a chance-corrected agreement report stored on the dataset.

## Setup

```bash
pip install "potato-annotation[fiftyone]"
```

Register the backend once per environment, either in code:

```python
import fiftyone as fo

fo.annotation_config.backends["potato"] = {
    "config_cls": "potato.integrations.fiftyone_backend.PotatoBackendConfig",
}
```

or in `~/.fiftyone/annotation_config.json`:

```json
{
    "backends": {
        "potato": {
            "config_cls": "potato.integrations.fiftyone_backend.PotatoBackendConfig"
        }
    }
}
```

## Usage

```python
import fiftyone as fo

dataset = fo.load_dataset("street-scenes")
view = dataset.take(200)

view.annotate(
    "round1",
    backend="potato",
    label_field="ground_truth",
    label_type="detections",
    classes=["car", "person", "bicycle"],
    project_dir="potato-round1",
    annotations_per_item=3,
)
```

`annotate` writes a Potato project to `project_dir` and returns straight away.
Start the project from the folder that contains it:

```bash
potato start potato-round1/config.yaml -p 8000
```

Pass `launch_editor=True` to `annotate` to start Potato in the background and
open it in the browser. When the annotators have finished:

```python
dataset.load_annotations("round1")
print(dataset.info["potato_agreement"]["round1"])
```

### Options

| Argument | Default | Meaning |
|---|---|---|
| `project_dir` | `./potato-<anno_key>` | Where the Potato project is written |
| `annotations_per_item` | `2` | How many people label each sample (`max_annotations_per_item`) |
| `media` | `"copy"` | `"copy"` copies each image into the project's `media/` folder. `"reference"` serves the images from the folder they are already in, without copying |
| `annotator_fields` | `False` | On load, also write each annotator's labels to `<label_field>_<username>` |
| `port` | `8000` | The port `launch_editor` starts Potato on |

`media="reference"` makes every file under the images' common folder
reachable through the study's URL, so only use it when that folder holds
nothing else. It raises an error when that folder is the filesystem root or
your home directory.

### Label types

| FiftyOne `label_type` | Potato question |
|---|---|
| `classification` | Single choice (radio), with the image shown above it |
| `classifications` | Multiple choice (multiselect) |
| `detection`, `detections` | Image annotation with the box tool |
| `polygon`, `polygons` | Image annotation with the polygon tool |
| `polyline`, `polylines` | Image annotation with the polyline tool |

Images only. Video, keypoints, segmentation masks, scalar fields and label
attributes are not supported yet. `annotate` raises an error for an
unsupported label type before writing anything.

If the field already has labels, they are shown to annotators as
pre-annotations to correct. A FiftyOne polyline with several shapes becomes
one Potato object per shape.

## Loading the labels back

### The merged label

For each sample with at least one saved answer:

- **Classification:** the class most annotators chose. A tie leaves the
  sample's existing label, if it has one, in place and is counted in the
  report as `n_ties`.
- **Classifications:** every class chosen by more than half of the annotators.
  If annotators chose classes but none reached a majority, the sample keeps
  its existing labels and the disagreement is counted in `n_ties`.
- **Boxes, polygons, polylines:** objects are matched across annotators by
  overlap (IoU 0.5). An object more than half of the annotators drew is kept,
  labelled with its most common class. A box becomes the mean of the matched
  boxes. A polygon or polyline becomes the matched shape that overlaps the
  others most. If objects were drawn but none was found by a majority, the
  sample keeps its existing labels and counts in `n_ties`.

With one annotator per sample, the merged label is that person's answer.

If the project uses Potato's [adjudication](../administration/adjudication.md)
queue, an adjudicator's decision replaces the merge for its sample.

Samples nobody has answered keep their existing labels, ids unchanged.
FiftyOne deletes any existing label a backend does not return, so the backend
returns these as they were. A sample whose annotators all saved an empty
answer, for example by deleting a wrong pre-annotated box, loses its old
labels.

### Each person's labels

With `annotator_fields=True`, each annotator's own labels are written to
`<label_field>_<username>`, for example `ground_truth_alice`. Use them to look
at one person's work, or to compare two people in the FiftyOne app.

### The agreement report

`load_annotations` stores a report per label field in
`dataset.info["potato_agreement"][anno_key]`. It counts only samples with two
or more annotators.

- **Classification:** Krippendorff's α (nominal) and the raw share of
  annotator pairs who agreed.
- **Classifications:** α with the MASI distance, and the raw share of pairs
  who chose the same set.
- **Boxes, polygons, polylines:** the [geometry agreement](../advanced/geometry_agreement.md)
  report, split into whether annotators found the same objects (`detection`),
  gave them the same class (`classification`), and drew them in the same place
  (`localization`).

When α is undefined, the report says why instead of giving a bare `None`. That
happens when every annotator gave the same answer on every shared sample.
`n_merged`, `n_ties` and `n_adjudicated` count what the merge did.

The same report is available without loading labels:

```python
results = dataset.load_annotation_results("round1")
results.agreement()
```

## Troubleshooting

**`Path ... is outside the project directory` when starting Potato.** Start
Potato from the folder that contains `project_dir`, with a relative path to
the config, as above.

**`fiftyone_run.json is missing`.** The folder passed to the run was not
written by this backend, or it was moved after `annotate`. The run keeps the
absolute path it was given.

**`results.cleanup()` leaves the folder in place.** The project holds people's
saved work, so the backend never deletes it. Remove the folder yourself when
you no longer need it.

## Related

- [Importing existing annotations](../tools/migration_cli.md)
- [Geometry agreement](../advanced/geometry_agreement.md)
- [Adjudication](../administration/adjudication.md)
