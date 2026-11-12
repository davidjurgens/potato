# Deep zoom: annotating an image too large to send to a browser

A 6000×4000 survey image, served as a tile pyramid through OpenSeadragon with
the annotation canvas layered over it. Boxes, polygons and **masks** all work,
at any magnification.

```bash
# from the repository root
python examples/image/deep-zoom/generate_image.py    # needs Pillow
python potato/flask_server.py start examples/image/deep-zoom/config.yaml -p 8000
```

The image is generated rather than committed: 9 MB of PNG for a picture whose
only job is to be big is not worth the repository space, and the example is
about the viewer.

## What to look at

- **Zoom in.** The image has two grids — a coarse one visible at fit-to-screen
  and a fine 20-pixel one that is not. If you can see the fine grid without
  zooming, you are not looking at full resolution. Most of the 400 structures
  are a few pixels across and only become distinguishable at magnification.
- **The network tab.** Panning fetches individual tiles, not the image. The
  first visit to a magnification is slow (one decode builds that whole level);
  panning around at that magnification afterwards is not.
- **Draw at one zoom, check at another.** A box drawn zoomed in stays glued to
  the same part of the image when you zoom out. That is the one property this
  feature lives or dies by.
- **Paint a mask.** V7 documents mask annotation on tiled images as
  unsupported. It works here, and the mask is indexed at the source's full
  6000×4000 resolution — not at the size it happened to be displayed at, which
  would make it incomparable with a mask drawn at a different zoom.

## Configuration

```yaml
annotation_schemes:
  - annotation_type: image_annotation
    viewer: deepzoom        # default is `fabric`, the single-image viewer
    tiles:
      tile_size: 254        # 254 + 1px overlap each side = a 256px tile
      overlap: 1
      max_pixels: 640000000
      navigator: true
```

`media_directory` is where the tile server reads from; paths in the data file
are relative to it.

## When *not* to use it

`viewer: deepzoom` is worse than the default for ordinary photographs. It adds a
277 KB library, a per-level build cost, and a tile request per screenful, in
exchange for solving a problem a 2-megapixel image does not have. Reach for it
when the source is large enough that the browser struggles with it as one file
— tens of megapixels and up.

## Limits

- Levels are built with Pillow, which decodes the whole source. Above
  `tiles.max_pixels` the build is **refused** with a message rather than
  silently serving a lower level, because drawing on a blurred approximation
  produces coordinates nothing downstream can detect as wrong.
- Whole-slide formats (SVS, NDPI) carry their own pyramids and should be read
  with `openslide` rather than rebuilt. That is the deferred medical-imaging
  track, not this.
- Region-aware fill needs to read the source's pixels and there is no single
  source image in this mode, so fill falls back to its `empty` behaviour.

## Related

- [Deep zoom & tiling](../../../docs/annotation-types/multimedia/deep_zoom.md)
- [Scaling & large datasets](../../../docs/deployment/scaling.md)
