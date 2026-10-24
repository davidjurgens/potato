# Import CLI

Turn an existing annotation dataset into a runnable Potato project — a data
file, a config, and a README — in one command.

```bash
potato import --input instances_val2017.json --output-dir my-project
python potato/flask_server.py start my-project/config.yaml -p 8000
```

Forty-five formats are supported:

- sixteen computer-vision dataset formats, the Hugging Face Hub among them;
- six text and qualitative ones (brat, doccano, Prodigy, CoNLL, REFI-QDA, TEI);
- sixteen whole-project formats, which bring questions, annotators and model
  suggestions across together: Label Studio, Argilla, Zooniverse, Ibex and
  PCIbex, TextGrid, ELAN, FLExText, Toolbox, MegaDetector, COCO Camera Traps,
  Raven, Audacity labels, BirdNET, IIIF, W3C Web Annotation and PAGE XML;
- seven survey formats (see [Importing surveys](survey_import.md)), Network
  Canvas among them. See the
[format matrix](../data-export/format_matrix.md) for what survives each
direction, and
[Bringing a Project Into Potato](../guides/migrating-into-potato.md) for the
per-tool walkthrough; this page is about running the tool.

Text formats are detected the same way and take the same flags, plus three of
their own:

| Flag | Format | What it does |
|---|---|---|
| `--conll-document-unit` | CoNLL | What counts as one item: `auto`, `sentence`, `file` |
| `--qdpx-end-position` | REFI-QDA | Force `inclusive` or `exclusive` instead of inferring it |
| `--prodigy-keep-rejected` | Prodigy | Import tasks answered `reject`/`ignore`, which are dropped by default |

Two more apply to the formats that carry people's answers:

| Flag | Format | What it does |
|---|---|---|
| `--ls-config XML` | Label Studio | The project's labeling config. Without it the questions are inferred from the answers, and options nobody chose are lost |
| `--keep-annotators` | Label Studio, Argilla, Zooniverse, W3C Web Annotation | Write each source annotator's answers as that person's saved work (see below) |

The research-tool formats take these:

| Flag | Format | What it does |
|---|---|---|
| `--md-threshold CONF` | MegaDetector | Lowest detection confidence to import (default 0.2) |
| `--sequences` | MegaDetector, COCO Camera Traps | One item per camera-trap sequence (`seq_id`), shown as a gallery |
| `--min-confidence CONF` | BirdNET | Lowest detection confidence to import (default 0.1) |
| `--label-column COLUMN` | Raven | Which selection-table column holds the label |
| `--texts PATH` | W3C Web Annotation | A folder or JSONL of the texts the annotations target |
| `--page-xml-mode lines\|regions` | PAGE XML | One item per text line to correct (default), or one per page to correct the layout |
| `--iiif-size SIZE` | IIIF | Image size to request from an IIIF Image service, such as `max` or `!2000,2000` |
| `--tei-unit p\|div\|s\|l` | TEI | What counts as one item (default `p`) |

Their guides: [Coming from Ibex](../guides/coming-from-ibex.md),
[Linguistic fieldwork](../guides/linguistic-fieldwork.md),
[Camera traps](../guides/camera-traps.md),
[Bioacoustics](../guides/bioacoustics.md),
[Digital humanities formats](../guides/digital-humanities.md).

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
potato import -i survey.qsf -o DIR      # a survey: see Importing surveys
potato import -i survey.lss --into config.yaml   # add a survey to a project
```

Surveys (Qualtrics, SurveyJS, LimeSurvey, XLSForm, REDCap, Beiwe, Network
Canvas) have their own page: [Importing surveys](survey_import.md). Zooniverse projects take
`--zooniverse-workflow`, `--zooniverse-subjects`, `--workflow-id` and
`--workflow-version`; see [Coming from Zooniverse](../guides/coming-from-zooniverse.md).

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
| KITTI tracking (lidar) | `potato import -i ./kitti_tracking -o proj --schema-name objects` | `label_02/` |
| MOT | `potato import -i ./MOT17-02 -o proj` | `seqinfo.ini` or `gt/gt.txt` |
| Cityscapes | `potato import -i ./gtFine -o proj` | `*_gtFine_polygons.json` |
| DAVIS | `potato import -i ./DAVIS -o proj` | `Annotations/**/*.png` |
| Open Images | `potato import -i ./oid -o proj` | a CSV with `ImageID,LabelName,XMin` |
| WebDataset | `potato import -i shard.tar -o proj --extract-media ./media` | any readable `.tar` |
| HuggingFace | `potato import -i ./saved-dataset -o proj` | `dataset_info.json` |

A KITTI tracking import needs `label_02/`, `velodyne/` and `calib/` in one
folder (`training/` or `testing/`, or the folder above them). It writes a
point-cloud project with one item per sequence, the scans listed in order and
each labelled object a keyframe of its track; see
[Point clouds: importing KITTI tracking labels](../annotation-types/spatial/point_cloud.md#importing-kitti-tracking-labels).

CVAT and Pascal VOC are **both XML**, so the file extension decides nothing.
Detection reads the root element instead — guessing from the suffix sent every
CVAT export to the VOC importer, which rejected it with a confusing error.

### From the HuggingFace Hub

```bash
potato import --hf-dataset cppe-5 --hf-split train -o proj
```

Needs `pip install datasets`. Hub datasets store images inline, so they must be
written out and served before the canvas can show them — the import says so.

An Argilla dataset pushed with `to_hub` is read the same way, with `-f argilla`:

```bash
potato import -f argilla --hf-dataset my-org/my-feedback -o proj --keep-annotators
```

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

The seeded annotator is assigned every item it holds work for, so progress and
assignment read the project as annotated rather than as untouched.

### `--keep-annotators`

Label Studio, Argilla, Zooniverse and W3C Web Annotation only. Writes each
source annotator's answers as that person's saved work under
`annotation_output/<name>/`, and adds each of them to the roster, so
`/admin/iaa` reports agreement as soon as the server starts.
Unlike `--seed-user` this invents nobody: the answers are real people's.

It also sets `max_annotations_per_item` to the number of people the source study
meant each item to get: Argilla's `distribution.min_submitted`, or for the
other formats, which do not export an overlap setting, the most annotators any
item has. Items the source study finished therefore count as complete, which is what
`/admin/iaa` needs to score them, and new annotators are given the rest. Raise
the value to collect more judgements per item.

The imported people have no Potato passwords, so the generated config sets
`require_password: false` and the roster rows carry no password. It also closes
enrolment: `user_config.allow_all_users` is false and `user_config.users` lists
the imported names, so nobody else can register. Add new annotators to that
list. Before you deploy the project, set `require_password: true` and add a
password to each row of `annotation_output/user_config.json`: until you do,
`potato deploy` refuses a public deployment (finding D022), because anyone who
knows a name could sign in as that person and change their work.

Without the flag, people's answers are left out and only model suggestions come
across, as pre-annotations.

### `--config-only`

Regenerate `config.yaml` without touching an existing data file.

## Provenance

Every imported shape is stamped `source: import`, along with the format it came
in as `import_format`. A file that already records where a shape came from
keeps what it says, so a COCO file Potato itself exported survives the round
trip with its human/model split intact. A detector's own score arrives as
`confidence` whatever the source format calls it: `score` in COCO, the
sixteenth column in KITTI, `Confidence` in Open Images, `conf` in MOT.

The importer refuses to write a project in which any shape has no `source`. An
imported box and a hand-drawn one are otherwise identical once stored, so
without this the export reports every imported shape as annotation effort.

See [Where a shape came from](../annotation-types/multimedia/image_annotation.md#where-a-shape-came-from).

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
