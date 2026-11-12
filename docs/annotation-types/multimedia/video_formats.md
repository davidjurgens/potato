# Video Annotation Formats

What Potato reads and writes for video, and where a video dataset's structure
survives the trip.

The short version: video tracking datasets import as **one item per frame**,
with the track identity preserved in each object's `instance` field. Every box
is editable and the identity that links them across frames survives — but they
do not yet move together as a single scrubable object inside the annotation UI.
The import says so rather than implying otherwise.

## Import

| Format | Source shape | What comes in |
|---|---|---|
| `mot` | `seqinfo.ini` + `gt/gt.txt` | Boxes per frame, track ids, ignore regions, visibility |
| `davis` | `Annotations/<seq>/*.png` | Per-instance masks per frame, stable object ids |
| `cvat` | CVAT XML 1.1 | Images only — `<track>` elements are **reported, not flattened** |

```bash
potato import -i ./MOT17-02 -o my-project --image-url-prefix /media
potato import -i ./DAVIS    -o my-project --image-url-prefix /media
```

Neither needs `--image-dir`: MOT carries its image dimensions in `seqinfo.ini`,
and a DAVIS mask PNG is the same size as its frame.

### Why CVAT tracks are refused rather than imported

A CVAT `<track>` is one object across many frames. Flattening it to frame 0
would look like a successful import of a dataset that had quietly lost its
video annotations — the worst of the available outcomes. The importer counts
the tracks and says so.

## Export

| Format | Writes |
|---|---|
| `mot` | `<sequence>/seqinfo.ini` + `<sequence>/gt/gt.txt` |
| `davis` | `Annotations/<sequence>/<frame>.png`, indexed |
| `coco` | One image entry per frame, carrying `sequence` and `frame_id` |

```bash
python -m potato.export --config config.yaml --format mot   --output ./out
python -m potato.export --config config.yaml --format davis --output ./out
```

Items carry `sequence` and `frame` (as the importers set them), and the
exporters group and number by those. An item with no recorded frame is numbered
in order **starting at 1** — never 0, which every MOT evaluator drops.

## The conventions that bite

| Format | Box | Frame index | Notes |
|---|---|---|---|
| MOT | `bb_left bb_top bb_width bb_height` — origin+size | **1-indexed** | `conf=0` means *exclude from evaluation*, not *low confidence* |
| KITTI | `x1 y1 x2 y2` — **corners** | per-file | Sits in the same pipelines as MOT and uses the opposite convention |
| DAVIS | n/a (raster) | 0-indexed filenames | Pixel **values** are object ids; 255 is void |

Three specific ways to lose data silently, each handled explicitly:

- **MOT's `conf` column.** In ground truth, 0 means the region is excluded from
  evaluation. Writing a real confidence score into that column converts
  uncertain annotations into ignore regions. Potato sets it from an explicit
  `ignore` flag only.
- **MOT track ids.** A `gt.txt` with id `-1` is a *detection* file, not ground
  truth, and evaluators treat the two very differently. Objects with no id get
  fresh ones rather than `-1`, and the export reports how many.
- **DAVIS indexed PNGs.** The pixel values are the object ids; the palette
  merely makes the file look sensible in an image viewer. Saving RGB renders
  identically and is unreadable as a mask — Potato writes mode `P` and there is
  a test that reads the pixel values back rather than comparing the rendering.

## Video files the browser cannot play

MOV, MKV, ProRes, HEVC and friends are transcoded on demand. See
[Media ingest](media_ingest.md). The failure without it is silent: the player
loads, reports nothing, and never paints a frame.

## Related

- [Video annotation](video_annotation.md)
- [Format matrix](../../data-export/format_matrix.md)
- [Import CLI](../../tools/import_cli.md)
- [Media ingest](media_ingest.md)
