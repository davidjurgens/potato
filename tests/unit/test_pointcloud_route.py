"""
``GET /media/pointcloud/<path>``.

Driven through a real Flask test client rather than by calling the handler
directly, because the things most likely to break are the wiring and the
response headers, not the function body — and a direct call exercises neither.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

flask = pytest.importorskip("flask")

from potato.media import routes as media_routes  # noqa: E402
from potato.media.pointcloud import from_wire  # noqa: E402


def kitti(points):
    return b"".join(struct.pack("<4f", *p) for p in points)


@pytest.fixture
def client(tmp_path):
    """A Flask app with only the media routes on it."""
    media = tmp_path / "media"
    media.mkdir()
    out = tmp_path / "out"
    out.mkdir()

    app = flask.Flask(__name__)
    app.config["TESTING"] = True
    media_routes.register_media_routes(app, {
        "media_directory": str(media),
        "task_dir": str(tmp_path),
        "output_annotation_dir": str(out),
    })
    with app.test_client() as c:
        yield c, media


class TestServing:
    def test_a_kitti_scan_comes_back_as_a_pnt_buffer(self, client):
        c, media = client
        (media / "scan.bin").write_bytes(
            kitti([(1.0, 2.0, 3.0, 0.5), (4.0, 5.0, 6.0, 0.25)]))

        resp = c.get("/media/pointcloud/scan.bin")
        assert resp.status_code == 200
        assert resp.mimetype == "application/octet-stream"

        header, cloud = from_wire(resp.data)
        assert header["count"] == 2
        assert header["source_format"] == "kitti_bin"
        assert list(cloud.positions) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        assert list(cloud.intensity) == [0.5, 0.25]

    def test_a_second_request_is_served_from_cache(self, client, tmp_path,
                                                   monkeypatch):
        c, media = client
        (media / "scan.bin").write_bytes(kitti([(1.0, 2.0, 3.0, 0.0)]))

        first = c.get("/media/pointcloud/scan.bin")
        assert first.status_code == 200
        assert len(list((tmp_path / "out" / ".media_cache").glob("*.pnt"))) == 1

        # Make re-reading impossible. A 200 on the second request can then only
        # have come from the cache — without it, a two-million-point scan is
        # re-parsed on every page load.
        def explode(*_args, **_kwargs):
            raise AssertionError("the cloud was re-read instead of cached")

        monkeypatch.setattr("potato.media.pointcloud.read_point_cloud", explode)
        second = c.get("/media/pointcloud/scan.bin")
        assert second.status_code == 200
        assert second.data == first.data

    def test_editing_the_source_invalidates_the_cache(self, client):
        # The other half of the contract: a corrected scan must not keep
        # serving the old points, which reads as a browser cache problem and
        # wastes an afternoon. The key covers size and mtime, not just path.
        c, media = client
        (media / "scan.bin").write_bytes(kitti([(1.0, 2.0, 3.0, 0.0)]))
        assert from_wire(c.get("/media/pointcloud/scan.bin").data)[0]["count"] == 1

        (media / "scan.bin").write_bytes(
            kitti([(1.0, 2.0, 3.0, 0.0), (4.0, 5.0, 6.0, 0.0)]))
        assert from_wire(c.get("/media/pointcloud/scan.bin").data)[0]["count"] == 2

    def test_max_points_is_part_of_the_cache_key(self, client):
        c, media = client
        points = [(float(i), 0.0, 0.0, 0.0) for i in range(100)]
        (media / "scan.bin").write_bytes(kitti(points))

        full = from_wire(c.get("/media/pointcloud/scan.bin").data)[0]
        thin = from_wire(
            c.get("/media/pointcloud/scan.bin?max_points=10").data)[0]

        # Sharing a key would serve the previous decimation to someone who
        # asked for a different one.
        assert full["count"] == 100
        assert thin["count"] == 10
        assert thin["original_count"] == 100

    def test_decimation_reports_what_it_dropped(self, client):
        c, media = client
        (media / "scan.bin").write_bytes(
            kitti([(float(i), 0.0, 0.0, 0.0) for i in range(50)]))
        header, _ = from_wire(
            c.get("/media/pointcloud/scan.bin?max_points=5").data)
        # The viewer has to be able to say "showing 5 of 50 points" rather than
        # quietly presenting a thinned cloud as the whole scan.
        assert header["count"] == 5
        assert header["original_count"] == 50


class TestFailures:
    def test_traversal_is_refused(self, client, tmp_path):
        c, _media = client
        (tmp_path / "secret.bin").write_bytes(kitti([(1.0, 1.0, 1.0, 0.0)]))
        resp = c.get("/media/pointcloud/../secret.bin")
        # Flask normalizes ../ in the URL, so this may 404 rather than 403;
        # what must never happen is a 200 with the file outside the media root.
        assert resp.status_code in (403, 404)

    def test_an_absolute_path_is_refused(self, client, tmp_path):
        # Driven through the handler rather than the URL, because a leading
        # double slash makes Flask emit a 308 before routing and the redirect
        # would prove nothing about the guard.
        c, _media = client
        app = flask.Flask(__name__)
        media_routes.register_media_routes(app, {
            "media_directory": str(tmp_path / "media"),
            "task_dir": str(tmp_path),
        })
        with app.test_request_context("/media/pointcloud/x"):
            _body, status = media_routes.point_cloud("/etc/passwd")
        assert status == 403

    def test_a_missing_file_is_404(self, client):
        c, _media = client
        resp = c.get("/media/pointcloud/nope.bin")
        assert resp.status_code == 404

    def test_an_unreadable_format_is_415_with_the_next_action(self, client):
        c, media = client
        (media / "scan.laz").write_bytes(b"\x00" * 64)
        resp = c.get("/media/pointcloud/scan.laz")
        # 415, not 500: the file is fine, we cannot read it, and the message
        # has to name the conversion command.
        assert resp.status_code == 415
        assert "laszip" in json.loads(resp.data)["error"]

    def test_a_truncated_kitti_scan_is_415_not_500(self, client):
        c, media = client
        (media / "scan.bin").write_bytes(b"\x00" * 30)
        resp = c.get("/media/pointcloud/scan.bin")
        assert resp.status_code == 415
        assert "multiple of 16" in json.loads(resp.data)["error"]


class TestLevelOfDetail:
    """``?lod=1`` — the manifest, then nodes by key."""

    def _scene(self, media, n=3000):
        import random
        rng = random.Random(3)
        points = [(rng.uniform(-20, 20), rng.uniform(-20, 20),
                   rng.uniform(-2, 3), rng.uniform(0, 1)) for _ in range(n)]
        (media / "scene.bin").write_bytes(kitti(points))
        return points

    def test_manifest_is_json_and_names_its_nodes(self, client):
        c, media = client
        self._scene(media)

        resp = c.get("/media/pointcloud/scene.bin?lod=1&min_points=500&grid=8")
        assert resp.status_code == 200
        assert resp.mimetype == "application/json"

        manifest = resp.get_json()
        assert manifest["total_count"] == 3000
        assert manifest["nodes"]
        assert manifest["nodes"][0]["key"] == "r"

    def test_manifest_does_not_leak_cache_file_offsets(self, client):
        c, media = client
        self._scene(media)

        manifest = c.get(
            "/media/pointcloud/scene.bin?lod=1&min_points=500&grid=8"
        ).get_json()
        for node in manifest["nodes"]:
            assert "offset" not in node
            assert "length" not in node

    def test_a_node_comes_back_as_a_pnt_buffer_with_indices(self, client):
        c, media = client
        self._scene(media)

        query = "lod=1&min_points=500&grid=8"
        manifest = c.get(f"/media/pointcloud/scene.bin?{query}").get_json()
        key = manifest["nodes"][0]["key"]

        resp = c.get(f"/media/pointcloud/scene.bin?{query}&node={key}")
        assert resp.status_code == 200
        assert resp.mimetype == "application/octet-stream"

        header, cloud = from_wire(resp.data)
        assert header["has_indices"] is True
        assert cloud.count == manifest["nodes"][0]["count"]
        # Indices are into the source file, so they can exceed this node's own
        # point count. That is the whole point of the channel.
        assert max(cloud.indices) < 3000

    def test_every_node_together_is_the_whole_cloud(self, client):
        c, media = client
        self._scene(media)

        query = "lod=1&min_points=500&grid=8"
        manifest = c.get(f"/media/pointcloud/scene.bin?{query}").get_json()

        seen = set()
        for node in manifest["nodes"]:
            resp = c.get(
                f"/media/pointcloud/scene.bin?{query}&node={node['key']}")
            _header, cloud = from_wire(resp.data)
            seen.update(cloud.indices)
        assert seen == set(range(3000))

    def test_an_unknown_node_is_a_404_not_a_500(self, client):
        c, media = client
        self._scene(media)
        query = "lod=1&min_points=500&grid=8"
        c.get(f"/media/pointcloud/scene.bin?{query}")

        resp = c.get(f"/media/pointcloud/scene.bin?{query}&node=r7777")
        assert resp.status_code == 404
        assert "node" in resp.get_json()["error"]

    def test_a_malformed_node_key_is_rejected(self, client):
        c, media = client
        self._scene(media)

        resp = c.get("/media/pointcloud/scene.bin?lod=1&node=../../etc/passwd")
        assert resp.status_code == 400

    def test_traversal_is_still_refused_under_lod(self, client):
        c, _media = client
        resp = c.get("/media/pointcloud/..%2f..%2fetc%2fpasswd?lod=1")
        assert resp.status_code in (403, 404)

    def test_the_octree_is_built_once_and_cached(self, client, tmp_path):
        c, media = client
        self._scene(media)

        query = "lod=1&min_points=500&grid=8"
        c.get(f"/media/pointcloud/scene.bin?{query}")
        cached = list((tmp_path / "out" / ".media_cache").glob("*.oct"))
        assert len(cached) == 1

        c.get(f"/media/pointcloud/scene.bin?{query}")
        assert len(list((tmp_path / "out" / ".media_cache").glob("*.oct"))) == 1

    def test_build_parameters_are_part_of_the_cache_key(self, client, tmp_path):
        # Otherwise lowering min_points would serve back the previous, coarser
        # octree -- the same class of bug the max_points key exists to avoid.
        c, media = client
        self._scene(media)

        c.get("/media/pointcloud/scene.bin?lod=1&min_points=500&grid=8")
        c.get("/media/pointcloud/scene.bin?lod=1&min_points=200&grid=8")
        assert len(list((tmp_path / "out" / ".media_cache").glob("*.oct"))) == 2

    def test_lod_ignores_max_points(self, client):
        """
        LOD must build from the undecimated cloud. Decimating first would
        promise detail that was thrown away before the structure was built.
        """
        c, media = client
        self._scene(media)

        manifest = c.get(
            "/media/pointcloud/scene.bin?lod=1&max_points=100&min_points=500"
        ).get_json()
        assert manifest["total_count"] == 3000
