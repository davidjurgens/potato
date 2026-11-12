"""
A minimal RGBA PNG writer (zlib + struct), so the heat-map preview needs no
imaging library.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def encode_png(rgba: np.ndarray) -> bytes:
    """PNG bytes for an ``(height, width, 4)`` uint8 array."""
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("expected an (h, w, 4) array")
    img = np.ascontiguousarray(rgba, dtype=np.uint8)
    h, w = img.shape[:2]
    raw = np.zeros((h, w * 4 + 1), dtype=np.uint8)   # filter byte 0 per row
    raw[:, 1:] = img.reshape(h, w * 4)
    header = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(raw.tobytes(), 9)) + _chunk(b"IEND", b""))


def write_png(path: str, rgba: np.ndarray) -> None:
    with open(path, "wb") as f:
        f.write(encode_png(rgba))
