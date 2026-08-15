"""
Octree level-of-detail for point clouds too large to send in one buffer.

## The problem uniform decimation cannot solve

:func:`potato.media.pointcloud.decimate` thins by uniform stride to 500k points.
That is the right default and the wrong ceiling. A 20-million-point aerial LAS
decimated to 500k is 2.5% density **everywhere**: the whole scene is visible and
nothing in it is annotatable, because the car you are drawing a box around is
now nine points. Raising the cap does not help either — WebGL will allocate a
20M-point buffer and then render at 3 fps, which reads as a broken viewer.

What is actually wanted is density where the camera is looking and sparsity
elsewhere, changing as the camera moves. That is level of detail.

## The structure

Potree's additive scheme, because it has the property that matters: **the union
of levels 0..k is itself a uniform-density sampling of the whole scene**, so
partially-loaded state always looks like a coarser cloud rather than like a
cloud with holes in it. A viewer that renders half-loaded data as missing
geometry teaches annotators to distrust it.

Each node owns a grid over its own box. Walking its points in order, the first
point to land in each cell stays at this node; everything else is pushed down to
the child octant containing it. Spacing therefore halves at each level, and no
point is stored twice.

## Serialization

One file, ``OCT1``:

    magic        4 bytes   b"OCT1"
    header_len   uint32 LE
    header       header_len bytes of UTF-8 JSON
    blobs        concatenated PNT1 buffers, one per node

One file rather than a directory of them, because
:class:`potato.media.cache.MediaCache` is content-addressed over single files
and accounts for their size when pruning. A directory would be invisible to the
prune pass and the cache would grow without limit.

Each node blob is a complete PNT1 buffer, so the client reuses the parser it
already has and a node fetched on its own is self-describing. Every blob carries
the **index channel** — with LOD the set of loaded points changes as the camera
moves, so a ``segment_3d`` index that meant "the i-th point currently loaded"
would mean something different one frame later.
"""

from __future__ import annotations

import json
import logging
import struct
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from potato.media.pointcloud import (MAGIC as PNT_MAGIC, PointCloud,
                                     PointCloudError, U32, to_wire)

logger = logging.getLogger(__name__)

OCT_MAGIC = b"OCT1"

#: Cells per axis inside a node's box. Points landing in the same cell after the
#: first are pushed to a child, so this sets the sampling spacing at each level:
#: ``node_size / GRID``. 48 keeps a typical lidar node in the low thousands of
#: points (surfaces occupy about GRID^2 cells, not GRID^3) while staying fine
#: enough that the root of a street scene is recognisable.
DEFAULT_GRID = 48

#: How deep to subdivide. Each level roughly quadruples the point count for
#: surface-like data, so 6 levels spans a ~4000x density range — more than the
#: gap between "whole scene" and "one object" in any dataset we target.
DEFAULT_MAX_LEVEL = 6

#: A node holding fewer than this keeps all its points rather than subdividing.
#: Below it the round-trip per node costs more than the points are worth.
DEFAULT_MIN_POINTS = 8_000

#: Refuse to build past this many nodes. A pathological cloud (every point
#: identical, so no cell ever splits) would otherwise recurse to max_level over
#: 8^6 boxes. Hitting it is reported in the manifest, not swallowed.
MAX_NODES = 4096


@dataclass
class OctreeNode:
    """One node's metadata. The points live in the blob region."""

    key: str
    level: int
    bounds: List[List[float]]
    count: int
    offset: int = 0
    length: int = 0
    children: List[str] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "level": self.level,
            "bounds": self.bounds,
            "count": self.count,
            "offset": self.offset,
            "length": self.length,
            "children": self.children,
        }


@dataclass
class Octree:
    """Node metadata plus the concatenated per-node PNT1 blobs."""

    nodes: Dict[str, OctreeNode]
    blobs: Dict[str, bytes]
    bounds: List[List[float]]
    total_count: int
    source_format: str = ""
    spacing: float = 0.0
    truncated: bool = False

    @property
    def depth(self) -> int:
        return max((n.level for n in self.nodes.values()), default=0)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_octree(cloud: PointCloud,
                 *,
                 grid: int = DEFAULT_GRID,
                 max_level: int = DEFAULT_MAX_LEVEL,
                 min_points: int = DEFAULT_MIN_POINTS) -> Octree:
    """
    Build an additive octree over ``cloud``.

    ``cloud`` must be the **undecimated** read — the whole point is to keep the
    density that decimation throws away. Pass ``max_points=0`` to
    :func:`~potato.media.pointcloud.read_point_cloud`.

    A cloud small enough not to need subdividing yields a single root node
    holding everything, which the client then loads exactly as it loads a
    non-LOD cloud. There is deliberately no "too small for LOD" special case:
    one code path that degenerates correctly beats two that must agree.
    """
    np = _numpy()

    n = cloud.count
    # Built once. Rebuilding these per node would make the whole walk quadratic
    # in the cloud size — 4000 nodes each copying 20 million points.
    channels = _Channels(np, cloud)
    positions = channels.positions

    if n == 0:
        root = OctreeNode(key="r", level=0,
                          bounds=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], count=0)
        return Octree(nodes={"r": root},
                      blobs={"r": to_wire(channels.subset(
                          np.zeros(0, dtype=np.int64)))},
                      bounds=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                      total_count=0, source_format=cloud.source_format)

    lo = positions.min(axis=0)
    hi = positions.max(axis=0)
    # A cube, not the tight box: octant subdivision halves each axis, so a
    # non-cubic root would produce ever more elongated cells and the grid would
    # sample one axis far more finely than the others.
    size = float(max(hi - lo).item())
    if size <= 0:
        size = 1.0
    center = (lo + hi) / 2.0
    origin = center - size / 2.0

    nodes: Dict[str, OctreeNode] = {}
    blobs: Dict[str, bytes] = {}
    truncated = False

    # Explicit stack rather than recursion: a degenerate cloud can reach
    # max_level on every branch, and Python's recursion limit is not a place to
    # discover that.
    stack: List[Tuple[str, int, Any, Any]] = [
        ("r", 0, origin, np.arange(n, dtype=np.int64))]

    while stack:
        key, level, node_origin, member = stack.pop()
        node_size = size / (2 ** level)
        node_bounds = [
            [float(v) for v in node_origin],
            [float(v + node_size) for v in node_origin],
        ]

        if len(nodes) >= MAX_NODES:
            truncated = True
            keep_local = member
            children: List[str] = []
        elif len(member) <= min_points or level >= max_level:
            keep_local = member
            children = []
        else:
            keep_local, remainder = _grid_sample(
                np, positions, member, node_origin, node_size, grid)
            children = []
            for octant in range(8):
                child_member = _octant_members(
                    np, positions, remainder, node_origin, node_size, octant)
                if child_member.size == 0:
                    continue
                child_key = f"{key}{octant}"
                child_origin = node_origin + _octant_offset(
                    np, octant, node_size / 2.0)
                children.append(child_key)
                stack.append((child_key, level + 1, child_origin, child_member))

        node = OctreeNode(key=key, level=level, bounds=node_bounds,
                          count=int(len(keep_local)), children=children)
        nodes[key] = node
        blobs[key] = to_wire(
            channels.subset(keep_local),
            extra={"node": key, "level": level, "node_bounds": node_bounds},
        )

    if truncated:
        logger.warning(
            "Octree for a %d-point cloud hit the %d-node cap; the deepest "
            "branches keep their points unsplit and will render coarser than "
            "requested.", n, MAX_NODES)

    return Octree(
        nodes=nodes,
        blobs=blobs,
        bounds=[[float(v) for v in lo], [float(v) for v in hi]],
        total_count=n,
        source_format=cloud.source_format,
        spacing=size / grid,
        truncated=truncated,
    )


def _grid_sample(np, positions, member, origin, node_size, grid):
    """
    Split ``member`` into (kept at this node, pushed to children).

    The first point to land in each grid cell stays. ``np.unique`` with
    ``return_index=True`` gives the index of the **first occurrence** of each
    distinct cell in the original order, which is exactly that rule.
    """
    local = positions[member] - origin
    cell = np.floor(local / node_size * grid).astype(np.int64)
    np.clip(cell, 0, grid - 1, out=cell)
    cell_id = (cell[:, 0] * grid + cell[:, 1]) * grid + cell[:, 2]

    _unique, first = np.unique(cell_id, return_index=True)
    mask = np.zeros(len(member), dtype=bool)
    mask[first] = True
    return member[mask], member[~mask]


def _octant_members(np, positions, member, origin, node_size, octant):
    if member.size == 0:
        return member
    mid = origin + node_size / 2.0
    p = positions[member]
    want = ((p[:, 0] >= mid[0]).astype(np.int64)
            | ((p[:, 1] >= mid[1]).astype(np.int64) << 1)
            | ((p[:, 2] >= mid[2]).astype(np.int64) << 2))
    return member[want == octant]


def _octant_offset(np, octant, half):
    return np.array([
        half if (octant & 1) else 0.0,
        half if (octant & 2) else 0.0,
        half if (octant & 4) else 0.0,
    ])


class _Channels:
    """
    Zero-copy numpy views over a cloud, built once and sliced per node.

    ``np.frombuffer`` rather than ``np.asarray``: the positions of a 20-million
    point cloud are 240 MB, and a build that copies them once per node instead
    of viewing them turns a seconds-long walk into a swap storm.
    """

    def __init__(self, np, cloud: PointCloud):
        self._np = np
        self._cloud = cloud
        self.positions = np.frombuffer(
            cloud.positions, dtype=np.float32).reshape(-1, 3).astype(np.float64)
        self.colors = (
            np.frombuffer(bytes(cloud.colors), dtype=np.uint8).reshape(-1, 3)
            if cloud.colors is not None else None)
        self.intensity = (
            np.frombuffer(cloud.intensity, dtype=np.float32)
            if cloud.intensity is not None else None)
        self.source_index = (
            np.frombuffer(cloud.indices, dtype=np.uint32).astype(np.int64)
            if cloud.indices is not None
            else np.arange(cloud.count, dtype=np.int64))

    def subset(self, member) -> PointCloud:
        """A :class:`PointCloud` holding only ``member``, with source indices."""
        np = self._np
        member = np.asarray(member, dtype=np.int64)

        positions = array("f")
        colors = bytearray() if self.colors is not None else None
        intensity = array("f") if self.intensity is not None else None
        indices = array(U32)

        if member.size:
            positions.frombytes(
                self.positions[member].astype(np.float32).tobytes())
            if colors is not None:
                colors += self.colors[member].tobytes()
            if intensity is not None:
                intensity.frombytes(self.intensity[member].tobytes())
            # Native uint32, not '<u4': array.frombytes reads native order and
            # to_wire byteswaps from native to little-endian on its way out.
            # Forcing little-endian here would double-swap on a big-endian host.
            indices.frombytes(self.source_index[member].astype(np.uint32)
                              .tobytes())

        return PointCloud(
            positions=positions, colors=colors, intensity=intensity,
            source_format=self._cloud.source_format,
            original_count=self._cloud.original_count or self._cloud.count,
            indices=indices,
        )


def _numpy():
    try:
        import numpy as np
    except ImportError as err:  # pragma: no cover - numpy is a hard dependency
        raise PointCloudError(
            "Level-of-detail point clouds need numpy, which should have been "
            "installed with Potato. Reinstall with `pip install -e .`, or set "
            "`lod: false` on the schema to use uniform decimation instead."
        ) from err
    return np


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def to_octree_bytes(tree: Octree) -> bytes:
    """Serialize an :class:`Octree` into the OCT1 container."""
    # Two passes: offsets are relative to the start of the blob region, and the
    # blob region's own start depends on the header length, which depends on the
    # offsets. Making them blob-relative breaks that circularity.
    ordered = sorted(tree.nodes.values(), key=lambda n: (n.level, n.key))
    cursor = 0
    for node in ordered:
        blob = tree.blobs[node.key]
        node.offset = cursor
        node.length = len(blob)
        cursor += len(blob)

    header = {
        "version": 1,
        "bounds": tree.bounds,
        "total_count": tree.total_count,
        "source_format": tree.source_format,
        "spacing": tree.spacing,
        "depth": tree.depth,
        "truncated": tree.truncated,
        "nodes": [node.to_json() for node in ordered],
    }
    blob_json = json.dumps(header, separators=(",", ":")).encode("utf-8")

    out = bytearray(OCT_MAGIC)
    out += struct.pack("<I", len(blob_json))
    out += blob_json
    for node in ordered:
        out += tree.blobs[node.key]
    return bytes(out)


def read_manifest(path: str | Path) -> Dict[str, Any]:
    """
    The header of an OCT1 file, without reading a single point.

    This is what the client fetches first: node keys, bounds and counts are a
    few tens of kilobytes for a scene whose points are hundreds of megabytes.
    """
    p = Path(path)
    with open(p, "rb") as fh:
        head = fh.read(8)
        if len(head) < 8 or head[:4] != OCT_MAGIC:
            raise PointCloudError(f"{p.name} is not an OCT1 octree file")
        (header_len,) = struct.unpack("<I", head[4:8])
        raw = fh.read(header_len)
    if len(raw) < header_len:
        raise PointCloudError(f"{p.name} is truncated in its header")
    return json.loads(raw.decode("utf-8"))


def read_node(path: str | Path, key: str) -> bytes:
    """
    The PNT1 blob for one node.

    Seeks rather than reading the file: a node is a few hundred kilobytes out
    of a container that may be gigabytes, and this runs once per node per
    camera move.
    """
    p = Path(path)
    manifest = read_manifest(p)
    entry = next((n for n in manifest["nodes"] if n["key"] == key), None)
    if entry is None:
        raise PointCloudError(f"no node '{key}' in {p.name}")

    with open(p, "rb") as fh:
        head = fh.read(8)
        (header_len,) = struct.unpack("<I", head[4:8])
        base = 8 + header_len
        fh.seek(base + int(entry["offset"]))
        blob = fh.read(int(entry["length"]))

    if len(blob) < 8 or blob[:4] != PNT_MAGIC:
        raise PointCloudError(
            f"node '{key}' in {p.name} does not start with a PNT1 header; the "
            f"octree cache is corrupt. Delete it and it will rebuild.")
    return blob


def manifest_for_client(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """
    The manifest as the viewer needs it.

    ``offset`` and ``length`` are stripped: they are byte positions inside a
    server-side cache file, and a client that knew them could only misuse them.
    Everything the traversal needs — key, level, bounds, count, children — stays.
    """
    return {
        "version": manifest.get("version", 1),
        "bounds": manifest.get("bounds"),
        "total_count": manifest.get("total_count", 0),
        "source_format": manifest.get("source_format", ""),
        "spacing": manifest.get("spacing", 0.0),
        "depth": manifest.get("depth", 0),
        "truncated": bool(manifest.get("truncated")),
        "nodes": [
            {k: node[k] for k in
             ("key", "level", "bounds", "count", "children") if k in node}
            for node in manifest.get("nodes", [])
        ],
    }


def node_key_is_safe(key: str) -> bool:
    """
    ``r`` followed by octant digits, and nothing else.

    The key reaches :func:`read_node`, which looks it up in the manifest rather
    than on the filesystem, so this is a second line rather than the only one —
    but a key is user input arriving in a query string and it costs nothing to
    say exactly what one is.
    """
    if not key or key[0] != "r" or len(key) > 64:
        return False
    return all(c in "01234567" for c in key[1:])
