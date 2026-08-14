# Import CLI

Turn an existing annotation dataset into a runnable Potato project — a data
file, a config, and a README — in one command.

```bash
potato import --input instances_val2017.json --output-dir my-project
python potato/flask_server.py start my-project/config.yaml -p 8000
```

Fifteen formats are supported. See the
[format matrix](../data-export/format_matrix.md) for what survives each
direction; this page is about running the tool.

!!! important "Imported annotations are pre-annotations"

    They are shown to every annotator as a starting point and are only stored
    once someone saves. An item nobody opens exports as **empty**, not as
    fabricated agreement. Use `--seed-user` only when you deliberately want a
    synthetic annotator (see below).

## Quick reference

```bash
potato import --list-formats            # what is supported
potato import -i FILE   -o DIR          # single-file formats
potato import -i DIR    -o DIR          # directory formats
potato import --hf-dataset cppe-5 -o DIR    # straight from the Hub
```

The format is auto-detected. Pass `--input-format` when detection is wrong or
ambiguous — auto-detection is deliberately conservative and refuses to guess
rather than handing you a silently wrong import.

## Per-format invocations

### Single-file formats

| Format | Command |
|---|---|
| COCO | `potato import -i instances.json -o proj` |
| Darwin (V7) | `potato import -i item.json -o proj` |
| LabelMe | `potato import -i image.json -o proj` |
| VIA | `potato import -i via_project.json -o proj --via-label-key class` |
| Labelbox | `potato import -i export.ndjson -o proj` |

Labelbox exports are **newline-delimited JSON**, not a JSON array. The CLI
detects that and reads them line by line; `json.load` on one fails at line 2
with a message about extra data that reads as file corruption.

### Directory formats

Point at the dataset root, not at a file inside it.

| Format | Command | Detected by |
|---|---|---|
| YOLO | `potato import -i ./dataset -o proj` | `data.yaml` or `labels/` |
| Pascal VOC | `potato import -i ./VOC2012 -o proj` | `.xml` with an `<annotation>` root |
| CVAT | `potato import -i ./export -o proj` | `.xml` with an `<annotations>` root |
| KITTI | `potato import -i ./training -o proj --image-dir ./training/image_2` | `label_2/` |
| MOT | `potato import -i ./MOT17-02 -o proj` | `seqinfo.ini` or `gt/gt.txt` |
| Cityscapes | `potato import -i ./gtFine -o proj` | `*_gtFine_polygons.json` |
| DAVIS | `potato import -i ./DAVIS -o proj` | `Annotations/**/*.png` |
| Open Images | `potato import -i ./oid -o proj` | a CSV with `ImageID,LabelName,XMin` |
| WebDataset | `potato import -i shard.tar -o proj --extract-media ./media` | any readable `.tar` |
| HuggingFace | `potato import -i ./saved-dataset -o proj` | `dataset_info.json` |

CVAT and Pascal VOC are **both XML**, so the file extension decides nothing.
Detection reads the root element instead — guessing from the suffix sent every
CVAT export to the VOC importer, which rejected it with a confusing error.

### From the HuggingFace Hub

```bash
potato import --hf-dataset cppe-5 --hf-split train -o proj
```

Needs `pip install datasets`. Hub datasets store images inline, so they must be
written out and served before the canvas can show them — the import says so.

## The flags that decide whether it works

### `--image-url-prefix` — almost always needed

The generated project stores whatever filename the source used. If no route
serves that path, the canvas shows a broken image and nothing in the UI
explains why.

```bash
# Images served by Potato from <task_dir>/media
potato import -i ann.json -o proj --image-url-prefix /media

# Images hosted elsewhere
potato import -i ann.json -o proj --image-url-prefix https://cdn.example.org/images
```

### `--image-dir` — needed when the format stores absolute pixels

KITTI, VIA and Labelme record coordinates in pixels but not the image
dimensions, so the images must be measured to normalize correctly. Without it
the import assumes 1000×1000, says so loudly, and every annotation lands in the
wrong place.

```bash
potato import -i ./training -o proj --image-dir ./training/image_2
```

Needs Pillow. Formats that store normalized coordinates (YOLO, Open Images) are
unaffected, and formats that carry their own dimensions (COCO, MOT's
`seqinfo.ini`, Cityscapes) never need it.

### `--extract-media` — WebDataset only

Images inside a `.tar` cannot be served. This writes them out:

```bash
potato import -i shard.tar -o proj --extract-media proj/media --image-url-prefix /media
```

### `--via-label-key` — VIA only

VIA's `region_attributes` is whatever the project author defined. The key is
inferred from the project's own attribute declarations and the choice is
reported; pass this to override it. Guessing silently would relabel a corpus.

### `--rle-as-polygon` — lossy, and says so

Traces COCO RLE masks into editable polygons. **Holes are dropped** and the
contour will not re-rasterize to the source mask. Without it, masks import as
masks and stay exact.

### `--keypoints`

COCO keypoint arrays import as ordered keypoint sets with visibility flags.
Off by default because most detection files carry them unpopulated.

### `--seed-user NAME`

Also writes the imported annotations as `NAME`'s saved work. This
**fabricates an annotator** and exists so import→export can be verified without
a human opening every item. Off by default for exactly that reason.

### `--config-only`

Regenerate `config.yaml` without touching an existing data file.

## What gets written

```
my-project/
├── config.yaml          # image_annotation schema with the labels found
├── data/<name>.json     # one JSONL row per image
└── README.md            # what was imported, and every warning
```

The README is **not overwritten** on re-import, so refreshing a data file never
destroys project notes.

Each data row carries `image_width` / `image_height` — exactly the keys
`cv_utils.get_image_dimensions()` reads — so COCO exports carry real sizes and
YOLO's `can_export()` check passes.

## Read the warnings

Every importer reports what it could not carry, and these are not decoration.
Real examples:

- *"complex polygon with 2 hole(s); only the exterior ring was imported"* —
  Potato has no hole concept, and unioning the rings would **fill** the holes.
- *"3 track(s) were imported as one box per frame"* — the identity survives in
  `instance`, but the boxes do not yet move together.
- *"Boxes were read as CORNERS"* — a HuggingFace dataset's `bbox` column does
  not declare its convention, so it is inferred and the conclusion stated.
  Check one item before annotating.
- *"masks are stored as separate authenticated PNG URLs"* — Labelbox does not
  ship mask pixels in its export.

The first 20 print to the console; all of them go into the generated README.

## Troubleshooting

**"could not tell what kind of dataset this is"** — detection found no
signature file. Pass `--input-format`.

**Images do not appear** — you almost certainly need `--image-url-prefix`. Check
what the data file stores under `image_url`.

**Every annotation is in the wrong place** — the import could not measure the
images and fell back to an assumed size. Re-run with `--image-dir` and Pillow
installed; the warning names this explicitly.

**Labels are `class_0`, `class_1`…** — YOLO needs its `data.yaml`, and Open
Images needs `class-descriptions-boxable.csv` beside the annotations.

**"is neither JSON nor newline-delimited JSON"** — the file is a different
container. `.tar` and `.csv` inputs are routed automatically; anything else
needs converting first.

## Related

- [Format matrix](../data-export/format_matrix.md) — what survives each direction
- [Media ingest](../annotation-types/multimedia/media_ingest.md) — for TIFF, HEIC, RAW and unplayable video
- [Image annotation](../annotation-types/multimedia/image_annotation.md)
