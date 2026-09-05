# Image Annotation Formats

Potato reads and writes the common computer-vision interchange formats. A COCO
file can be imported **as-is** — every segmentation encoding, including crowd
regions — annotated or corrected in the browser, and exported back out.

## Supported import formats

| Format | Geometry read |
|--------|---------------|
| **COCO JSON** | bounding boxes, polygon segmentation (single and multi-ring), uncompressed RLE, compressed RLE strings, crowd regions, keypoints (opt-in) |

## Supported export formats

| Format | Geometry written |
|--------|------------------|
| **COCO JSON** | bbox, polygon `segmentation`, RLE `segmentation` |
| **YOLO** | bbox (other shapes reduced to their enclosing box) |
| **Pascal VOC** | bbox (other shapes reduced to their enclosing box) |
| **Mask PNG** | one PNG per label |

See [Export Formats](../../data-export/export_formats.md) for the export CLI.

## Quick start

```bash
# 1. Turn a COCO file into a runnable Potato project
potato import --input instances_val2017.json \
    --image-dir /data/val2017 \
    --image-url-prefix /files \
    --output-dir my-project/ \
    --schema-name object_detection

# 2. Annotate
python potato/flask_server.py start my-project/config.yaml -p 8000

# 3. Export back to COCO
python -m potato.export -c my-project/config.yaml -f coco -o ./export/
```

`python -m potato.importers` is equivalent to `potato import` if you are running
from a source checkout.

## The four COCO segmentation encodings

COCO files in the wild use all of these, often in the same file. No conversion
step is required for any of them.

| Input | Becomes |
|-------|---------|
| `"segmentation": [[x1, y1, x2, y2, ...]]` | a polygon |
| `"segmentation": [[...], [...]]` (multi-ring) | one polygon **per ring** |
| `"segmentation": {"counts": [ints], "size": [h, w]}` | a mask |
| `"segmentation": {"counts": "ascii", "size": [h, w]}` | a mask |
| `"segmentation": []` or absent, with `bbox` | a bounding box |

Compressed `counts` strings are decoded with a pure-Python port of
pycocotools' `rleFrString`; **pycocotools is not a dependency.**

## Crowd regions

Canonical COCO pairs `iscrowd: 1` with RLE segmentation. Potato imports those
annotations rather than skipping them.

- `iscrowd: 1` regions of the same category **merge into one mask** per image.
  COCO permits at most one crowd annotation per category per image, and a crowd
  region is already an unlabeled blob. They export again as `iscrowd: 1`.
- `iscrowd: 0` RLE annotations each keep their own instance index and export as
  N separate annotations.

## Instances vs. labels

Brush masks are keyed by **label**: every stroke of one class merges into a
single region. That is semantic segmentation.

Imported non-crowd RLE annotations are keyed by **label and instance**, so two
adjacent instances of one class stay separate through a save/reload cycle and
export as two annotations.

The current limitation: you can see, move between, and preserve imported
instance masks, but painting always edits the label-level mask. Brushing will
not add pixels to a specific imported instance.

## Category IDs

COCO category IDs are frequently sparse — COCO 2017 runs from 1 to 90 with gaps.
The generated config records each original ID as `label_id` on the label:

```yaml
labels:
  - name: person
    color: '#e6194b'
    label_id: 1
    supercategory: person
  - name: dog
    color: '#3cb44b'
    label_id: 18
    supercategory: animal
```

The COCO exporter honours `label_id`, so a file keeps its original numbering
through a round trip. Labels without a `label_id` are assigned IDs above the
highest explicit one, so they never collide.

## Image dimensions on import

COCO coordinates are absolute pixels; Potato stores them normalized to 0–1. The
importer therefore needs each image's size and **fails loudly** if it is missing
rather than writing zeros:

```
Image 'street.jpg' has no usable width/height in images[] ...
```

Two fixes: repair the `images[]` entries, or pass `--image-dir` so sizes are
read from the files directly (needs Pillow).

The generated data file carries `image_width` / `image_height` on every row,
which is what the exporters read first. A data file written by hand usually
does not, so when the fields are absent the exporters derive the size: from a mask's
own RLE, or by reading the image. Carrying them is still worth it: it is
faster, and it is the only thing that works when the images live somewhere the
exporter cannot read.

## How imported annotations reach annotators

Imported annotations are loaded as **pre-annotations**:

```yaml
pre_annotation:
  enabled: true
  field: predictions
  allow_modification: true
```

Every annotator sees them as a starting point. As soon as someone saves, their
corrections replace the imported ones permanently.

They are deliberately **not** written into any user's saved annotations. Doing
that would make machine output indistinguishable from human work, and with
several annotators an untouched item would export as multiple identical
"independent" annotations — fabricating perfect agreement in the subsystem
Potato is most used for.

The consequence to be aware of: an item nobody has opened exports as empty. Use
`--seed-user NAME` if you need an import→export cycle with no human in the loop;
it says plainly that it fabricates an annotator.

## Options

| Flag | Effect |
|------|--------|
| `--input-format` | Force a format instead of auto-detecting |
| `--image-dir` | Read missing image sizes from the files (needs Pillow) |
| `--image-url-prefix` | Prefix joined to each `file_name` to build the served URL |
| `--schema-name` | Name of the generated annotation scheme |
| `--keypoints` | Import COCO keypoints as landmarks, one per visible point |
| `--rle-as-polygon` | Trace masks into polygons (**lossy**, see below) |
| `--no-merge-crowd` | Keep each crowd region separate |
| `--config-only` | Regenerate `config.yaml` without touching the data file |
| `--seed-user NAME` | Also write the annotations as NAME's saved work |

### `--rle-as-polygon` is lossy

Off by default, and worth understanding before using:

- Holes are dropped; a single outer ring cannot represent them.
- The traced contour will not re-rasterize to exactly the source bitmap.
- Boundaries follow pixel centres, so they sit half a pixel inside the mask.

Use it when annotators need to drag vertices and you accept the fidelity loss.
Otherwise keep masks as masks — they round-trip pixel-exactly.

## Round-trip guarantees

| Geometry | Guarantee |
|----------|-----------|
| Masks (RLE) | **Exact pixel equality.** Counts pass through as integers. |
| Bounding boxes | Within `1e-6` relative |
| Polygon vertices | Within `1e-6` relative, vertex count exact |
| Categories | Exact, including sparse IDs and `supercategory` |
| Image metadata | `file_name`, `width`, `height` exact |

The tolerance on shapes exists because coordinates are stored normalized, so a
round trip is a float division followed by a multiplication
(`10 / 640 * 640 == 10.000000000000002`).

Two documented many-to-one cases:

- A multi-ring polygon becomes one annotation per ring.
- Crowd regions of one category merge into a single annotation.

## Troubleshooting

**"could not detect the format"** — pass `--input-format coco`. Auto-detection
requires `images[]` and `annotations[]` arrays with `id` and `file_name`.

**Exported boxes are all `[0, 0, 0, 0]`** — the data file is missing
`image_width` / `image_height`. Versions before this feature also had an
exporter bug with the same symptom; see
[Export Formats](../../data-export/export_formats.md).

**Masks look like diagonal streaks** — the image being served is a different
size from the one the annotations were made against. The client rescales and
logs a console warning; fix the served image to remove the warning.

**A mask saved before v2.9 comes back inverted, or a full-canvas fill comes
back empty** — masks are stored as run lengths that alternate background,
foreground, background, …, always starting with background. Client versions
before v2.9 suppressed a leading zero-length background run, so any mask whose
**top-left pixel was painted** was written with its runs one position out of
phase, and a completely painted mask was indistinguishable from an empty one.

Masks that do not touch the top-left pixel — which is nearly all object
masks — were never affected. Affected masks cannot be repaired automatically:
the corrupt form is a legitimate encoding of a different mask, so nothing in
the file distinguishes them. Repaint the affected masks, or invert them
manually if you know they were whole-image fills. New saves are correct.

**An exported file is empty** — imported annotations are pre-annotations and
only persist once an annotator saves. See above.

## Related documentation

- [Image Annotation](image_annotation.md) — the annotation UI and schema options
- [Export Formats](../../data-export/export_formats.md) — the export CLI
- [Data Format](../../configuration/data_format.md) — `data_files` and `item_properties`
- [Quality Control](../../workflow/quality_control.md) — the `pre_annotation` block
