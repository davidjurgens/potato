# Deep Zoom & Tiling

Annotating an image that is too large to send to a browser as one file — an
aerial survey, a stitched microscopy mosaic, a scanned map. Potato serves a
**tile pyramid** and layers the annotation canvas over it, so boxes, polygons
and masks all work at any magnification.

```yaml
annotation_schemes:
  - annotation_type: image_annotation
    name: structures
    description: "Mark every structure"
    source_field: image
    viewer: deepzoom          # the default is `fabric`
    tools: [bbox, polygon, brush, eraser]
    labels:
      - {name: building, color: "#c0392b"}
```

`media_directory` is where the tile routes read from; paths in your data file
are relative to it.

Runnable example: [`examples/image/deep-zoom/`](https://github.com/davidjurgens/potato/tree/master/examples/image/deep-zoom).

---

## When to use it

| | `viewer: fabric` (default) | `viewer: deepzoom` |
|---|---|---|
| How the image arrives | one file | tiles, on demand |
| Extra download | none | 277 KB (OpenSeadragon) |
| Server work per item | none | one decode per magnification visited |
| Good for | photographs, screenshots, ordinary images | tens of megapixels and up |

**Deep zoom is worse than the default for an ordinary image.** It adds a
library, a build cost and a request per screenful to solve a problem a
2-megapixel photograph does not have. Turn it on when the browser struggles
with the source as a single file.

---

## Configuration

```yaml
    viewer: deepzoom
    tiles:
      tile_size: 254        # DZI's default; 254 + 1px overlap = a 256px tile
      overlap: 1            # pixels of neighbour included on each side
      max_pixels: 640000000 # refuse to build a level larger than this
      page: 0               # which page of a multi-page TIFF
      navigator: true       # the thumbnail overview, bottom right
```

**Overlap is not optional padding.** Without it, bilinear filtering at a tile's
edge samples beyond the tile and the browser draws a visible grid over your
image — which annotators read as image content.

---

## What the server does

Three routes, registered alongside the other media routes:

| Route | Purpose |
|---|---|
| `GET /media/tiles/<path>.dzi` | The DZI descriptor. `?format=json` returns the same geometry as JSON. |
| `GET /media/tiles/<path>_files/<level>/<col>_<row>.jpg` | One tile. |
| `GET /media/iiif/<path>/info.json` and `/<region>/<size>/<rotation>/<quality>.<fmt>` | The same pyramid over the IIIF Image API 3.0, for Mirador and other IIIF clients. |

### Levels are built whole, and lazily

Two obvious designs are both wrong here:

- **Pre-generate everything on first request.** A 4-gigapixel source is ~60,000
  tiles and several minutes of blank screen, most of it for magnifications
  nobody will visit.
- **Generate each tile on demand.** Pillow has no cheap random access into most
  formats, so cropping one 254 px tile decodes the whole image — and a
  screenful is ~30 tiles.

So a **level** is built as a unit the first time any of its tiles is requested:
the source is decoded once, resized, and every tile of that level written in one
pass. Zooming to a magnification costs one decode; panning around at that
magnification costs nothing; a level nobody visits is never built.

Tiles live in the media cache under `<output_dir>/.media_cache/`, keyed by the
source's path, size and mtime plus the tile parameters — so editing the source
produces a new key and the stale render is never served. Deleting the cache
costs a rebuild and nothing else.

### Level numbering

DZI numbers levels from **0 = smallest**: level 0 is a single tile of at most
`tile_size` pixels and each level doubles, so the top level is the image at full
resolution. A 40000×30000 image has 16 levels. This is inverted from how most
people describe zoom, and it is where tile-server off-by-ones live.

### The pixel ceiling refuses rather than downgrades

Building a level holds that level's image in memory. Above `tiles.max_pixels`
the build is refused with a message naming the limit and the setting.

The alternative — quietly serving a lower level — would let the annotator draw
on a blurred approximation and produce coordinates that are wrong in a way
nothing downstream can detect. The ceiling governs *building*: a level already
on disk is still served if you lower the setting afterwards.

---

## How annotation works over tiles

There is no single image object to draw against — there are thousands of tiles
that appear and vanish as you move. So the mode inverts the usual arrangement:

- **the annotation canvas draws in image-pixel coordinates**, and
- the whole canvas is transformed by OpenSeadragon's viewport.

The upshot is that a box drawn zoomed in stays glued to the same part of the
image at every other magnification, and every existing coordinate calculation —
normalization, mask indexing, the export contract — is correct without a second
implementation for the tiled case.

**Masks work, and they do not depend on the GPU.** The mask buffer indexes
*image pixels*, at the source's full resolution rather than at whatever size the
image happened to be displayed at, so a mask painted zoomed in is directly
comparable with one painted zoomed out — and nothing about it is bounded by a
texture limit.

That last part is the practical difference from a WebGL-backed painter. V7, for
example, tiles automatically above 10,000 px and lets you annotate a tiled file
as one image, but its masking is
[disabled once the image exceeds what the device's WebGL implementation
supports](https://docs.v7labs.com/docs/introducing-masks) — commonly
16,384 × 16,384 — and shows a warning instead. That is a device limit rather
than a product decision, which is exactly why it is not something a user can
work around.

### The pointer

OpenSeadragon and the annotation canvas both want the mouse, so the overlay
follows the armed tool: a drawing tool takes the pointer, select/move (`v`)
gives it back so you can pan. The scroll wheel always zooms, even with a brush
selected.

---

## Limits

- **Whole-slide formats (SVS, NDPI) are not handled.** They carry their own
  pyramids and should be read through `openslide` rather than rebuilt. That is
  the deferred medical-imaging track.
- **Region-aware fill falls back to `empty` mode.** The `region` fill reads the
  source's pixels to grow across similar colours, and in this mode there is no
  single source image in the page to read.
- **Pillow is required.** Without it the viewer reports what is missing and
  suggests `viewer: fabric`; it does not fail silently.

---

## Air-gapped deployments

OpenSeadragon is **vendored** (`potato/static/vendor/`), like fabric.js and
three.js, and is loaded only for schemas that ask for `viewer: deepzoom`. No
part of deep zoom reaches the internet.

Note that the rest of the application is not yet fully air-gap clean — see
[Air-gapped deployment](../../deployment/air_gap.md) for what still is not.

---

## Related

- [Image annotation](image_annotation.md)
- [Media ingest](media_ingest.md) — TIFF, HEIC and RAW conversion
- [Scaling & large datasets](../../deployment/scaling.md)
- [Air-gapped deployment](../../deployment/air_gap.md)
