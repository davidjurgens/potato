# Multichannel microscopy

The `microscopy` annotation type shows a fluorescence (or any multichannel) microscopy image stored as OME-Zarr or OME-TIFF. The annotator switches channels on and off, sets each channel's colour and contrast limits, moves through z-slices and time points, and zooms through the file's own resolution pyramid. On that image they can:

- draw regions of interest (rectangles, polygons and points), each with a class, and
- click cells in the image's label image (a segmentation with one integer id per cell) and give each a class.

Exports write the ROIs as GeoJSON, the cell classes as CSV, and one class label image per annotator as OME-Zarr.

## Overview

- **Formats:** OME-Zarr 0.4 (Zarr v2) and 0.5 (Zarr v3), read with zarr-python. Multiscales that list their axes under `coordinateSystems`, the shape used by the current NGFF development specification, are read too. OME-TIFF is read with tifffile, including pyramids stored as SubIFDs.
- **Axes:** any of `t`, `c`, `z` plus `y` and `x`. Other axes are refused with a message. An RGB TIFF with no `C` axis has its samples treated as channels.
- **Channels:** names, colours and display windows come from the OME-Zarr `omero` block or the OME-XML `Channel` elements. When the file has no window, the contrast limits are the 0.5th and 99.8th percentiles of the coarsest level, and the slider range is the smallest bit depth that holds the data (4095 for 12-bit data stored as uint16).
- **Rendering:** tiles are composited on the server and shown in OpenSeadragon 5.0.1, which Potato already ships. Rendering needs no WebGL.
- **Label images:** an OME-Zarr image's `labels/` group is found automatically. An OME-TIFF has no standard place for one, so an item can name a separate integer label TIFF.
- **Offline:** nothing is loaded from outside the Potato server.

Install the readers:

```bash
pip install 'potato-annotation[microscopy]'
```

The extra installs zarr-python 3 (MIT) on Python 3.11 and later, zarr-python 2 on older Pythons, and tifffile (BSD-3-Clause). zarr-python 2 cannot read OME-Zarr 0.5. This was tested with zarr-python 3.1.6 and tifffile 2025.10.16.

### Why the server composites the tiles

Viv (MIT) composites channels on the GPU in WebGL2, and Potato does not use it. Viv is published on npm as ES modules on top of deck.gl and luma.gl (and React for its viewer components), with no self-contained browser build. Potato has no JavaScript build step and serves no CDN assets, so using Viv would mean building and committing a bundle of several megabytes of generated code. Potato composites on the server instead:

| | Server compositing (this page) | Viv in the browser |
|---|---|---|
| Changing contrast or a channel | the visible tiles are fetched again, about one round trip | a shader parameter changes; immediate |
| Browser requirements | any browser with a 2D canvas | WebGL2 |
| Air-gapped installs | works; OpenSeadragon is vendored | needs the bundle shipped with Potato |
| What reaches the browser | 8-bit JPEG tiles of the current rendering | the raw channel data |
| Server cost | reads the chunks a tile covers and composites them with numpy | serves chunks only |

To keep the image from blanking while settings change, the page opens the new rendering over the old one and removes the old one once all of the new tiles have loaded. Tile URLs carry every rendering setting and the file's modification time, so a browser caches tiles it has already seen.

## Configuration

```yaml
media_directory: media

data_files:
  - data/images.json

annotation_schemes:
  - annotation_type: microscopy
    name: cells
    description: "Classify the cells, and outline any region that looks damaged."
    image_key: image              # item field naming the OME-Zarr or OME-TIFF
    labels_key: cells             # item field naming a label TIFF (OME-TIFF only)
    tools: [bbox, polygon, landmark]
    labels:                       # classes for regions
      - name: damaged
        color: "#e8590c"
      - name: debris
    cell_labels:                  # classes for cells (default: labels)
      - name: marker positive
        color: "#f03e3e"
      - name: marker negative
    channels:                     # optional overrides of the file's channel settings
      - name: DAPI
        label: "DAPI (nuclei)"
        contrast: [100, 3000]
      - index: 2
        color: "#ff00ff"
        visible: false
    min_cells: 1
```

### Options

| Key | Default | Meaning |
|---|---|---|
| `labels` | required | Classes for regions: names, or `{name, color}` with `#rrggbb` colours. |
| `cell_labels` | `labels` | Classes for cells, in the same form. The class number in the label-array export is the position in this list, from 1. |
| `image_key` | `image` | Item field holding the image path, relative to `media_directory` (a `/media/` prefix is accepted). |
| `labels_key` | none | Item field holding a separate integer label TIFF. The label image is then named `cells`. |
| `label_image` | first one | Which entry of an OME-Zarr `labels/` group to use. |
| `tools` | `[bbox, polygon, landmark]` | Region tools: rectangle, polygon, point. `[]` gives a cells-only task. |
| `channels` | from the file | Overrides per channel, matched by `index` (from 0) or `name`: `label` (display name), `color`, `contrast: [low, high]`, `visible`. |
| `min_rois` | 0 | The item counts as incomplete until this many regions are drawn. Enforced when the scheme is required (`label_requirement: {required: true}`). |
| `min_cells` | 0 | The item counts as incomplete until this many cells have a class. Enforced when the scheme is required (`label_requirement: {required: true}`). |
| `height` | 520 | Viewer height in pixels (capped at 70% of the window, less on phones). |
| `tile_size` | 254 | Tile size in pixels (64 to 1024). |
| `max_pixels` | 64000000 | Largest TIFF page decoded whole, and largest label plane read for export. |
| `label_max_side` | 2048 | The label raster sent to the browser is at most this many pixels a side. |
| `instructions` | none | Text shown under the description. |

Every value is checked when the server starts; a bad value stops it with a message naming the key.

## Data format

Each item names its image:

```json
{"id": "tissue_a", "image": "tissue_a.ome.zarr"}
{"id": "tissue_b", "image": "tissue_b.ome.tif", "cells": "tissue_b_cells.tif"}
```

Paths are resolved inside `media_directory`, then inside `task_dir`; anything that resolves outside both, absolute paths and URLs are refused. Remote OME-Zarr (over HTTP or S3) is not supported. For an HCS plate or a `bioformats2raw` container, name one image inside it (for example `plate.ome.zarr/A/1/0`).

A label TIFF must hold integers, have the image's width and height, and use `T`, `Z`, `Y` and `X` axes only (as many of them as the image has).

## Using it

- **Pan and zoom:** drag and scroll in the image, or pinch on a touch screen.
- **Channels:** the checkbox shows or hides a channel, the colour swatch sets its colour, and the Min and Max sliders set its contrast limits. Reset restores the file's (or the config's) settings. Channel settings carry over from item to item within a browser session.
- **Z-slice and time point:** sliders under the image, shown only when the image has more than one.
- **Regions:** choose Rectangle (key R), Polygon (P) or Point (O), and a class in "Region class". Drag to draw a rectangle. For a polygon, click each vertex and finish by clicking the first vertex, double-clicking, pressing Enter or using "Finish polygon"; Escape cancels and Backspace removes the last vertex. A region belongs to the z-slice and time point it was drawn on and is shown only there; selecting it in the Regions list moves to its plane. Each list entry has a class menu and a delete button. Pan / select (V) returns to navigation.
- **Cells:** with Pan / select, click a cell to select it (outlined in yellow), then press 1-9 or click a class button. Classified cells are filled with their class colour. A cell can also be selected by typing its id. A cell's class applies to its id on every z-slice and time point; the stored `z` and `t` record where it was classified.

The stored answer is JSON:

```json
{"image": {"width": 256, "height": 256},
 "rois": [{"type": "polygon", "label": "damaged", "color": "#e8590c",
           "coordinates": [{"x": 0.58, "y": 0.08}, {"x": 0.86, "y": 0.12}, {"x": 0.78, "y": 0.35}],
           "z": 1, "t": 0}],
 "cells": [{"label_id": 1, "class": "marker positive", "z": 1, "t": 0}],
 "label_image": "cells"}
```

Region coordinates use the image_annotation format: fractions of the full-resolution image, `bbox` as `{x, y, width, height}`, `polygon` as a list of points, `landmark` as one point.

## Export

```bash
python -m potato.export --config config.yaml --format microscopy --output out/
```

| File | Contents |
|---|---|
| `microscopy_rois.geojson` | A FeatureCollection of every region in full-resolution pixel coordinates (x right, y down; not georeferenced). Rectangles and polygons are closed Polygons, points are Points. Properties: `objectType: "annotation"` and `classification: {name, color: [r, g, b]}` in the form QuPath reads, plus `item_id`, `user_id`, `schema`, `roi_type`, `z`, `t`. |
| `microscopy_cells.csv` | One row per classified cell: `user_id`, `instance_id`, `schema`, `label_image`, `label_id`, `class`, `z`, `t`. |
| `ome_zarr/<item>.ome.zarr/labels/<schema>__<user>/` | The item's label image with each cell id replaced by its class number (0 for unclassified cells and background), as an OME-Zarr label image with `image-label` colours and a `properties` list mapping each number to its class name. Written as OME-Zarr 0.5 when the source is OME-Zarr 0.5 and as 0.4 otherwise (override with `--option zarr_format=2` or `3`). |

The label-array store holds only a `labels/` group, so most viewers will not open it on its own: copy `labels/<schema>__<user>` into the source image's `labels/` directory and add its name to that group's `labels` list. Label arrays need zarr-python and the source images under `media_directory`; without them the export writes the GeoJSON and CSV and lists a warning. Skip them with `--option label_arrays=false`.

## Example

`examples/image/multichannel-microscopy/` has two synthetic images: an OME-Zarr 0.5 image (3 channels, 3 z-slices, a `labels/cells` group) and an OME-TIFF (3 channels, 3 time points, a separate label TIFF). `generate_data.py` in that directory writes them.

```bash
python potato/flask_server.py start examples/image/multichannel-microscopy/config.yaml -p 8000
```

## Troubleshooting

- **"Reading this microscopy file needs zarr"** (or tifffile): install the extra, `pip install 'potato-annotation[microscopy]'`.
- **"could not be opened as a Zarr group ... needs zarr-python 3":** the store is OME-Zarr 0.5 (it has `zarr.json` files) and the installed zarr-python is 2.x, which happens on Python 3.10 and older.
- **"has no microscopy image in its 'image' field":** the item's field is empty, misnamed (see `image_key`), or the file is not under `media_directory`.
- **"above the 64 MP limit for decoding a TIFF plane":** a TIFF page is decoded whole. Save large images as tiled, pyramidal OME-TIFF or as OME-Zarr, or raise `max_pixels`.
- **"This image has no label image":** the OME-Zarr has no `labels/` group (or `label_image` names an entry it does not have), or an OME-TIFF item has no `labels_key` field.
- **Cells look shifted against the image:** the label image must have the image's full-resolution width and height. A label TIFF of a different size is refused.
- **Contrast sliders run to 65535:** the file declares a window range of 0-65535 in its metadata. Set `channels: [{index: 0, contrast: [low, high]}]` to start from a useful window.

## Related

- [Image annotation](../multimedia/image_annotation.md) for ordinary images, and its deep-zoom viewer for large RGB images and whole-slide scans
- [Image formats](../multimedia/image_formats.md)
- [Export formats](../../data-export/export_formats.md)
