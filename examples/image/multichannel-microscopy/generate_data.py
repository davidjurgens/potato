"""
Write the synthetic images for the multichannel microscopy example.

    python examples/image/multichannel-microscopy/generate_data.py

Needs numpy, tifffile and zarr-python (``pip install
potato-annotation[microscopy]``). Writes into ``media/``:

* ``tissue_a.ome.zarr`` -- OME-Zarr 0.5 (Zarr v3): 3 channels x 3 z-slices,
  256 x 256 px, three pyramid levels, and a ``labels/cells`` label image with
  one id per cell.
* ``tissue_b.ome.tif`` -- OME-TIFF: 3 channels x 3 time points, 256 x 256 px
  with two SubIFD pyramid levels, and ``tissue_b_cells.tif``, its label image.

Channel 0 is a nuclear stain (blue), 1 a membrane stain (green) and 2 a
marker (red) that only some cells express. Everything is generated from a
fixed seed; nothing is copied from real data.
"""

from __future__ import annotations

import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

CHANNELS = [
    {"name": "DAPI", "color": "3b6cff", "start": 150, "end": 3200, "min": 0, "max": 4095},
    {"name": "Membrane", "color": "2fd16b", "start": 150, "end": 2200, "min": 0, "max": 4095},
    {"name": "Marker", "color": "ff3b3b", "start": 150, "end": 2600, "min": 0, "max": 4095},
]


def cell_layout(size: int = 256, count: int = 12, seed: int = 7):
    """Cell centres and radii, kept apart so cells rarely touch."""
    rng = np.random.default_rng(seed)
    centres, radii = [], []
    attempts = 0
    while len(centres) < count and attempts < 5000:
        attempts += 1
        r = float(rng.uniform(size * 0.06, size * 0.09))
        cy, cx = rng.uniform(r + 4, size - r - 4, size=2)
        if all((cy - y) ** 2 + (cx - x) ** 2 > (r + rr + 3) ** 2
               for (y, x), rr in zip(centres, radii)):
            centres.append((float(cy), float(cx)))
            radii.append(r)
    return centres, radii


def render(size, centres, radii, shift_x=0.0, depth=1.0, seed=0):
    """``(channels[3, y, x] uint16, labels[y, x] uint16)`` for one plane.

    ``depth`` in (0, 1] shrinks every cell, as a z-slice away from the
    cells' middle would."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size].astype("float64")
    labels = np.zeros((size, size), dtype="uint16")
    nuclei = np.zeros((size, size))
    cytoplasm = np.zeros((size, size))
    for index, ((cy, cx), r) in enumerate(zip(centres, radii), start=1):
        cx = cx + shift_x
        rz = r * depth
        d2 = (yy - cy) ** 2 + (xx - cx) ** 2
        inside = d2 <= rz ** 2
        labels[inside & (labels == 0)] = index
        nuclei += 2800 * depth * np.exp(-d2 / (2 * (0.42 * rz) ** 2))
        if index % 3 == 1:
            cytoplasm += np.where(inside, 2100.0 * depth, 0.0)
    edge = np.zeros((size, size), dtype=bool)
    edge[:-1, :] |= labels[:-1, :] != labels[1:, :]
    edge[1:, :] |= labels[1:, :] != labels[:-1, :]
    edge[:, :-1] |= labels[:, :-1] != labels[:, 1:]
    edge[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    membrane = np.where(edge, 1900.0, 0.0)
    membrane = (membrane + np.roll(membrane, 1, 0) + np.roll(membrane, -1, 0)
                + np.roll(membrane, 1, 1) + np.roll(membrane, -1, 1)) / 2.2
    planes = []
    for signal in (nuclei, membrane, cytoplasm):
        noise = rng.normal(0, 10, size=(size, size))
        planes.append(np.clip(110 + signal + noise, 0, 4095))
    # Quantised to multiples of 8, as many 12-bit cameras deliver: keeps the
    # committed example small without changing what it looks like.
    stack = (np.stack(planes) // 8 * 8).astype("uint16")
    return stack, labels


def write_zarr(path: str, size: int = 256, z_slices: int = 3, chunk: int = 256,
               zarr_format: int = 3, levels: int = 3, with_labels: bool = True,
               seed: int = 7) -> str:
    """An OME-Zarr image of shape (c, z, y, x) with a labels/cells image."""
    from potato.science.converters import ome

    centres, radii = cell_layout(size, seed=seed)
    stacks, label_planes = [], []
    middle = (z_slices - 1) / 2
    for z in range(z_slices):
        depth = 1.0 if z_slices == 1 else float(np.sqrt(max(0.2, 1 - ((z - middle) / (middle + 1)) ** 2)))
        stack, labels = render(size, centres, radii, depth=depth, seed=seed * 100 + z)
        stacks.append(stack)
        label_planes.append(labels)
    data = np.stack(stacks, axis=1)                    # c, z, y, x
    labels = np.stack(label_planes)                    # z, y, x
    if os.path.exists(path):
        shutil.rmtree(path)
    root = ome.open_zarr_for_writing(path, zarr_format)
    scale = {"z": 1.0, "y": 0.325, "x": 0.325}
    units = {"z": "micrometer", "y": "micrometer", "x": "micrometer"}
    ome.write_multiscale(root, ome.downsample_levels(data, "czyx", levels), "czyx",
                         zarr_format, scale=scale, units=units, chunk=chunk,
                         extra=ome.omero_block(CHANNELS), name="tissue_a")
    if with_labels:
        colors = {i: "ffffff" for i in range(1, len(centres) + 1)}
        ome.write_labels_group(root, {"cells": labels}, "zyx", zarr_format,
                               colors={"cells": colors}, scale=scale, levels=levels,
                               chunk=chunk)
    return path


def write_tiff(path: str, label_path: str, size: int = 256, timepoints: int = 3,
               seed: int = 11) -> str:
    """An OME-TIFF of shape (t, c, y, x) with a SubIFD pyramid, and a
    (t, y, x) label TIFF beside it."""
    import tifffile

    centres, radii = cell_layout(size, seed=seed)
    stacks, label_planes = [], []
    for t in range(timepoints):
        stack, labels = render(size, centres, radii, shift_x=3.0 * t, seed=seed * 100 + t)
        stacks.append(stack)
        label_planes.append(labels)
    data = np.stack(stacks)                            # t, c, y, x
    labels = np.stack(label_planes)                    # t, y, x
    colours = [int(c["color"] + "ff", 16) for c in CHANNELS]
    colours = [c - (1 << 32) if c >= (1 << 31) else c for c in colours]
    options = dict(photometric="minisblack", tile=(128, 128), compression="zlib")
    with tifffile.TiffWriter(path) as tif:
        tif.write(data, subifds=1, metadata={
            "axes": "TCYX",
            "PhysicalSizeX": 0.325, "PhysicalSizeXUnit": "µm",
            "PhysicalSizeY": 0.325, "PhysicalSizeYUnit": "µm",
            "Channel": {"Name": [c["name"] for c in CHANNELS], "Color": colours},
        }, **options)
        tif.write(data[:, :, ::2, ::2], subfiletype=1, **options)
    tifffile.imwrite(label_path, labels, compression="zlib", photometric="minisblack",
                     metadata={"axes": "TYX"})
    return path


def main() -> None:
    media = os.path.join(HERE, "media")
    os.makedirs(media, exist_ok=True)
    write_zarr(os.path.join(media, "tissue_a.ome.zarr"))
    write_tiff(os.path.join(media, "tissue_b.ome.tif"),
               os.path.join(media, "tissue_b_cells.tif"))
    print("Wrote", ", ".join(sorted(os.listdir(media))))


if __name__ == "__main__":
    main()
