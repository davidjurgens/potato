"""
The depth map display, end to end in a real browser.

The specific thing being proved here is that the **readout reports metres**.
A colourised depth image is easy to produce and easy to be wrong about: every
window setting produces a plausible-looking picture, so the picture cannot tell
you the values are right. The readout can, and these tests check it against
depths written by hand into the fixture.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

WIDTH, HEIGHT = 8, 4
#: Depth in millimetres, row-major. Row 0 is 1..4 m, row 3 has a hole.
MILLIMETRES = [
    [1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500],
    [1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500],
    [5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000],
    [0,    0,    9000, 9000, 9000, 9000, 9000, 9000],
]


def _png_chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_depth_png(path: Path):
    """A 16-bit greyscale PNG, written directly so the test needs no Pillow."""
    rows = [struct.pack(f">{WIDTH}H", *row) for row in MILLIMETRES]
    raw = b"".join(b"\x00" + row for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR",
                     struct.pack(">IIBBBBB", WIDTH, HEIGHT, 16, 0, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b""))


@pytest.fixture
def depth_server(make_server, tmp_path_factory):
    media = tmp_path_factory.mktemp("depth-media")
    write_depth_png(media / "d.png")

    schemes = [{
        "annotation_type": "radio",
        "name": "quality",
        "description": "Is the depth usable?",
        "labels": ["yes", "no"],
    }]
    return make_server(
        schemes,
        items=[{"id": "s1", "depth": "d.png", "note": "check the readout"}],
        extra_config={
            "media_directory": str(media),
            "item_properties": {"id_key": "id", "text_key": "note"},
            "instance_display": {
                "fields": [{
                    "key": "depth",
                    "type": "depth_map",
                    "label": "Predicted depth",
                    "display_options": {"depth_scale": 0.001},
                }],
            },
        },
    )


def open_depth(test, page, server):
    test.register_and_login(page, server)
    page.goto(f"{server.base_url}/annotate")
    page.wait_for_selector(".depth-display", timeout=30000)
    # The raw float buffer arrives after the picture, deliberately — the
    # readout depends on it, so wait for it rather than for the image.
    page.wait_for_function(
        """() => {
            const el = document.querySelector('.depth-display');
            return el && el.depthViewer && el.depthViewer.parsed;
        }""", timeout=30000)


def viewer_eval(page, expression):
    return page.evaluate(
        "() => { const v = document.querySelector('.depth-display')"
        ".depthViewer; return (" + expression + "); }")


class TestTheDisplayLoads(BasePlaywrightTest):
    def test_the_asset_is_gated_on_and_actually_loaded(self, depth_server, page):
        # FRONTEND_ASSET_MARKERS decides whether depth-viewer.js is in the
        # page at all. A missing marker is silent: the markup renders and
        # nothing initialises it.
        open_depth(self, page, depth_server)
        assert page.evaluate("typeof window.DepthViewer") == "function"

    def test_the_colourised_image_is_a_real_png(self, depth_server, page):
        open_depth(self, page, depth_server)
        assert page.evaluate(
            """() => {
                const img = document.querySelector('.depth-overlay');
                return img.complete && img.naturalWidth;
            }""") == WIDTH

    def test_the_window_is_seeded_from_the_percentiles(self, depth_server, page):
        # Not min/max: one stray return otherwise compresses everything real
        # into a single colour and the map opens looking blank.
        open_depth(self, page, depth_server)
        near = float(page.input_value(".depth-near"))
        far = float(page.input_value(".depth-far"))
        assert 1.0 <= near <= 2.0
        assert 5.0 <= far <= 9.0
        assert far > near


class TestTheReadoutReportsMetres(BasePlaywrightTest):
    def test_a_known_pixel_reports_its_written_depth(self, depth_server, page):
        open_depth(self, page, depth_server)
        # Column 0, row 0 was written as 1000 mm.
        value = viewer_eval(
            page,
            "window.DepthViewer.depthAt(v.parsed, 0.01, 0.01)")
        assert value == pytest.approx(1.0, abs=1e-4)

    def test_the_scale_is_applied_not_ignored(self, depth_server, page):
        # Without depth_scale this would read 5000 — a number that still looks
        # like a plausible depth map once the window rescales, which is exactly
        # why the readout exists.
        open_depth(self, page, depth_server)
        value = viewer_eval(
            page, "window.DepthViewer.depthAt(v.parsed, 0.5, 0.6)")
        assert value == pytest.approx(5.0, abs=1e-4)

    def test_a_hole_says_no_measurement(self, depth_server, page):
        open_depth(self, page, depth_server)
        assert viewer_eval(
            page, "window.DepthViewer.depthAt(v.parsed, 0.01, 0.95)") is None
        assert viewer_eval(
            page,
            "window.DepthViewer.formatDepth("
            "window.DepthViewer.depthAt(v.parsed, 0.01, 0.95))"
        ) == "No measurement here"

    def test_moving_the_pointer_updates_the_live_region(self, depth_server,
                                                        page):
        open_depth(self, page, depth_server)
        box = page.locator(".depth-overlay").bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.5,
                        box["y"] + box["height"] * 0.6)
        page.wait_for_timeout(150)
        assert "m" in page.text_content(".depth-readout-value")

    def test_leaving_the_stage_clears_the_readout(self, depth_server, page):
        # A stale distance left under the cursor after the pointer has gone is
        # worse than none: it reads as the value for wherever you look next.
        open_depth(self, page, depth_server)
        box = page.locator(".depth-overlay").bounding_box()
        page.mouse.move(box["x"] + 2, box["y"] + 2)
        page.wait_for_timeout(120)
        page.mouse.move(box["x"] - 200, box["y"] - 200)
        page.wait_for_timeout(200)
        assert page.text_content(".depth-readout-value").strip() == "—"


class TestControls(BasePlaywrightTest):
    def test_changing_the_colormap_refetches_the_render(self, depth_server,
                                                        page):
        open_depth(self, page, depth_server)
        before = page.get_attribute(".depth-overlay", "src")
        page.select_option(".depth-colormap", "viridis")
        page.wait_for_timeout(300)
        after = page.get_attribute(".depth-overlay", "src")
        assert after != before
        assert "colormap=viridis" in after

    def test_reset_restores_the_percentile_window(self, depth_server, page):
        open_depth(self, page, depth_server)
        original = page.input_value(".depth-far")
        page.fill(".depth-far", "99")
        page.wait_for_timeout(350)
        page.click(".depth-reset")
        page.wait_for_timeout(200)
        assert page.input_value(".depth-far") == original

    def test_the_window_reaches_the_request(self, depth_server, page):
        open_depth(self, page, depth_server)
        page.fill(".depth-near", "2")
        page.fill(".depth-far", "6")
        page.wait_for_timeout(400)
        src = page.get_attribute(".depth-overlay", "src")
        assert "window_min=2" in src
        assert "window_max=6" in src
