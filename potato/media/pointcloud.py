"""
Point cloud ingest: read what researchers have, serve one thing the browser can.

## Why the browser is not given the original file

Lidar and photogrammetry arrive as PCD, PLY, KITTI ``.bin`` or LAS. A browser
understands none of them, so something has to convert. Doing it in JavaScript
would mean four parsers to get right, four sets of endianness and
point-record-format bugs, and re-parsing on every page load.

Converting server-side means one parser per format in Python — where the
byte-level formats are far easier to test — and **one** wire format in the
browser. It also puts decimation somewhere sensible: a 2-million-point scan has
to be reduced before it reaches WebGL, and doing that once at conversion beats
doing it per viewer.

This mirrors what ``potato/media/images.py`` and ``video.py`` already do for
formats browsers cannot display, and reuses the same content-addressed cache.

## The wire format

``PNT1``, deliberately boring:

    magic        4 bytes   b"PNT1"
    header_len   uint32 LE
    header       header_len bytes of UTF-8 JSON
    positions    float32 * 3N   (x, y, z interleaved)
    colors       uint8 * 3N     (optional, r, g, b interleaved)
    intensity    float32 * N    (optional)
    indices      uint32 * N     (optional, source-file index per point)

Interleaved XYZ is what a three.js ``BufferGeometry`` position attribute wants,
so the client does ``new Float32Array(buffer, offset, 3 * n)`` and hands it
straight over — no per-point JavaScript loop anywhere in the path.

Everything is little-endian. Big-endian machines are not a realistic target for
a WebGL viewer, and pretending to support them without a machine to test on
would be worse than saying so.

## Why there is an index channel

``segment_3d`` stores **point indices**, and the spatial contract originally
justified that with "the served cloud is a fixed decimation, so index *i* always
means the same point". It is not fixed. ``max_points`` is a schema option, so
lowering it — exactly what an admin does when a machine struggles — changes the
stride and silently re-points every stored per-point segment at different
points. Nothing errors; the labels just move.

So whenever the served set is not the whole file in file order, each point
carries its index **into the source file**. Absent indices means the identity
mapping, which keeps the common small-cloud case a byte-for-byte no-op. Octree
LOD (:mod:`potato.media.octree`) needs the same channel for the same reason:
there, the set of loaded points changes as the camera moves.
"""

from __future__ import annotations

import json
import logging
import re
import struct
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAGIC = b"PNT1"

#: Points beyond this are dropped by uniform stride before the cloud is served.
#: WebGL will happily allocate a 2M-point buffer and then render at 4 fps, which
#: reads as a broken viewer rather than an oversized scan.
DEFAULT_MAX_POINTS = 500_000

#: Extensions we can read. LAZ is deliberately absent; see read_point_cloud.
SUPPORTED_SUFFIXES = (".pcd", ".ply", ".bin", ".las", ".xyz", ".pts")

#: Typecode for a 4-byte unsigned int. ``array('I')`` is C ``unsigned int``,
#: which is 4 bytes everywhere that matters but is not guaranteed to be — and
#: the index channel is read on the client as a Uint32Array, so a 2- or 8-byte
#: itemsize would produce silently misaligned garbage rather than an error.
U32 = "I" if array("I").itemsize == 4 else "L"


class PointCloudError(RuntimeError):
    """A point cloud could not be read. The message names the next action."""


@dataclass
class PointCloud:
    """
    A cloud in the one shape the rest of Potato uses.

    ``positions`` is interleaved xyz, so ``len(positions) == 3 * count``.
    ``colors`` is interleaved rgb bytes or None. ``intensity`` is one float per
    point or None — lidar returns it, photogrammetry usually does not.
    """

    positions: array          # 'f', length 3N
    colors: Optional[bytearray] = None      # length 3N
    intensity: Optional[array] = None       # 'f', length N
    source_format: str = ""
    #: Points in the file before decimation, so the UI can say what it dropped.
    original_count: int = 0
    #: Source-file index per point ('I', length N), or None for the identity
    #: mapping. See the module docstring: this is what makes ``segment_3d``
    #: survive a change of ``max_points`` or a switch to octree LOD.
    indices: Optional[array] = None

    @property
    def count(self) -> int:
        return len(self.positions) // 3

    def bounds(self) -> Optional[List[List[float]]]:
        """``[[minx, miny, minz], [maxx, maxy, maxz]]``, or None when empty."""
        n = self.count
        if n == 0:
            return None
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        pos = self.positions
        for i in range(0, len(pos), 3):
            for axis in range(3):
                v = pos[i + axis]
                if v < lo[axis]:
                    lo[axis] = v
                if v > hi[axis]:
                    hi[axis] = v
        return [lo, hi]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def detect_format(path: str | Path) -> str:
    """
    Which reader handles this file.

    Content first, extension second. ``.bin`` in particular is claimed by KITTI
    velodyne scans and by roughly everything else in computing, so a magic-byte
    check has to come before the suffix — and PCD/PLY both start with a text
    header that is unambiguous.
    """
    p = Path(path)
    try:
        with open(p, "rb") as fh:
            head = fh.read(64)
    except OSError as err:
        raise PointCloudError(f"cannot read {p}: {err}") from err

    if head.startswith(b"ply"):
        return "ply"
    if head.startswith(b"# .PCD") or head.startswith(b"VERSION"):
        return "pcd"
    if head.startswith(b"LASF"):
        return "las"

    suffix = p.suffix.lower()
    if suffix == ".las":
        # Named .las but without the signature. Route it to the LAS reader
        # anyway so the error names the actual problem ("does not start with
        # LASF") rather than listing every format we support, which reads as
        # "LAS is unsupported" when in fact the file is truncated or corrupt.
        return "las"
    if suffix == ".bin":
        return "kitti_bin"
    if suffix in (".xyz", ".pts"):
        return "xyz"
    if suffix == ".laz":
        return "laz"
    raise PointCloudError(
        f"unrecognised point cloud format for {p.name}. Supported: "
        f"PCD, PLY, KITTI .bin, LAS, and whitespace-separated .xyz/.pts.")


def read_point_cloud(path: str | Path,
                     max_points: int = DEFAULT_MAX_POINTS) -> PointCloud:
    """
    Read any supported cloud, decimated to ``max_points``.

    Pass ``max_points=0`` to disable decimation — used by the exporters, which
    must not silently write back a thinned cloud.
    """
    fmt = detect_format(path)
    if fmt == "laz":
        raise PointCloudError(
            "LAZ is compressed LAS and needs laszip to read. Convert first: "
            "`laszip -i scan.laz -o scan.las`, or install laspy[laszip].")

    reader = {
        "pcd": _read_pcd,
        "ply": _read_ply,
        "kitti_bin": _read_kitti_bin,
        "las": _read_las,
        "xyz": _read_xyz,
    }[fmt]
    cloud = reader(Path(path))
    cloud.source_format = fmt
    cloud.original_count = cloud.count
    if max_points:
        cloud = decimate(cloud, max_points)
    return cloud


def decimate(cloud: PointCloud, max_points: int) -> PointCloud:
    """
    Thin a cloud to at most ``max_points`` by **uniform stride**.

    Not truncation. A lidar file is written in scan order, so keeping the first
    N points keeps one contiguous slice of the sweep and drops the rest of the
    scene — which looks like a sensor failure, not like decimation. Every Nth
    point keeps the whole scene at lower density, which looks like exactly what
    it is.

    The kept points carry their **source index**, so a stored ``segment_3d``
    still means the same points after ``max_points`` changes. Without that, the
    thinning silently relabels: at stride 4 index 10 is source point 40, at
    stride 5 it is source point 50.
    """
    n = cloud.count
    if max_points <= 0 or n <= max_points:
        return cloud

    step = (n + max_points - 1) // max_points
    keep = range(0, n, step)

    positions = array("f")
    for i in keep:
        positions.extend(cloud.positions[i * 3:i * 3 + 3])

    colors = None
    if cloud.colors is not None:
        colors = bytearray()
        for i in keep:
            colors.extend(cloud.colors[i * 3:i * 3 + 3])

    intensity = None
    if cloud.intensity is not None:
        intensity = array("f", (cloud.intensity[i] for i in keep))

    # Compose rather than overwrite: decimating an already-decimated cloud must
    # still yield indices into the original file, not into the intermediate.
    if cloud.indices is not None:
        indices = array(U32, (cloud.indices[i] for i in keep))
    else:
        indices = array(U32, keep)

    return PointCloud(
        positions=positions, colors=colors, intensity=intensity,
        source_format=cloud.source_format,
        original_count=cloud.original_count or n,
        indices=indices,
    )


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

def to_wire(cloud: PointCloud, extra: Optional[Dict[str, Any]] = None) -> bytes:
    """Serialize a cloud into the PNT1 buffer the viewer fetches."""
    n = cloud.count
    header: Dict[str, Any] = {
        "version": 1,
        "count": n,
        "has_colors": cloud.colors is not None,
        "has_intensity": cloud.intensity is not None,
        "has_indices": cloud.indices is not None,
        "source_format": cloud.source_format,
        "original_count": cloud.original_count or n,
        "bounds": cloud.bounds(),
    }
    if extra:
        header.update(extra)

    blob = json.dumps(header, separators=(",", ":")).encode("utf-8")
    out = bytearray(MAGIC)
    out += struct.pack("<I", len(blob))
    out += blob
    out += _to_le_bytes(cloud.positions)
    if cloud.colors is not None:
        out += bytes(cloud.colors)
    if cloud.intensity is not None:
        out += _to_le_bytes(cloud.intensity)
    if cloud.indices is not None:
        out += _to_le_bytes(cloud.indices)
    return bytes(out)


def from_wire(data: bytes) -> Tuple[Dict[str, Any], PointCloud]:
    """Inverse of :func:`to_wire`. Exists so the format has a round-trip test."""
    if len(data) < 8 or data[:4] != MAGIC:
        raise PointCloudError("not a PNT1 point cloud buffer")
    (header_len,) = struct.unpack("<I", data[4:8])
    header = json.loads(data[8:8 + header_len].decode("utf-8"))
    offset = 8 + header_len
    n = int(header["count"])

    positions = array("f")
    positions.frombytes(data[offset:offset + n * 12])
    _from_le(positions)
    offset += n * 12

    colors = None
    if header.get("has_colors"):
        colors = bytearray(data[offset:offset + n * 3])
        offset += n * 3

    intensity = None
    if header.get("has_intensity"):
        intensity = array("f")
        intensity.frombytes(data[offset:offset + n * 4])
        _from_le(intensity)
        offset += n * 4

    indices = None
    if header.get("has_indices"):
        indices = array(U32)
        indices.frombytes(data[offset:offset + n * 4])
        _from_le(indices)

    return header, PointCloud(
        positions=positions, colors=colors, intensity=intensity,
        source_format=header.get("source_format", ""),
        original_count=int(header.get("original_count", n)),
        indices=indices,
    )


def _to_le_bytes(values: array) -> bytes:
    """Little-endian bytes of a typed array, whatever the host endianness."""
    import sys
    if sys.byteorder == "little":
        return values.tobytes()
    copy = array(values.typecode, values)
    copy.byteswap()
    return copy.tobytes()


def _from_le(values: array) -> None:
    import sys
    if sys.byteorder != "little":
        values.byteswap()


# ---------------------------------------------------------------------------
# KITTI velodyne .bin
# ---------------------------------------------------------------------------

def _read_kitti_bin(path: Path) -> PointCloud:
    """
    Raw float32 x, y, z, intensity with no header at all.

    Because there is no header, a wrong file read as KITTI produces a plausible
    cloud of garbage rather than an error. The only available check is that the
    length divides by 16, so that check is enforced rather than assumed.
    """
    raw = path.read_bytes()
    if len(raw) % 16 != 0:
        raise PointCloudError(
            f"{path.name} is {len(raw)} bytes, which is not a multiple of 16. "
            f"A KITTI velodyne scan is float32 x,y,z,intensity per point. "
            f"If this is a different .bin format, convert it to PCD or PLY.")
    flat = array("f")
    flat.frombytes(raw)
    _from_le(flat)

    n = len(flat) // 4
    positions = array("f", bytes(12 * n))
    intensity = array("f", bytes(4 * n))
    for i in range(n):
        positions[i * 3] = flat[i * 4]
        positions[i * 3 + 1] = flat[i * 4 + 1]
        positions[i * 3 + 2] = flat[i * 4 + 2]
        intensity[i] = flat[i * 4 + 3]
    return PointCloud(positions=positions, intensity=intensity)


# ---------------------------------------------------------------------------
# Whitespace-separated text
# ---------------------------------------------------------------------------

def _read_xyz(path: Path) -> PointCloud:
    """
    ``x y z [r g b]`` per line, the lowest-common-denominator export.

    Columns beyond six are ignored rather than guessed at: some tools put
    normals there, some put intensity, and there is no header to tell them
    apart. Guessing wrong would colour a cloud by its surface normals and look
    like a rendering bug.
    """
    positions = array("f")
    colors = bytearray()
    saw_color = False
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line[0] in "#/":
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 3:
            continue
        try:
            positions.extend((float(parts[0]), float(parts[1]), float(parts[2])))
        except ValueError:
            continue
        if len(parts) >= 6:
            saw_color = True
            colors.extend(_as_byte(p) for p in parts[3:6])
        else:
            colors.extend(b"\x00\x00\x00")
    return PointCloud(positions=positions,
                      colors=colors if saw_color else None)


def _as_byte(text: str) -> int:
    """Colour channel as 0-255, accepting both 0-255 and 0-1 conventions."""
    try:
        v = float(text)
    except ValueError:
        return 0
    if 0.0 <= v <= 1.0 and "." in text:
        v *= 255.0
    return max(0, min(255, int(round(v))))


# ---------------------------------------------------------------------------
# PCD
# ---------------------------------------------------------------------------

_PCD_TYPE_CODES = {
    ("F", 4): "f", ("F", 8): "d",
    ("U", 1): "B", ("U", 2): "H", ("U", 4): "I", ("U", 8): "Q",
    ("I", 1): "b", ("I", 2): "h", ("I", 4): "i", ("I", 8): "q",
}


def _read_pcd(path: Path) -> PointCloud:
    raw = path.read_bytes()
    header, body_offset = _parse_pcd_header(raw)

    fields: List[str] = header["FIELDS"]
    sizes = [int(s) for s in header["SIZE"]]
    types = header["TYPE"]
    counts = [int(c) for c in header.get("COUNT", ["1"] * len(fields))]
    n = int(header["POINTS"][0]) if "POINTS" in header else (
        int(header["WIDTH"][0]) * int(header["HEIGHT"][0]))
    data_kind = header["DATA"][0].lower()

    if data_kind == "ascii":
        records = _pcd_ascii_records(raw[body_offset:], fields, counts, n)
    else:
        body = raw[body_offset:]
        if data_kind == "binary_compressed":
            body = _lzf_decompress_pcd(body)
            records = _pcd_planar_records(body, fields, sizes, types, counts, n)
        elif data_kind == "binary":
            records = _pcd_binary_records(body, fields, sizes, types, counts, n)
        else:
            raise PointCloudError(
                f"unsupported PCD DATA mode '{data_kind}'. "
                f"Expected ascii, binary, or binary_compressed.")

    return _records_to_cloud(records, fields)


def _parse_pcd_header(raw: bytes) -> Tuple[Dict[str, List[str]], int]:
    header: Dict[str, List[str]] = {}
    offset = 0
    while True:
        end = raw.find(b"\n", offset)
        if end < 0:
            raise PointCloudError("PCD header has no DATA line")
        line = raw[offset:end].decode("ascii", errors="replace").strip()
        offset = end + 1
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        header[parts[0].upper()] = parts[1:]
        if parts[0].upper() == "DATA":
            break
    for required in ("FIELDS", "SIZE", "TYPE", "DATA"):
        if required not in header:
            raise PointCloudError(f"PCD header is missing {required}")
    return header, offset


def _pcd_ascii_records(body: bytes, fields: List[str], counts: List[int],
                       n: int) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {f: [] for f in fields}
    # Expanded field order: COUNT > 1 means that field occupies several columns.
    order: List[Optional[str]] = []
    for name, count in zip(fields, counts):
        order.append(name)
        order.extend([None] * (count - 1))

    for line in body.decode("ascii", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < len(order):
            continue
        for name, text in zip(order, parts):
            if name is None:
                continue
            try:
                out[name].append(float(text))
            except ValueError:
                out[name].append(0.0)
        if len(out[fields[0]]) >= n:
            break
    return out


def _pcd_binary_records(body: bytes, fields: List[str], sizes: List[int],
                        types: List[str], counts: List[int],
                        n: int) -> Dict[str, List[float]]:
    fmt = "<"
    slots: List[Optional[str]] = []
    for name, size, kind, count in zip(fields, sizes, types, counts):
        code = _PCD_TYPE_CODES.get((kind.upper(), size))
        if code is None:
            raise PointCloudError(
                f"PCD field '{name}' has unsupported TYPE {kind} SIZE {size}")
        fmt += code * count
        slots.append(name)
        slots.extend([None] * (count - 1))

    stride = struct.calcsize(fmt)
    out: Dict[str, List[float]] = {f: [] for f in fields}
    available = len(body) // stride
    if available < n:
        # Truncated file: read what is there rather than raising. A partially
        # written scan is common on interrupted transfers and a half cloud is
        # more useful than an error, as long as it is logged.
        logger.warning("PCD claims %d points but only %d fit in the file", n,
                       available)
        n = available
    for i in range(n):
        values = struct.unpack_from(fmt, body, i * stride)
        for name, value in zip(slots, values):
            if name is not None:
                out[name].append(float(value))
    return out


def _pcd_planar_records(body: bytes, fields: List[str], sizes: List[int],
                        types: List[str], counts: List[int],
                        n: int) -> Dict[str, List[float]]:
    """
    binary_compressed stores each field CONTIGUOUSLY, not interleaved.

    This is the detail that silently produces a garbled cloud rather than an
    error if it is missed: decompressing and then reading the buffer as
    interleaved records gives plausible-looking coordinates made of one field's
    bytes mixed with another's.
    """
    out: Dict[str, List[float]] = {}
    offset = 0
    for name, size, kind, count in zip(fields, sizes, types, counts):
        code = _PCD_TYPE_CODES.get((kind.upper(), size))
        if code is None:
            raise PointCloudError(
                f"PCD field '{name}' has unsupported TYPE {kind} SIZE {size}")
        span = size * count * n
        chunk = body[offset:offset + span]
        offset += span
        values = array(code)
        values.frombytes(chunk[:len(chunk) - (len(chunk) % values.itemsize)])
        _from_le(values)
        out[name] = [float(v) for v in values[::count]] if count > 1 else \
            [float(v) for v in values]
    return out


def _lzf_decompress_pcd(body: bytes) -> bytes:
    """
    Decompress the LZF payload of a binary_compressed PCD.

    The body starts with two uint32: compressed size, then uncompressed size.
    LZF itself is small enough to implement directly, which is the point —
    adding a dependency for forty lines of well-specified bit twiddling would be
    a worse trade for a research tool people install offline.
    """
    if len(body) < 8:
        raise PointCloudError("binary_compressed PCD has no size prefix")
    compressed_size, uncompressed_size = struct.unpack_from("<II", body, 0)
    payload = body[8:8 + compressed_size]

    out = bytearray()
    i = 0
    end = len(payload)
    while i < end:
        ctrl = payload[i]
        i += 1
        if ctrl < 32:
            # Literal run of ctrl + 1 bytes.
            run = ctrl + 1
            out += payload[i:i + run]
            i += run
        else:
            length = ctrl >> 5
            if length == 7:
                length += payload[i]
                i += 1
            ref = len(out) - ((ctrl & 0x1f) << 8) - payload[i] - 1
            i += 1
            if ref < 0:
                raise PointCloudError("corrupt LZF stream in PCD")
            # Byte-at-a-time on purpose: LZF back-references may overlap the
            # output being written (run-length encoding of a repeated byte),
            # which a slice copy would get wrong.
            for _ in range(length + 2):
                out.append(out[ref])
                ref += 1

    if len(out) != uncompressed_size:
        logger.warning("LZF produced %d bytes, header said %d",
                       len(out), uncompressed_size)
    return bytes(out)


# ---------------------------------------------------------------------------
# PLY
# ---------------------------------------------------------------------------

_PLY_TYPE_CODES = {
    "float": "f", "float32": "f", "double": "d", "float64": "d",
    "char": "b", "int8": "b", "uchar": "B", "uint8": "B",
    "short": "h", "int16": "h", "ushort": "H", "uint16": "H",
    "int": "i", "int32": "i", "uint": "I", "uint32": "I",
}


def _read_ply(path: Path) -> PointCloud:
    raw = path.read_bytes()
    header_end = raw.find(b"end_header")
    if header_end < 0:
        raise PointCloudError("PLY file has no end_header")
    line_end = raw.find(b"\n", header_end)
    body_offset = line_end + 1
    header_text = raw[:header_end].decode("ascii", errors="replace")

    fmt = "ascii"
    elements: List[Tuple[str, int, List[Tuple[str, str]]]] = []
    for line in header_text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "format":
            fmt = parts[1]
        elif parts[0] == "element":
            elements.append((parts[1], int(parts[2]), []))
        elif parts[0] == "property" and elements:
            if parts[1] == "list":
                # Face lists and similar. Recorded so the reader can refuse
                # rather than mis-stride a binary body.
                elements[-1][2].append(("__list__", parts[-1]))
            else:
                elements[-1][2].append((parts[-1], parts[1]))

    vertex = next((e for e in elements if e[0] == "vertex"), None)
    if vertex is None:
        raise PointCloudError("PLY file has no vertex element")

    if fmt == "ascii":
        records = _ply_ascii_records(raw[body_offset:], vertex)
    elif fmt in ("binary_little_endian", "binary_big_endian"):
        records = _ply_binary_records(raw[body_offset:], elements, vertex,
                                      big_endian=fmt.endswith("big_endian"))
    else:
        raise PointCloudError(f"unsupported PLY format '{fmt}'")

    return _records_to_cloud(records, list(records.keys()))


def _ply_ascii_records(body: bytes,
                       vertex: Tuple[str, int, List[Tuple[str, str]]]
                       ) -> Dict[str, List[float]]:
    names = [n for n, _ in vertex[2]]
    out: Dict[str, List[float]] = {n: [] for n in names}
    lines = body.decode("ascii", errors="replace").splitlines()
    for line in lines[:vertex[1]]:
        parts = line.split()
        if len(parts) < len(names):
            continue
        for name, text in zip(names, parts):
            try:
                out[name].append(float(text))
            except ValueError:
                out[name].append(0.0)
    return out


def _ply_binary_records(body: bytes,
                        elements: List[Tuple[str, int, List[Tuple[str, str]]]],
                        vertex: Tuple[str, int, List[Tuple[str, str]]],
                        big_endian: bool) -> Dict[str, List[float]]:
    prefix = ">" if big_endian else "<"
    offset = 0
    for element in elements:
        names = [n for n, _ in element[2]]
        if any(n == "__list__" for n in names):
            if element is vertex:
                raise PointCloudError(
                    "PLY vertex element has a list property, which this reader "
                    "does not handle. Re-export without per-vertex lists.")
            # A list-valued element before the vertices would need to be walked
            # entry by entry to find where vertices start. Refuse rather than
            # guess a stride and read garbage.
            raise PointCloudError(
                f"PLY element '{element[0]}' precedes the vertices and has a "
                f"list property, so the vertex offset cannot be computed. "
                f"Re-export with vertices first.")
        fmt = prefix + "".join(
            _ply_code(kind, element[0], name) for name, kind in element[2])
        stride = struct.calcsize(fmt)
        if element is vertex:
            out: Dict[str, List[float]] = {n: [] for n in names}
            available = min(element[1], (len(body) - offset) // stride)
            for i in range(available):
                values = struct.unpack_from(fmt, body, offset + i * stride)
                for name, value in zip(names, values):
                    out[name].append(float(value))
            return out
        offset += stride * element[1]
    raise PointCloudError("PLY vertex element not found in the body")


def _ply_code(kind: str, element: str, prop: str) -> str:
    code = _PLY_TYPE_CODES.get(kind)
    if code is None:
        raise PointCloudError(
            f"PLY property {element}.{prop} has unsupported type '{kind}'")
    return code


# ---------------------------------------------------------------------------
# LAS
# ---------------------------------------------------------------------------

def _read_las(path: Path) -> PointCloud:
    """
    Uncompressed LAS 1.0-1.4, point data record formats 0-3 and 6-8.

    Coordinates are stored as int32 and must be multiplied by the header's scale
    and offset. Reading them raw gives a cloud in the right shape at entirely
    the wrong scale and position, which looks like a units problem rather than a
    parsing bug — so the scale is applied here and tested.
    """
    raw = path.read_bytes()
    if len(raw) < 227 or raw[:4] != b"LASF":
        raise PointCloudError(
            f"{path.name} has a .las extension but does not start with the "
            f"'LASF' signature, so it is not a LAS file.")

    header_size = struct.unpack_from("<H", raw, 94)[0]
    offset_to_data = struct.unpack_from("<I", raw, 96)[0]
    point_format = struct.unpack_from("<B", raw, 104)[0] & 0x3f
    record_len = struct.unpack_from("<H", raw, 105)[0]
    legacy_count = struct.unpack_from("<I", raw, 107)[0]

    # Public header block, LAS 1.2 spec: three float64 scale factors at byte
    # 131, then three float64 offsets at byte 155. These are adjacent, so an
    # offset that is a few bytes out reads part of the scale block as the
    # origin and produces a cloud at a plausible-looking wrong position.
    scale = struct.unpack_from("<3d", raw, 131)
    origin = struct.unpack_from("<3d", raw, 155)

    count = legacy_count
    if count == 0 and header_size >= 375:
        # LAS 1.4 moved the count to a 64-bit field and zeroes the legacy one
        # for formats above 5.
        count = struct.unpack_from("<Q", raw, 247)[0]

    color_offsets = {2: 20, 3: 28, 7: 30, 8: 30}
    color_at = color_offsets.get(point_format)

    positions = array("f")
    intensity = array("f")
    colors = bytearray() if color_at is not None else None

    available = (len(raw) - offset_to_data) // record_len if record_len else 0
    if available < count:
        logger.warning("LAS claims %d points but only %d fit in the file",
                       count, available)
        count = available

    for i in range(count):
        base = offset_to_data + i * record_len
        xi, yi, zi = struct.unpack_from("<3i", raw, base)
        positions.append(float(xi * scale[0] + origin[0]))
        positions.append(float(yi * scale[1] + origin[1]))
        positions.append(float(zi * scale[2] + origin[2]))
        intensity.append(float(struct.unpack_from("<H", raw, base + 12)[0]))
        if colors is not None:
            r, g, b = struct.unpack_from("<3H", raw, base + color_at)
            # LAS colour is 16-bit; 8-bit files leave the high byte clear, so
            # scaling unconditionally by 257 would darken them to near black.
            shift = 8 if max(r, g, b) > 255 else 0
            colors.extend(((r >> shift) & 0xff, (g >> shift) & 0xff,
                           (b >> shift) & 0xff))

    return PointCloud(positions=positions, colors=colors, intensity=intensity)


# ---------------------------------------------------------------------------
# Shared assembly
# ---------------------------------------------------------------------------

_COLOR_ALIASES = (("red", "green", "blue"), ("r", "g", "b"),
                  ("diffuse_red", "diffuse_green", "diffuse_blue"))


def _records_to_cloud(records: Dict[str, List[float]],
                      fields: List[str]) -> PointCloud:
    lowered = {k.lower(): v for k, v in records.items()}
    for axis in ("x", "y", "z"):
        if axis not in lowered:
            raise PointCloudError(
                f"point cloud has no '{axis}' field (found: "
                f"{', '.join(sorted(records)) or 'nothing'})")

    xs, ys, zs = lowered["x"], lowered["y"], lowered["z"]
    n = min(len(xs), len(ys), len(zs))
    positions = array("f", bytes(12 * n))
    for i in range(n):
        positions[i * 3] = xs[i]
        positions[i * 3 + 1] = ys[i]
        positions[i * 3 + 2] = zs[i]

    colors = None
    for names in _COLOR_ALIASES:
        if all(name in lowered for name in names):
            channels = [lowered[name] for name in names]
            colors = bytearray()
            # A float colour field is 0-1 by convention; an integer one is
            # 0-255. Deciding per file rather than per value keeps a dark cloud
            # from being read as normalized and blown out to white.
            peak = max((max(c[:n], default=0.0) for c in channels), default=0.0)
            scale = 255.0 if peak <= 1.0 else 1.0
            for i in range(n):
                for channel in channels:
                    v = int(round(channel[i] * scale))
                    colors.append(max(0, min(255, v)))
            break

    intensity = None
    for name in ("intensity", "scalar_intensity", "i"):
        if name in lowered:
            intensity = array("f", (float(v) for v in lowered[name][:n]))
            break

    return PointCloud(positions=positions, colors=colors, intensity=intensity)
