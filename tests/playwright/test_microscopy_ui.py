"""
The microscopy schema in a browser, on the shipped example
(examples/image/multichannel-microscopy): channel toggles and contrast change
the composited pixels, a click selects a cell and a key gives it a class,
rectangles and polygons are drawn with the mouse, and all of it survives
navigating away and back. Also: no console errors, a phone layout that fits,
and dark mode.
"""

import json
import os
import shutil

import pytest

pytest.importorskip("playwright.sync_api")
pytest.importorskip("zarr")
pytest.importorskip("tifffile")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems  # noqa: E402
from tests.helpers.port_manager import find_free_port  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "image", "multichannel-microscopy")
SHOTS = os.environ.get("MICROSCOPY_SCREENSHOTS")

#: Image pixel (x, y) -> page coordinates, through OpenSeadragon.
TO_PAGE = """([x, y]) => { const s = window.PotatoMicroscopy.state(); const W = s.info.width;
  const p = s.viewer.viewport.viewportToViewerElementCoordinates(new OpenSeadragon.Point(x / W, y / W));
  const r = s.host.getBoundingClientRect(); return [r.left + p.x, r.top + p.y]; }"""

#: The composited image's RGB at an image pixel, read from OpenSeadragon's canvas.
PIXEL = """([x, y]) => { const s = window.PotatoMicroscopy.state(); const W = s.info.width;
  const p = s.viewer.viewport.viewportToViewerElementCoordinates(new OpenSeadragon.Point(x / W, y / W));
  const c = s.viewer.drawer.canvas; const k = c.width / c.clientWidth;
  return Array.from(c.getContext('2d').getImageData(Math.round(p.x * k), Math.round(p.y * k), 1, 1).data).slice(0, 3); }"""

#: The cell overlay's RGBA at an image pixel.
CELL_PIXEL = """([x, y]) => { const s = window.PotatoMicroscopy.state(); const r = s.raster;
  const ctx = s.canvas.getContext('2d');
  return Array.from(ctx.getImageData(Math.floor(x / r.scale), Math.floor(y / r.scale), 1, 1).data); }"""


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("microscopy_ui"), "mic")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", "layouts", "__pycache__"))
    srv = FlaskTestServer(port=find_free_port(), config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the microscopy example")
    yield srv
    srv.stop()


def _login(page, server, user):
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})


def _ready(page, instance):
    page.wait_for_function(f"document.getElementById('instance_id').value === '{instance}'")
    page.wait_for_selector("form.microscopy[data-mic-ready='true'][data-mic-labels]", timeout=20000)
    # The opening zoom animates; wait for a stable transform.
    page.wait_for_function("""() => { const s = window.PotatoMicroscopy.state();
        const t = s.layer.style.transform; const ok = t && t === window.__micLast; window.__micLast = t;
        return ok && s.viewer.world.getItemAt(0).getFullyLoaded(); }""", polling=200, timeout=20000)


def _rendered(page, previous):
    page.wait_for_function(
        f"""() => {{ const f = document.querySelector('form.microscopy');
             return f.getAttribute('data-mic-rendering') === 'false'
                 && Number(f.getAttribute('data-mic-render-seq') || 0) > {previous}; }}""",
        timeout=20000)
    page.wait_for_timeout(150)


def _seq(page):
    return int(page.get_attribute("form.microscopy", "data-mic-render-seq") or 0)


def _cells(page, server, instance, z):
    return {c["id"]: c for c in page.context.request.get(
        f"{server.base_url}/api/microscopy/cells?schema=cells&instance_id={instance}&z={z}").json()["cells"]}


def _stored(page, server, instance):
    """The saved answer, as the server reports it."""
    body = page.context.request.get(f"{server.base_url}/get_annotations?instance_id={instance}").json()

    def walk(node):
        if isinstance(node, str) and node.startswith('{"image"'):
            return json.loads(node)
        children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else []
        for child in children:
            found = walk(child)
            if found:
                return found
        return None

    found = walk(body)
    assert found, body
    return found


def _drag(page, a, b):
    x0, y0 = page.evaluate(TO_PAGE, a)
    x1, y1 = page.evaluate(TO_PAGE, b)
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, steps=6)
    page.mouse.move(x1, y1, steps=6)
    page.mouse.up()


def _click_image(page, point):
    x, y = page.evaluate(TO_PAGE, point)
    page.mouse.click(x, y)
    page.wait_for_timeout(120)


def test_channels_contrast_cells_rois_and_persistence(server, page):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    _login(page, server, "mic_ui")
    page.goto(f"{server.base_url}/annotate")
    _ready(page, "tissue_a")
    z = int(page.eval_on_selector(".mic-plane-z", "e => e.value"))
    cells = _cells(page, server, "tissue_a", z)
    # Cell 1 expresses the marker (red); the generator gives it to ids 1, 4, 7, 10.
    c1 = cells[1]
    assert page.evaluate(PIXEL, [c1["x"], c1["y"]])[0] > 150

    # Channel toggle: the marker off, the red goes.
    seq = _seq(page)
    page.click(".mic-channel[data-channel='2'] .mic-ch-visible")
    _rendered(page, seq)
    assert page.evaluate(PIXEL, [c1["x"], c1["y"]])[0] < 60

    # Contrast: DAPI's upper limit to the bottom of its range brightens the
    # dim edge of a nucleus.
    edge = [c1["x"] + 8, c1["y"]]
    before = page.evaluate(PIXEL, edge)[2]
    seq = _seq(page)
    page.focus(".mic-channel[data-channel='0'] .mic-ch-end")
    page.keyboard.press("Home")
    _rendered(page, seq)
    assert page.inner_text(".mic-channel[data-channel='0'] .mic-ch-limit:nth-of-type(2) .mic-ch-value") == "151"
    assert page.evaluate(PIXEL, edge)[2] > before + 30

    # A click selects the cell under the pointer; a number key classifies it.
    _click_image(page, [c1["x"], c1["y"]])
    assert page.inner_text(".mic-selected").startswith("Cell 1 selected")
    page.keyboard.press("1")
    page.wait_for_selector(".mic-cell-list li[data-cell='1']")
    assert page.inner_text(".mic-cell-list li[data-cell='1'] .mic-cell-go") == "Cell 1: marker positive"

    # A rectangle by dragging, a polygon by clicking and Enter.
    page.click(".mic-tool[data-tool='bbox']")
    _drag(page, [20, 20], [80, 60])
    page.click(".mic-tool[data-tool='polygon']")
    for point in ([150, 20], [220, 30], [200, 90]):
        _click_image(page, point)
    page.keyboard.press("Enter")
    assert page.locator(".mic-shapes .mic-roi").count() == 2
    answer = json.loads(page.eval_on_selector(".microscopy-input", "e => e.value"))
    rect, poly = answer["rois"]
    assert rect["type"] == "bbox" and rect["label"] == "damaged" and rect["z"] == z
    assert rect["coordinates"]["x"] * 256 == pytest.approx(20, abs=1.5)
    assert rect["coordinates"]["width"] * 256 == pytest.approx(60, abs=1.5)
    assert [round(p["x"] * 256) for p in poly["coordinates"]] == pytest.approx([150, 220, 200], abs=1.5)
    assert answer["cells"] == [{"label_id": 1, "class": "marker positive", "z": z, "t": 0}]

    page.wait_for_timeout(1600)       # autosave debounce
    stored = _stored(page, server, "tissue_a")
    assert stored["cells"] == answer["cells"] and len(stored["rois"]) == 2

    # Away to the OME-TIFF item, which has time points, and back.
    page.click("#next-btn")
    _ready(page, "tissue_b")
    assert page.locator(".mic-shapes .mic-roi").count() == 0
    assert page.locator(".mic-cell-list li").count() == 0
    assert page.locator(".mic-plane-z").count() == 0
    page.focus(".mic-plane-t")
    page.keyboard.press("ArrowRight")
    page.wait_for_selector("form.microscopy[data-mic-labels='0:1']")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "tiff_t2.png"), full_page=True)

    page.click("#prev-btn")
    _ready(page, "tissue_a")
    assert page.locator(".mic-shapes rect.mic-roi").count() == 1
    assert page.locator(".mic-shapes polygon.mic-roi").count() == 1
    assert page.inner_text(".mic-cell-list li[data-cell='1'] .mic-cell-go") == "Cell 1: marker positive"
    # The cell is filled with its class colour (#f03e3e) in the overlay.
    # (canvas stores premultiplied alpha, so allow a unit of rounding)
    assert page.evaluate(CELL_PIXEL, [c1["x"], c1["y"]]) == pytest.approx([240, 62, 62, 115], abs=2)
    # Channel settings carry over within the session.
    assert not page.is_checked(".mic-channel[data-channel='2'] .mic-ch-visible")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "restored.png"), full_page=True)
    assert not errors, errors


def test_a_double_click_finishes_a_polygon(server, page):
    _login(page, server, "mic_dbl")
    page.goto(f"{server.base_url}/annotate")
    _ready(page, "tissue_a")
    page.click(".mic-tool[data-tool='polygon']")
    for point in ([150, 20], [220, 30]):
        _click_image(page, point)
    x, y = page.evaluate(TO_PAGE, [200, 90])
    page.mouse.dblclick(x, y)
    page.wait_for_timeout(200)
    assert page.locator(".mic-shapes polygon.mic-roi").count() == 1
    poly = json.loads(page.eval_on_selector(".microscopy-input", "e => e.value"))["rois"][0]
    # The double-click's two clicks add one vertex, not two.
    assert [round(p["x"] * 256) for p in poly["coordinates"]] == pytest.approx([150, 220, 200], abs=1.5)


def test_select_a_cell_by_id_with_the_keyboard(server, page):
    _login(page, server, "mic_keys")
    page.goto(f"{server.base_url}/annotate")
    _ready(page, "tissue_a")
    page.fill(".mic-cell-id", "4")
    page.keyboard.press("Enter")
    assert page.inner_text(".mic-selected").startswith("Cell 4 selected")
    page.click(".mic-cell-class[data-class='dividing']")
    page.wait_for_selector(".mic-cell-list li[data-cell='4']")
    page.fill(".mic-cell-id", "999")
    page.keyboard.press("Enter")
    assert page.inner_text(".mic-selected") == "There is no cell 999 in this plane."
    assert page.is_disabled(".mic-cell-class[data-class='dividing']")


def test_fits_a_phone(server, browser_instance):
    context = browser_instance.new_context(
        viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True,
        has_touch=True,
        user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"))
    page = context.new_page()
    try:
        _login(page, server, "mic_phone")
        page.goto(f"{server.base_url}/annotate?desktop=1")
        _ready(page, "tissue_a")
        problems = layout_problems(page, reachable=[
            ".mic-tool[data-tool='polygon']", ".mic-viewer", ".mic-channel[data-channel='2'] .mic-ch-end",
            ".mic-cell-class[data-class='dividing']", "#next-btn"])
        if SHOTS:
            page.screenshot(path=os.path.join(SHOTS, "phone.png"), full_page=True)
        assert not problems, problems
    finally:
        context.close()


def _luminance(rgb):
    import re
    r, g, b = (int(v) / 255 for v in re.findall(r"[\d.]+", rgb)[:3])
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def test_dark_mode_panels_read(server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1400, "height": 1000}, color_scheme="dark")
    page = context.new_page()
    try:
        _login(page, server, "mic_dark")
        page.goto(f"{server.base_url}/annotate")
        _ready(page, "tissue_a")
        colours = page.evaluate("""() => {
            const s = getComputedStyle(document.querySelector('.mic-channels'));
            const h = getComputedStyle(document.querySelector('.mic-channels .mic-ch-name span'));
            const b = getComputedStyle(document.querySelector('.mic-tool'));
            return {bg: s.backgroundColor, text: h.color, button: b.color, buttonBg: b.backgroundColor}; }""")
        if SHOTS:
            page.screenshot(path=os.path.join(SHOTS, "dark.png"), full_page=True)
        bg, fg = _luminance(colours["bg"]), _luminance(colours["text"])
        assert bg < 0.05
        assert (max(bg, fg) + 0.05) / (min(bg, fg) + 0.05) >= 7
        bb, bf = _luminance(colours["buttonBg"]), _luminance(colours["button"])
        assert (max(bb, bf) + 0.05) / (min(bb, bf) + 0.05) >= 4.5
    finally:
        context.close()
