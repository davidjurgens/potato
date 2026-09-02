#!/usr/bin/env python
"""
Build the example's lidar scans and the camera views that go with them.

Run from the repository root::

    python examples/spatial/kitti-cuboids/generate_scene.py

The scenes are synthetic so the example stays small and carries no licence
questions. Real KITTI data drops in unchanged.

## Why the images are generated rather than photographed

The camera panels exist so an annotator can check a 3D box against what the
camera saw. That check is only meaningful if the image and the cloud really are
the same scene, viewed through the calibration in ``calib/``. Pairing a
synthetic cloud with a stock photograph would produce a panel where nothing
ever lines up, which teaches the opposite of the lesson.

So both come from one scene description below: the cloud is sampled from the
object surfaces, and the image is those same objects projected through the same
calibration this repository ships. A box drawn correctly in 3D lands on the
object in 2D because there is nothing else it could do.

The calibration is a real KITTI ``calib`` file (sequence 0000 of the object
benchmark), so the intrinsics, the rectification and the velodyne-to-camera
transform are all genuine — only the scene is invented.
"""

from __future__ import annotations

import math
import random
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from potato.export.spatial_utils import cuboid_corners, yaw_to_quaternion  # noqa: E402
from potato.media.calibration import parse_kitti_calib, project_point  # noqa: E402

# A real KITTI object-detection calibration. P2 is the left colour camera.
CALIB_TEXT = """P0: 7.215377e+02 0.000000e+00 6.095593e+02 0.000000e+00 0.000000e+00 7.215377e+02 1.728540e+02 0.000000e+00 0.000000e+00 0.000000e+00 1.000000e+00 0.000000e+00
P1: 7.215377e+02 0.000000e+00 6.095593e+02 -3.875744e+02 0.000000e+00 7.215377e+02 1.728540e+02 0.000000e+00 0.000000e+00 0.000000e+00 1.000000e+00 0.000000e+00
P2: 7.215377e+02 0.000000e+00 6.095593e+02 4.485728e+01 0.000000e+00 7.215377e+02 1.728540e+02 2.163791e-01 0.000000e+00 0.000000e+00 1.000000e+00 2.745884e-03
P3: 7.215377e+02 0.000000e+00 6.095593e+02 -3.395242e+02 0.000000e+00 7.215377e+02 1.728540e+02 2.199936e+00 0.000000e+00 0.000000e+00 1.000000e+00 2.729905e-03
R0_rect: 9.999239e-01 9.837760e-03 -7.445048e-03 -9.869795e-03 9.999421e-01 -4.278459e-03 7.402527e-03 4.351614e-03 9.999631e-01
Tr_velo_to_cam: 7.533745e-03 -9.999714e-01 -6.166020e-04 -4.069766e-03 1.480249e-02 7.280733e-04 -9.998902e-01 -7.631618e-02 9.998621e-01 7.523790e-03 1.480755e-02 -2.717806e-01
Tr_imu_to_velo: 9.999976e-01 7.553071e-04 -2.035826e-03 -8.086759e-01 -7.854027e-04 9.998898e-01 -1.482298e-02 3.195559e-01 2.024406e-03 1.482454e-02 9.998881e-01 -7.997231e-01
"""

IMAGE_W, IMAGE_H = 1242, 375

#: Sensor height above the road, so the ground sits at z = -GROUND.
GROUND = -1.73

#: (label, centre, size (l, w, h), yaw, paint colour)
SCENES = {
    "scene_0001": [
        ("car", (14.0, 1.2, GROUND + 0.75), (4.3, 1.8, 1.5), 0.02, (150, 60, 60)),
        ("truck", (23.0, -4.6, GROUND + 1.35), (7.0, 2.5, 2.7), -0.06,
         (70, 120, 125)),
        ("pole", (11.0, -5.4, GROUND + 2.0), (0.22, 0.22, 4.0), 0.0,
         (105, 105, 110)),
    ],
    "scene_0002": [
        ("car", (9.5, -1.9, GROUND + 0.72), (4.1, 1.75, 1.45), -0.31,
         (150, 60, 60)),
        ("truck", (31.0, 2.0, GROUND + 1.4), (7.4, 2.55, 2.8), 0.09,
         (70, 120, 125)),
        ("pedestrian", (8.0, 3.4, GROUND + 0.87), (0.6, 0.6, 1.74), 0.4,
         (170, 150, 60)),
        ("pedestrian", (8.9, 4.3, GROUND + 0.84), (0.6, 0.6, 1.68), -0.2,
         (170, 150, 60)),
    ],
}


def sample_cloud(objects, rng):
    """
    A velodyne-like sweep of this scene: (x, y, z, intensity) tuples.

    Sampled as surfaces rather than volumes, because a lidar only ever sees the
    face pointing at it — filling the boxes solid would give the height-fitting
    tool a denser signal than any real scan provides and make the example
    easier than the real thing.
    """
    points = []

    # The road, in polar rings the way a spinning lidar actually samples it.
    for ring in range(48):
        radius = 3.0 + ring * 1.15
        step = max(0.02, 0.35 / max(radius, 1.0))
        angle = -math.pi / 2
        while angle < math.pi / 2:
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            z = GROUND + rng.gauss(0, 0.012)
            points.append((x, y, z, 0.12 + rng.random() * 0.05))
            angle += step

    for _label, center, size, yaw, _color in objects:
        corners = cuboid_corners(center, size, yaw_to_quaternion(yaw))
        # Only the faces a sensor at the origin could see. Sampling all six
        # would put returns on the far side of every object, which no lidar
        # ever produces and which would make boxes look better-supported than
        # they are.
        density = 900 if size[2] > 2 else 600
        for _ in range(density):
            u, v = rng.random(), rng.random()
            face = rng.random()
            if face < 0.45:                    # the face toward the sensor
                p = _bilinear(corners[0], corners[3], corners[4], corners[7],
                              u, v)
            elif face < 0.8:                   # a side
                side = (corners[0], corners[1], corners[4], corners[5]) \
                    if center[1] > 0 else (corners[3], corners[2],
                                           corners[7], corners[6])
                p = _bilinear(*side, u, v)
            else:                              # the top
                p = _bilinear(corners[4], corners[5], corners[6], corners[7],
                              u, v)
            points.append((p[0] + rng.gauss(0, 0.01),
                           p[1] + rng.gauss(0, 0.01),
                           p[2] + rng.gauss(0, 0.01),
                           0.35 + rng.random() * 0.4))
    rng.shuffle(points)
    return points


def _bilinear(a, b, c, d, u, v):
    """A point on the quad a-b-d-c, interpolating a->b by u and a->c by v."""
    return [a[i] + (b[i] - a[i]) * u + (c[i] - a[i]) * v for i in range(3)]


def write_kitti_bin(path, points):
    with open(path, "wb") as handle:
        for x, y, z, i in points:
            handle.write(struct.pack("<4f", x, y, z, i))


def render_camera(objects, camera):
    """
    The scene as the left colour camera would see it.

    A painter's-algorithm render: far objects first, so a near object occludes
    them. Crude, and deliberately so — it exists to be *geometrically* right,
    not to look photographic.
    """
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (IMAGE_W, IMAGE_H))
    draw = ImageDraw.Draw(image)

    # The horizon is wherever the camera's optical axis meets infinity, which
    # is the principal point. Painting a fixed fraction of the frame instead
    # would put the road and the projected boxes on different planets.
    horizon = int(camera.k[5])
    for y in range(IMAGE_H):
        if y < horizon:
            t = y / max(horizon, 1)
            draw.line([(0, y), (IMAGE_W, y)],
                      fill=(int(120 + 70 * t), int(140 + 70 * t),
                            int(175 + 55 * t)))
        else:
            t = (y - horizon) / max(IMAGE_H - horizon, 1)
            shade = int(58 + 26 * t)
            draw.line([(0, y), (IMAGE_W, y)],
                      fill=(shade, shade, shade + 4))

    # One depth-sorted list of faces across every object, rather than sorting
    # objects and then faces: a long truck can be nearer than a car at one end
    # and further at the other, and per-object ordering gets that wrong.
    faces = []
    for _label, center, size, yaw, color in objects:
        corners = cuboid_corners(center, size, yaw_to_quaternion(yaw))
        projected = [project_point(camera, c) for c in corners]
        if any(p is None for p in projected):
            continue
        # All six faces, far ones first. Drawing only a subset leaves the box
        # hollow -- you see the road through the middle of the car -- because
        # the missing faces are exactly the ones that would have closed the
        # silhouette. The tints are a cheap stand-in for lighting: the top is
        # brightest, the underside darkest.
        for face, tint in (((0, 1, 2, 3), 0.55),      # bottom
                           ((0, 3, 7, 4), 0.80),      # toward the sensor
                           ((1, 2, 6, 5), 0.70),      # away
                           ((0, 1, 5, 4), 0.95),      # -y side
                           ((3, 2, 6, 7), 0.85),      # +y side
                           ((4, 5, 6, 7), 1.15)):     # top
            depth = sum(corners[i][0] for i in face) / 4.0
            faces.append((depth, [projected[i] for i in face], tint, color))

    for _depth, polygon, tint, color in sorted(faces, key=lambda f: -f[0]):
        draw.polygon(polygon,
                     fill=tuple(min(255, int(c * tint)) for c in color))
    return image


def main():
    calibration = parse_kitti_calib(CALIB_TEXT)
    camera = calibration.cameras[0]

    # Everything the browser may fetch lives under one media root, so
    # `media_directory: media` in the config scopes the traversal guard to
    # exactly these files -- and not to the project's own annotation output.
    root = HERE / "media"
    clouds = root / "clouds"
    images = root / "images"
    calib_dir = root / "calib"
    for directory in (root, clouds, images, calib_dir):
        directory.mkdir(exist_ok=True)

    for name, objects in SCENES.items():
        # Seeded per scene: regenerating must not produce a diff on files
        # whose contents nobody changed.
        rng = random.Random(hash(name) % (2 ** 31))
        points = sample_cloud(objects, rng)
        write_kitti_bin(clouds / f"{name}.bin", points)
        render_camera(objects, camera).save(images / f"{name}.png")
        (calib_dir / f"{name}.txt").write_text(CALIB_TEXT)
        print(f"{name}: {len(points):,} points, "
              f"{len(objects)} objects, image {IMAGE_W}x{IMAGE_H}")


if __name__ == "__main__":
    main()
