# Geographic Annotation on Maps

`geo_annotation` puts a map on the annotation page. Annotators draw labelled
points, lines and polygons on it, pin places, or give labels to the regions
of an outline map. The map is [OpenLayers](https://openlayers.org/) 10.9.0
(BSD-2-Clause), served by Potato from `potato/static/vendor/ol-10.9.0/`.

```yaml
annotation_schemes:
  - annotation_type: geo_annotation
    name: land_cover
    description: "Outline the land cover"
    task: draw
    tools: [polygon, freehand, point]
    labels:
      - {name: Water, color: "#0072B2"}
      - {name: Forest, color: "#009E73"}
    basemap:
      geojson: maps/regions.geojson
```

Runnable examples:

- `examples/advanced/dialect-map/`: a draw-a-map dialect survey on a
  fictional country, using all three tasks. See the
  [perceptual dialectology guide](../../guides/perceptual-dialectology.md).
- `examples/image/geo-annotation/`: land-cover polygons over georeferenced
  images, one image per item, with a suggested polygon on the first item.

## Tasks

| `task` | What the annotator does | What is stored |
|---|---|---|
| `draw` (default) | Draws points, lines, polygons and freehand polygons, and gives each a label (and a typed name with `feature_text`) | One GeoJSON feature per drawing |
| `pin` | Places one point for each label. Each label is a question, such as "Where were you born?" | One point per label |
| `classify_region` | Picks a label, then clicks regions of the basemap outline to give them that label. Clicking a region again with the same label clears it | One feature per labelled region, `geometry: null`, with the region id |

## The basemap

Potato works offline by default and does not load a map from the internet
unless the configuration names one. Every scheme needs a basemap, either in
`basemap` or per item through `basemap_field`. Without one, `potato validate`
and the server refuse the config.

| Source | Config | Notes |
|---|---|---|
| GeoJSON outline | `basemap: {geojson: maps/regions.geojson}` | A file under `task_dir`, read when the page is generated and embedded in it. Country or region boundaries, coastlines, a study-area polygon. Keep it simplified (a few hundred KB at most): it is part of every annotation page. A path starting with `/` or `http(s)://` is fetched by the browser instead |
| Georeferenced image | `basemap: {image: /media/area.png, extent: [min_lon, min_lat, max_lon, max_lat]}` | A PNG or JPEG in plate carrée (equirectangular) projection covering `extent`. Serve it from `media_directory` |
| GeoTIFF / Cloud Optimized GeoTIFF | `basemap: {geotiff: /media/area.tif}` | Read with geotiff.js 3.0.5 (MIT, with Esri's LERC decoder under Apache-2.0 bundled in), which loads only on a page with a GeoTIFF. The file must be in EPSG:4326 or EPSG:3857; other projections are not supported. Needs WebGL; without it the page says so and the outline still works |
| XYZ tiles | `basemap: {tiles: "https://tiles.example.org/{z}/{x}/{y}.png", attribution: "..."}` | Your own tile server or a provider you have an agreement with. `attribution` is required for an external URL. `{-y}` is accepted for TMS numbering. A path such as `/tiles/{z}/{x}/{y}.png` needs no attribution |

A GeoJSON outline can be combined with one raster source (`image`,
`geotiff` or `tiles`); the outline is drawn on top.

**OpenStreetMap tiles.** The OpenStreetMap Foundation's tile servers
(`tile.openstreetmap.org`) are run on donated resources, and their
[tile usage policy](https://operations.osmfoundation.org/policies/tiles/)
forbids heavy use. A study with many annotators panning a map is heavy use.
Potato accepts the URL and logs a warning. Host your own tiles or use a
commercial provider instead.

### A basemap per item

`basemap_field` names an item field that holds the item's basemap. It can be:

- a GeoJSON FeatureCollection (an outline drawn for this item);
- a string URL: `.tif`/`.tiff` is read as a GeoTIFF, anything else as GeoJSON;
- an object with the same keys as `basemap`, such as
  `{"image": "/media/tile_a.png", "extent": [-30.1, -38.53, -30.04, -38.5]}`.

Item values replace the scheme's raster source and outline key by key.

Item data is not configuration, so the server checks each item's basemap
before sending the item to the page. The merged basemap must pass the same
rules as `basemap` (a tile URL with `{z}`, `{x}` and `{y}`, `attribution`
with external tiles, `extent` with an image). An item may name an external
server only when the scheme's own `basemap` names a URL on that host. A
basemap that fails is not sent: the map area says why, the annotator is asked
to tell the researcher, and the server log has the same message.

### Regions

For `classify_region` (and for the region names drawn on any outline), each
outline feature is a region. Its id is the `region_id_property` property
(default `id`), else the GeoJSON feature id, else `r<index>`. Its name is the
`region_name_property` property (default `name`).

## Options

| Key | Default | Meaning |
|---|---|---|
| `task` | `draw` | `draw`, `pin` or `classify_region` |
| `labels` | required | Strings or `{name, color, description}`. Colours default to an Okabe-Ito palette. Quote YAML words such as `Yes`, `No`, `On`: unquoted, they load as booleans and are refused |
| `tools` | `[point, line, polygon, freehand]` | `draw` only. A *Select / move* tool is always added |
| `feature_text` | off | `true`, or `{prompt, required, placeholder}`: a text box per feature (draw and pin), stored as `properties.text` |
| `basemap` | none | See above. Keys: `geojson`, `image`, `extent`, `geotiff`, `tiles`, `attribution`, `max_zoom`, `region_id_property`, `region_name_property` |
| `basemap_field` | none | Item field with a per-item basemap |
| `preannotation_field` | none | Item field with GeoJSON features to start from (not for `classify_region`) |
| `coordinate_order` | `lonlat` | `latlon` if `preannotation_field` data or the outline write latitude first. Output is always `[lon, lat]` |
| `projection` | `EPSG:3857` | The map's display projection: `EPSG:3857` (Web Mercator) or `EPSG:4326`. Storage is always EPSG:4326 |
| `center`, `zoom` | fit the basemap | Initial view, `center: [lon, lat]` |
| `height` | `440` | Map height in pixels (200 to 1200). Capped at 70% of the window height, 60% on phones |
| `snapping` | `false` | Snap new vertices to existing features and to the outline |
| `min_features` | 1 if required, else 0 | `draw` only |
| `max_features` | none | `draw` only. Drawing tools are disabled at the limit |
| `require_all_regions` | `false` | `classify_region`: every region must get a label before Next |
| `instructions` | none | Text shown under the question |
| `label_requirement` | none | `{required: true}` blocks Next until the task's own condition holds (see below) |

With `label_requirement: {required: true}`:

- `draw`: at least `min_features` features (default 1), and a name on every
  feature if `feature_text.required`;
- `pin`: a pin for every label;
- `classify_region`: at least one region labelled, or all of them with
  `require_all_regions`.

## Using the map

**Draw.** Choose a label in *Label for new features*, then a tool.

- *Point*: click.
- *Line*: click each point, double-click the last one.
- *Polygon*: click each corner; click the first corner or double-click to
  finish. Backspace removes the last corner, Esc cancels, Enter finishes.
- *Freehand*: press and drag; releasing finishes the outline.
- *Select / move*: click a feature to select it, drag its outline or a vertex
  to reshape it, press Delete to remove it.

Every feature appears in the list under the map with a label menu, the name
box if `feature_text` is on, *Show* (select and zoom to it) and *Delete*.

**Pin.** The list shows one row per label. The active one is highlighted;
click the map to place it, and the next unplaced label becomes active. Drag a
pin to move it, or press *Move* and click elsewhere. *Use map centre* places
the pin at the centre of the view.

**Classify regions.** Pick a label button (or *Erase*) and click regions. The
list under the map has a menu per region and does the same from the keyboard.

**Keyboard.** Tab to the map, then the arrow keys pan and `+` / `-` zoom.
While the map has focus, the arrow keys do not move to another item. *Add
point at map centre* and *Use map centre* place points without a mouse; every
feature's label, name and deletion are reachable through the list.

**Suggested features.** Features from `preannotation_field` are marked
"(suggested)". They are not saved as the annotator's answer until the
annotator edits one or presses *Accept suggestions*, so an item the annotator
only opened does not count as labelled. A required scheme asks for one of the two.
Suggested features keep `properties.source: "preannotation"` until they are
edited.

## Stored data

The answer is one hidden input holding a GeoJSON FeatureCollection in EPSG:4326
([RFC 7946](https://www.rfc-editor.org/rfc/rfc7946)): positions are
`[longitude, latitude]`, exterior rings run counter-clockwise and holes
clockwise, coordinates have 7 decimals (about 1 cm), and longitudes are
wrapped into -180..180.

```json
{"type": "FeatureCollection", "features": [
  {"type": "Feature", "id": "f1",
   "geometry": {"type": "Polygon", "coordinates": [[[-29.0, -38.3], [-28.2, -38.3], [-28.6, -37.5], [-29.0, -38.3]]]},
   "properties": {"label": "Very different", "text": "Coast talk", "tool": "polygon"}},
  {"type": "Feature", "id": "f2",
   "geometry": {"type": "Point", "coordinates": [-26.0, -37.0]},
   "properties": {"label": "A little different", "tool": "point"}}
]}
```

`classify_region` stores
`{"type": "Feature", "geometry": null, "properties": {"region": "westfold", "region_name": "Westfold", "label": "Sounds like home"}}`
per labelled region. The `geojson` export puts the region geometry back.

The scheme also works on survey and other phase pages. There is no item
there, so `basemap_field` and `preannotation_field` do nothing.

## Export

```bash
# Every feature as GeoJSON, one file per item (geojson/<item>.geojson)
python -m potato.export --config config.yaml --format geojson --output out/
# ... or one file for the whole project
python -m potato.export --config config.yaml --format geojson --output out/ --option layout=single

# Heat maps of overlapping polygons, plus CSVs of names and region labels
python -m potato.export --config config.yaml --format geo_overlap --output out/
```

`geojson` normalises every feature again on export and adds `item_id`,
`user_id`, `schema` and `feature_id` to its properties. Features that cannot
be normalised (a position out of range, a ring with no area) are left out and
listed in the export warnings. Answers from phase pages get
`item_id: "<phase>/<page>"`.

`geo_overlap` is described in the
[perceptual dialectology guide](../../guides/perceptual-dialectology.md#the-geo_overlap-export).

## Troubleshooting

| Symptom | Cause |
|---|---|
| `give the map a basemap` at startup | No `basemap` and no `basemap_field`. Potato does not fall back to an internet map |
| `basemap GeoJSON not found` in a red box on the page | `basemap.geojson` is resolved against `task_dir`. Check the path |
| `out of range as [longitude, latitude] but would fit as [latitude, longitude]` | The GeoJSON writes latitude first. Fix the file or set `coordinate_order: latlon` |
| The GeoTIFF does not show | WebGL is unavailable (the page says so), or the file is in a projection other than EPSG:4326/3857 |
| A GeoTIFF looks blocky when zoomed in | Pixels are drawn without interpolation, so the annotator sees the real pixel boundaries |
| A polygon across the 180° meridian is wrong | Antimeridian-crossing shapes are not split; draw two polygons |
| Tiles load slowly or are refused | The tile provider is rate-limiting. Host your own tiles |

## Related

- [Perceptual dialectology: draw-a-map tasks](../../guides/perceptual-dialectology.md)
- [Image annotation](../multimedia/image_annotation.md), for pixel coordinates rather than geographic ones
- [Export formats](../../data-export/export_formats.md)
- [Air-gapped deployment](../../deployment/air_gap.md)
