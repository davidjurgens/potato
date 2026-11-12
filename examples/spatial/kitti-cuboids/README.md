# Lidar 3D boxes

Oriented 3D bounding boxes on a lidar point cloud.

```bash
python potato/flask_server.py start examples/spatial/kitti-cuboids/config.yaml -p 8000
```

## The data

`clouds/*.bin` are KITTI-style velodyne scans: raw `float32` x, y, z, intensity
with **no header at all**. They are generated synthetically (a ground plane, two
vehicles, a pole, two pedestrians) so the example stays small and carries no
licence questions. Drop real KITTI scans in the same directory and they load
unchanged.

PCD, PLY, LAS and plain `.xyz` work too — the server converts whatever it finds
into one wire format before the browser sees it. See
`potato/media/pointcloud.py` for why the conversion is server-side.

## Controls

| Action | Result |
|---|---|
| Left-drag | Orbit |
| Right-drag | Pan |
| Scroll | Zoom |
| `c` | 3D box tool |
| `k` | Point tool |
| `1` `2` `3` | Pick a class |
| `h` / `Shift+H` | Hide the armed class / solo it |

## Coordinates are metres, not fractions

Image annotations are normalized to `[0, 1]` against the image. Spatial ones
are **absolute metres in the sensor frame**, because there is no extent to
normalize against and no meaningful "width" of a lidar sweep. A stored box looks
like:

```json
{"type": "cuboid_3d", "label": "car", "color": "#FF6B6B",
 "coordinates": {"center": [12.0, 1.5, -0.9],
                 "size": [4.3, 1.8, 1.6],
                 "rotation": [0.0, 0.0, 0.025, 0.9997]}}
```

Rotation is a **quaternion**, not a yaw angle. KITTI stores yaw only, and
matching that would make any dataset with pitch or roll — drone, handheld,
indoor scan — unrepresentable, silently. The KITTI exporter converts at its own
boundary and is the place that admits the loss.

## Large clouds are thinned, and the viewer says so

`max_points` caps what is sent. Anything larger is reduced by **uniform stride**
— every Nth point — rather than truncated, because a lidar file is written in
scan order and keeping the first N points would drop the far half of the sweep
and look like a sensor failure. The status line under the viewer reports both
numbers, so a thinned cloud is never mistaken for the whole scan.
