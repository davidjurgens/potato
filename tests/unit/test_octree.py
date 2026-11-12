"""
Octree level-of-detail: build, serialize, and the index channel it needs.

The property that matters most here is not "does it build" but **does it
partition**. An additive octree that loses points renders a scene with holes
that an annotator reads as missing returns, and one that duplicates points
renders denser than the data warrants. Both are silent, so both are asserted
directly rather than inferred from a node count.
"""

import json
import random
import struct
from array import array
from pathlib import Path

import pytest

from potato.media.octree import (DEFAULT_GRID, MAX_NODES, OCT_MAGIC,
                                 build_octree, manifest_for_client,
                                 node_key_is_safe, read_manifest, read_node,
                                 to_octree_bytes)
from potato.media.pointcloud import (MAGIC as PNT_MAGIC, PointCloud,
                                     PointCloudError, decimate, from_wire,
                                     to_wire)


def make_cloud(n=40000, seed=11, with_colors=False, with_intensity=False):
    """A slab-shaped cloud, which is what a lidar sweep actually looks like."""
    rng = random.Random(seed)
    positions = array("f")
    colors = bytearray() if with_colors else None
    intensity = array("f") if with_intensity else None
    for _ in range(n):
        positions.extend([rng.uniform(-30, 30), rng.uniform(-30, 30),
                          rng.uniform(-2, 4)])
        if colors is not None:
            colors.extend([rng.randrange(256) for _ in range(3)])
        if intensity is not None:
            intensity.append(rng.uniform(0, 1))
    return PointCloud(positions=positions, colors=colors, intensity=intensity,
                      source_format="test", original_count=n)


class TestPartition:
    """Every point lands in exactly one node."""

    def test_every_point_is_kept_exactly_once(self):
        cloud = make_cloud(40000)
        tree = build_octree(cloud, grid=16, max_level=4, min_points=2000)

        total = sum(node.count for node in tree.nodes.values())
        assert total == cloud.count

        seen = []
        for key in tree.nodes:
            _header, sub = from_wire(tree.blobs[key])
            seen.extend(sub.indices)
        assert len(seen) == cloud.count
        assert len(set(seen)) == cloud.count
        assert set(seen) == set(range(cloud.count))

    def test_points_land_inside_their_node_bounds(self):
        """
        A point stored in the wrong node breaks frustum culling: the node is
        culled while its points are on screen, so they vanish.
        """
        cloud = make_cloud(20000)
        tree = build_octree(cloud, grid=16, max_level=4, min_points=1000)

        for key, node in tree.nodes.items():
            _header, sub = from_wire(tree.blobs[key])
            lo, hi = node.bounds
            for i in range(sub.count):
                for axis in range(3):
                    v = sub.positions[i * 3 + axis]
                    # A hair of tolerance: bounds are float64 and positions
                    # float32, so a point exactly on a boundary can round out.
                    assert lo[axis] - 1e-3 <= v <= hi[axis] + 1e-3

    def test_children_are_denser_than_their_parent(self):
        """
        The additive property: descending a level buys detail rather than
        re-sending what the parent already had.
        """
        cloud = make_cloud(80000)
        tree = build_octree(cloud, grid=16, max_level=4, min_points=1000)

        by_level = {}
        for node in tree.nodes.values():
            by_level.setdefault(node.level, 0)
            by_level[node.level] += node.count

        assert len(by_level) > 1, "the fixture should have subdivided"
        # Points per level rise before they taper off as the cloud runs out.
        assert by_level[1] > by_level[0]

    def test_root_is_a_sample_of_the_whole_scene(self):
        """
        Not the first N points. A root that is one corner of the scene is what
        truncation looks like, and it is why the viewer frames on it.
        """
        cloud = make_cloud(40000)
        tree = build_octree(cloud, grid=16, max_level=4, min_points=1000)
        _header, root = from_wire(tree.blobs["r"])

        assert root.count > 100
        lo = [min(root.positions[i * 3 + a] for i in range(root.count))
              for a in range(3)]
        hi = [max(root.positions[i * 3 + a] for i in range(root.count))
              for a in range(3)]
        # The fixture spans [-30, 30] in x and y; a sample of the whole scene
        # reaches most of that, a corner would not.
        assert hi[0] - lo[0] > 45
        assert hi[1] - lo[1] > 45


class TestChannels:
    def test_colors_and_intensity_survive_the_split(self):
        cloud = make_cloud(8000, with_colors=True, with_intensity=True)
        tree = build_octree(cloud, grid=8, max_level=3, min_points=500)

        for key in tree.nodes:
            header, sub = from_wire(tree.blobs[key])
            if sub.count == 0:
                continue
            assert header["has_colors"] is True
            assert header["has_intensity"] is True
            assert len(sub.colors) == sub.count * 3
            assert len(sub.intensity) == sub.count

    def test_the_split_keeps_each_point_with_its_own_colour(self):
        """
        A per-channel reindex that used a different member order would swap
        colours between points — visible only as a wrongly-coloured cloud.
        """
        cloud = make_cloud(6000, with_colors=True, with_intensity=True)
        tree = build_octree(cloud, grid=8, max_level=3, min_points=400)

        for key in tree.nodes:
            _header, sub = from_wire(tree.blobs[key])
            for i in range(sub.count):
                src = sub.indices[i]
                assert sub.intensity[i] == pytest.approx(
                    cloud.intensity[src], abs=1e-6)
                assert (list(sub.colors[i * 3:i * 3 + 3])
                        == list(cloud.colors[src * 3:src * 3 + 3]))
                for axis in range(3):
                    assert sub.positions[i * 3 + axis] == pytest.approx(
                        cloud.positions[src * 3 + axis], abs=1e-4)

    def test_indices_compose_through_an_existing_mapping(self):
        """
        Building over an already-decimated cloud must yield source-file indices,
        not indices into the intermediate.
        """
        cloud = make_cloud(4000)
        thinned = decimate(cloud, 500)
        tree = build_octree(thinned, grid=8, max_level=2, min_points=100)

        seen = set()
        for key in tree.nodes:
            _header, sub = from_wire(tree.blobs[key])
            seen.update(sub.indices)
        assert seen == set(thinned.indices)
        assert max(seen) >= 3000, "indices should span the original file"


class TestSerialization:
    def test_round_trips_through_a_file(self, tmp_path):
        cloud = make_cloud(20000)
        tree = build_octree(cloud, grid=16, max_level=3, min_points=1000)
        path = tmp_path / "scene.oct"
        path.write_bytes(to_octree_bytes(tree))

        assert path.read_bytes()[:4] == OCT_MAGIC
        manifest = read_manifest(path)
        assert manifest["total_count"] == cloud.count
        assert len(manifest["nodes"]) == len(tree.nodes)

        recovered = 0
        for entry in manifest["nodes"]:
            blob = read_node(path, entry["key"])
            assert blob[:4] == PNT_MAGIC
            _header, sub = from_wire(blob)
            assert sub.count == entry["count"]
            recovered += sub.count
        assert recovered == cloud.count

    def test_offsets_do_not_overlap(self, tmp_path):
        """
        Offsets are assigned before the header is written, and the header's own
        length shifts every blob. Getting that circularity wrong yields nodes
        that decode as garbage rather than erroring.
        """
        cloud = make_cloud(12000)
        tree = build_octree(cloud, grid=8, max_level=3, min_points=500)
        path = tmp_path / "scene.oct"
        path.write_bytes(to_octree_bytes(tree))

        manifest = read_manifest(path)
        spans = sorted((n["offset"], n["length"]) for n in manifest["nodes"])
        cursor = 0
        for offset, length in spans:
            assert offset == cursor
            cursor += length
        assert cursor + 8 + _header_len(path) == path.stat().st_size

    def test_unknown_node_raises_rather_than_serving_bytes(self, tmp_path):
        cloud = make_cloud(2000)
        tree = build_octree(cloud, grid=8, max_level=2, min_points=500)
        path = tmp_path / "scene.oct"
        path.write_bytes(to_octree_bytes(tree))

        with pytest.raises(PointCloudError, match="no node"):
            read_node(path, "r7777777")

    def test_manifest_for_client_hides_byte_offsets(self, tmp_path):
        cloud = make_cloud(2000)
        tree = build_octree(cloud, grid=8, max_level=2, min_points=500)
        path = tmp_path / "scene.oct"
        path.write_bytes(to_octree_bytes(tree))

        client = manifest_for_client(read_manifest(path))
        assert client["total_count"] == cloud.count
        for node in client["nodes"]:
            assert "offset" not in node
            assert "length" not in node
            assert set(node) <= {"key", "level", "bounds", "count", "children"}

    def test_rejects_a_file_that_is_not_an_octree(self, tmp_path):
        path = tmp_path / "not.oct"
        path.write_bytes(b"PNT1" + struct.pack("<I", 2) + b"{}")
        with pytest.raises(PointCloudError, match="not an OCT1"):
            read_manifest(path)


def _header_len(path: Path) -> int:
    with open(path, "rb") as fh:
        head = fh.read(8)
    return struct.unpack("<I", head[4:8])[0]


class TestDegenerate:
    def test_an_empty_cloud_yields_one_empty_root(self):
        tree = build_octree(PointCloud(positions=array("f")))
        assert list(tree.nodes) == ["r"]
        assert tree.nodes["r"].count == 0

    def test_a_small_cloud_is_one_node(self):
        """
        The degenerate case the viewer relies on: no "too small for LOD"
        branch exists, so a small cloud must simply produce a single node.
        """
        cloud = make_cloud(500)
        tree = build_octree(cloud, min_points=1000)
        assert list(tree.nodes) == ["r"]
        assert tree.nodes["r"].count == 500

    def test_identical_points_do_not_recurse_forever(self):
        """
        Every point in one cell: no split ever separates them, so the recursion
        guard rather than the grid has to stop it.
        """
        positions = array("f")
        for _ in range(5000):
            positions.extend([1.0, 2.0, 3.0])
        cloud = PointCloud(positions=positions, original_count=5000)
        tree = build_octree(cloud, grid=8, max_level=4, min_points=10)

        assert len(tree.nodes) <= MAX_NODES
        assert sum(n.count for n in tree.nodes.values()) == 5000

    def test_default_grid_is_used_when_not_overridden(self):
        cloud = make_cloud(3000)
        tree = build_octree(cloud)
        assert tree.spacing > 0
        assert tree.spacing == pytest.approx(
            _extent(cloud) / DEFAULT_GRID, rel=0.01)


def _extent(cloud):
    lo, hi = cloud.bounds()
    return max(hi[a] - lo[a] for a in range(3))


class TestNodeKeys:
    @pytest.mark.parametrize("key", ["r", "r0", "r01234567", "r777"])
    def test_accepts_real_keys(self, key):
        assert node_key_is_safe(key)

    @pytest.mark.parametrize("key", [
        "", "x0", "r8", "r9", "r-1", "../etc/passwd", "r0/../..",
        "r" + "0" * 200, "R0",
    ])
    def test_rejects_everything_else(self, key):
        assert not node_key_is_safe(key)
