# Point Cloud Annotation (3D)

Oriented 3D boxes, points, polylines and per-point segments on lidar and
photogrammetry data, rendered in the browser with three.js.

```yaml
annotation_schemes:
  - annotation_type: spatial_annotation
    name: objects
    description: "Put a 3D box around every vehicle and pedestrian."
    source_field: point_cloud
    tools: [cuboid_3d, point_3d]
    labels:
      - {name: car, color: "#FF6B6B", key_value: "1"}
      - {name: pedestrian, color: "#FFD93D", key_value: "2"}
    color_mode: height
    point_size: 2.0
    max_points: 400000
```

Runnable example: `examples/spatial/kitti-cuboids/`.

## Formats

Point clouds are read **server-side** and converted into one compact binary the
browser understands. The alternative — parsing each format in JavaScript —
would mean four parsers, four sets of endianness and record-layout bugs, and
re-parsing a two-million-point scan on every page load.

| Format | Read | Notes |
|---|---|---|
| KITTI velodyne `.bin` | ✅ | Raw `float32` x, y, z, intensity, no header |
| PCD | ✅ | `ascii`, `binary`, and `binary_compressed` (LZF) |
| PLY | ✅ | `ascii`, `binary_little_endian`, `binary_big_endian` |
| LAS | ✅ | 1.0–1.4, point record formats 0–3 and 6–8 |
| `.xyz` / `.pts` | ✅ | `x y z [r g b]` per line |
| LAZ | ❌ | Compressed LAS. Convert first: `laszip -i scan.laz -o scan.las` |

Colour is read where a format carries it (PLY, LAS formats 2/3/7/8, `.xyz`);
intensity is read from KITTI, PCD and LAS.

### Options

| Option | Default | What it does |
|---|---|---|
| `source_field` | `point_cloud` | Item field holding the cloud path |
| `calibration_field` | `calibration` | Item field holding the camera rig; turns on the [2D verification panels](calibration.md) |
| `tools` | — | Any of `cuboid_3d`, `point_3d`, `polyline_3d`, `segment_3d` |
| `color_mode` | `height` | `height`, `intensity`, `rgb`, `uniform` |
| `point_size` | `1.5` | Rendered point size in pixels |
| `max_points` | `500000` | Decimation cap (see below) |
| `default_box_height` | `1.7` | Height a new box starts at, in metres |
| `fit_box_height` | `true` | Snap a new box's vertical extent to the points inside its footprint |
| `min_annotations` / `max_annotations` | — | Completion rules |

`color_mode: rgb` needs a file that carries colour, and `intensity` needs one
that carries intensity. When the data is absent the viewer falls back to height
**and says so** in the status line, rather than silently rendering something
that looks like the mode you asked for.

Colour ramps are normalized against the 2nd and 98th percentile rather than
min/max, because a single stray return from a reflective surface otherwise
compresses everything else into one colour and the cloud renders as a flat
sheet.

## Large clouds: detail where the camera is looking

By default the cloud is served as an **octree**, and the viewer loads density
where you are looking rather than a thin sample of everywhere.

That distinction is the difference between a usable viewer and a decorative
one. Uniform thinning of a 20-million-point aerial scan to 500,000 points is
2.5% density *everywhere*: the whole scene is visible and nothing in it is
annotatable, because the car you are boxing is now nine returns. Raising the cap
does not help — WebGL will allocate the buffer and then render at 3 fps, which
reads as a broken page.

The structure is additive, so the union of what is loaded is always a
uniform-density sampling of the whole scene. A partially loaded cloud looks
*coarse*, never *incomplete* — a viewer that renders half-loaded data as missing
geometry teaches annotators to distrust it.

The status line under the viewport says what is on screen:

> Showing 412,000 of 2,100,000 points. More detail loads as you zoom in.

| Option | Default | Effect |
|---|---|---|
| `lod` | `true` | Octree loading. `false` falls back to one uniformly thinned buffer. |
| `point_budget` | 2,000,000 | Points held at once. Lower it for weak GPUs. |
| `min_screen_size` | 120 | Projected pixels below which a node is not fetched. Lower means more detail and more requests. |
| `max_loaded_nodes` | 512 | Cache size before least-recently-visible nodes are released. |
| `max_points` | 500,000 | **Only used when `lod: false`.** |

The octree is built once per file and cached, so the first request for a very
large scan is slow and every later one is not.

### With `lod: false`

Anything above `max_points` is reduced by **uniform stride** — every Nth point —
not truncated. A lidar file is written in scan order, so keeping the first N
points keeps one contiguous slice of the sweep and drops the rest of the scene,
which looks like a sensor failure rather than a decimation.

### Per-point labels stay stable

`segment_3d` stores **point indices**, and those indices are into the source
file, not into whatever subset the viewer has loaded. Every served buffer
carries an index channel to make that true.

This was a real defect rather than a hypothetical one. `max_points` is a schema
option, so lowering it — exactly what you do when a machine struggles — changed
the stride and silently re-pointed every stored per-point segment at different
points. Nothing errored; the labels just moved. If you have `segment_3d`
annotations from before this change and the `max_points` value has been edited
since, they are suspect.

## Controls

| Action | Result |
|---|---|
| Left-drag *(no tool armed)* | Orbit |
| Right-drag | Pan |
| Scroll | Zoom |
| `c` then left-drag | Draw a 3D box footprint on the ground |
| `k` then click | Place a point |
| `n` | Polyline |
| `g` | Paint points |
| `q` / `e` | Rotate the selected box (Shift for 1° steps) |
| `Delete` | Remove the selected box |
| `Escape` | Deselect |
| click *(no tool armed)* | Select the nearest annotation |
| `h` / `Shift+H` | Hide the armed class / solo it |

Per-class show/hide is the same feature image and video annotation have — the
schema renders the same label-button markup deliberately, so it works with no
extra configuration.

### Drawing a box

Drag out the **footprint** on the ground plane. The ground is estimated from
the cloud's own `z` values rather than assumed to be zero — a roof-mounted
lidar reports the road at about −1.7 m, so a box drawn on `z = 0` floats above
the whole scene.

The box's **height is then fitted to the points inside the footprint**. Height
is the dimension a footprint drag cannot express and the one annotators judge
worst in a perspective view of a sparse cloud, and the returns answer it
exactly. A footprint containing only road is left at the drawn height rather
than collapsed onto the tarmac — the annotator drew around something the lidar
did not see, and fitting to nothing would be fabricating a measurement.

Yaw is not part of the drag; `q` and `e` rotate the selected box afterwards, in
the world frame, so the key always turns it the same way on screen.

## The slab views

Under the viewport are three orthographic panels — **top** (X-Y), **front**
(Y-Z) and **side** (X-Z) — each showing a slab of the scene a couple of metres
thick, centred on whatever is selected.

They are there because a perspective view is systematically misleading in one
direction: the projection compresses the extent along the view axis, so boxes
placed by eye come out short in depth, and the error is invisible from the
camera that drew them. In a slab a metre is a metre in both screen directions,
and the returns behind a face are not hidden by the ones in front of it.

| Action | Result |
|---|---|
| Drag inside the box | Move it in that plane |
| Drag an edge | Move **that face**, leaving the opposite one fixed |
| Scroll | Thicken or thin the slab |

Dragging one edge deliberately does *not* resize symmetrically: the point of a
slab is aligning one boundary against the returns behind it, and a symmetric
resize would move the far face away from wherever you had just put it.

### From the keyboard

Tab to a panel and the same three actions are available without a pointer. This
is not a courtesy: the panels exist *because* placing a box by eye in
perspective is imprecise in depth, so "adjust it in the 3D view instead" would
hand a keyboard user exactly the imprecision the panels remove.

| Key | Result |
|---|---|
| `,` / `.` | Previous / next annotation — how you select an existing box without a mouse |
| Arrow | Move the selected box 10 cm in that direction, within the focused plane |
| `Shift` + arrow | Move the face **on that side** 5 cm outward |
| `Alt` + arrow | Move that same face 5 cm inward |
| `[` / `]` | Thin or thicken the slab |

The arrow names the *face*, not the direction of travel — a scheme where it
named the direction would leave two of the four faces unreachable. Each press
is its own undo step, unlike a drag, which undoes as one.

Every edit is announced to a screen reader with the box's new size and centre,
since the panels themselves are pixels. The status line under the viewport is
deliberately *not* a live region: level-of-detail loading rewrites it several
times a second while the camera moves.

The panels centre and scale themselves on the selection, so selecting a
pedestrian does not leave them four pixels wide in a view framed for the street.
With nothing selected they follow the camera target.

| Option | Default | Effect |
|---|---|---|
| `mpr` | on when `cuboid_3d` is a tool | Show the panels. |
| `slab_thickness` | `2.0` | Metres of depth each slab shows. The wheel changes it live. |

A **tilted** box — one with pitch or roll, not just yaw — is edited through its
axis-aligned envelope here, which is an approximation rather than a frame-exact
edit. That is stated rather than hidden: use the perspective view and `q`/`e`
for a rotated box, and the slabs for its extent.

## Coordinates are metres, not fractions

This is the one thing to get right when moving from 2D.

Image annotations are normalized to `[0, 1]` against the image. Spatial ones are
**absolute metres in the sensor frame**, because there is no extent to normalize
against — a lidar sweep has no "width" the way a photograph does.

```json
{"type": "cuboid_3d", "label": "car", "color": "#FF6B6B",
 "coordinates": {"center": [12.0, 1.5, -0.9],
                 "size": [4.3, 1.8, 1.6],
                 "rotation": [0.0, 0.0, 0.025, 0.9997]}}
```

| Type | Stored as |
|---|---|
| `cuboid_3d` | `{center: [x,y,z], size: [l,w,h], rotation: [qx,qy,qz,qw]}` |
| `point_3d` | `[x, y, z]` |
| `polyline_3d` | `[[x,y,z], ...]` |
| `segment_3d` | `indices: [i, ...]` into the served cloud |

`segment_3d` stores **point indices**, not coordinates: per-point labels over a
million-point cloud would otherwise be larger than the cloud itself. The
indices are stable because the served cloud is a fixed decimation, and the
decimation is part of the cache key.

### Rotation is a quaternion, not a yaw angle

KITTI stores a single yaw, and matching it would be simpler. nuScenes stores
quaternions, and any dataset with pitch or roll — drone, handheld, indoor scan,
anything that is not a car on a flat road — needs them. Storing yaw alone would
make those datasets unrepresentable, and the loss would be **silent**: a tilted
box would be written back flat with no warning.

So storage keeps the full rotation and format-specific exporters convert at
their own boundary, which is where a format's limitation belongs.

## Troubleshooting

**"No point cloud for this item"** — the field named by `source_field` is empty,
or its value does not end in a recognised extension. The viewer checks the
extension before fetching, so a text-only item does not produce a request for
the sentence it contains.

**"…needs laszip to read"** — LAZ is compressed LAS. Convert with
`laszip -i scan.laz -o scan.las`.

**"is not a multiple of 16"** — a `.bin` file read as a KITTI scan must be
`float32` x, y, z, intensity per point. This is the only integrity check the
format allows, since it has no header; without it, any binary file read as KITTI
yields a confident cloud of noise.

**"3D viewer unavailable: three.js did not load"** — three.js is vendored, not
CDN-loaded, and is gated on this schema being present. Check that the schema is
`spatial_annotation` and that `potato/static/vendor/three-0.160.0.min.js`
exists.

**The cloud is there but nothing is visible** — check `color_mode`. A cloud with
no colour rendered in `rgb` mode falls back to height, but a viewport zoomed
inside the cloud looks empty either way; scroll out.

## Related documentation

- [Calibration and 2D Verification](calibration.md) — project boxes into the camera images
- [Image Annotation](../multimedia/image_annotation.md) — the 2D equivalent
- [Media Ingest](../multimedia/media_ingest.md) — formats browsers cannot display
- [Geometry Agreement](../../advanced/geometry_agreement.md) — agreement over shapes
