# Format Migration

The same two annotated images shipped in **four** annotation formats, so you
can run the conversion yourself and see that the geometry comes out identical.

```
source/
  coco/instances.json          # [x, y, width, height], absolute pixels
  yolo/data.yaml + labels/     # cx cy w h, NORMALIZED and CENTRE-based
  voc/*.xml                    # xmin ymin xmax ymax, CORNERS
  kitti/label_2/*.txt          # x1 y1 x2 y2, CORNERS, 15 fields
media/                         # the images themselves
```

Four different conventions for the same rectangles. Getting any of them wrong
produces a box that is still a box — plausible on screen, wrong in the data —
which is why they are worth converting rather than hand-parsing.

## Run it

```bash
python potato/flask_server.py start examples/image/format-migration/config.yaml -p 8000
```

The imported annotations appear as editable pre-annotations. They are only
stored once an annotator saves, so an item nobody opens exports as empty rather
than as fabricated agreement.

## Convert each source yourself

```bash
cd <repo root>
E=examples/image/format-migration

potato import -i $E/source/coco/instances.json -o /tmp/from-coco  --image-url-prefix /media
potato import -i $E/source/yolo             -o /tmp/from-yolo  --image-url-prefix /media
potato import -i $E/source/voc              -o /tmp/from-voc   --image-url-prefix /media
potato import -i $E/source/kitti            -o /tmp/from-kitti --image-url-prefix /media \
                                            --image-dir $E/source/kitti/image_2
```

No `--input-format` needed: each is detected from its own signature file
(`data.yaml`, `label_2/`, an XML root element). KITTI needs `--image-dir`
because it stores absolute pixels and no image dimensions anywhere — without
it the import assumes a size, says so loudly, and every box lands wrong.

## Check they agree

```bash
python - <<'PY'
import json, glob
def load(d):
    row = [json.loads(l) for l in open(glob.glob(f"{d}/data/*.json")[0]) if l.strip()]
    return {r["file_name"].split("/")[-1].rsplit(".",1)[0]: sorted(
        (round(o["coordinates"]["x"],4), round(o["coordinates"]["y"],4),
         round(o["coordinates"]["width"],4), round(o["coordinates"]["height"],4))
        for o in r.get("predictions",{}).get("image_annotation",[]))
        for r in row}

ref = load("/tmp/from-coco")
for fmt in ("yolo", "voc", "kitti"):
    print(fmt, "identical:", load(f"/tmp/from-{fmt}") == ref)
PY
```

All three print `True`. Potato normalizes every format to one internal contract
— shapes as 0–1 fractions under `coordinates` — defined in exactly one place,
`potato/export/cv_utils.py`.

## Convert back out

```bash
python -m potato.export --config /tmp/from-coco/config.yaml --format yolo   --output /tmp/out-yolo
python -m potato.export --config /tmp/from-coco/config.yaml --format cvat   --output /tmp/out-cvat
python -m potato.export --config /tmp/from-coco/config.yaml --format kitti  --output /tmp/out-kitti
```

Export needs saved annotations, so either annotate an item first or re-import
with `--seed-user reference` — which **fabricates an annotator** and exists
purely so the round trip can be checked without a human opening every item.

## The conventions, side by side

| Format | This dataset's first box | Convention |
|---|---|---|
| COCO | `[60, 120, 140, 190]` | `x, y, width, height` |
| YOLO | `0 0.203 0.448 0.219 0.396` | class, **centre**, normalized |
| VOC | `xmin=60 ymin=120 xmax=200 ymax=310` | **corners** |
| KITTI | `Car ... 60.00 120.00 200.00 310.00 ...` | **corners**, at fields 4–7 |

Read YOLO's centre as a top-left and every box shifts by half its own size.
Read VOC's `xmax` as a width and every box runs too far. Both still look like
boxes.

## What is not here

Masks, polygons, keypoints and polylines — this example is deliberately
boxes-only so the four conventions are directly comparable. For the full
picture of what each format can carry, see the
[format matrix](../../../docs/data-export/format_matrix.md).

## Related

- [Import CLI](../../../docs/tools/import_cli.md)
- [Format matrix](../../../docs/data-export/format_matrix.md)
