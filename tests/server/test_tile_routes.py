"""
The deep-zoom tile routes, end to end over HTTP.

The arithmetic is covered in ``tests/unit/test_tiles.py``. What can only be
checked here is the part that has bitten this codebase before: that the routes
are reachable at all under the app ``create_app()`` builds (a bare
``@app.route`` 404s), that Flask's URL matching does not let the descriptor and
the tile routes swallow each other, and that the traversal guard applies.
"""

import json
import os

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

PIL = pytest.importorskip("PIL", reason="the tile routes need Pillow")

SCHEMA = "regions"


def _build_project(test_dir):
    from PIL import Image, ImageDraw

    media = os.path.join(test_dir, "media", "scans")
    os.makedirs(media, exist_ok=True)
    image = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([400, 200, 800, 600], fill="blue")
    image.save(os.path.join(media, "slide.png"))

    items = [{"id": "s1", "note": "Find the regions.",
              "image": "scans/slide.png"}]
    data_file = os.path.join(test_dir, "items.json")
    with open(data_file, "w", encoding="utf-8") as handle:
        json.dump(items, handle)

    config = {
        "port": 0,
        "annotation_task_name": "tiles",
        "task_dir": test_dir,
        "media_directory": os.path.join(test_dir, "media"),
        "output_annotation_dir": os.path.join(test_dir, "out"),
        "output_annotation_format": "json",
        "data_files": [data_file],
        "item_properties": {"id_key": "id", "text_key": "note"},
        "user_config": {"allow_all_users": True},
        "annotation_schemes": [{
            "annotation_type": "image_annotation",
            "name": SCHEMA,
            "description": "Regions",
            "tools": ["bbox", "brush"],
            "labels": [{"name": "tissue", "color": "#f00"}],
            "viewer": "deepzoom",
            "source_field": "image",
        }],
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle)
    return config_path


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("tile_routes")
    config_path = _build_project(test_dir)
    srv = FlaskTestServer(config_file=config_path)
    if not srv.start():
        pytest.fail("Failed to start the tile test server")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


class TestDescriptor:
    def test_the_route_is_registered(self, server):
        """A bare @app.route never reaches the app create_app() builds."""
        response = requests.get(f"{server.base_url}/media/tiles/scans/slide.png.dzi")
        assert response.status_code != 404

    def test_it_returns_a_dzi(self, server):
        response = requests.get(f"{server.base_url}/media/tiles/scans/slide.png.dzi")
        assert response.status_code == 200
        assert "application/xml" in response.headers["Content-Type"]
        assert 'Width="1200"' in response.text
        assert 'Height="800"' in response.text

    def test_json_form_carries_the_same_geometry(self, server):
        response = requests.get(
            f"{server.base_url}/media/tiles/scans/slide.png.dzi",
            params={"format": "json"})
        body = response.json()
        assert (body["width"], body["height"]) == (1200, 800)
        assert body["max_level"] == 11        # ceil(log2(1200))
        assert body["levels"] == 12

    def test_a_missing_source_is_a_404(self, server):
        response = requests.get(f"{server.base_url}/media/tiles/scans/gone.png.dzi")
        assert response.status_code == 404

    def test_traversal_is_refused(self, server):
        """
        The path comes off a data file. It reaches the filesystem, so it goes
        through the same guard as every other media route.
        """
        response = requests.get(
            f"{server.base_url}/media/tiles/../../../etc/passwd.dzi")
        assert response.status_code in (403, 404)


class TestTiles:
    def test_a_tile_is_served(self, server):
        response = requests.get(
            f"{server.base_url}/media/tiles/scans/slide.png_files/11/0_0.jpg")
        assert response.status_code == 200, response.text
        assert response.headers["Content-Type"].startswith("image/")
        assert len(response.content) > 100

    def test_the_descriptor_and_the_tile_routes_do_not_shadow_each_other(self, server):
        """
        `<path:filepath>` is greedy. Registered in the wrong order it swallows
        `_files/<level>/<col>_<row>.jpg` whole, and the viewer renders nothing
        while both URLs return 200 for the descriptor.
        """
        descriptor = requests.get(
            f"{server.base_url}/media/tiles/scans/slide.png.dzi")
        tile = requests.get(
            f"{server.base_url}/media/tiles/scans/slide.png_files/8/0_0.jpg")
        assert "xml" in descriptor.headers["Content-Type"]
        assert tile.headers["Content-Type"].startswith("image/")

    def test_the_tile_has_the_size_the_descriptor_implies(self, server):
        from io import BytesIO

        from PIL import Image

        geometry = requests.get(
            f"{server.base_url}/media/tiles/scans/slide.png.dzi",
            params={"format": "json"}).json()
        response = requests.get(
            f"{server.base_url}/media/tiles/scans/slide.png_files/"
            f"{geometry['max_level']}/1_1.jpg")
        assert response.status_code == 200
        # An interior tile is tile_size + one overlap on each side.
        expected = geometry["tile_size"] + 2 * geometry["overlap"]
        assert Image.open(BytesIO(response.content)).size == (expected, expected)

    def test_a_tile_outside_the_grid_is_refused(self, server):
        response = requests.get(
            f"{server.base_url}/media/tiles/scans/slide.png_files/11/99_99.jpg")
        assert response.status_code == 415
        assert "outside level" in response.json()["error"]

    def test_tiles_are_cacheable(self, server):
        """
        Deep zoom fetches dozens per pan. Re-validating each one would put the
        network back into the interaction the pyramid exists to remove.
        """
        response = requests.get(
            f"{server.base_url}/media/tiles/scans/slide.png_files/9/0_0.jpg")
        assert "max-age" in response.headers.get("Cache-Control", "")

    def test_the_pixel_ceiling_refuses_a_level_that_is_not_built_yet(self, server):
        """
        The ceiling governs *building* a level, not serving one that already
        exists — lowering it should not invalidate work already done. So this
        asks for a tile size nothing has built at, which forces the build path.
        """
        response = requests.get(
            f"{server.base_url}/media/tiles/scans/slide.png_files/11/0_0.jpg",
            params={"max_pixels": 1000, "tile_size": 128})
        assert response.status_code == 415
        assert "ceiling" in response.json()["error"]

    def test_an_already_built_tile_is_still_served_under_a_lower_ceiling(self, server):
        """The other half of that decision, stated so it cannot drift."""
        requests.get(f"{server.base_url}/media/tiles/scans/slide.png_files/11/0_0.jpg")
        response = requests.get(
            f"{server.base_url}/media/tiles/scans/slide.png_files/11/0_0.jpg",
            params={"max_pixels": 1000})
        assert response.status_code == 200


class TestIIIF:
    def test_info_json(self, server):
        response = requests.get(
            f"{server.base_url}/media/iiif/scans/slide.png/info.json")
        assert response.status_code == 200
        body = response.json()
        assert body["width"] == 1200 and body["height"] == 800
        assert body["type"] == "ImageService3"

    def test_a_region_request_renders(self, server):
        from io import BytesIO

        from PIL import Image

        response = requests.get(
            f"{server.base_url}/media/iiif/scans/slide.png"
            f"/0,0,600,400/300,/0/default.jpg")
        assert response.status_code == 200, response.text
        assert Image.open(BytesIO(response.content)).size == (300, 200)

    def test_an_unsupported_format_is_rejected(self, server):
        response = requests.get(
            f"{server.base_url}/media/iiif/scans/slide.png/full/max/0/default.tif")
        assert response.status_code == 400


class TestThePageWiresTheViewer:
    def _annotate(self, server):
        session = requests.Session()
        session.post(f"{server.base_url}/register",
                     data={"email": "tiler", "pass": "pw", "action": "signup"})
        session.post(f"{server.base_url}/auth",
                     data={"email": "tiler", "pass": "pw"})
        return session.get(f"{server.base_url}/annotate").text

    def test_the_host_element_and_the_library_are_both_present(self, server):
        """
        The asset is gated on the marker the schema renders. If the marker and
        the gate disagree, the page has a viewer host and no library — which
        fails at runtime, not at render, and only for deep-zoom projects.
        """
        page = self._annotate(server)
        assert "deepzoom-host" in page
        assert "openseadragon-5.0.1.min.js" in page
        assert "deepzoom-viewer.js" in page

    def test_the_client_config_says_deepzoom(self, server):
        page = self._annotate(server)
        assert '"viewer": "deepzoom"' in page
