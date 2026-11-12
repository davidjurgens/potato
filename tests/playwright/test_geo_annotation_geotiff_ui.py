"""
A GeoTIFF basemap: geotiff.js loads on demand, OpenLayers draws the raster
with WebGL (SwiftShader here), and a browser without WebGL gets a message and
keeps the rest of the map.

The GeoTIFF is written by this test (an uncompressed RGB strip with GeoKeys
for EPSG:4326), so no GDAL is needed.
"""

import json
import os
import struct

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402
from tests.playwright.test_geo_annotation_ui import SCRATCH  # noqa: E402

pytestmark = pytest.mark.playwright

EXTENT = [10.0, 45.0, 10.4, 45.3]


def write_geotiff(path, width=64, height=48, extent=EXTENT):
    """An uncompressed RGB GeoTIFF in EPSG:4326 (left half red, right half blue)."""
    pixels = bytearray()
    for _y in range(height):
        for x in range(width):
            pixels += bytes((220, 40, 40)) if x < width // 2 else bytes((40, 60, 220))
    sx = (extent[2] - extent[0]) / width
    sy = (extent[3] - extent[1]) / height
    geokeys = [1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326]
    extra = []          # (tag, type, count, payload bytes)
    tags = [
        (256, 3, 1, width), (257, 3, 1, height), (258, 3, 3, struct.pack("<3H", 8, 8, 8)),
        (259, 3, 1, 1), (262, 3, 1, 2), (273, 4, 1, None), (277, 3, 1, 3), (278, 3, 1, height),
        (279, 4, 1, len(pixels)), (284, 3, 1, 1),
        (33550, 12, 3, struct.pack("<3d", sx, sy, 0.0)),
        (33922, 12, 6, struct.pack("<6d", 0, 0, 0, extent[0], extent[3], 0)),
        (34735, 3, len(geokeys), struct.pack(f"<{len(geokeys)}H", *geokeys)),
    ]
    n = len(tags)
    ifd_size = 2 + n * 12 + 4
    data_offset = 8 + ifd_size
    blobs = b""
    entries = b""
    strip_offset = None
    offsets = {}
    for tag, typ, count, value in tags:
        if isinstance(value, bytes) and len(value) > 4:
            offsets[tag] = data_offset + len(blobs)
            blobs += value
            if len(blobs) % 2:
                blobs += b"\0"
    strip_offset = data_offset + len(blobs)
    for tag, typ, count, value in tags:
        if tag == 273:
            value = strip_offset
        if isinstance(value, bytes):
            field = struct.pack("<I", offsets[tag]) if tag in offsets else value.ljust(4, b"\0")
        elif typ == 3:
            field = struct.pack("<HH", value, 0)
        else:
            field = struct.pack("<I", value)
        entries += struct.pack("<HHI", tag, typ, count) + field
    with open(path, "wb") as f:
        f.write(b"II*\0" + struct.pack("<I", 8))
        f.write(struct.pack("<H", n) + entries + struct.pack("<I", 0))
        f.write(blobs)
        f.write(bytes(pixels))
    del extra


@pytest.fixture(scope="module")
def server():
    import yaml
    work = os.path.join(create_test_directory("geo_annotation_geotiff"), "project")
    os.makedirs(os.path.join(work, "media"), exist_ok=True)
    os.makedirs(os.path.join(work, "data"), exist_ok=True)
    write_geotiff(os.path.join(work, "media", "area.tif"))
    with open(os.path.join(work, "data", "items.json"), "w") as f:
        json.dump([{"id": "t1", "text": "GeoTIFF basemap"}], f)
    config = {
        "annotation_task_name": "GeoTIFF basemap", "data_files": ["data/items.json"],
        "item_properties": {"id_key": "id", "text_key": "text"}, "task_dir": ".",
        "output_annotation_dir": "annotation_output", "media_directory": "media",
        "user_config": {"allow_all_users": True, "users": []},
        "annotation_schemes": [{"annotation_type": "geo_annotation", "name": "area",
                                "description": "Outline something", "labels": ["Thing"],
                                "basemap": {"geotiff": "/media/area.tif"}}],
    }
    with open(os.path.join(work, "config.yaml"), "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the GeoTIFF project")
    yield srv
    srv.stop()


def _open(server, user, args):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(args=args)
    page = browser.new_page(base_url=server.base_url, viewport={"width": 1100, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto("/annotate")
    page.wait_for_selector("form#area[data-geo-ready='true']")
    return p, browser, page, errors


def test_geotiff_renders_with_webgl(server):
    p, browser, page, errors = _open(server, "geo_tiff", ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
    try:
        if not page.evaluate("() => !!document.createElement('canvas').getContext('webgl')"):
            pytest.skip("no WebGL in this Chromium, even with SwiftShader")
        page.wait_for_function("() => !!window.GeoTIFF")
        page.wait_for_timeout(2500)
        assert not page.locator("form#area .geo-note").count(), page.inner_text("form#area")
        # The view was fitted to the GeoTIFF's own extent.
        extent = page.evaluate("""() => {
            const st = window.PotatoGeoAnnotation.state('area');
            return ol.proj.transformExtent(st.map.getView().calculateExtent(), st.proj, 'EPSG:4326');
        }""")
        assert extent[0] <= 10.0 + 0.05 and extent[2] >= 10.4 - 0.05
        shot = os.path.join(SCRATCH, "geo_geotiff.png")
        page.locator("form#area .geo-map").screenshot(path=shot)
        # Sample the screenshot: red on the left half of the raster, blue on the right.
        Image = pytest.importorskip("PIL.Image")
        pts = page.evaluate("""() => {
            const st = window.PotatoGeoAnnotation.state('area');
            return [[10.1, 45.15], [10.3, 45.15]].map(ll =>
                st.map.getPixelFromCoordinate(ol.proj.fromLonLat(ll, st.proj)));
        }""")
        img = Image.open(shot).convert("RGB")
        left, right = (img.getpixel((int(x), int(y))) for x, y in pts)
        assert left[0] > 150 and left[2] < 100, left
        assert right[2] > 150 and right[0] < 100, right
        assert not errors, errors
    finally:
        browser.close()
        p.stop()


def test_no_webgl_says_so_and_keeps_the_map(server):
    p, browser, page, errors = _open(server, "geo_nogl", ["--disable-webgl", "--disable-gpu",
                                                          "--disable-software-rasterizer"])
    try:
        if page.evaluate("() => !!document.createElement('canvas').getContext('webgl')"):
            pytest.skip("this Chromium still offers WebGL with --disable-webgl")
        note = page.inner_text("form#area .geo-note")
        assert "WebGL" in note
        assert page.locator("form#area .geo-tool[data-tool='polygon']").is_visible()
        assert not errors, errors
    finally:
        browser.close()
        p.stop()
