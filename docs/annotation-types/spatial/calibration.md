# Camera Calibration and 2D Verification

Draw a 3D box in the point cloud, and see it land on the object in the
photograph that saw it.

```yaml
annotation_schemes:
  - annotation_type: spatial_annotation
    name: objects
    source_field: point_cloud
    calibration_field: calibration    # the item field holding the rig
    tools: [cuboid_3d]
    labels:
      - {name: car, color: "#FF6B6B"}
```

Runnable example: `examples/spatial/kitti-cuboids/`.

## Why this matters more than it sounds

A car at 40 m is a few dozen lidar returns. Whether the box is tight, whether
it is the right length, and whether it is rotated correctly are all close to
unanswerable from the cloud alone — but obvious in the camera image. So the
annotator **edits in 3D and verifies in 2D**: the panels under the viewport
show each camera's view of the scene with the boxes projected onto it, redrawn
as the box moves.

Without it, 3D labelling is a guessing game with no feedback. With it, a wrong
box is visible at a glance.

## Configuring it

Add a field to each item naming the rig. Nothing else changes; the panels
appear when the field is present and stay absent when it is not — a lidar-only
project is a normal thing to have, not a misconfiguration.

### A KITTI calibration file

```json
{"id": "scene_0001",
 "point_cloud": "clouds/scene_0001.bin",
 "calibration": {"file": "calib/scene_0001.txt",
                 "images": {"P2": "images/scene_0001.png"}}}
```

`file` is a standard KITTI `calib` file — `P0`–`P3`, `R0_rect`,
`Tr_velo_to_cam`. `images` maps a camera to the picture it took; the keys are
either the `P` row (`P2`) or KITTI's own directory name (`image_2`).

By default only `P2` (the left colour camera, which every KITTI benchmark uses)
is built. Ask for more with `"cameras": ["P2", "P3"]` alongside `file`.

### Explicit intrinsics and extrinsics

For any other rig — nuScenes, a custom multi-camera setup, an RGB-D sensor:

```json
{"id": "sample_042",
 "point_cloud": "lidar/sample_042.pcd",
 "calibration": {"cameras": [
   {"name": "CAM_FRONT",
    "image": "cams/front_042.jpg",
    "intrinsics": {"fx": 1266.4, "fy": 1266.4, "cx": 816.3, "cy": 491.5},
    "extrinsics": {"rotation": [0.500, -0.499, 0.501, -0.500],
                   "translation": [1.70, 0.02, -1.51]},
    "distortion": [-0.28, 0.11, 0.001, -0.002, 0.0]}]}}
```

| Field | Accepted forms |
|---|---|
| `intrinsics` | `{fx, fy, cx, cy}` (plus optional `skew`), a 3×3 matrix, or a 3×4 `P` |
| `extrinsics` | `{rotation, translation}` with rotation as a quaternion `[x,y,z,w]` or a 3×3 matrix; or a 3×4 / 4×4 matrix directly |
| `distortion` | Brown-Conrady `[k1, k2, p1, p2, k3]`. Omit for a rectified rig |
| `image` | Path to the picture, relative to `media_directory` |
| `width` / `height` | Optional; the browser reads them from the image itself |

nuScenes' `calibrated_sensor` spelling — `camera_intrinsic`, `rotation` and
`translation` at the top level — is accepted as written.

**Extrinsics map the sensor frame to the camera frame**, where +Z is forward,
+X right and +Y down (the OpenCV convention). The sensor frame is whatever
frame the point cloud is in, which is the frame annotations are stored in.

## What it does not silently get wrong

**Points behind the camera.** Negative depth divides to a perfectly plausible
pixel, mirrored through the principal point. A box straddling the image plane
would draw inside-out across the frame, which reads as an annotator error
rather than a projection bug. Points behind the camera project to nothing, and
box edges crossing the plane are clipped at it, so a box half in front of the
camera draws its visible half correctly.

**Boxes outside the frame.** An object off to one side still projects to real
pixel coordinates. Drawing it would put lines along the panel edge for things
the camera never saw. Boxes whose projection does not overlap the image are
left out.

**The stereo baseline.** KITTI's `P` matrices are `K · [I | t]` where `t` is
the rectified baseline — 6 cm for the left colour camera, 54 cm for the right.
It is recovered exactly, as `K⁻¹ · P[:,3]`. Assuming it is zero (or dividing
`P[0,3]` by `fx`, which is the same mistake more subtly) puts every box off by
a few centimetres — small, systematic, and easy to read as sloppy annotation.

**A calibration it cannot read.** The panels report the reason, and the reason
names what was missing. A calibration that is quietly wrong puts boxes in the
wrong place in the one view meant to catch wrong boxes, which is worse than
having no view at all.

## Paths are contained

A calibration path comes out of your data file and is opened by the server, so
it is resolved against `media_directory` with the same containment guard the
image and point cloud routes use. A path escaping that directory is refused,
and the refusal does not report whether the file exists.

Keep everything the browser may fetch under one media root:

```
media/
  clouds/   scene_0001.bin
  images/   scene_0001.png
  calib/    scene_0001.txt
```

## Drawing boxes with the projection

Arm the box tool (`c`), pick a class, and **drag out the footprint on the
ground plane**. Two things then happen automatically:

- The ground plane is the cloud's own ground, estimated as a low percentile of
  its `z` values — not `z = 0`. A roof-mounted lidar reports the road at about
  −1.7 m, so a box drawn on `z = 0` would float above the whole scene.
- The box's **height is fitted to the points inside its footprint**. Height is
  the dimension a footprint drag cannot express and the one annotators judge
  worst in a perspective view of a sparse cloud, and the returns answer it
  exactly. A footprint containing only road is left alone rather than collapsed
  onto the tarmac.

| Key | Action |
|---|---|
| drag | Draw the footprint |
| `q` / `e` | Rotate the selected box (hold Shift for 1° steps) |
| `Delete` | Remove the selected box |
| `Escape` | Deselect |
| click | Select the nearest annotation |

Rotation is applied in the world frame, so `q` always turns the box the same
way on screen regardless of how it is already oriented.

Set `fit_box_height: false` to keep the drawn height, and `default_box_height`
to change what a new box starts at (1.7 m by default).

## Troubleshooting

**The panels never appear.** The item's `calibration_field` is empty. That is
silent by design. Check the field name matches the schema and that the value is
not an empty string.

**"Camera views unavailable: …".** The calibration exists but could not be
read; the message names what was missing. A missing `Tr_velo_to_cam` parses but
warns, because the lidar frame is then assumed to be the camera frame and every
box will be in the wrong place.

**The boxes are consistently offset.** Check the direction of your extrinsics.
`rotation`/`translation` must map **sensor → camera**; supplying the inverse
gives a rig that looks correct until an object is off-centre.

**The image is there but no boxes.** Either every box is behind the camera or
outside the frame — both are drawn as nothing on purpose. Confirm the box
centres are in the sensor frame and in metres.

## Related documentation

- [Point Cloud Annotation](point_cloud.md) — the 3D surface itself
- [Media Ingest](../multimedia/media_ingest.md) — camera formats browsers cannot display
- [Geometry Agreement](../../advanced/geometry_agreement.md) — agreement over shapes
