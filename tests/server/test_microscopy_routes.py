"""
The microscopy routes on a running server, over the shipped example: sign-in
is required, the image is named by the item and never by a path, tiles are
JPEGs composited from the requested channels, the label raster matches the
label image byte for byte, and bad requests get a 415 with a message.
"""

import gzip
import io
import json
import os
import shutil

import pytest
import requests

np = pytest.importorskip("numpy")
zarr = pytest.importorskip("zarr")
pytest.importorskip("tifffile")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.port_manager import find_free_port  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "image", "multichannel-microscopy")


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("microscopy_routes"), "mic")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", "layouts", "__pycache__"))
    # A third item whose image is missing, and one that tries to leave the project.
    with open(os.path.join(work, "data", "images.json")) as f:
        items = json.load(f)
    items.append({"id": "missing", "image": "nope.ome.zarr", "note": "x"})
    items.append({"id": "escape", "image": "../../../../etc", "note": "x"})
    with open(os.path.join(work, "data", "images.json"), "w") as f:
        json.dump(items, f)
    srv = FlaskTestServer(port=find_free_port(), config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the microscopy example")
    srv.work = work
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def session(server):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"action": "signup", "email": "mic_r", "pass": "p"})
    s.post(f"{server.base_url}/auth", data={"action": "login", "email": "mic_r", "pass": "p"})
    return s


def _q(instance, **extra):
    params = {"schema": "cells", "instance_id": instance}
    params.update(extra)
    return params


def test_signed_out_requests_are_refused(server):
    r = requests.get(f"{server.base_url}/api/microscopy/info", params=_q("tissue_a"))
    assert r.status_code == 401


def test_info_describes_the_image(server, session):
    r = session.get(f"{server.base_url}/api/microscopy/info", params=_q("tissue_a"))
    assert r.status_code == 200, r.text
    info = r.json()
    assert (info["width"], info["height"], info["size_c"], info["size_z"]) == (256, 256, 3, 3)
    assert info["dzi"]["max_level"] == 8 and info["dzi"]["tile_size"] == 254
    assert [p["width"] for p in info["pyramid"]] == [256, 128, 64]
    # The scheme's `channels` entry renames DAPI; the file's colours stay.
    assert [c["name"] for c in info["channels"]] == ["DAPI (nuclei)", "Membrane", "Marker"]
    assert info["channels"][2]["color"] == "#ff3b3b"
    assert info["label_image"] == "cells"

    tiff = session.get(f"{server.base_url}/api/microscopy/info", params=_q("tissue_b")).json()
    assert (tiff["format"], tiff["size_t"], tiff["label_image"]) == ("ome-tiff", 3, "cells")


def test_a_tile_is_the_requested_composite(server, session):
    from PIL import Image

    r = session.get(f"{server.base_url}/api/microscopy/tile/8/0_0.jpg",
                    params=_q("tissue_a", ch="2:ff0000:150:2600", z=1))
    assert r.status_code == 200 and r.headers["Content-Type"] == "image/jpeg"
    tile = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB")).astype(int)
    assert tile.shape == (255, 255, 3)              # 254 + 1 px of overlap
    assert tile[..., 1].max() < 40 and tile[..., 2].max() < 40     # red only
    assert tile[..., 0].max() > 200


def test_label_raster_matches_the_label_image(server, session):
    r = session.get(f"{server.base_url}/api/microscopy/labels", params=_q("tissue_a", z=2))
    assert r.status_code == 200
    assert (r.headers["X-Label-Width"], r.headers["X-Label-Bytes"], r.headers["X-Label-Scale"]) == (
        "256", "2", "1.0")
    # requests undoes the gzip Content-Encoding.
    raster = np.frombuffer(r.content, "<u2").reshape(256, 256)
    store = zarr.open_group(store=os.path.join(server.work, "media", "tissue_a.ome.zarr"), mode="r")
    assert np.array_equal(raster, np.asarray(store["labels"]["cells"]["0"][2]))

    cells = session.get(f"{server.base_url}/api/microscopy/cells", params=_q("tissue_a", z=2)).json()
    assert len(cells["cells"]) == len(np.unique(raster)) - 1


@pytest.mark.parametrize("path, params, message", [
    ("tile/8/0_0.jpg", {"ch": "0:zzzzzz:1:2"}, "hex colour"),
    ("tile/8/0_0.jpg", {"ch": "0:ff0000:1:2", "z": 7}, "z=7 is outside"),
    ("tile/9/0_0.jpg", {"ch": ""}, "not in this image's tile pyramid"),
    ("tile/8/5_0.jpg", {"ch": ""}, "outside level"),
    ("info", {}, None),
])
def test_bad_requests_get_a_message(server, session, path, params, message):
    instance = "tissue_a" if message else "missing"
    r = session.get(f"{server.base_url}/api/microscopy/{path}", params=_q(instance, **params))
    assert r.status_code in (415,), r.text
    text = r.json()["error"]
    if message:
        assert message in text
    else:
        assert "no microscopy image" in text


def test_an_item_path_outside_the_project_is_not_opened(server, session):
    r = session.get(f"{server.base_url}/api/microscopy/info", params=_q("escape"))
    assert r.status_code == 415
    assert "not inside the project's media directory" in r.json()["error"]


def test_unknown_scheme_or_item_is_404(server, session):
    assert session.get(f"{server.base_url}/api/microscopy/info",
                       params={"schema": "nope", "instance_id": "tissue_a"}).status_code == 404
    assert session.get(f"{server.base_url}/api/microscopy/info",
                       params=_q("no_such_item")).status_code == 404
