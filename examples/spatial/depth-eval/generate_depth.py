#!/usr/bin/env python3
"""
Generate the synthetic RGB + depth pairs this example annotates.

Committed as a generator rather than as fixture binaries for the same reason
the KITTI example is: a reviewer can read what the scene contains, and the
example does not carry megabytes of opaque PNG in the repository.

The scenes are deliberately *imperfect* — the "predicted" depth carries the
failures a monocular depth model actually makes, so the annotation task has
something real to find:

- a **flying-pixel halo** at the depth edge of the near box, where the model
  interpolates between foreground and background;
- a **hole** where a dark surface returned nothing, so the annotator sees what
  a non-measurement looks like against a real one;
- a **scale error** on the far wall in scene 2, which is invisible in the
  colourised picture and obvious in the metre readout. That one exists to make
  the point that a depth display without a readout is decorative.

Run from the repository root:

    python examples/spatial/depth-eval/generate_depth.py
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
RGB_DIR = HERE / "media" / "rgb"
DEPTH_DIR = HERE / "media" / "depth"

WIDTH, HEIGHT = 320, 240

#: Stored units per metre. 1000 = millimetres, the RGB-D convention, and what
#: `depth_scale: 0.001` in the config undoes.
UNITS_PER_METRE = 1000


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: Path, rows: list[bytes], bit_depth: int, color_type: int):
    """
    A minimal PNG writer, so the generator needs no Pillow.

    Filter byte 0 (None) on every row: the images are small and a real filter
    would only save bytes at the cost of being another thing to get wrong.
    """
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, bit_depth, color_type,
                         0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b""))


def scene(index: int):
    """
    Return (rgb_rows, depth_metres) for one scene.

    A corridor: floor receding to a back wall, one box near the camera, one
    further away. Depth is computed analytically so the "ground truth" is
    exact and the injected errors are the only wrong values.
    """
    back_wall = 8.0 if index == 1 else 12.0
    near_box = {"x0": 60, "x1": 150, "y0": 90, "y1": 200, "z": 2.2}
    far_box = {"x0": 200, "x1": 260, "y0": 120, "y1": 175, "z": 5.5}

    depth = [[0.0] * WIDTH for _ in range(HEIGHT)]
    rgb = [[(0, 0, 0)] * WIDTH for _ in range(HEIGHT)]

    horizon = HEIGHT * 0.45
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if y < horizon:
                z = back_wall
                shade = 150
            else:
                # Floor: depth falls off with the inverse of the row's height
                # below the horizon, which is what a pinhole camera sees.
                t = (y - horizon) / (HEIGHT - horizon)
                z = min(back_wall, 1.2 / max(t, 0.02))
                shade = int(90 + 60 * (1 - t))

            if (near_box["y0"] <= y < near_box["y1"]
                    and near_box["x0"] <= x < near_box["x1"]):
                z = near_box["z"]
                shade = 210
            elif (far_box["y0"] <= y < far_box["y1"]
                    and far_box["x0"] <= x < far_box["x1"]):
                z = far_box["z"]
                shade = 60

            depth[y][x] = z
            rgb[y][x] = (shade, int(shade * 0.85), int(shade * 0.7))

    _inject_flying_pixels(depth, near_box)
    _inject_hole(depth, far_box)
    if index == 2:
        _inject_scale_error(depth, horizon)

    return rgb, depth


def _inject_flying_pixels(depth, box):
    """A halo of interpolated depth around the near box's silhouette."""
    for y in range(box["y0"] - 3, box["y1"] + 3):
        for x in range(box["x0"] - 3, box["x1"] + 3):
            if not (0 <= y < HEIGHT and 0 <= x < WIDTH):
                continue
            inside = (box["y0"] <= y < box["y1"]
                      and box["x0"] <= x < box["x1"])
            if inside:
                continue
            depth[y][x] = (depth[y][x] + box["z"]) / 2


def _inject_hole(depth, box):
    """The dark far box returns nothing, as a low-albedo surface does."""
    for y in range(box["y0"] + 5, box["y1"] - 5):
        for x in range(box["x0"] + 5, box["x1"] - 5):
            depth[y][x] = 0.0          # 0 = no measurement, by convention


def _inject_scale_error(depth, horizon):
    """
    The back wall reported 30% nearer than it is.

    Invisible in the colourised image — the window rescales and the wall is
    still the far end — and immediately visible in the metre readout.
    """
    for y in range(int(horizon)):
        for x in range(WIDTH):
            depth[y][x] *= 0.7


def main():
    items = []
    for index in (1, 2):
        rgb, depth = scene(index)

        rgb_rows = [bytes(v for pixel in row for v in pixel) for row in rgb]
        rgb_name = f"scene_{index:04d}.png"
        write_png(RGB_DIR / rgb_name, rgb_rows, bit_depth=8, color_type=2)

        depth_rows = []
        for row in depth:
            units = [min(65535, int(round(z * UNITS_PER_METRE))) for z in row]
            depth_rows.append(struct.pack(f">{WIDTH}H", *units))
        depth_name = f"scene_{index:04d}.png"
        write_png(DEPTH_DIR / depth_name, depth_rows, bit_depth=16,
                  color_type=0)

        items.append({
            "id": f"scene_{index:04d}",
            # Served through /media, which is the route scoped to
            # `media_directory`. A bare relative path would resolve against the
            # page URL and 404 -- the depth display builds its own /media/depth
            # URL, but the RGB field is a plain image and needs the prefix.
            "rgb": f"/media/rgb/{rgb_name}",
            "depth": f"depth/{depth_name}",
            "note": ("Predicted depth for a synthetic corridor. "
                     + ("The back wall's scale is wrong in this one."
                        if index == 2 else
                        "Look at the edge of the near box.")),
        })

    data_dir = HERE / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "scenes.json").write_text(
        json.dumps(items, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {len(items)} scenes to {RGB_DIR} and {DEPTH_DIR}")


if __name__ == "__main__":
    main()
