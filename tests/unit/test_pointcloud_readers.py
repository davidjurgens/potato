"""
Point cloud readers.

Every fixture is **generated in the test**, byte by byte, rather than committed
as a binary blob. Two reasons: a committed blob cannot be read in review, so a
wrong fixture is invisible; and writing the bytes out here forces the test to
state what each format actually says, which is where the bugs live (LAS scale
factors, PCD's planar compressed layout, PLY endianness).

The formats are exactly the ones researchers arrive with: PCD from PCL, PLY from
photogrammetry and CloudCompare, KITTI velodyne `.bin`, and LAS from survey and
airborne lidar.
"""

import math
import struct
from array import array
from pathlib import Path

import pytest

from potato.media.pointcloud import (
    DEFAULT_MAX_POINTS,
    PointCloud,
    PointCloudError,
    decimate,
    detect_format,
    from_wire,
    read_point_cloud,
    to_wire,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def write(tmp_path: Path, name: str, data: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def kitti_bytes(points):
    """float32 x, y, z, intensity per point, no header."""
    return b"".join(struct.pack("<4f", *p) for p in points)


def pcd_ascii(points):
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\n"
        "VERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\n"
        f"WIDTH {len(points)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\n"
        f"POINTS {len(points)}\nDATA ascii\n")
    body = "".join(f"{x} {y} {z}\n" for x, y, z in points)
    return (header + body).encode("ascii")


def pcd_binary(points):
    header = (
        "VERSION 0.7\nFIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\n"
        f"COUNT 1 1 1 1\nWIDTH {len(points)}\nHEIGHT 1\n"
        f"POINTS {len(points)}\nDATA binary\n")
    body = b"".join(struct.pack("<4f", *p) for p in points)
    return header.encode("ascii") + body


def lzf_literals(payload: bytes) -> bytes:
    """
    A valid LZF stream that uses only literal runs.

    LZF permits an encoder to emit nothing but literals, so this is a legal
    stream and exercises the decompressor's literal path without needing a real
    compressor in the test suite.
    """
    out = bytearray()
    i = 0
    while i < len(payload):
        chunk = payload[i:i + 32]
        out.append(len(chunk) - 1)      # ctrl < 32 means a literal run
        out += chunk
        i += len(chunk)
    return bytes(out)


def pcd_binary_compressed(points):
    """
    binary_compressed stores each field CONTIGUOUSLY, then LZF-compresses it.

    Building the planar layout explicitly here is the point of the fixture: a
    reader that treats the decompressed buffer as interleaved records produces a
    plausible cloud of nonsense rather than an error.
    """
    xs = array("f", [p[0] for p in points]).tobytes()
    ys = array("f", [p[1] for p in points]).tobytes()
    zs = array("f", [p[2] for p in points]).tobytes()
    planar = xs + ys + zs
    compressed = lzf_literals(planar)

    header = (
        "VERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\n"
        f"WIDTH {len(points)}\nHEIGHT 1\n"
        f"POINTS {len(points)}\nDATA binary_compressed\n")
    return (header.encode("ascii")
            + struct.pack("<II", len(compressed), len(planar))
            + compressed)


def ply_ascii(points, colors=None):
    header = ["ply", "format ascii 1.0", f"element vertex {len(points)}",
              "property float x", "property float y", "property float z"]
    if colors:
        header += ["property uchar red", "property uchar green",
                   "property uchar blue"]
    header.append("end_header")
    lines = []
    for i, (x, y, z) in enumerate(points):
        row = f"{x} {y} {z}"
        if colors:
            row += " " + " ".join(str(c) for c in colors[i])
        lines.append(row)
    return ("\n".join(header) + "\n" + "\n".join(lines) + "\n").encode("ascii")


def ply_binary(points, big_endian=False, colors=None):
    order = "binary_big_endian" if big_endian else "binary_little_endian"
    header = ["ply", f"format {order} 1.0", f"element vertex {len(points)}",
              "property float x", "property float y", "property float z"]
    if colors:
        header += ["property uchar red", "property uchar green",
                   "property uchar blue"]
    header.append("end_header")
    prefix = ">" if big_endian else "<"
    body = b""
    for i, (x, y, z) in enumerate(points):
        body += struct.pack(prefix + "3f", x, y, z)
        if colors:
            body += struct.pack(prefix + "3B", *colors[i])
    return ("\n".join(header) + "\n").encode("ascii") + body


def las_bytes(points, point_format=0, scale=(0.001, 0.001, 0.001),
              offset=(0.0, 0.0, 0.0), colors=None, version=(1, 2)):
    """A minimal but structurally real LAS file."""
    record_len = {0: 20, 1: 28, 2: 26, 3: 34}[point_format]
    header_size = 227
    header = bytearray(header_size)
    header[0:4] = b"LASF"
    header[24] = version[0]
    header[25] = version[1]
    struct.pack_into("<H", header, 94, header_size)
    struct.pack_into("<I", header, 96, header_size)
    struct.pack_into("<B", header, 104, point_format)
    struct.pack_into("<H", header, 105, record_len)
    struct.pack_into("<I", header, 107, len(points))
    # Scale factors at byte 131, offsets at 155 (LAS 1.2 public header block).
    # These blocks are adjacent, so writing the offsets a few bytes early
    # silently overwrites two of the three scale factors.
    struct.pack_into("<3d", header, 131, *scale)
    struct.pack_into("<3d", header, 155, *offset)

    body = b""
    for i, (x, y, z) in enumerate(points):
        rec = bytearray(record_len)
        struct.pack_into("<3i", rec, 0,
                         int(round((x - offset[0]) / scale[0])),
                         int(round((y - offset[1]) / scale[1])),
                         int(round((z - offset[2]) / scale[2])))
        struct.pack_into("<H", rec, 12, 100 + i)      # intensity
        if colors is not None and point_format in (2, 3):
            at = 20 if point_format == 2 else 28
            struct.pack_into("<3H", rec, at, *colors[i])
        body += bytes(rec)
    return bytes(header) + body


def positions_of(cloud):
    return [tuple(round(v, 4) for v in cloud.positions[i:i + 3])
            for i in range(0, len(cloud.positions), 3)]


CUBE = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 3.0)]


# ---------------------------------------------------------------------------

class TestDetectFormat:
    def test_content_beats_extension(self, tmp_path):
        # A PLY named .bin must not be read as raw KITTI floats. There is no
        # header in KITTI, so the mistake produces garbage rather than an error.
        path = write(tmp_path, "scan.bin", ply_ascii(CUBE))
        assert detect_format(path) == "ply"

    @pytest.mark.parametrize("name,data,expected", [
        ("a.bin", kitti_bytes([(1, 2, 3, 4)]), "kitti_bin"),
        ("a.pcd", pcd_ascii(CUBE), "pcd"),
        ("a.ply", ply_ascii(CUBE), "ply"),
        ("a.las", las_bytes(CUBE), "las"),
        ("a.xyz", b"1 2 3\n", "xyz"),
    ])
    def test_each_format(self, tmp_path, name, data, expected):
        assert detect_format(write(tmp_path, name, data)) == expected

    def test_unknown_names_the_supported_set(self, tmp_path):
        path = write(tmp_path, "notes.txt", b"hello")
        with pytest.raises(PointCloudError, match="PCD, PLY, KITTI"):
            detect_format(path)

    def test_laz_says_how_to_convert(self, tmp_path):
        # LAZ is compressed LAS; refusing without naming laszip leaves the user
        # with a file they cannot use and no next step.
        path = write(tmp_path, "scan.laz", b"\x00" * 64)
        with pytest.raises(PointCloudError, match="laszip"):
            read_point_cloud(path)


class TestKittiBin:
    def test_reads_xyz_and_intensity(self, tmp_path):
        path = write(tmp_path, "0001.bin", kitti_bytes(
            [(1.0, 2.0, 3.0, 0.5), (4.0, 5.0, 6.0, 0.25)]))
        cloud = read_point_cloud(path)
        assert cloud.count == 2
        assert positions_of(cloud) == [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
        assert list(cloud.intensity) == [0.5, 0.25]
        assert cloud.colors is None

    def test_a_length_that_is_not_a_multiple_of_16_is_refused(self, tmp_path):
        # The only integrity check the format allows. Without it, any binary
        # file read as KITTI yields a confident cloud of noise.
        path = write(tmp_path, "0001.bin", b"\x00" * 30)
        with pytest.raises(PointCloudError, match="multiple of 16"):
            read_point_cloud(path)


class TestPcd:
    def test_ascii(self, tmp_path):
        cloud = read_point_cloud(write(tmp_path, "a.pcd", pcd_ascii(CUBE)))
        assert positions_of(cloud) == [tuple(map(float, p)) for p in CUBE]

    def test_binary_with_intensity(self, tmp_path):
        points = [(1.0, 2.0, 3.0, 0.75), (4.0, 5.0, 6.0, 0.25)]
        cloud = read_point_cloud(write(tmp_path, "a.pcd", pcd_binary(points)))
        assert positions_of(cloud) == [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
        assert list(cloud.intensity) == [0.75, 0.25]

    def test_binary_compressed_is_read_as_planar(self, tmp_path):
        # The regression this guards: reading the decompressed buffer as
        # interleaved records mixes x bytes with y bytes and yields coordinates
        # that look real. The values here are distinct per axis so a planar/
        # interleaved mix-up cannot coincidentally pass.
        points = [(1.0, 10.0, 100.0), (2.0, 20.0, 200.0), (3.0, 30.0, 300.0)]
        cloud = read_point_cloud(
            write(tmp_path, "a.pcd", pcd_binary_compressed(points)))
        assert positions_of(cloud) == points

    def test_a_missing_data_line_is_reported(self, tmp_path):
        path = write(tmp_path, "a.pcd", b"VERSION 0.7\nFIELDS x y z\n")
        with pytest.raises(PointCloudError, match="DATA"):
            read_point_cloud(path)

    def test_a_cloud_with_no_z_is_refused_by_name(self, tmp_path):
        data = ("VERSION 0.7\nFIELDS x y\nSIZE 4 4\nTYPE F F\nCOUNT 1 1\n"
                "WIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n1 2\n").encode()
        with pytest.raises(PointCloudError, match="no 'z' field"):
            read_point_cloud(write(tmp_path, "a.pcd", data))


class TestPly:
    def test_ascii(self, tmp_path):
        cloud = read_point_cloud(write(tmp_path, "a.ply", ply_ascii(CUBE)))
        assert positions_of(cloud) == [tuple(map(float, p)) for p in CUBE]

    def test_binary_little_endian(self, tmp_path):
        cloud = read_point_cloud(write(tmp_path, "a.ply", ply_binary(CUBE)))
        assert positions_of(cloud) == [tuple(map(float, p)) for p in CUBE]

    def test_binary_big_endian(self, tmp_path):
        # PLY is the one format here that really is written big-endian in the
        # wild, and the byte order is declared in the header rather than
        # guessable from the data.
        cloud = read_point_cloud(
            write(tmp_path, "a.ply", ply_binary(CUBE, big_endian=True)))
        assert positions_of(cloud) == [tuple(map(float, p)) for p in CUBE]

    def test_colors_are_read(self, tmp_path):
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (10, 20, 30)]
        cloud = read_point_cloud(
            write(tmp_path, "a.ply", ply_ascii(CUBE, colors)))
        assert list(cloud.colors) == [c for rgb in colors for c in rgb]

    def test_a_vertex_list_property_is_refused_rather_than_mis_strided(
            self, tmp_path):
        data = (b"ply\nformat binary_little_endian 1.0\nelement vertex 1\n"
                b"property float x\nproperty float y\nproperty float z\n"
                b"property list uchar int extra\nend_header\n" + b"\x00" * 16)
        with pytest.raises(PointCloudError, match="list property"):
            read_point_cloud(write(tmp_path, "a.ply", data))


class TestLas:
    def test_scale_and_offset_are_applied(self, tmp_path):
        # Reading the raw int32 coordinates gives the right shape at the wrong
        # scale and position, which reads as a units problem rather than a bug.
        points = [(10.5, -3.25, 100.125), (0.0, 0.0, 0.0)]
        path = write(tmp_path, "a.las", las_bytes(
            points, scale=(0.001, 0.001, 0.001), offset=(500.0, -200.0, 30.0)))
        cloud = read_point_cloud(path)
        for got, want in zip(positions_of(cloud), points):
            assert all(math.isclose(a, b, abs_tol=1e-3)
                       for a, b in zip(got, want))

    def test_intensity(self, tmp_path):
        cloud = read_point_cloud(
            write(tmp_path, "a.las", las_bytes(CUBE)))
        assert list(cloud.intensity) == [100.0, 101.0, 102.0, 103.0]

    def test_sixteen_bit_color_is_scaled_down(self, tmp_path):
        colors = [(65535, 0, 32768)] * len(CUBE)
        cloud = read_point_cloud(write(tmp_path, "a.las", las_bytes(
            CUBE, point_format=2, colors=colors)))
        assert list(cloud.colors[:3]) == [255, 0, 128]

    def test_eight_bit_color_is_left_alone(self, tmp_path):
        # Files that store 0-255 in the 16-bit field are common. Scaling them
        # unconditionally by 1/257 would render the cloud almost black.
        colors = [(255, 128, 0)] * len(CUBE)
        cloud = read_point_cloud(write(tmp_path, "a.las", las_bytes(
            CUBE, point_format=2, colors=colors)))
        assert list(cloud.colors[:3]) == [255, 128, 0]

    def test_a_las_extension_without_the_signature_says_so(self, tmp_path):
        with pytest.raises(PointCloudError, match="not a LAS file"):
            read_point_cloud(write(tmp_path, "a.las", b"NOPE" + b"\x00" * 400))


class TestXyz:
    def test_plain_xyz(self, tmp_path):
        cloud = read_point_cloud(
            write(tmp_path, "a.xyz", b"1 2 3\n4 5 6\n\n# comment\n"))
        assert positions_of(cloud) == [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
        assert cloud.colors is None

    def test_float_colors_are_read_as_zero_to_one(self, tmp_path):
        cloud = read_point_cloud(
            write(tmp_path, "a.xyz", b"1 2 3 1.0 0.0 0.5\n"))
        assert list(cloud.colors) == [255, 0, 128]

    def test_integer_colors_are_read_as_bytes(self, tmp_path):
        cloud = read_point_cloud(
            write(tmp_path, "a.xyz", b"1 2 3 255 0 128\n"))
        assert list(cloud.colors) == [255, 0, 128]


class TestDecimate:
    def test_uniform_stride_not_truncation(self, tmp_path):
        # The property that matters: a decimated lidar sweep must still cover
        # the whole scene. Truncating keeps one contiguous slice and drops the
        # rest, which looks like a sensor failure.
        points = [(float(i), 0.0, 0.0) for i in range(100)]
        cloud = PointCloud(positions=array(
            "f", [c for p in points for c in p]))
        thinned = decimate(cloud, 10)

        xs = [p[0] for p in positions_of(thinned)]
        assert len(xs) == 10
        assert xs[0] == 0.0
        assert xs[-1] == 90.0                      # reaches the far end
        assert xs == sorted(xs)
        assert len(set(xs)) == len(xs)

    def test_colors_and_intensity_stay_aligned(self, tmp_path):
        n = 50
        cloud = PointCloud(
            positions=array("f", [float(i) for i in range(n * 3)]),
            colors=bytearray(i % 256 for i in range(n * 3)),
            intensity=array("f", [float(i) for i in range(n)]))
        thinned = decimate(cloud, 5)
        assert thinned.count == 5
        assert len(thinned.colors) == 15
        assert len(thinned.intensity) == 5
        # Point k of the thinned cloud must carry point k*step's own data.
        assert thinned.intensity[1] == 10.0
        assert thinned.positions[3] == 30.0

    def test_a_small_cloud_is_untouched(self):
        cloud = PointCloud(positions=array("f", [1, 2, 3]))
        assert decimate(cloud, 100) is cloud

    def test_zero_means_no_decimation(self, tmp_path):
        points = [(float(i), 0.0, 0.0) for i in range(50)]
        path = write(tmp_path, "a.xyz",
                     "\n".join(f"{x} {y} {z}" for x, y, z in points).encode())
        # Exporters must never write back a thinned cloud.
        assert read_point_cloud(path, max_points=0).count == 50
        assert read_point_cloud(path, max_points=10).count == 10

    def test_original_count_survives_decimation(self, tmp_path):
        points = [(float(i), 0.0, 0.0) for i in range(200)]
        path = write(tmp_path, "a.xyz",
                     "\n".join(f"{x} {y} {z}" for x, y, z in points).encode())
        cloud = read_point_cloud(path, max_points=20)
        # The UI has to be able to say what it dropped.
        assert cloud.count == 20
        assert cloud.original_count == 200


class TestWireFormat:
    def test_round_trip_with_everything(self):
        cloud = PointCloud(
            positions=array("f", [1, 2, 3, 4, 5, 6]),
            colors=bytearray([255, 0, 0, 0, 255, 0]),
            intensity=array("f", [0.5, 0.25]),
            source_format="pcd", original_count=99)
        header, back = from_wire(to_wire(cloud))

        assert header["count"] == 2
        assert header["has_colors"] and header["has_intensity"]
        assert header["original_count"] == 99
        assert header["bounds"] == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        assert list(back.positions) == list(cloud.positions)
        assert list(back.colors) == list(cloud.colors)
        assert list(back.intensity) == list(cloud.intensity)

    def test_round_trip_positions_only(self):
        cloud = PointCloud(positions=array("f", [1, 2, 3]))
        header, back = from_wire(to_wire(cloud))
        assert not header["has_colors"]
        assert not header["has_intensity"]
        assert back.colors is None and back.intensity is None
        assert list(back.positions) == [1.0, 2.0, 3.0]

    def test_offsets_are_where_the_header_says(self):
        # The client slices typed arrays straight out of this buffer by offset,
        # so a wrong size claim is a silently misaligned cloud, not an error.
        cloud = PointCloud(positions=array("f", [1, 2, 3, 4, 5, 6]),
                           colors=bytearray(6), intensity=array("f", [0, 0]))
        blob = to_wire(cloud)
        header_len = struct.unpack_from("<I", blob, 4)[0]
        expected = 8 + header_len + (2 * 12) + (2 * 3) + (2 * 4)
        assert len(blob) == expected

    def test_extra_header_fields_survive(self):
        header, _ = from_wire(to_wire(PointCloud(positions=array("f", [0, 0, 0])),
                                      extra={"calibration": {"foo": 1}}))
        assert header["calibration"] == {"foo": 1}

    def test_a_foreign_buffer_is_refused(self):
        with pytest.raises(PointCloudError, match="PNT1"):
            from_wire(b"NOPE" + b"\x00" * 32)

    def test_empty_cloud_has_no_bounds(self):
        header, back = from_wire(to_wire(PointCloud(positions=array("f"))))
        assert header["count"] == 0
        assert header["bounds"] is None
        assert back.count == 0


class TestDefaults:
    def test_the_point_cap_is_documented_and_applied(self, tmp_path):
        # Not a magic number buried in the reader: WebGL will allocate a
        # multi-million-point buffer and then render at a few frames a second,
        # which reads as a broken viewer rather than an oversized scan.
        assert DEFAULT_MAX_POINTS == 500_000
        points = [(float(i), 0.0, 0.0) for i in range(1000)]
        path = write(tmp_path, "a.xyz",
                     "\n".join(f"{x} {y} {z}" for x, y, z in points).encode())
        assert read_point_cloud(path).count == 1000  # under the cap
