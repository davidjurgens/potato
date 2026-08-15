# Depth Maps

Runnable example: `examples/spatial/depth-eval/`.

Depth is how monocular estimators, stereo rigs and RGB-D sensors deliver 3D, and
it is the format most robot datasets ship alongside their video. Potato reads
it, makes it legible, reports the distance under the cursor **in metres**, and
— given intrinsics — turns it into a point cloud you can put 3D boxes on.

## The three things that make depth different from an image

A depth map opened as an image is a black rectangle, and if it were not, you
would still be looking at colours with no idea what distance any of them means.

**1. The file does not know its own unit.** Millimetres for RealSense, Azure
Kinect and NYU-Depth; 1/256 m for the KITTI completion benchmark; metres for
anything written from a float array. `depth_scale` is metres per stored unit and
defaults to `0.001`. Getting it wrong is silent — the picture looks the same,
because the window rescales — which is exactly why the readout exists.

**2. Zero is not a distance.** It is the near-universal "no return" code. Read as
depth it paints a bright wall across every hole in the sensor's coverage. Potato
carries non-measurements as NaN and paints them **magenta**, a colour that
appears in none of the colormaps, so a hole cannot be mistaken for near or far
depth. The info line reports what fraction of the map is holes: a stereo rig on
a textureless wall really does return 80%, and an annotator who cannot see that
will read the holes as geometry.

**3. The interesting range is almost never the full range.** The near/far window
defaults to the 2nd and 98th percentile of the *valid* pixels.

## Configuration

```yaml
instance_display:
  fields:
    - key: rgb
      type: image
      label: "RGB frame"
    - key: depth
      type: depth_map
      label: "Predicted depth"
      display_options:
        depth_scale: 0.001      # metres per stored unit; 1/256 for KITTI
        colormap: turbo         # turbo | viridis | magma | gray
        invert: false           # true puts near at the bright end
        rgb_field: rgb          # underlay this field's image
        overlay_opacity: 0.85
        show_controls: true
```

| Option | Default | Meaning |
|---|---|---|
| `depth_scale` | `0.001` | Metres per stored unit. Float formats (NPY, PFM, EXR) default to `1.0` — they are already metres. |
| `colormap` | `turbo` | `turbo`, `viridis`, `magma`, `gray`. |
| `invert` | `false` | Swap which end of the ramp is near. |
| `rgb_field` | — | Another display field whose image is underlaid, so the overlay slider cross-fades. |
| `overlay_opacity` | `0.75` | Starting opacity of the depth over the RGB. |
| `show_controls` | `true` | Hide the window/colormap controls for a fixed presentation. |

## Formats

| Format | Read | Notes |
|---|---|---|
| 16-bit PNG | ✅ | The RGB-D and KITTI convention. Set `depth_scale`. |
| 16-bit TIFF | ✅ | Same. |
| NumPy `.npy` / `.npz` | ✅ | Float metres. An `.npz` with several arrays reads the first and logs which. |
| PFM | ✅ | Middlebury and optical-flow. Rows are stored **bottom-up** and are flipped back. |
| EXR | ⚠️ | Needs `pip install imageio[openexr]`. The error names the command. |
| Colour PNG/JPEG | ❌ | Refused with a reason: a colourised preview has already lost the values. |

## Turning depth into geometry

With camera intrinsics, a depth map becomes a point cloud:

```
GET /media/depth/<path>?pointcloud=1&fx=525&fy=525&cx=319.5&cy=239.5
```

The result is the same `PNT1` buffer the lidar viewer consumes, so a depth item
can be annotated with the existing `cuboid_3d` tools. That is deliberately the
whole integration — a depth display that could only be looked at would be a
second, weaker image viewer.

**Axes.** `frame=z_up` (the default) gives X forward, Y left, Z up, matching
every lidar format Potato reads and what the viewer assumes. `frame=camera`
gives the optical frame: X right, Y **down**, Z forward. The distinction is not
cosmetic — the optical frame has Y pointing down, so getting it wrong puts the
sky underground and every fitted box height comes out negative.

Each unprojected point carries its **source pixel index**, so a `segment_3d`
drawn on the cloud maps back to pixels in the original image.

## The endpoints

| Request | Returns |
|---|---|
| `/media/depth/<path>` | Colourised PNG |
| `?info=1` | Range, percentiles, and the hole fraction |
| `?raw=1` | `DPT1` float32 metres, for the cursor readout |
| `?pointcloud=1&fx=..&fy=..&cx=..&cy=..` | `PNT1` point cloud |

Renders are cached by every parameter that changes them, so dragging the window
does not re-colourise the same view twice, and changing it does not serve back
the previous one.

## Why the readout is not optional

A colormap is not injective at 8 bits: the picture cannot be inverted back to
metres. So the raw floats travel separately and the cursor position indexes
them directly.

This is what makes a **scale error findable**. A depth map whose values are all
30% short looks completely normal once the window rescales — same structure,
same colours, same everything. The only way to catch it is to point at something
whose distance you know and read the number. The bundled example
(`examples/spatial/depth-eval/`) has exactly that failure injected into its
second scene for this reason.

## Troubleshooting

**Everything is one colour.** The window is wider than the content. Press
*Reset window*, or check `depth_scale` — a millimetre file read as metres puts
the whole scene between 1000 and 9000.

**Large magenta regions.** Those are non-measurements, not annotations. The
info line reports the fraction; above 50% the display says so explicitly.

**"needs Pillow" or "needs imageio".** PNG and TIFF depth need Pillow; EXR needs
imageio with its OpenEXR plugin. The error message carries the install command.

**The readout says "Loading depth values…" and stays there.** The raw buffer is
fetched after the picture so the picture is not delayed; on a very large map
this takes a moment. If it never resolves, the `?raw=1` request failed — check
the browser console.

## Related documentation

- [Point cloud annotation](point_cloud.md) — the 3D viewer unprojected depth feeds
- [Calibration](calibration.md) — where `fx`, `fy`, `cx`, `cy` come from
- [Media ingest](../multimedia/media_ingest.md) — the same cache and transcode path
