# COCO Import Example

Correcting annotations imported from a COCO file, rather than annotating from
scratch.

`data/annotations/instances_sample.json` deliberately exercises **every**
segmentation encoding that appears in real COCO files, so it doubles as a
fixture for the round-trip test:

| Image | Annotations |
|-------|-------------|
| `street.jpg` | a bbox-only annotation (`segmentation: []`) and a single-ring polygon |
| `park.jpg` | a two-ring polygon (outer + hole), plus two `person` instances — one as **uncompressed RLE**, one as a **compressed RLE string** |
| `crowd.jpg` | an `iscrowd: 1` crowd region, the encoding some platforms drop on import |

Category IDs are **sparse** (`1`, `18`, `90`), as in COCO 2017.

## Run it

```bash
python potato/flask_server.py start examples/image/coco-import/config.yaml -p 8000
```

The imported annotations appear pre-populated on each image. Correct them as
normal; your edits replace the imported ones as soon as you save.

## How this project was generated

```bash
potato import \
    --input data/annotations/instances_sample.json \
    --output-dir . \
    --schema-name object_detection \
    --image-url-prefix /media
```

That produced `config.yaml` and `data/instances_sample.json`. Re-run it to
regenerate after editing the source COCO file — it will not overwrite this
README.

## Where the images live

The images sit in `media/`, and the data file points at them as `/media/*.jpg`.
Potato serves `<task_dir>/media` at the `/media/` URL, so no external image
host is needed. Images referenced by absolute URL work too — pass the host as
`--image-url-prefix` instead.

## Export back to COCO

```bash
python -m potato.export -c examples/image/coco-import/config.yaml -f coco -o ./export/
```

Sparse category IDs survive the round trip because the generated config records
each original ID as `label_id` on the label.

Imported annotations are *pre-annotations*: they are shown to every annotator
but not stored until someone saves, so an item nobody has opened exports as
empty. That is deliberate — writing them into a user's saved work would make
machine output indistinguishable from human annotation and fabricate agreement
between annotators who never touched the item. Use `--seed-user` if you need an
import→export cycle with no human involved.

## What to look at

- Both `person` masks on `park.jpg` stay **separate** (keyed `person#0` and
  `person#1`). Merging them by label would destroy instance segmentation.
- The crowd region on `crowd.jpg` is imported, not skipped, and exports again
  as `iscrowd: 1`.
- The two-ring polygon on `park.jpg` becomes two polygons — the rings survive,
  their grouping into one annotation does not.

## Related documentation

- [Image Annotation Formats](../../../docs/annotation-types/multimedia/image_formats.md)
- [Image Annotation](../../../docs/annotation-types/multimedia/image_annotation.md)
