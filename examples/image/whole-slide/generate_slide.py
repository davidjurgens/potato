#!/usr/bin/env python
"""
Build the example's whole-slide image: a synthetic Aperio SVS.

Run from the repository root::

    python examples/image/whole-slide/generate_slide.py

The slide is invented (pink "tissue" with darker nuclei on a white
background), so it carries no patient data and no licence questions. It is a
real Aperio-format TIFF, the layout scanners write: a tiled full-resolution
level, a thumbnail, two reduced tiled levels, and MPP / AppMag in the
description, which openslide reads as 0.25 microns per pixel at 40x.

Needs numpy and tifffile. Real slides (.svs, .ndpi, .mrxs, ...) drop in
unchanged.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT = 6144, 4096
TILE = 256
MPP, MAG = 0.25, 40


def tissue(width: int, height: int, seed: int = 7) -> np.ndarray:
    """An RGB slide: two tissue islands, nuclei inside them, white elsewhere."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    mask = np.zeros((height, width), np.float32)
    for cx, cy, rx, ry in ((0.33, 0.45, 0.24, 0.32), (0.72, 0.55, 0.18, 0.28)):
        d = ((x - cx * width) / (rx * width)) ** 2 + ((y - cy * height) / (ry * height)) ** 2
        mask = np.maximum(mask, np.clip(1.4 - d, 0, 1))
    img = np.full((height, width, 3), 245, np.float32)
    pink = np.array([232, 170, 200], np.float32)
    img = img * (1 - mask[..., None]) + pink * mask[..., None]
    # Nuclei: small dark-purple discs where there is tissue.
    nuclei = np.zeros((height, width), np.float32)
    count = 9000
    xs = rng.integers(0, width, count)
    ys = rng.integers(0, height, count)
    for nx, ny in zip(xs, ys):
        if mask[ny, nx] < 0.3:
            continue
        r = int(rng.integers(4, 9))
        x0, x1 = max(0, nx - r), min(width, nx + r + 1)
        y0, y1 = max(0, ny - r), min(height, ny + r + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        disc = ((xx - nx) ** 2 + (yy - ny) ** 2) <= r * r
        nuclei[y0:y1, x0:x1][disc] = 1.0
    purple = np.array([110, 60, 140], np.float32)
    img = img * (1 - nuclei[..., None]) + purple * nuclei[..., None]
    return img.astype(np.uint8)


def main():
    out = HERE / "media"
    out.mkdir(parents=True, exist_ok=True)
    image = tissue(WIDTH, HEIGHT)
    head = f"Aperio Image Library v12.0.0 \n{WIDTH}x{HEIGHT} [0,0 {WIDTH}x{HEIGHT}] ({TILE}x{TILE})"
    meta = f"|AppMag = {MAG}|MPP = {MPP}"
    path = out / "synthetic_tissue.svs"
    # metadata=None: tifffile otherwise writes its own description, and
    # openslide recognises an Aperio slide by the description it reads.
    with tifffile.TiffWriter(path) as tif:
        tif.write(image, tile=(TILE, TILE), compression="zlib", photometric="rgb",
                  description=f"{head} -> {WIDTH}x{HEIGHT}{meta}", metadata=None)
        thumb = image[::16, ::16].copy()
        tif.write(thumb, compression="zlib", photometric="rgb", metadata=None,
                  description=f"{head} -> {thumb.shape[1]}x{thumb.shape[0]} - thumbnail")
        for factor in (4, 16):
            level = image[::factor, ::factor].copy()
            tif.write(level, tile=(TILE, TILE), compression="zlib", photometric="rgb",
                      metadata=None,
                      description=f"{head} -> {level.shape[1]}x{level.shape[0]}{meta}")
    print(f"{path.name}: {WIDTH}x{HEIGHT}, {path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
