# Computer Vision Format Matrix

What Potato can read, what it can write, and which geometry types survive each
direction. If you are deciding whether to migrate a dataset, this is the page.

!!! note "This table is tested"

    `tests/unit/test_format_matrix_accuracy.py` asserts every format named here
    is actually registered, that no registered CV format is missing from the
    table, and that one-way paths are labelled one-way **in both directions** —
    so a format that gains an exporter cannot keep being described as one-way.
    A matrix that can drift from the code is worse than no matrix: it tells
    people a migration will work when it will not, and understating what works
    steers them away from a migration that would have succeeded.

## Import

| Format | Source shape | Boxes | Polygons | Masks | Points | Polylines |
|---|---|:---:|:---:|:---:|:---:|:---:|
| `coco` | single JSON | ✅ | ✅ | ✅ RLE, incl. `iscrowd=1` | ✅ keypoint sets | ❌ |
| `cvat` | CVAT XML 1.1 | ✅ | ✅ | ❌ ⁴ | ✅ points + sets | ✅ |
| `darwin` | V7 JSON v2, one per item | ✅ | ⚠️ ⁵ | ❌ | ✅ skeletons | ✅ |
| `pascal_voc` | one XML per image | ✅ | ❌ ¹ | ❌ ¹ | ❌ | ❌ |
| `yolo` | `data.yaml` + `labels/*.txt` | ✅ | ✅ | ❌ ² | ❌ | ❌ |
| `labelme` | one JSON per image | ✅ | ✅ | ⚠️ ³ | ✅ | ✅ |
| `kitti` | `label_2/*.txt` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `mot` | `seqinfo.ini` + `gt/gt.txt` | ✅ ⁸ | ❌ | ❌ | ❌ | ❌ |
| `cityscapes` | `*_gtFine_polygons.json` | ❌ | ✅ | ❌ ⁹ | ❌ | ❌ |
| `davis` | indexed PNG per frame | ❌ | ❌ | ✅ per instance | ❌ | ❌ |
| `via` | VIA project JSON | ✅ | ✅ | ❌ | ✅ | ✅ |
| `labelbox` | NDJSON export | ✅ | ✅ | ⚠️ ¹⁰ | ✅ | ✅ |
| `openimages` | CSV | ✅ | ❌ | ❌ | ✅ V7 points | ❌ |
| `webdataset` | `.tar` shards | ⚠️ ¹¹ | ⚠️ ¹¹ | ⚠️ ¹¹ | ⚠️ ¹¹ | ⚠️ ¹¹ |
| `huggingface` | Hub id or `save_to_disk` dir | ✅ | ❌ | ❌ | ❌ | ❌ |

¹ Pascal VOC keeps segmentation in a separate `SegmentationObject/` directory of
indexed PNGs, not in the XML. The importer says so in a warning rather than
silently returning boxes only.

² YOLO's segmentation variant stores polygon outlines, which import as polygons.
There is no raster mask in the format.

³ LabelMe's `mask` shape type imports as its polygon outline.

⁴ CVAT's `<mask>` element and its video `<track>` elements are not imported. A
track is one object across frames, which the image schema cannot express;
flattening it to frame 0 would look like a successful import of a dataset that
had quietly lost its video annotations, so it is reported instead.

⁵ V7 "complex polygons" carry holes as extra rings. Potato's polygon has no hole
concept, and unioning the rings would **fill** the holes rather than preserve
them — a plausible-looking wrong answer. The exterior ring is imported and each
dropped hole is reported. V7 image-level `tag` annotations are classifications
rather than regions; they are reported with a pointer to using a radio or
multiselect schema.

⁸ MOT tracks import as **one box per frame**, with the track id kept in each
object's `instance` field. The identity survives and every box is editable, but
they do not yet move together as a single scrubable object.

⁹ Cityscapes' `*_labelIds.png` rasters are derived from the polygons, so the
polygons are the editable source and the PNGs need no separate path.

¹⁰ Labelbox stores each segmentation mask as a separate authenticated PNG URL,
not as pixels in the export. Downloading them needs your API key and an
unbounded fetch during what looks like a local conversion, so the URLs are kept
on each item under `labelbox_mask_urls` and reported. Download them, then import
the PNGs with `--input-format davis`.

¹¹ WebDataset is a **container, not an annotation format**. Sidecars are handed
to whichever importer recognises them, so a WebDataset-wrapped LabelMe file
imports as LabelMe, with LabelMe's conventions and caveats. Whatever that
format supports is what survives.

## Export

| Format | Boxes | Polygons | Masks | Keypoints | Notes |
|---|:---:|:---:|:---:|:---:|---|
| `coco` | ✅ | ✅ | ✅ RLE | ✅ | Preserves original (often sparse) category IDs |
| `yolo` | ✅ | ✅ | ❌ | ❌ | Normalized centre-based boxes |
| `pascal_voc` | ✅ | ❌ | ❌ | ❌ | Corner coordinates |
| `cvat` | ✅ | ✅ | ❌ ⁶ | ⚠️ ⁷ | Also polylines and ellipses — nothing is flattened to a box |
| `labelme` | ✅ | ✅ | ❌ | ⚠️ ⁷ | Also polylines; circular ellipses survive, others become polygons |
| `darwin` | ✅ | ✅ | ⚠️ ¹² | ✅ as keypoints | Also ellipses and lines; stable content-derived ids |
| `kitti` | ✅ | ❌ | ❌ | ❌ | Corners; 3D fields written as the devkit's unset sentinels |
| `mot` | ✅ | ❌ | ❌ | ❌ | Origin+size; writes `seqinfo.ini` so the size survives |
| `cityscapes` | ✅ as 4-gon | ✅ | ⚠️ traced | ❌ | Painter's order preserved — it **is** the occlusion |
| `davis` | ✅ rasterized | ✅ rasterized | ✅ | ❌ | Indexed PNG; pixel values are object ids |
| `mask_png` | — | ✅ | ✅ | — | Rasterized indexed PNGs |
| `episode_jsonl` | — | — | — | — | Per-frame phase, progress reward and outcome for embodied episodes, keyed by `(episode_id, frame_index)` ¹³ |

⁶ CVAT 1.1's `<mask>` uses its own RLE dialect with an offset origin. Emitting
an untested approximation of someone else's binary format would be worse than
saying it is unsupported, so masks are reported and you are pointed at COCO.

⁷ Neither format has an ordered skeleton type. CVAT's `<points>` has no
visibility flag, so unlabelled joints are dropped rather than written at (0, 0)
where they would read back as real points in the corner; LabelMe loses joint
identity entirely. Both report it. Use COCO to keep keypoints intact.

¹³ Not a geometry format: an episode annotation is temporal, so the spatial
columns do not apply. It is a **sidecar** rather than a rewrite of the source
dataset, because the dataset being annotated is usually read-only — see
`docs/annotation-types/embodied/episodes.md`.

¹² Darwin stores masks as `raster_layer`, a dense encoding tied to V7's own
layer model. Rather than write a plausible guess into a file you would upload to
a paid platform, masks are traced to polygons and the loss is reported.

Potato also exports `csv`, `tsv`, `jsonl`, `parquet`, `huggingface`, several
NLP formats and `adjudication`; those carry annotations generically rather than
as CV geometry.

## What survives a round trip

| Path | Lossless? |
|---|---|
| COCO → Potato → COCO | ✅ including crowd RLE, sparse category IDs, and keypoint visibility flags |
| YOLO → Potato → YOLO | ✅ for boxes and polygons |
| Pascal VOC → Potato → Pascal VOC | ✅ for boxes; `difficult` / `truncated` / `occluded` flags are preserved |
| LabelMe → Potato → LabelMe | ✅ for boxes, polygons, polylines, points and circles |
| CVAT → Potato → CVAT | ✅ for boxes, polygons, polylines and ellipses, with label colours and shape attributes intact |
| V7 Darwin → Potato → Darwin | ✅ for boxes, polygons, ellipses, lines and keypoints; holes and raster masks are reported |
| KITTI → Potato → KITTI | ✅ for 2D boxes; `truncated` / `occluded` / `alpha` and the 3D fields ride through untouched |
| KITTI 3D → Potato → KITTI 3D | ✅ exact, with the calibration — see [3D labels](#kitti-3d-labels) |
| MOT → Potato → MOT | ✅ for boxes, track ids, ignore regions and visibility |
| Cityscapes → Potato → Cityscapes | ✅ for polygons, crowd `group` labels and painter's order |
| DAVIS → Potato → DAVIS | ✅ for per-instance masks and stable object ids |
| `labelbox` → Potato | ⚠️ one-way — no exporter |
| `openimages` → Potato | ⚠️ one-way — no exporter |
| `via` → Potato | ⚠️ one-way — no exporter |
| `webdataset` → Potato | ⚠️ one-way — no exporter |
| CVAT masks / video tracks | ⚠️ not read on import, not written on export |
| COCO → Potato → YOLO | ⚠️ lossy: masks have no YOLO representation |

### Conversions worth knowing about

**Ellipses** export as a 36-vertex polygon approximation, so any format that
understands polygons accepts them. The parametric form is preserved inside
Potato, so re-importing your own export loses precision but editing in place
does not.

**Polylines** have `area: 0` and are never converted to a closed region.
Formats with no open-path concept simply omit them rather than fabricating one.

**Keypoint sets** round-trip through COCO's `keypoints` array with visibility
flags intact. In formats with no keypoint concept they are dropped with a
warning, not silently flattened into loose points.

**Masks to outlines** (Cityscapes, Darwin) is genuinely lossy: holes are
dropped and the traced contour will not re-rasterize to the source pixels.
Every exporter that does this reports it and names COCO as the lossless route.

## Coordinate conventions

The ones that produce a *plausible* wrong answer when misread, and are
therefore worth stating:

| Format | Box convention |
|---|---|
| COCO | `[x, y, width, height]`, absolute pixels, top-left origin |
| YOLO | `cx cy w h`, **normalized, centre-based** — reading as `x y w h` shifts every box by half its own size |
| Pascal VOC | `xmin ymin xmax ymax`, **corners** — reading `xmax` as a width makes every box run too far |
| LabelMe rectangle | **two opposite corners**, in whichever order the user dragged |
| CVAT | `xtl ytl xbr ybr`, **corners**, like VOC |
| V7 Darwin | `x y w h`, origin plus size, like COCO |
| KITTI | `x1 y1 x2 y2`, **corners** — and it sits next to MOT, which does not |
| MOT | `bb_left bb_top bb_width bb_height`, **origin plus size** — the opposite of KITTI |
| Open Images | `XMin XMax YMin YMax` — **both X values first**, normalized; every other CSV format here interleaves them |
| Labelbox | `{top, left, height, width}` — named differently from everything else, so reading `top` as `x` transposes every box |
| VIA ellipse | `theta` is in **radians**; Potato stores degrees |

Potato stores shapes normalized to 0–1 under `coordinates`; masks stay absolute
RLE. `potato/export/cv_utils.py` is the single definition of that contract.

## KITTI 3D labels

3D annotations are the one place with a **second** coordinate contract, because
a cuboid is in metres in a sensor frame with an orientation and there is no
image to normalize against. `potato/export/spatial_utils.py` defines it; the
KITTI conversion lives in `potato/export/kitti3d.py` and needs the sequence's
`calib` file.

Four things in the format are easy to get wrong, and all four bite silently:

| | KITTI | Read naively |
|---|---|---|
| Frame | Rectified **reference** camera | Using a camera's own matrix shifts every box by that camera's stereo baseline |
| Location | Centre of the **bottom face** | Read as the centre, every object sinks half its height |
| Dimensions | `h w l`, with **length along the box's local X** and width along Z | Assuming length runs along camera +Z rotates every box exactly 90° |
| Rotation | A single yaw about camera Y | Hard-coding `yaw = −ry − π/2` is right for the standard rig and wrong, silently, for any other |

Potato derives the rotation from the calibration matrices rather than from that
constant, so a non-standard rig converts correctly and the standard one
reproduces the familiar number.

**Direction of loss.** KITTI → Potato is lossless: the *full* rotation is
carried across, including the roughly 0.85° at which the standard rig's camera
is mounted relative to its lidar — a box that is level in the camera frame is
genuinely tilted in the lidar frame, and storing only a yaw would throw that
away. Potato → KITTI discards pitch and roll, because the format has nowhere to
put them; the exporter reports how much rotation each box lost rather than
writing a flat box and saying nothing.

## Importing

```bash
potato import annotations.json --output-dir my-project     # auto-detects
potato import --input-format yolo ./yolo-dataset --output-dir my-project
potato import --hf-dataset cppe-5 --output-dir my-project
potato import --list-formats
```

Most CV formats are **directory-based** — point at the dataset root, not a
single file. COCO, Darwin, LabelMe, VIA and Labelbox are also readable as a
single file. See the [Import CLI guide](../tools/import_cli.md) for per-format
invocations and the flags each one needs.

## Related

- [Image Annotation](../annotation-types/multimedia/image_annotation.md)
- [Import CLI](../tools/import_cli.md)
- [Media ingest](../annotation-types/multimedia/media_ingest.md)
