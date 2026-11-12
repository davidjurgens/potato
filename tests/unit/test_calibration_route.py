"""
``GET /api/calibration`` — the item's cameras, for the 2D verification panels.

Two things are checked, and they fail independently:

* the **wiring**, because a bare ``@app.route`` decorator 404s under
  ``potato start`` (invariant 4);
* the **behaviour**, in particular the difference between "this project has no
  cameras" (normal, 200, empty) and "this project has cameras and the file is
  broken" (an admin's problem, 400, with the reason). Collapsing those two into
  one response is how a misconfigured rig looks like a lidar-only project and
  nobody investigates.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

flask = pytest.importorskip("flask")

ROUTES = Path("potato/routes.py")

KITTI_CALIB = """P2: 7.215377e+02 0.000000e+00 6.095593e+02 4.485728e+01 0.000000e+00 7.215377e+02 1.728540e+02 2.163791e-01 0.000000e+00 0.000000e+00 1.000000e+00 2.745884e-03
R0_rect: 1 0 0 0 1 0 0 0 1
Tr_velo_to_cam: 0 -1 0 0 0 0 -1 0 1 0 0 0
"""


class TestRouteRegistration:
    def test_the_rule_is_added_in_configure_routes(self):
        source = ROUTES.read_text(encoding="utf-8")
        assert 'add_url_rule("/api/calibration"' in source, (
            "/api/calibration has a decorator but no add_url_rule, so it will "
            "404 under `potato start` while working fine under pytest.")


@pytest.fixture
def client(tmp_path):
    """
    A Flask app carrying only the calibration handler.

    Built by hand rather than through FlaskTestServer because the handler's
    dependencies -- the item store, the session, the config -- are exactly what
    needs controlling, and a full server would make each case a fixture-heavy
    integration test for no extra coverage.
    """
    from potato import routes as potato_routes

    media = tmp_path / "media"
    media.mkdir()

    app = flask.Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test"
    app.add_url_rule("/api/calibration", "get_item_calibration",
                     potato_routes.get_item_calibration, methods=["GET"])

    items = {}

    def fake_get_item(instance_id):
        if instance_id not in items:
            raise KeyError(instance_id)
        item = MagicMock()
        item.get_data.return_value = items[instance_id]
        return item

    manager = MagicMock()
    manager.get_item.side_effect = fake_get_item

    with patch.object(potato_routes, "get_item_state_manager",
                      return_value=manager), \
         patch.dict(potato_routes.config,
                    {"media_directory": str(media), "task_dir": str(tmp_path)},
                    clear=False):
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["username"] = "annotator@example.org"
            yield c, media, items


class TestBehaviour:
    def test_an_item_with_no_calibration_is_a_normal_empty_result(self, client):
        # 200, not 404: a lidar-only project is the common case and the panel
        # area has to render it. An error here would put a warning on every
        # item of every point-cloud project that has no cameras.
        c, _media, items = client
        items["scene_1"] = {"id": "scene_1", "point_cloud": "a.bin"}

        resp = c.get("/api/calibration?instance_id=scene_1")
        assert resp.status_code == 200
        assert resp.get_json()["cameras"] == []
        assert resp.get_json()["reason"] == "no_calibration"

    def test_a_kitti_file_yields_a_camera(self, client):
        c, media, items = client
        (media / "calib.txt").write_text(KITTI_CALIB)
        items["scene_1"] = {"id": "scene_1", "calibration": "calib.txt"}

        payload = c.get("/api/calibration?instance_id=scene_1").get_json()
        assert len(payload["cameras"]) == 1
        camera = payload["cameras"][0]
        assert camera["k"][0] == pytest.approx(721.5377)
        assert len(camera["rt"]) == 12

    def test_a_relative_path_resolves_against_the_media_directory(self, client):
        # One path spelling has to work for the image, the cloud and the
        # calibration alike, or an admin writes three different kinds of path.
        c, media, items = client
        (media / "seq").mkdir()
        (media / "seq" / "calib.txt").write_text(KITTI_CALIB)
        items["scene_1"] = {"id": "scene_1", "calibration": "seq/calib.txt"}

        resp = c.get("/api/calibration?instance_id=scene_1")
        assert resp.status_code == 200
        assert len(resp.get_json()["cameras"]) == 1

    def test_an_image_becomes_a_url_the_browser_can_fetch(self, client):
        c, _media, items = client
        items["scene_1"] = {"id": "scene_1", "calibration": {"cameras": [{
            "name": "front", "image": "img/front_01.png",
            "intrinsics": {"fx": 100, "fy": 100, "cx": 50, "cy": 50}}]}}

        camera = c.get("/api/calibration?instance_id=scene_1").get_json()[
            "cameras"][0]
        # Through the proxy, so a camera stream in a format browsers cannot
        # display still renders. The proxy passes PNG straight through.
        assert camera["image_url"] == "/media/proxy/img/front_01.png"

    def test_an_absolute_url_is_left_alone(self, client):
        c, _media, items = client
        items["scene_1"] = {"id": "scene_1", "calibration": {"cameras": [{
            "image": "https://example.org/a.png",
            "intrinsics": {"fx": 1, "fy": 1, "cx": 0, "cy": 0}}]}}

        camera = c.get("/api/calibration?instance_id=scene_1").get_json()[
            "cameras"][0]
        assert camera["image_url"] == "https://example.org/a.png"

    def test_a_camera_with_no_image_is_still_returned(self, client):
        # Calibration without imagery is legitimate -- it still lets an
        # exporter project boxes. The panel says "calibration only".
        c, _media, items = client
        items["scene_1"] = {"id": "scene_1", "calibration": {"cameras": [{
            "intrinsics": {"fx": 1, "fy": 1, "cx": 0, "cy": 0}}]}}

        camera = c.get("/api/calibration?instance_id=scene_1").get_json()[
            "cameras"][0]
        assert camera["image_url"] is None

    def test_a_broken_calibration_is_a_400_carrying_the_reason(self, client):
        # NOT an empty 200. The distinction is the point: an admin has to be
        # able to tell "no cameras configured" from "cameras configured, file
        # unreadable", and only the second needs fixing.
        c, media, items = client
        (media / "calib.txt").write_text("this is not a calibration\n")
        items["scene_1"] = {"id": "scene_1", "calibration": "calib.txt"}

        resp = c.get("/api/calibration?instance_id=scene_1")
        assert resp.status_code == 400
        assert "KITTI" in resp.get_json()["error"]

    def test_a_missing_file_says_which_one(self, client):
        c, _media, items = client
        items["scene_1"] = {"id": "scene_1", "calibration": "nope.txt"}

        resp = c.get("/api/calibration?instance_id=scene_1")
        assert resp.status_code == 400
        assert "nope.txt" in resp.get_json()["error"]

    @pytest.mark.parametrize("attack", [
        "../../../../etc/passwd",
        "../secret.txt",
        "/etc/passwd",
        "sub/../../secret.txt",
    ])
    def test_a_path_escaping_the_media_directory_is_refused(self, client,
                                                            attack, tmp_path):
        """
        The calibration path comes out of a project's data file and is handed
        straight to open(). Without the media-directory containment guard this
        route is an arbitrary-file-read primitive, and the parse error would
        happily quote the first line of whatever it read.
        """
        c, _media, items = client
        (tmp_path / "secret.txt").write_text("P2: 1 0 0 0 0 1 0 0 0 0 1 0\n")
        items["scene_1"] = {"id": "scene_1", "calibration": attack}

        resp = c.get("/api/calibration?instance_id=scene_1")
        assert resp.status_code == 400
        error = resp.get_json()["error"]
        assert "media directory" in error or "not found" in error
        assert "P2" not in error, "the file's contents must not leak"

    def test_the_guard_also_covers_a_file_key(self, client, tmp_path):
        # The dict form takes a different code path to the bare string, and a
        # guard applied to only one of them is the usual way this reopens.
        c, _media, items = client
        (tmp_path / "secret.txt").write_text("P2: 1 0 0 0 0 1 0 0 0 0 1 0\n")
        items["scene_1"] = {"id": "scene_1",
                            "calibration": {"file": "../secret.txt"}}

        assert c.get("/api/calibration?instance_id=scene_1").status_code == 400

    def test_a_custom_field_name_is_honoured(self, client):
        c, _media, items = client
        items["scene_1"] = {"id": "scene_1", "rig": {"cameras": [{
            "intrinsics": {"fx": 1, "fy": 1, "cx": 0, "cy": 0}}]}}

        assert c.get("/api/calibration?instance_id=scene_1"
                     ).get_json()["cameras"] == []
        assert len(c.get("/api/calibration?instance_id=scene_1&field=rig"
                         ).get_json()["cameras"]) == 1

    def test_an_unknown_instance_does_not_500(self, client):
        c, _media, _items = client
        resp = c.get("/api/calibration?instance_id=does-not-exist")
        assert resp.status_code == 200
        assert resp.get_json()["reason"] == "no_instance"

    def test_an_unauthenticated_request_is_refused(self, client):
        c, _media, items = client
        items["scene_1"] = {"id": "scene_1", "calibration": "x"}
        with c.session_transaction() as sess:
            sess.clear()

        assert c.get("/api/calibration?instance_id=scene_1").status_code == 401

    def test_kitti_warnings_reach_the_client(self, client):
        # A calibration missing Tr_velo_to_cam still parses, but every box
        # will be in the wrong place. The viewer logs what came back, so the
        # warning has to survive the round trip rather than staying server-side.
        c, media, items = client
        (media / "calib.txt").write_text(
            KITTI_CALIB.split("Tr_velo_to_cam")[0])
        items["scene_1"] = {"id": "scene_1", "calibration": "calib.txt"}

        payload = c.get("/api/calibration?instance_id=scene_1").get_json()
        assert any("Tr_velo_to_cam" in w for w in payload["warnings"])
