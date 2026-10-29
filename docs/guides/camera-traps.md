# Camera Traps: Reviewing MegaDetector Output

This guide covers reviewing camera-trap images in Potato after a detector has
run over them. You import MegaDetector's batch output (or a COCO Camera Traps
file), annotators triage each image and correct its boxes, and you export the
result as MegaDetector JSON, a Camtrap DP data package or Darwin Core
occurrences.

## Import

```bash
# MegaDetector batch output; images under /data/traps
potato import -i md_output.json --image-dir /data/traps -o review-project/

# The same, with the images hosted elsewhere
potato import -i md_output.json --image-url-prefix https://example.org/traps -o review-project/

# Keep only detections with confidence 0.5 or more
potato import -i md_output.json --image-dir /data/traps --md-threshold 0.5 -o review-project/

# COCO Camera Traps, one item per sequence
potato import -i cct.json --image-dir /data/traps --sequences -o review-project/
```

The format is detected from the content; pass `-f megadetector` (or `-f md`)
or `-f coco_camera_traps` (or `-f cct`) to choose explicitly.

File paths in the source are relative to the image folder. With `--image-dir`
the generated config sets `media_directory` to that folder, so Potato serves
the images from where they already are, at `/media/<file>`. With
`--image-url-prefix` the prefix is joined to each file name instead. With
neither, the URLs are `/media/<file>` and the import warns you to copy or link
the image folder into the project's `media/`. The import also uses
`--image-dir` to report files that are not there and, when Pillow is
installed, to read each image's width and height.

### Items and questions

Each image is one item with these questions:

| Scheme | Type | Pre-filled with |
|---|---|---|
| `triage` | radio: `empty`, `animal`, `person`, `vehicle` | The category of the most confident detection; `empty` when no detection reaches the threshold |
| `detections` | image_annotation, bounding boxes | Every detection at or above the threshold. The label is the detection's top species classification when the file has one, otherwise its category |
| `species` | multiselect | The species of those detections. Only created when the source names species |

The triage question gives a quick first pass. Annotators can answer it with
the keys `1`–`4` and move on, and come back to the boxes of the images that
need them. Boxes keep the detector's provenance (`"source": "ai"`, the
detector's name and the confidence), and get `"edited": true` when an
annotator changes them.

Item ids are the file paths with `/` replaced by `_` (`cam01/IMG_0001.JPG`
becomes `cam01_IMG_0001.JPG`); the original path stays in the item's `file`
field. The item also keeps `datetime`, `location`, `seq_id` and `frame_num`
when the source has them.

### MegaDetector batch output

The importer reads format version 1.x: `info`, `detection_categories`
(`1` animal, `2` person, `3` vehicle), the optional
`classification_categories`, and `images[]`, each with `file` and
`detections[]` of `{category, conf, bbox}`. `bbox` is `[x, y, width, height]`
as fractions of the image, measured from the top-left corner, which is the
convention Potato's image annotation stores, so boxes need no image size.
Per-detection `classifications` (`[[class_id, confidence], ...]`) give the
species label. The box keeps both scores: the detector's `conf` as
`confidence`, and the top classification's score as
`attributes.classification_confidence`. Images with a `failure` are left
out, and the summary says how many. Detections below `--md-threshold`
(default 0.2) are left out of both the boxes and the triage. A detection whose
`conf` or `bbox` is not a number is left out, and a warning names the file,
the image and the detection's index. A `bbox` that reaches outside the image
(below 0, or past 1 once its width or height is added) is kept, with a
warning.

A file of video results (entries with `frame_rate`, detections with
`frame_number`) is reviewed at clip level: each video is one item shown with
a video player, with the `triage` and `species` questions only. The
detections are kept in the data file and written back by the `megadetector`
export. In a file that mixes images and videos, the video entries are left
out with a warning.

### COCO Camera Traps

A COCO file whose `images[]` carry `seq_id` (with `seq_num_frames`,
`frame_num`, `location`, `datetime`) is read as COCO Camera Traps. Its
categories are the species, plus `empty`. Annotations with a `bbox` (in
pixels) become boxes. This needs the image's `width` and `height`, from the
file or from `--image-dir`. Annotations without one are image-level labels:
they fill in `triage` and `species` only.

### Sequences

With `--sequences`, images that share a `seq_id` become one item, shown as a
gallery of the frames in `frame_num` order. The sequence gets `triage` (the
most confident detection over all frames) and `species`, but no boxes, since
boxes cannot be drawn on a gallery. The frames' detections stay in the data
file. MegaDetector output has no sequence ids of its own; a file with
`seq_id` added to its image entries works.

## Review

```bash
python potato/flask_server.py start review-project/config.yaml -p 8000
```

On each image: check the triage answer, then move, resize, relabel or delete
the boxes and draw any animal that was missed, and tick the species present.
Pre-filled answers are stored only when the annotator saves, so an export
contains reviewed images only.

## Export

```bash
python -m potato.export -c review-project/config.yaml -f megadetector -o export/
python -m potato.export -c review-project/config.yaml -f camtrap_dp -o export/ \
    --option timezone=-05:00 --option contributor="Your Name" \
    --option sampling_design=opportunistic --option capture_method=activityDetection
python -m potato.export -c review-project/config.yaml -f darwin_core -o export/
```

The exporters find the boxes in the first `image_annotation` scheme, the
triage in a `radio` scheme with an `empty` label, and the species in a
`multiselect` named `species`. `--option box_scheme=`, `triage_scheme=` and
`species_scheme=` name them explicitly.

### MegaDetector JSON (`megadetector`)

`megadetector_reviewed.json` in batch-output format 1.4, with one entry per
reviewed image, so it can go back into tools that read MegaDetector results.
Each box is a detection with `category` (`1` animal, `2` person, `3`
vehicle), `conf` and a normalized `bbox`. A species label is written as
category `1` plus a `classifications` entry, with the species listed in
`classification_categories`. A box the reviewer drew or changed gets
`conf` 1.0, and its classification also gets 1.0. A detector box they left
as it was keeps the detector's `conf` and the classifier's own score in
`classifications`. Sequence and video items write the imported detections
for each frame, or none when the reviewer chose `empty`.

The file holds one answer per image. When several people reviewed an image,
the first by user id is written, and the export warns; `--option
annotator=<user>` picks one person. Camtrap DP and Darwin Core do the same,
because there a second reviewer's boxes would be a second observation of the
same animal, and GBIF would count it twice. Adjudicate disagreements first, or
pick the reviewer whose answers to publish.

### Camtrap DP (`camtrap_dp`)

A [Camtrap DP](https://camtrap-dp.tdwg.org/) 1.0 data package:
`datapackage.json`, `deployments.csv`, `media.csv` and `observations.csv`,
with the column names of the 1.0 table schemas.

- `media.csv`: one row per image (per frame for sequence items), whether
  reviewed or not, with `mediaID` (the item id), `deploymentID`, `timestamp`,
  `filePath` (the source path), `filePublic` (`false`), `fileName` and
  `fileMediatype`.
- `observations.csv`: for each reviewed item (from one reviewer, as above), one observation
  per box (`observationType` `animal`, `human` or `vehicle`, `scientificName`
  for species labels, `count` 1, `bboxX`/`bboxY`/`bboxWidth`/`bboxHeight` as
  fractions from the top-left corner); one per ticked species that has no
  box; one `blank` observation for an image triaged `empty`; and, when there
  are no boxes and no species, one observation of the triage class.
  `classificationMethod` is `machine` (with `classifiedBy` the detector) for a
  detector box the reviewer left unchanged, and `human` (with `classifiedBy`
  the annotator) otherwise. `classificationProbability` is the classifier's
  score for a species label and the detector's for `animal`, `person` or
  `vehicle`.
  Sequence items give event-level observations (`observationLevel: event`,
  `eventID` the sequence id, `eventStart`/`eventEnd` its first and last
  timestamp).
- `deployments.csv`: one row per deployment, taken from the item's
  `deployment_id`, or else its `location`. `latitude` and `longitude` come
  from item fields of those names. `deploymentStart` and `deploymentEnd` are
  the first and last timestamps.

Camtrap DP requires facts that Potato does not have: the coordinates of
each deployment, a UTC offset on every timestamp, and package metadata. Pass
what you know as export options:

| Option | Fills |
|---|---|
| `timezone` | UTC offset added to timestamps that have none, such as `+02:00` or `Z` |
| `title` | `title` and `project.title` (default: `annotation_task_name`) |
| `contributor` | `contributors` (one entry, role `contact`) |
| `license` | `licenses` (scope `data`) |
| `sampling_design` | `project.samplingDesign` (`simpleRandom`, `systematicRandom`, `clusteredRandom`, `experimental`, `targeted` or `opportunistic`) |
| `capture_method` | `project.captureMethod` and `media.captureMethod` (`activityDetection` or `timeLapse`) |

Anything still missing is listed in the export warnings. Fill it in, for
example the deployment coordinates in `deployments.csv`, and check the
package with a Camtrap DP validator before publishing it.

### Darwin Core (`darwin_core`)

`occurrence.csv` with one Darwin Core occurrence per animal observation that
has a scientific name: `occurrenceID`, `basisOfRecord`, `eventID`,
`eventDate`, `scientificName`, `individualCount`, `occurrenceStatus`
(`present`), `decimalLatitude`, `decimalLongitude`, `geodeticDatum`
(`EPSG:4326` when there are coordinates), `locationID`, `associatedMedia`,
`identifiedBy` and `identificationRemarks`. Animals labelled only `animal`
are left out, since an occurrence needs a scientific name, and the export
says how many.

`basisOfRecord` is `MachineObservation` when the identification is the
detector's and the reviewer left it unchanged, and `HumanObservation` when a
person drew, changed or added it. `--option basis_of_record=HumanObservation`
(or `MachineObservation`) writes the same value on every row.

### An image triaged empty that still has boxes

A reviewer can answer `empty` and leave boxes on the image. The camera-trap
exports and the Darwin JSON export handle this the same way. They write the
boxes, because deleting a box is the reviewer's decision and not the
exporter's, and the export warnings list each such item and annotator. In `megadetector` the boxes are ordinary
detections. In `camtrap_dp` they are box observations with
`observationComments` set to `triaged empty, but the reviewer left this box`,
and no `blank` observation is written. In `darwin_core` the same text goes in
`identificationRemarks`. The Darwin JSON export (`darwin`) writes the boxes
and gives the same warning. The Web Annotation export writes the boxes too.
Fix such items in Potato and export again.

## Example

`examples/image/camera-trap-review/` has eight synthetic frames from two
cameras (deer, a raccoon at night, a person, a vehicle, empty frames) and the
MegaDetector file they were imported from, in `source/`.

```bash
python potato/flask_server.py start examples/image/camera-trap-review/config.yaml -p 8000
```

## Related

- [Image annotation](../annotation-types/multimedia/image_annotation.md)
- [Bioacoustics](bioacoustics.md)
- [Import CLI](../tools/import_cli.md)
- [Export formats](../data-export/export_formats.md)
