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
