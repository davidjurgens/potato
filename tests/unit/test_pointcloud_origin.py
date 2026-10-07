"""
Point clouds in map coordinates keep their precision.

Positions reach the browser as float32, which holds about seven significant
digits. A UTM northing has seven digits before the decimal point, so a LAS
file recorded to the centimetre used to be drawn, and annotated, on a 0.5 m
grid. The reader now subtracts a round origin before the float32 conversion
and the wire header carries it; ``positions + origin`` must give back the
file's coordinates to the file's precision.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from potato.media.pointcloud import (choose_origin, decimate, from_wire,
                                     read_point_cloud, to_wire)
from tests.helpers.test_utils import create_test_directory
from tests.unit.test_pointcloud_readers import las_bytes

#: A point in UTM zone 17N, recorded at 0.01 m.
UTM = [(500000.13, 4700000.27, 312.45), (500012.58, 4700021.91, 318.02),
       (499987.06, 4699990.44, 309.77)]


def _write(name: str, data: bytes) -> str:
    path = os.path.join(create_test_directory("pc_origin"), name)
    Path(path).write_bytes(data)
    return path


def _with_bounds(raw: bytes, points) -> bytes:
    """Fill the LAS header's max/min x, y, z block at byte 179."""
    header = bytearray(raw)
    xs, ys, zs = zip(*points)
    struct.pack_into("<6d", header, 179, max(xs), min(xs), max(ys), min(ys),
                     max(zs), min(zs))
    return bytes(header)


def _world(cloud):
    o = cloud.origin or [0.0, 0.0, 0.0]
    p = cloud.positions
    return [(p[i] + o[0], p[i + 1] + o[1], p[i + 2] + o[2])
            for i in range(0, len(p), 3)]


def _worst_error(cloud, points):
    return max(abs(a - b) for got, want in zip(_world(cloud), points)
               for a, b in zip(got, want))


def _utm_las(**kw):
    return las_bytes(UTM, scale=(0.01, 0.01, 0.01),
                     offset=(500000.0, 4700000.0, 0.0), **kw)


class TestLas:
    def test_utm_coordinates_keep_their_centimetres(self):
        cloud = read_point_cloud(_write("utm.las", _with_bounds(_utm_las(), UTM)))
        assert cloud.origin is not None
        # float32 at 4.7e6 steps by 0.5 m; the file says 0.01 m.
        assert _worst_error(cloud, UTM) < 1e-3

    def test_the_origin_is_round_and_inside_the_data(self):
        cloud = read_point_cloud(_write("utm.las", _with_bounds(_utm_las(), UTM)))
        assert cloud.origin == [500000.0, 4700006.0, 314.0]

    def test_wrong_header_bounds_fall_back_to_the_first_point(self):
        # Writers do leave the bounds block zeroed. The origin then comes from
        # the first point, and the precision is kept all the same.
        cloud = read_point_cloud(_write("zeroed.las", _utm_las()))
        assert cloud.origin == [500000.0, 4700000.0, 312.0]
        assert _worst_error(cloud, UTM) < 1e-3

    def test_a_cloud_near_zero_is_served_as_before(self):
        points = [(1.5, -2.25, 0.5), (12.0, 3.0, 1.0)]
        cloud = read_point_cloud(_write("small.las", las_bytes(points)))
        assert cloud.origin is None
        assert _worst_error(cloud, points) < 1e-3


class TestTextFormats:
    def test_xyz_in_map_coordinates(self):
        text = "".join(f"{x} {y} {z}\n" for x, y, z in UTM)
        cloud = read_point_cloud(_write("utm.xyz", text.encode()))
        assert cloud.origin is not None
        assert _worst_error(cloud, UTM) < 1e-3

    def test_ascii_ply_in_map_coordinates(self):
        header = ("ply\nformat ascii 1.0\nelement vertex 3\n"
                  "property double x\nproperty double y\nproperty double z\n"
                  "end_header\n")
        body = "".join(f"{x} {y} {z}\n" for x, y, z in UTM)
        cloud = read_point_cloud(_write("utm.ply", (header + body).encode()))
        assert cloud.origin is not None
        assert _worst_error(cloud, UTM) < 1e-3

    def test_small_xyz_has_no_origin(self):
        cloud = read_point_cloud(_write("small.xyz", b"1 2 3\n4 5 6\n"))
        assert cloud.origin is None
        assert list(cloud.positions) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


class TestTransport:
    def test_the_wire_header_carries_the_origin(self):
        cloud = read_point_cloud(_write("utm.las", _with_bounds(_utm_las(), UTM)))
        header, back = from_wire(to_wire(cloud))
        assert header["origin"] == cloud.origin
        assert back.origin == cloud.origin
        # Bounds are in the served frame, which is what the viewer frames on.
        assert max(abs(v) for corner in header["bounds"] for v in corner) < 100

    def test_no_origin_means_no_header_key(self):
        cloud = read_point_cloud(_write("small.xyz", b"1 2 3\n"))
        header, _ = from_wire(to_wire(cloud))
        assert "origin" not in header

    def test_decimation_keeps_the_origin(self):
        cloud = read_point_cloud(_write("utm.las", _with_bounds(_utm_las(), UTM)))
        assert decimate(cloud, 1).origin == cloud.origin

    def test_the_octree_manifest_and_its_nodes_carry_the_origin(self):
        pytest.importorskip("numpy")
        from potato.media.octree import (build_octree, manifest_for_client,
                                         read_manifest, read_node,
                                         to_octree_bytes)
        cloud = read_point_cloud(
            _write("utm.las", _with_bounds(_utm_las(), UTM)), max_points=0)
        path = _write("utm.oct", to_octree_bytes(build_octree(cloud)))
        assert manifest_for_client(read_manifest(path))["origin"] == cloud.origin
        header, _ = from_wire(read_node(path, "r"))
        assert header["origin"] == cloud.origin


class TestChooseOrigin:
    def test_small_bounds_need_none(self):
        assert choose_origin([-50.0, -50.0, 0.0], [50.0, 50.0, 10.0]) is None

    def test_large_bounds_get_their_rounded_centre(self):
        assert choose_origin([500000.2, 4700000.0, 300.0],
                             [500010.0, 4700020.6, 320.0]) == [500005.0,
                                                               4700010.0, 310.0]

    def test_non_finite_bounds_get_none(self):
        assert choose_origin([float("nan"), 0.0, 0.0], [1e6, 0.0, 0.0]) is None
