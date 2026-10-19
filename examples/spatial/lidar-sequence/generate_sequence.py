#!/usr/bin/env python
"""
Build the example's lidar sequence: six frames of one short drive.

Run from the repository root::

    python examples/spatial/lidar-sequence/generate_sequence.py

The scans are synthetic, sampled the same way as the kitti-cuboids example
(whose generator this reuses): a car drives away from the sensor and turns
slightly, a pedestrian crosses in front of it, and a parked truck stays put.
The calibration is the same real KITTI file, so `kitti_3d` exports work.
Real KITTI tracking scans (`velodyne/<sequence>/<frame>.bin`) drop in
unchanged: list them in order under `point_cloud`.
"""

from __future__ import annotations

import importlib.util
import json
import random
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "kitti_scene", HERE.parent / "kitti-cuboids" / "generate_scene.py")
scene = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scene)

FRAMES = 6
SEQUENCE = "drive_0001"


def objects_at(frame: int):
    t = frame / (FRAMES - 1)
    g = scene.GROUND
    return [
        ("car", (10.0 + 6.0 * t, -1.0 + 0.8 * t, g + 0.75), (4.3, 1.8, 1.5), 0.15 * t,
         (150, 60, 60)),
        ("pedestrian", (8.0, 4.0 - 3.0 * t, g + 0.87), (0.6, 0.6, 1.74), -1.4,
         (170, 150, 60)),
        ("truck", (24.0, -5.0, g + 1.35), (7.0, 2.5, 2.7), 0.0, (70, 120, 125)),
    ]


def main():
    root = HERE / "media"
    frames_dir = root / "frames" / SEQUENCE
    calib_dir = root / "calib"
    for directory in (frames_dir, calib_dir):
        directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for frame in range(FRAMES):
        rng = random.Random(zlib.crc32(f"{SEQUENCE}/{frame}".encode()))
        points = scene.sample_cloud(objects_at(frame), rng)
        # Every other road return: six frames at full density would make the
        # example several times larger without showing anything more.
        road = [p for p in points if abs(p[2] - scene.GROUND) < 0.05]
        rest = [p for p in points if abs(p[2] - scene.GROUND) >= 0.05]
        points = rest + road[::2]
        name = f"{frame:06d}.bin"
        scene.write_kitti_bin(frames_dir / name, points)
        paths.append(f"frames/{SEQUENCE}/{name}")
        print(f"frame {frame}: {len(points):,} points")
    (calib_dir / f"{SEQUENCE}.txt").write_text(scene.CALIB_TEXT)
    item = {"id": SEQUENCE, "point_cloud": paths,
            "calibration": {"file": f"calib/{SEQUENCE}.txt"},
            "notes": "A car pulls away and turns a little; a pedestrian crosses in front "
                     "of it; a truck is parked further out on the right."}
    (HERE / "data" / "sequences.jsonl").write_text(json.dumps(item) + "\n")


if __name__ == "__main__":
    main()
