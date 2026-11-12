"""
Draw-a-map aggregation: what share of participants put each place inside an
area they drew.

The map is cut into a regular longitude/latitude grid. A participant covers
a cell when the cell's centre lies inside any of the polygons they drew for
the group being aggregated (one label, or one free-text name). Inside is
decided by the even-odd rule over every ring of a polygon, so holes are
holes and a self-intersecting freehand outline still fills the way it looks.
A participant counts once per cell however many of their polygons overlap
there. ``share = count / respondents``.

Everything is in degrees. Cells are equal in degrees, not in area; at
dialect-survey scales (one country) that is a small distortion, and the
GeoJSON output carries each cell's corners so a GIS can reproject it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np

from .geojson import polygons_of


@dataclass
class Grid:
    x0: float
    y0: float
    dx: float
    dy: float
    nx: int
    ny: int

    @property
    def xs(self) -> np.ndarray:
        """Cell-centre longitudes, west to east."""
        return self.x0 + (np.arange(self.nx) + 0.5) * self.dx

    @property
    def ys(self) -> np.ndarray:
        """Cell-centre latitudes, south to north (row 0 is the southern edge)."""
        return self.y0 + (np.arange(self.ny) + 0.5) * self.dy

    @property
    def extent(self) -> List[float]:
        return [self.x0, self.y0, self.x0 + self.nx * self.dx, self.y0 + self.ny * self.dy]

    def cell_ring(self, row: int, col: int, decimals: int = 7) -> List[List[float]]:
        """The cell as a closed counter-clockwise ring."""
        w = round(self.x0 + col * self.dx, decimals)
        e = round(self.x0 + (col + 1) * self.dx, decimals)
        s = round(self.y0 + row * self.dy, decimals)
        n = round(self.y0 + (row + 1) * self.dy, decimals)
        return [[w, s], [e, s], [e, n], [w, n], [w, s]]


def make_grid(extent: Sequence[float], cell_size: Optional[float] = None, cells: int = 100) -> Grid:
    """A grid over ``[min_lon, min_lat, max_lon, max_lat]``.

    ``cell_size`` is in degrees; without it the longer side of the extent is
    cut into ``cells`` cells and the cells are square in degrees.
    """
    x0, y0, x1, y1 = (float(v) for v in extent)
    if not (x1 > x0 and y1 > y0):
        raise ValueError(f"extent {list(extent)!r} has no area")
    if cell_size is None:
        if cells < 1:
            raise ValueError("cells must be at least 1")
        cell_size = max(x1 - x0, y1 - y0) / cells
    if not cell_size > 0:
        raise ValueError("cell_size must be positive")
    nx = max(1, int(math.ceil((x1 - x0) / cell_size - 1e-9)))
    ny = max(1, int(math.ceil((y1 - y0) / cell_size - 1e-9)))
    return Grid(x0, y0, cell_size, cell_size, nx, ny)


def _ring_crossings(ring: Sequence[Sequence[float]], ys: np.ndarray):
    pts = np.asarray([p[:2] for p in ring], dtype=float)
    if len(pts) < 2:
        return np.zeros((0, len(ys)), bool), np.zeros((0, len(ys)))
    x1, y1 = pts[:-1, 0], pts[:-1, 1]
    x2, y2 = pts[1:, 0], pts[1:, 1]
    # Half-open in y, so a vertex shared by two edges is counted once and a
    # horizontal edge never.
    crosses = (y1[:, None] > ys[None, :]) != (y2[:, None] > ys[None, :])
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (ys[None, :] - y1[:, None]) / (y2 - y1)[:, None]
    xi = x1[:, None] + t * (x2 - x1)[:, None]
    return crosses, xi


def polygon_mask(rings: Sequence[Sequence[Sequence[float]]], grid: Grid) -> np.ndarray:
    """``(ny, nx)`` bool: cell centres inside the polygon by the even-odd rule."""
    xs, ys = grid.xs, grid.ys
    parts = [_ring_crossings(r, ys) for r in rings if r]
    mask = np.zeros((grid.ny, grid.nx), dtype=bool)
    if not parts:
        return mask
    crosses = np.concatenate([p[0] for p in parts], axis=0)
    xi = np.concatenate([p[1] for p in parts], axis=0)
    for row in np.nonzero(crosses.any(axis=0))[0]:
        vals = np.sort(xi[crosses[:, row], row])
        # Crossings strictly east of each centre; odd means inside.
        east = len(vals) - np.searchsorted(vals, xs, side="right")
        mask[row] = (east % 2) == 1
    return mask


def geometry_mask(geom: Optional[Dict[str, Any]], grid: Grid) -> np.ndarray:
    """Union of the masks of every polygon in a geometry."""
    mask = np.zeros((grid.ny, grid.nx), dtype=bool)
    for poly in polygons_of(geom):
        mask |= polygon_mask(poly, grid)
    return mask


def coverage(geometries_by_participant: Mapping[str, Iterable[Optional[Dict[str, Any]]]],
             grid: Grid) -> np.ndarray:
    """``(ny, nx)`` int: how many participants cover each cell."""
    counts = np.zeros((grid.ny, grid.nx), dtype=np.int32)
    for geoms in geometries_by_participant.values():
        mask = np.zeros((grid.ny, grid.nx), dtype=bool)
        for g in geoms:
            mask |= geometry_mask(g, grid)
        counts += mask
    return counts


def grid_features(counts: np.ndarray, respondents: int, grid: Grid,
                  properties: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """One GeoJSON polygon per covered cell (cells nobody covered are left out)."""
    out = []
    base = dict(properties or {})
    for row, col in zip(*np.nonzero(counts)):
        count = int(counts[row, col])
        out.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [grid.cell_ring(int(row), int(col))]},
            "properties": {**base, "row": int(row), "col": int(col), "count": count,
                           "respondents": respondents,
                           "share": round(count / respondents, 6) if respondents else 0.0},
        })
    return out


# ---------------------------------------------------------------------------
# Preview image
# ---------------------------------------------------------------------------

#: Sequential ramp, light (low share) to dark (high share).
_RAMP = np.array([(255, 247, 188), (254, 196, 79), (236, 112, 20), (189, 44, 12), (102, 20, 6)], float)


def _colour(share: np.ndarray) -> np.ndarray:
    pos = np.clip(share, 0, 1) * (len(_RAMP) - 1)
    i = np.minimum(np.floor(pos).astype(int), len(_RAMP) - 2)
    f = (pos - i)[..., None]
    return _RAMP[i] * (1 - f) + _RAMP[i + 1] * f


def render_preview(share: np.ndarray, grid: Grid,
                   outlines: Iterable[Optional[Dict[str, Any]]] = (),
                   max_side: int = 640) -> np.ndarray:
    """An ``(h, w, 4)`` uint8 image: north up, uncovered cells white, outlines grey."""
    scale = max(1, max_side // max(grid.nx, grid.ny))
    rgb = np.full((grid.ny, grid.nx, 3), 255.0)
    covered = share > 0
    rgb[covered] = _colour(share[covered])
    img = np.repeat(np.repeat(rgb[::-1], scale, axis=0), scale, axis=1)
    h, w = img.shape[:2]
    x0, y0, x1, y1 = grid.extent

    def to_px(lon, lat):
        return (lon - x0) / (x1 - x0) * w, (y1 - lat) / (y1 - y0) * h

    for geom in outlines:
        for poly in polygons_of(geom):
            for ring in poly:
                for a, b in zip(ring[:-1], ring[1:]):
                    ax, ay = to_px(a[0], a[1])
                    bx, by = to_px(b[0], b[1])
                    steps = int(max(abs(bx - ax), abs(by - ay)) * 2) + 1
                    t = np.linspace(0, 1, steps)
                    px = np.clip((ax + (bx - ax) * t).astype(int), 0, w - 1)
                    py = np.clip((ay + (by - ay) * t).astype(int), 0, h - 1)
                    img[py, px] = (90, 90, 90)
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[..., :3] = np.round(img).astype(np.uint8)
    out[..., 3] = 255
    return out
