# FiftyOne Annotation Backend

[FiftyOne](https://github.com/voxel51/fiftyone) can send a view of a dataset to
an external annotation tool and load the labels back. Potato is one of those
tools. A view sent to Potato can be labeled by several people. Loading it back
gives each sample one merged label, each person's own labels if you ask for
them, and an agreement report stored on the dataset. Images and videos both
work: classifications, boxes, polygons, polylines, keypoints, segmentation
masks and video tracks, with attributes.

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
| `keypoint`, `keypoints` | With a skeleton for the field (`dataset.skeletons[field]` or `dataset.default_skeleton`): the keypoint-set tool, points in the skeleton's order. Without one: the landmark tool, one point per object |
| `segmentation` | Image annotation with the brush and eraser, one mask per class in the field's `mask_targets` |
| `detections` on a video frame field (`frames.<name>`) | Video annotation in tracking mode |

On a video dataset, sample-level `classification` and `classifications`
fields also work, with the video shown above the question; a frame field must
be `detections`. Scalar fields are not supported. `annotate` raises an error
for an unsupported label type before writing anything.

If an image field already has labels, they are shown to annotators as
pre-annotations to correct. A FiftyOne polyline with several shapes becomes
one Potato object per shape. A keypoint FiftyOne marks missing (NaN) is an
unlabelled point (visibility 0) in Potato, and comes back as NaN.

### Attributes

Attributes on boxes, polygons, polylines, keypoints and video tracks become a
panel beside the selected object:

```python
dataset.annotate("round2", backend="potato", label_field="ground_truth",
                 label_type="detections", classes=["car", "person"],
                 attributes={"occluded": {"type": "checkbox"},
                             "state": {"type": "select", "values": ["parked", "moving"]}})
```

| FiftyOne attribute type | Potato control |
|---|---|
| `select`, `radio` | A choice from `values` |
| `checkbox` | A checkbox |
| `text` | A text box |

Existing attribute values are pre-filled. On load each label gets the
attribute values back as label fields (`detection["state"]`). Masks have no
attributes. In the project the backend writes, a video track's attribute has
one value for the whole track, and every frame's detection carries it.

### Masks

The field's `mask_targets` (from `annotate(mask_targets=...)`,
`dataset.mask_targets[field]` or `dataset.default_mask_targets`) name the
classes; 0 is background. Existing masks are pre-filled one class at a time.
On load the classes' masks are combined into one `Segmentation`; where two
overlap, the class with the higher value in `mask_targets` wins. RGB mask
targets (`"#rrggbb"` keys) are not supported, and `annotate` raises an error
for them before writing anything. Instance masks on detections are not
supported either.

### Video

A `frames.<name>` detections field becomes a tracking task: annotators draw a
box on a frame, move to a later frame and draw it again, and Potato
interpolates between the keyframes. Potato reads each video's frame rate from
its metadata (computed if missing). On load every frame from a track's first
keyframe to its last gets a detection: interpolated linearly between
keyframes (held, for a track set to constant), with the track's number as
`index` and `keyframe=True` on the frames the annotator drew.

Existing tracks on the field are not shown to annotators, and loading adds new
tracks beside them rather than replacing them; the backend logs a warning
when the field already has labels.

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
- **Keypoints and masks:** the same rule, matched by OKS for keypoint sets,
  distance for landmarks and IoU for masks; the kept object is the matched one
  that agrees most with the others.
- **Attributes:** each attribute takes the most common value among the matched
  objects.
- **Video tracks:** tracks are matched across annotators by how much their
  frame ranges overlap times the IoU of their boxes. A track more than half of
  the annotators drew is kept: the matched track that agrees most with the
  others, with the most common class.

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
at one person's work, or to compare two people in the FiftyOne app. Video
tracks are not copied this way.

### The agreement report

`load_annotations` stores a report per label field in
`dataset.info["potato_agreement"][anno_key]`. It counts only samples with two
or more annotators.

- **Classification:** Krippendorff's α (nominal) and the raw share of
  annotator pairs who agreed.
- **Classifications:** α with the MASI distance, and the raw share of pairs
  who chose the same set.
- **Boxes, polygons, polylines, keypoints, masks:** the [geometry agreement](../advanced/geometry_agreement.md)
  report, split into whether annotators found the same objects (`detection`),
  gave them the same class (`classification`), and drew them in the same place
  (`localization`).
- **Video tracks:** `tracks_drawn`, `track_match_rate` (the share of tracks
  matched by another annotator's track) and `mean_track_similarity` over the
  matched pairs.

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
