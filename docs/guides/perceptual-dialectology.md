# Perceptual Dialectology: Draw-a-Map Tasks

Perceptual dialectology studies where non-linguists believe dialect areas
are, and what they call them. One of its methods is Dennis Preston's
draw-a-map task: participants get an outline map and draw the areas where
they think people speak differently, then name each area. Overlaying many
participants' maps shows which areas they agree on.

Potato runs this task with the [`geo_annotation`](../annotation-types/spatial/geo_annotation.md)
scheme and aggregates the drawings with the `geo_overlap` export. The draw-a-map
tools found online carry no licence, so Potato's version is its own
implementation and shares no code with them.

## The example

`examples/advanced/dialect-map/` is a complete study on a fictional country,
Arventa. Its ten province outlines (`maps/regions.geojson`) are synthetic and
resemble no real borders. It asks three questions on one page:

1. **Draw the areas where people speak differently** (`task: draw`):
   freehand or polygon outlines, a label for how different the speech sounds,
   and a required name for each area.
2. **Where did you grow up?** (`task: pin`): one pin.
3. **How does the speech of each province sound to you?**
   (`task: classify_region`): each province gets *Sounds like home*, *Sounds
   different* or *Don't know*.

```bash
python potato/flask_server.py start examples/advanced/dialect-map/config.yaml -p 8000
```

The map needs no network connection. Nothing is fetched from a tile server.

## Setting up your own study

### The outline map

Use an outline the participants will recognise, without the dialect labels or
regional names you are trying to elicit; a labelled map leads the answers.
Boundaries of states, provinces or counties are the usual choice.

- Put the file under the project directory and name it in
  `basemap.geojson`. It is embedded in the page, so simplify it first (with
  mapshaper, QGIS or similar) to a few hundred kilobytes or less.
- Check the licence of the boundary data before you put it in the project.
  Many national statistics offices publish boundary files under open
  licences; some commercial boundary sets cannot be redistributed.
- If the file writes latitude first, set `coordinate_order: latlon`.
- Region names in the outline (`region_name_property`) are drawn on the map.
  If they would lead the participants, leave the property out of the file.

### The draw question

```yaml
- annotation_type: geo_annotation
  name: dialect_areas
  description: "Draw the areas where people speak differently"
  task: draw
  tools: [freehand, polygon]
  labels:
    - "A little different"
    - "Very different"
    - "Hard to understand"
  feature_text:
    prompt: "What do you call how people talk there?"
    required: true
  basemap:
    geojson: maps/regions.geojson
  label_requirement:
    required: true
```

- `tools: [freehand]` alone is closest to drawing with a pen on a paper map.
  Freehand outlines may cross themselves; the aggregate fills them by the
  even-odd rule, so a figure-eight counts as its two loops.
- One label is enough if you only want the areas and their names. More
  labels let participants rate each area as they draw it (how different,
  how pleasant, how easy to understand).
- `feature_text.required` makes every area need a name before Next.
- `min_features` and `max_features` bound how many areas a participant draws.

### Pins and region ratings

`task: pin` with one label per question records places such as birthplace
or current residence, which you will usually want for grouping the drawings.
`task: classify_region` asks for one judgement per region and gives a
choropleth instead of free outlines.

## The `geo_overlap` export

```bash
python -m potato.export --config examples/advanced/dialect-map/config.yaml \
    --format geo_overlap --output out/
```

For each item and draw scheme, the export lays a regular longitude/latitude
grid over the outline map (or over the drawings, if there is no outline).
For every label (or name, see `group_by`), a cell's **share** is the
fraction of respondents with at least one polygon of that label whose
outline contains the cell's centre. *Respondents* are the participants who
drew at least one polygon in that scheme on that item. A participant counts
once per cell however many of their polygons overlap there.

Written files:

| File | Content |
|---|---|
| `geo_overlap/<item>__<schema>__<group>.geojson` | One square polygon per covered cell, with `count`, `respondents`, `share`, `row`, `col`, and the item, scheme and group |
| `geo_overlap/<item>__<schema>__<group>.png` | Preview: covered cells shaded from light (few) to dark (all respondents), outline in grey, north up, plate carrée |
| `geo_overlap_summary.csv` | One row per heat map: respondents, participants in the group, polygons, cells covered, largest share, grid size and extent, file names |
| `geo_names.csv` | Every drawn feature: participant, item, label, the name as typed, a normalised form (case-folded, whitespace collapsed), geometry type, area in km², a label point |
| `geo_name_counts.csv` | Per scheme, label and normalised name: how many participants used it |
| `geo_regions.csv` | `classify_region` schemes: per region and label, how many participants chose it and the share |

Options (`--option key=value`):

| Option | Default | Meaning |
|---|---|---|
| `group_by` | `label` | `label`, `text` (the normalised name) or `label_text` (both) |
| `cells` | `100` | Cells along the longer side of the extent |
| `cell_size` | none | Cell size in degrees; overrides `cells` |
| `extent` | outline bounds | `min_lon,min_lat,max_lon,max_lat` |
| `schema` | all | Export one scheme |

Cells are equal in degrees, not in area. Over one country the difference is
small; the GeoJSON cells carry their corner coordinates, so a GIS can
reproject them. The computation uses numpy only (no GDAL).

Grouping by name puts two areas together only when their normalised names
match. `geo_name_counts.csv` shows the spellings participants used. To merge variants ("Southern",
"the south", "southern drawl"), recode `geo_names.csv` and aggregate the
polygons yourself, or ask participants to choose from labels instead.

The `geojson` export (`--format geojson`) writes every drawing with its
participant and item, for analysis in QGIS, R (`sf`) or Python (`geopandas`).

## Troubleshooting

| Symptom | Cause |
|---|---|
| A heat map has share 1.0 everywhere it is shaded | Only one participant drew that label |
| A name appears as several groups with `group_by=text` | Spellings differ beyond case and spacing; see `geo_name_counts.csv` |
| The PNG looks wider than the map on the page | The page uses Web Mercator; the preview is plate carrée |
| No heat map for a scheme | Nobody drew a polygon in it (points and lines are not aggregated) |

## Related

- [Geographic annotation on maps](../annotation-types/spatial/geo_annotation.md)
- [Linguistic fieldwork](linguistic-fieldwork.md)
- [Export formats](../data-export/export_formats.md)
