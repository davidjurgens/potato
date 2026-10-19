# Per-Object Attributes

A box labelled `car` is often only half of what a dataset records. Driving and
detection datasets also note how occluded each object is, whether the image edge
cuts it off, and whether a vehicle is parked. These belong to the object, not the
image. `attributes` adds typed fields that the annotator fills in for each
object: each shape on an `image_annotation` scheme, each track on a
`video_annotation` scheme in `tracking` or `combined` mode, and each box or
point on a `spatial_annotation` (point cloud) scheme. Potato then reports
agreement on each attribute over the objects that two annotators both drew.

## Configuration

```yaml
annotation_schemes:
  - annotation_type: image_annotation
    name: objects
    description: Box each vehicle and person, then set its attributes
    source_field: image_url
    tools: [bbox, polygon]
    labels: [vehicle, person]
    attributes:
      - name: occlusion
        type: select
        options: [none, partial, heavy]
        required: true
        default: none
        description: How much of the object is hidden behind something else
      - name: truncated
        type: bool
        default: false
      - name: truncated_share
        type: number
        min: 0
        max: 1
        show_if: {attribute: truncated, equals: true}
      - name: parked
        type: bool
        labels: [vehicle]
      - name: activity
        type: multi
        options: [walking, standing, cycling, carrying]
        labels: [person]
```

| Key | Default | Meaning |
|---|---|---|
| `name` | required | The attribute's name, as stored and exported |
| `type` | `select` | `select` (one option), `multi` (several options), `text`, `number` or `bool` |
| `options` | | The choices, for `select` and `multi` |
| `labels` | every label | The labels this attribute applies to. A shape with another label does not show it |
| `required` | `false` | Next is refused while any shape lacks a value |
| `default` | | Set on each shape the annotator draws. Model and imported shapes keep what they arrived with |
| `show_if` | | `{attribute: <name>, equals: <value>}`: show this field only while another attribute has that value |
| `min`, `max` | | Bounds for a `number` |
| `description` | | Help text under the field |

A mistake in the block, such as a misspelled key, a select with no options, a
`labels` entry that is not one of the scheme's labels, or a default that is not
one of the options, stops the config from loading, with a message naming the
attribute.

## Annotating

Select a shape, by drawing it or clicking it, and its attributes appear in the
panel under the image. The panel lists only the attributes for that shape's
label, and it changes when you relabel the shape. The fields are ordinary form
controls: Tab moves between them, and they show a focus ring.

On a video, the panel sits under the track list and shows the active track's
attributes: create a track or click it in the list. Attributes belong to the
whole track, not to one frame. On a point cloud, the panel sits under the
viewer and shows the selected box or point's attributes.

If a required attribute is missing on any object, the panel says how many
still need one, and pressing Next shows the same reason in the banner instead
of moving on. A required field hidden by `show_if` does not count.

Changing an attribute on a model's or an imported shape marks it `edited`, the
same as moving it, so accepting a suggestion and correcting one stay
distinguishable.

## Storage and export formats

Each shape carries an `attributes` object:

```json
{"type": "bbox", "label": "vehicle", "coordinates": {"x": 0.2, "y": 0.4, "width": 0.3, "height": 0.2},
 "source": "human", "attributes": {"occlusion": "partial", "truncated": false, "parked": true}}
```

The CVAT XML exporter writes them as `<attribute>` elements, KITTI as its
truncation and occlusion columns, MOT and Darwin as their own fields, and COCO
as an `attributes` key on each annotation. The CVAT, KITTI, MOT, Darwin, VIA and
COCO importers read them back, and they survive edits, undo and navigation.

A video track stores its attributes beside its keyframes, and a point-cloud
object beside its coordinates, in the same `attributes` object.

## Agreement over attributes

With two or more annotators per image, `/admin/iaa` adds one group per
attribute to the scheme's report. The units are the objects both annotators drew
in the same place, and the values are what each set. Objects are matched by
shape overlap on an image (as for the scheme's detection and classification
agreement), by 3D box overlap on a point cloud (on a point-cloud
[sequence](../spatial/point_cloud.md#sequences), whole tracks are matched, the
same way as on a video), and on a video by how much
two tracks overlap in time multiplied by how much their boxes overlap on the
frames where both have one. Two tracks count as one object at 0.5 or
more; when the box overlap holds steady along the track, that product equals
their overlap in space and time together, so 0.5 is the usual bar for
tracking. Video boxes are compared as fractions of the picture, which
keyframes store beside the screen position (`bboxNorm`). A track with no
`bboxNorm` (one imported or written by hand) is never matched, since on time
alone a car and a pedestrian tracked over the same frames would look like
one object; the report counts such tracks under "tracks without normalized
boxes".

| Attribute type | Krippendorff's alpha at |
|---|---|
| `select`, `bool` | nominal level |
| `number` | interval level |
| `multi` | MASI distance between the chosen sets |
| `text` | not scored |

Raw percent agreement is shown beside alpha. A shape only one annotator drew, a
shape whose label the attribute does not apply to, and a blank value contribute
nothing. When every annotator gave the same value everywhere, alpha is undefined
and the table prints the reason in its place rather than a bare n/a.

## Limits

- Attributes are set per object, not per frame: a video track has one value
  for its whole length.
- Brush masks have no attribute panel; masks imported with attributes keep them.
- A box drawn on top of another shape is not selected automatically. Click it to
  see its attributes.

## Example

`examples/image/object-attributes/` is a runnable project with the
configuration above:

```bash
python potato/flask_server.py start examples/image/object-attributes/config.yaml -p 8000
```

## Related

- [Image Annotation](image_annotation.md)
- [Image Annotation Formats](image_formats.md)
- [Quality Control](../../workflow/quality_control.md)
