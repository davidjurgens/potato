# Image Annotation

Image annotation allows annotators to mark regions on images using bounding boxes, polygons, freeform drawing, and landmark points. This is useful for object detection, segmentation, and keypoint annotation tasks.

![Image Annotation Interface](../../img/screenshots/image_annotation_full.png)
*The image annotation interface with bounding box and polygon tools*

## Features

- **Bounding Box (bbox)**: Draw rectangular boxes around objects
- **Polygon**: Draw multi-point polygons for precise object boundaries
- **Freeform Drawing**: Free-hand drawing for irregular shapes
- **Landmark Points**: Mark specific points of interest on images
- **Segmentation Brush**: Pixel-level mask painting for semantic segmentation
- **Fill Tool**: Flood-fill enclosed regions with a label
- **Eraser**: Remove mask regions
- **Zoom & Pan**: Navigate large images with ease
- **Label Assignment**: Assign category labels to each annotation
- **Keyboard Shortcuts**: Fast annotation with customizable hotkeys

## Configuration

### Basic Configuration

```yaml
annotation_schemes:
  - annotation_type: image_annotation
    name: object_detection
    description: "Draw boxes around objects in the image"
    tools:
      - bbox
      - polygon
    labels:
      - name: person
        color: "#FF6B6B"
        key_value: "1"
      - name: vehicle
        color: "#4ECDC4"
        key_value: "2"
      - name: animal
        color: "#45B7D1"
        key_value: "3"
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | string | required | Unique identifier for the schema |
| `description` | string | required | Instructions shown to annotators |
| `tools` | list | required | Annotation tools to enable |
| `labels` | list | required | Category labels for annotations |
| `zoom_enabled` | boolean | `true` | Enable zoom controls |
| `pan_enabled` | boolean | `true` | Enable pan/drag navigation |
| `min_annotations` | integer | `0` | Minimum required annotations |
| `max_annotations` | integer | `null` | Maximum allowed annotations |
| `freeform_brush_size` | integer | `5` | Default brush size for freeform tool |
| `freeform_simplify` | float | `2.0` | Path simplification tolerance |
| `brush_size` | integer | `20` | Default brush size for segmentation (1-100) |
| `eraser_size` | integer | `20` | Default eraser size for segmentation (1-100) |
| `mask_opacity` | float | `0.5` | Mask overlay opacity (0-1) |

### Available Tools

| Tool | Key | Description |
|------|-----|-------------|
| `bbox` | `b` | Rectangular bounding boxes |
| `polygon` | `p` | Multi-point polygons |
| `freeform` | `f` | Free-hand drawing |
| `landmark` | `l` | Single point markers |
| `brush` | `m` | Segmentation brush for pixel-level masks |
| `eraser` | `e` | Eraser for removing mask regions |
| `fill` | `g` | Flood fill for enclosed regions |

### Label Configuration

Labels can be specified as strings or objects:

```yaml
# Simple string labels (auto-assigned colors)
labels:
  - person
  - car
  - tree

# Detailed label objects
labels:
  - name: person
    color: "#FF6B6B"      # Custom color (hex)
    key_value: "1"        # Keyboard shortcut
  - name: vehicle
    color: "#4ECDC4"
    key_value: "2"
```

## Data Format

### Input Data

The image URL should be provided in the data file field specified by `text_key`:

```json
{"id": "img_001", "image_url": "https://example.com/image1.jpg"}
{"id": "img_002", "image_url": "/static/images/image2.png"}
```

Configure in YAML:
```yaml
item_properties:
  id_key: id
  text_key: image_url
```

### Output Data

Annotations are stored as a **flat JSON array**, with every shape and mask in
the same list. Shape coordinates are **normalized to the range 0–1** against the
image, so annotations stay correct if the image is served at a different size.

```json
[
  {
    "type": "bbox",
    "label": "person",
    "color": "#FF6B6B",
    "coordinates": {"x": 0.125, "y": 0.104, "width": 0.3125, "height": 0.625}
  },
  {
    "type": "polygon",
    "label": "vehicle",
    "color": "#4ECDC4",
    "coordinates": [
      {"x": 0.02, "y": 0.04}, {"x": 0.20, "y": 0.04},
      {"x": 0.20, "y": 0.21}, {"x": 0.02, "y": 0.21}
    ]
  },
  {
    "type": "mask",
    "label": "road",
    "color": "#45B7D1",
    "rle": {"counts": [12, 40, 8], "size": [480, 640]}
  }
]
```

Per type:

| Type | Geometry key | Shape |
|------|--------------|-------|
| `bbox` | `coordinates` | `{x, y, width, height}`, normalized |
| `polygon` | `coordinates` | list of `{x, y}`, normalized |
| `landmark` | `coordinates` | `{x, y}`, normalized |
| `freeform` | `coordinates` | `{path, left, top, scaleX, scaleY}` |
| `mask` | `rle` | `{counts: [ints], size: [height, width]}` |

Notes:

- `rle.size` is `[height, width]`, in that order.
- Mask `counts` are row-major and alternate between background and foreground
  runs, starting with a background run.
- Masks may also carry `instance` (an index that keeps two instances of one
  class apart) and `iscrowd`. A mask with no `iscrowd` is treated as a crowd
  region on export, because a brush mask is keyed by label and merges every
  stroke of that class.

To convert to and from these shapes in Python, use
`normalize_annotation_object()` and `to_client_object()` from
`potato.export.cv_utils` rather than reading the fields directly.

## Segmentation Masks

For pixel-level semantic segmentation tasks, use the brush, eraser, and fill tools. These create mask overlays that are stored as RLE (Run-Length Encoding) for efficiency.

### Segmentation Configuration Example

```yaml
annotation_schemes:
  - annotation_type: image_annotation
    name: segmentation
    description: "Paint regions using the brush tool"
    tools:
      - brush      # Pixel-level painting
      - eraser     # Remove mask regions
      - fill       # Fill enclosed areas
      - polygon    # Precise polygon boundaries
    labels:
      - name: foreground
        color: "#FF6B6B"
        key_value: "1"
      - name: background
        color: "#4ECDC4"
        key_value: "2"
    brush_size: 20        # Default brush size
    eraser_size: 20       # Default eraser size
    mask_opacity: 0.5     # Overlay transparency
```

### Segmentation Output Format

Masks are stored as RLE (Run-Length Encoding) **in the same array as the
shapes** — not under a separate `masks` key:

```json
[
  {
    "type": "mask",
    "label": "foreground",
    "color": "#FF6B6B",
    "rle": {"counts": [0, 100, 50, 200, 25], "size": [600, 800]}
  },
  {
    "type": "mask",
    "label": "background",
    "color": "#4ECDC4",
    "rle": {"counts": [50, 150, 100, 300], "size": [600, 800]}
  }
]
```

`size` is `[height, width]`. Counts are row-major and alternate between
background and foreground runs, starting with background.

Brush masks are keyed by **label**, so every stroke of one class merges into a
single region — that is semantic segmentation, and it exports as COCO
`iscrowd: 1`. Imported per-instance masks additionally carry an `instance`
index and an explicit `iscrowd: 0`, which keeps them separate and exports them
as N distinct annotations. Painting always edits the label-level mask and
leaves imported instances untouched.

### Segmentation Tips

1. **Brush Size**: Use a larger brush (40-60) for filling large areas, smaller brush (5-15) for precise edges
2. **Eraser**: Switch to eraser to fix mistakes without deleting the entire mask
3. **Fill Tool**: Use after drawing a boundary with polygon or brush to quickly fill enclosed regions
4. **Layer Order**: Masks are rendered in label order; later labels appear on top

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `b` | Select bounding box tool |
| `p` | Select polygon tool |
| `f` | Select freeform tool |
| `l` | Select landmark tool |
| `m` | Select segmentation brush tool |
| `e` | Select eraser tool |
| `g` | Select fill tool |
| `1-9` | Select label by number (whatever `key_value` you configure) |
| `Delete` / `Backspace` | Delete selected annotation |
| `Ctrl/Cmd+Z` | Undo |
| `Ctrl/Cmd+Shift+Z` | Redo |
| `+` / `=` | Zoom in |
| `-` | Zoom out |
| `0` | Fit image to view |
| Hold `Space` or `Alt` | Pan (drag the image) |

A tool shortcut only fires if that tool is enabled in `tools`.

## User Interface

### Toolbar

The toolbar provides:
- **Tool Selection**: Buttons to switch between annotation tools
- **Label Selection**: Color-coded buttons for each label
- **Zoom Controls**: Zoom in, zoom out, fit to view, reset
- **Edit Controls**: Undo, redo, delete selected

### Canvas

- Click and drag to create annotations
- Click existing annotations to select them
- Drag corners/edges to resize (bbox)
- Drag points to reshape (polygon)
- Double-click to close a polygon
- Zoom with the toolbar buttons or `+` / `-` / `0`
- Hold `Space` (or `Alt`) and drag to pan

## Importing existing annotations

You do not have to start from a blank image. A COCO file — polygons,
uncompressed RLE, compressed RLE strings and crowd regions — can be imported
as-is and shown to annotators pre-populated for correction:

```bash
potato import --input instances.json --image-dir ./images \
    --output-dir my-project/ --schema-name object_detection
```

See [Image Annotation Formats](image_formats.md) for the full format reference.

## Example Projects

- `examples/image/image-annotation/config.yaml` — annotating from scratch
- `examples/image/coco-import/config.yaml` — correcting imported COCO annotations

## Tips for Administrators

1. **Image Hosting**: Ensure images are accessible from the annotation server. Use absolute URLs or place images in the static folder.

2. **Tool Selection**: Only enable tools needed for your task to reduce annotator confusion.

3. **Label Colors**: Choose distinct, high-contrast colors for labels to improve visibility.

4. **Zoom for Detail**: Enable zoom for tasks requiring precise boundaries.

5. **Min/Max Annotations**: Set `min_annotations` to ensure annotators don't skip images. Set `max_annotations` to prevent over-annotation.
