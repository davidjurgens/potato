"""
``GET /media/depth/<path>`` — four representations of one file.

Driven through a real Flask test client rather than by calling the handler,
because what breaks is the wiring and the content types, and a direct call
exercises neither.
"""

from __future__ import annotations

import struct

import pytest

flask = pytest.importorskip("flask")
np = pytest.importorskip("numpy")

from potato.media import routes as media_routes  # noqa: E402
from potato.media.depth import from_wire  # noqa: E402
from potato.media.pointcloud import from_wire as cloud_from_wire  # noqa: E402


@pytest.fixture
def client(tmp_path):
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


def write_depth(media, name="d.npy", rows=None):
    rows = rows if rows is not None else [[1.0, 2.0], [3.0, 0.0]]
    np.save(media / name, np.array(rows, dtype=np.float32))
    return name


class TestRepresentations:
    def test_the_default_is_a_png(self, client):
        c, media = client
        write_depth(media)
        resp = c.get("/media/depth/d.npy")
        assert resp.status_code == 200
        assert resp.mimetype == "image/png"
        assert resp.data[:4] == b"\x89PNG"

    def test_info_reports_the_real_range(self, client):
        # The window has to be set before the first render, and a 16-bit depth
        # map opened blind renders as a black rectangle.
        c, media = client
        write_depth(media)
        info = c.get("/media/depth/d.npy?info=1").get_json()
        assert info["kind"] == "depth"
        assert info["min"] == 1.0
        assert info["max"] == 3.0
        assert info["invalid_fraction"] == pytest.approx(0.25)

    def test_raw_returns_float_metres(self, client):
        # A colourmap is not injective at 8 bits, so the cursor readout cannot
        # be recovered from the picture and the numbers travel separately.
        c, media = client
        write_depth(media)
        resp = c.get("/media/depth/d.npy?raw=1")
        assert resp.mimetype == "application/octet-stream"

        header, depth = from_wire(resp.data)
        assert header["units"] == "m"
        assert depth.values[0] == 1.0
        assert depth.values[3] != depth.values[3], "0 must come back as NaN"

    def test_pointcloud_unprojects_with_supplied_intrinsics(self, client):
        c, media = client
        write_depth(media, rows=[[2.0]])
        resp = c.get("/media/depth/d.npy?pointcloud=1"
                     "&fx=5&fy=5&cx=10&cy=10&frame=camera")
        assert resp.status_code == 200

        header, cloud = cloud_from_wire(resp.data)
        assert header["from_depth"] is True
        assert list(cloud.positions) == pytest.approx([-4.0, -4.0, 2.0])
        assert list(cloud.indices) == [0]

    def test_unprojection_without_intrinsics_says_which_are_missing(self, client):
        c, media = client
        write_depth(media)
        body = c.get("/media/depth/d.npy?pointcloud=1&fx=5").get_json()
        assert "fy" in body["error"]
        assert "calibration" in body["error"]


class TestParameters:
    def test_scale_changes_the_reported_range(self, client):
        c, media = client
        write_depth(media, rows=[[1000.0, 2000.0]])
        metres = c.get("/media/depth/d.npy?info=1&scale=0.001").get_json()
        assert metres["max"] == pytest.approx(2.0)

    def test_an_unknown_colormap_lists_the_real_ones(self, client):
        c, media = client
        write_depth(media)
        resp = c.get("/media/depth/d.npy?colormap=rainbow")
        assert resp.status_code == 400
        assert "turbo" in resp.get_json()["error"]

    def test_the_window_is_part_of_the_cache_key(self, client, tmp_path):
        # Otherwise dragging the near slider would serve back the previous
        # render and the control would appear dead.
        c, media = client
        write_depth(media)
        c.get("/media/depth/d.npy?window_min=1&window_max=2")
        c.get("/media/depth/d.npy?window_min=1&window_max=3")
        cached = list((tmp_path / "out" / ".media_cache").glob("*.depth.png"))
        assert len(cached) == 2

    def test_a_repeat_request_is_served_from_cache(self, client, tmp_path):
        c, media = client
        write_depth(media)
        c.get("/media/depth/d.npy?window_min=1&window_max=2")
        c.get("/media/depth/d.npy?window_min=1&window_max=2")
        cached = list((tmp_path / "out" / ".media_cache").glob("*.depth.png"))
        assert len(cached) == 1


class TestFailures:
    def test_a_missing_file_is_a_404(self, client):
        c, _media = client
        assert c.get("/media/depth/nope.npy").status_code == 404

    def test_an_unreadable_format_is_a_415_with_an_action(self, client):
        # 415 rather than 500: the file is fine and we cannot read it, and the
        # message has to name the next step rather than a stack trace.
        c, media = client
        (media / "d.xyz").write_bytes(b"not a depth map")
        resp = c.get("/media/depth/d.xyz")
        assert resp.status_code == 415
        assert "Supported" in resp.get_json()["error"]

    def test_traversal_is_refused(self, client):
        c, _media = client
        resp = c.get("/media/depth/..%2f..%2fetc%2fpasswd")
        assert resp.status_code in (403, 404)

    def test_a_colour_png_is_refused_rather_than_read_as_depth(self, client):
        Image = pytest.importorskip("PIL.Image")
        c, media = client
        Image.new("RGB", (2, 2), (5, 6, 7)).save(media / "rgb.png")
        resp = c.get("/media/depth/rgb.png")
        assert resp.status_code == 415
        assert "colour image" in resp.get_json()["error"]
