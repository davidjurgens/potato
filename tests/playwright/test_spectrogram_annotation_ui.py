"""
spectrogram_annotation in a real browser, on the bioacoustics example: the
imported Raven boxes are drawn, a box drawn with real mouse drags is stored
with the time and frequency under the pointer, the label keys relabel it,
arrow keys nudge it, a dragged imported box is marked edited, everything is
drawn again after navigating away and back, and the page fits a phone.
"""

import json
import os
import shutil

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems, mobile_page  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "audio", "bioacoustics-boxes")
NYQUIST = 22050 / 2


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("spectrogram_ui"), "bio")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache", "layouts"))
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the bioacoustics example")
    yield srv
    srv.stop()


def _login(page, server, user):
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})


def _desktop(server, user):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    page = browser.new_page(base_url=server.base_url, viewport={"width": 1280, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    _login(page, server, user)
    page.goto("/annotate")
    page.wait_for_selector("form.spectrogram-annotation.sg-ready")
    return p, browser, page, errors


def _boxes(page):
    raw = page.eval_on_selector(".spectrogram-input", "e => e.value")
    return json.loads(raw) if raw else []


def _stored(page, server, instance_id):
    r = page.context.request.get(f"{server.base_url}/get_annotations?instance_id={instance_id}")
    values = (r.json().get("label_values") or {}).get("calls") or {}
    raw = values.get("_data")
    return json.loads(raw) if raw else None


def _wrap(page):
    return page.locator(".sg-wrap").bounding_box()


def _drag(page, x0, y0, x1, y1):
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, steps=6)
    page.mouse.move(x1, y1, steps=6)
    page.mouse.up()


def _geometry(page):
    return page.eval_on_selector_all(
        ".sg-box", "els => els.map(e => [e.style.left, e.style.top, e.style.width, e.style.height,"
                   " e.querySelector('.sg-tag').textContent])")


def test_draw_label_nudge_and_restore(server):
    p, browser, page, errors = _desktop(server, "sg_ui")
    try:
        assert page.input_value("#instance_id") == "site_a_0600"
        # The three boxes from the Raven table, drawn on the spectrogram.
        assert page.locator(".sg-box").count() == 3
        assert [b["label"] for b in _boxes(page)] == ["whistle", "upsweep", "trill"]

        # Draw the missing downsweep (4.5-5.0 s, 4-7 kHz) with the mouse.
        w = _wrap(page)
        x = lambda s: w["x"] + w["width"] * s / 6.0            # noqa: E731
        y = lambda hz: w["y"] + w["height"] * (1 - hz / NYQUIST)  # noqa: E731
        _drag(page, x(4.45), y(7300), x(5.05), y(3800))
        page.wait_for_function("document.querySelectorAll('.sg-box').length === 4")
        new = _boxes(page)[-1]
        assert new["label"] == "whistle" and new["source"] == "human"
        assert abs(new["start_s"] - 4.45) < 0.05 and abs(new["end_s"] - 5.05) < 0.05
        assert abs(new["low_hz"] - 3800) < 150 and abs(new["high_hz"] - 7300) < 150

        # Key 3 relabels the selected (new) box as a downsweep.
        page.keyboard.press("3")
        assert _boxes(page)[-1]["label"] == "downsweep"
        assert "downsweep" in page.get_attribute(".sg-box.sg-selected", "aria-label")
        # Arrow keys nudge it; Shift+arrow widens it.
        before = _boxes(page)[-1]
        page.keyboard.press("ArrowLeft")
        page.keyboard.press("Shift+ArrowRight")
        after = _boxes(page)[-1]
        step = 6.0 / 100
        assert after["start_s"] == pytest.approx(before["start_s"] - step, abs=0.002)
        assert after["end_s"] == pytest.approx(before["end_s"], abs=0.002)
        assert after["low_hz"] == before["low_hz"]

        # Dragging an imported box moves it and marks it edited.
        trill = page.locator(".sg-box").nth(2).bounding_box()
        _drag(page, trill["x"] + trill["width"] / 2, trill["y"] + trill["height"] / 2,
              trill["x"] + trill["width"] / 2 + w["width"] * 0.1 / 6, trill["y"] + trill["height"] / 2)
        moved = [b for b in _boxes(page) if b["label"] == "trill"][0]
        assert moved["edited"] is True and moved["source"] == "import"
        assert moved["start_s"] == pytest.approx(3.1, abs=0.03)

        geometry = _geometry(page)
        page.wait_for_timeout(1500)   # autosave debounce
        stored = _stored(page, server, "site_a_0600")
        assert stored and sorted(b["label"] for b in stored) == ["downsweep", "trill", "upsweep", "whistle"]

        page.click("#next-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'site_b_0615'")
        page.wait_for_selector("form.spectrogram-annotation.sg-ready")
        assert page.locator(".sg-box").count() == 3
        page.click("#prev-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'site_a_0600'")
        page.wait_for_selector("form.spectrogram-annotation.sg-ready")
        page.wait_for_function("document.querySelectorAll('.sg-box').length === 4")
        assert _geometry(page) == geometry
        assert page.locator(".sg-list tbody tr").count() == 4
        assert not errors, errors
    finally:
        browser.close()
        p.stop()


def test_delete_and_keyboard_box(server):
    p, browser, page, errors = _desktop(server, "sg_keys")
    try:
        page.locator(".sg-box").first.focus()
        page.keyboard.press("Delete")
        assert page.locator(".sg-box").count() == 2
        page.focus(".sg-root")
        page.keyboard.press("n")
        assert page.locator(".sg-box").count() == 3
        assert _boxes(page)[-1]["source"] == "human"
        page.keyboard.press(" ")
        page.wait_for_function("document.querySelector('.sg-play').getAttribute('aria-pressed') === 'true'")
        page.keyboard.press(" ")
        page.wait_for_function("document.querySelector('.sg-play').getAttribute('aria-pressed') === 'false'")
        assert not errors, errors
    finally:
        browser.close()
        p.stop()


def test_fits_a_phone(server):
    with mobile_page("iPhone 13", server.base_url) as page:
        _login(page, server, "sg_phone")
        page.goto("/annotate")
        page.wait_for_selector("form.spectrogram-annotation.sg-ready")
        assert not layout_problems(page, reachable=[".sg-play", ".sg-zoom-in", ".sg-viewport",
                                                    ".sg-label[data-label='trill']"])
        # A finger drag draws a box (touch events through the DevTools
        # protocol, which Chrome turns into pointer events as on a phone).
        before = page.locator(".sg-box").count()
        page.locator(".sg-wrap").scroll_into_view_if_needed()
        w = page.locator(".sg-wrap").bounding_box()
        cdp = page.context.new_cdp_session(page)
        x0, y0 = w["x"] + w["width"] * 0.80, w["y"] + w["height"] * 0.30
        x1, y1 = w["x"] + w["width"] * 0.92, w["y"] + w["height"] * 0.60
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]})
        for i in range(1, 9):
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [
                {"x": x0 + (x1 - x0) * i / 8, "y": y0 + (y1 - y0) * i / 8}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_function(f"document.querySelectorAll('.sg-box').length === {before + 1}")
        assert not layout_problems(page)
