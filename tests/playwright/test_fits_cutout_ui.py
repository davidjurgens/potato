"""
fits_cutout in a real browser, on the astronomy-real-bogus example: the
science / reference / difference triplet renders from server-made PNGs, the
RA/Dec readout follows the mouse and agrees with astropy, zoom and the
crosshair are shared, the light curve is drawn, the real / bogus / unsure
answer is given with keys and survives navigating away and back (on the
page, on the server and on disk), the Galaxy-Zoo-style tree opens and closes
on its whole path, the triplet stacks on a phone, and dark mode reads.
"""

import json
import os
import re
import shutil

import pytest

pytest.importorskip("playwright.sync_api")
pytest.importorskip("astropy")

from astropy.io import fits  # noqa: E402
from astropy.wcs import WCS  # noqa: E402

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems  # noqa: E402
from tests.helpers.port_manager import find_free_port  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "image", "astronomy-real-bogus")
SHOTS = os.environ.get("POTATO_SCREENSHOT_DIR") or create_test_directory("fits_cutout_screens")
READY = ("document.querySelector('.potato-viewer') && "
         "document.querySelector('.potato-viewer').getAttribute('data-viewer-state') === 'ready'")

#: Pixel 7, as Playwright's device table gives it. The shared session browser
#: is used, so the descriptor is written out rather than read from a second
#: sync_playwright() instance.
PHONE = {
    "viewport": {"width": 412, "height": 839}, "device_scale_factor": 2.625,
    "is_mobile": True, "has_touch": True,
    "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"),
}


def _copy_example(name):
    work = os.path.join(create_test_directory(name), "astro")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache", "__pycache__"))
    return work


@pytest.fixture(scope="module")
def server():
    work = _copy_example("fits_cutout_ui")
    srv = FlaskTestServer(port=find_free_port(), config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the astronomy example")
    srv.work = work
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def broken_server():
    """One item whose reference is a table-only FITS file."""
    work = _copy_example("fits_cutout_ui_broken")
    table = fits.BinTableHDU.from_columns([fits.Column(name="mag", format="E", array=[1.0])],
                                          name="CATALOG")
    fits.HDUList([fits.PrimaryHDU(), table]).writeto(
        os.path.join(work, "media", "cutouts", "table.fits"), overwrite=True)
    items = json.load(open(os.path.join(work, "data", "candidates.json")))[1:2]
    items[0]["candidate"]["reference"] = "cutouts/table.fits"
    json.dump(items, open(os.path.join(work, "data", "candidates.json"), "w"))
    srv = FlaskTestServer(port=find_free_port(), config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the broken astronomy config")
    yield srv
    srv.stop()


def _login(page, server, user):
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto(f"{server.base_url}/annotate")
    page.wait_for_function(READY, timeout=30000)
    page.wait_for_function("document.querySelectorAll('.fc-img').length === 3 && "
                           "[...document.querySelectorAll('.fc-img')].every(i => i.naturalWidth > 0)")


def _frame_point(page, index, u, v):
    """Viewport coordinates of fraction (u, v) of cutout `index`'s image."""
    return page.evaluate("""([i, u, v]) => {
        const f = document.querySelectorAll('.fc-frame')[i], r = f.getBoundingClientRect();
        return {x: r.left + f.clientLeft + u * f.clientWidth, y: r.top + f.clientTop + v * f.clientHeight};
    }""", [index, u, v])


def _readout(page):
    text = page.locator(".fc-readout").text_content()
    m = re.search(r"\(([\d.]+)°, ([+-][\d.]+)°\).*x ([\d.]+)\s+y ([\d.]+)", text)
    assert m, text
    return tuple(float(g) for g in m.groups()), text


def _science_wcs(server):
    path = os.path.join(server.work, "media", "cutouts", "cand-001_sci.fits")
    with fits.open(path) as h:
        return WCS(h[0].header)


def test_triplet_renders_and_readout_follows_the_mouse(server, page):
    page.set_viewport_size({"width": 1280, "height": 1000})
    _login(page, server, "astro_hover")
    # Nothing is marked until the pointer is on a cutout (the lines used to
    # sit unpositioned along the frames' top and left edges).
    assert page.eval_on_selector_all(".fc-cross", "els => els.every(e => !e.checkVisibility())")
    labels = page.locator(".fc-caption").all_text_contents()
    assert labels == ["Science", "Reference", "Difference"]
    # Each PNG is the 48 x 48 cutout the item asked for, served by the cache route.
    srcs = page.eval_on_selector_all(".fc-img", "els => els.map(e => [e.getAttribute('src'), e.naturalWidth, e.naturalHeight])")
    assert all(re.fullmatch(r"/science/fits/[0-9a-f]{32}\.png", s) and w == h == 48 for s, w, h in srcs)
    w = _science_wcs(server)
    seen = []
    for u, v in ((0.5, 0.5), (0.2, 0.8)):
        pt = _frame_point(page, 0, u, v)
        page.mouse.move(pt["x"], pt["y"])
        (ra, dec, x, y), text = _readout(page)
        assert "Science" in text and "RA 10:00:" in text
        # Cutout spans FITS x, y 25..72 (48 pixels around 48.5, 48.5).
        assert abs(x - (24.5 + u * 48)) < 0.3 and abs(y - (24.5 + (1 - v) * 48)) < 0.3
        truth = w.all_pix2world([[x - 1, y - 1]], 0)[0]
        assert abs(ra - truth[0]) < 2e-5 and abs(dec - truth[1]) < 2e-5
        seen.append((ra, dec))
    assert seen[0] != seen[1]
    # The crosshair shows on all three cutouts at the same place.
    lefts = page.eval_on_selector_all(".fc-cross-v", "els => els.map(e => e.hidden ? null : e.style.left)")
    assert len(set(lefts)) == 1 and lefts[0] is not None and abs(float(lefts[0][:-1]) - 20) < 1
    # Leaving the cutouts clears it and the readout goes back to the centre.
    page.mouse.move(5, 5)
    assert page.eval_on_selector_all(".fc-cross-v", "els => els.every(e => e.hidden)")
    assert page.locator(".fc-readout").text_content().startswith("Centre RA 10:00:28.61")
    # The light curve is drawn, magnitudes brighter-up, with the epoch marked.
    page.wait_for_selector(".fc-lightcurve[data-plotted='true']", timeout=15000)
    layout = page.evaluate("(() => { const d = document.querySelector('.fc-lightcurve'); "
                           "const r = d._fullLayout.yaxis.range; return {rev: r[0] > r[1], n: d.data.length, "
                           "shape: d.layout.shapes[0].x0}; })()")
    assert layout["rev"] is True and layout["n"] == 4 and abs(layout["shape"] - 60612.31) < 1e-6
    page.screenshot(path=os.path.join(SHOTS, "fits_triplet.png"), full_page=True)
    assert not page.errors, page.errors


def test_zoom_and_pan_are_shared(server, page):
    page.set_viewport_size({"width": 1280, "height": 1000})
    _login(page, server, "astro_zoom")
    page.click(".fc-btn[data-fc='zoom-in']")
    page.click(".fc-btn[data-fc='zoom-in']")
    transforms = page.eval_on_selector_all(".fc-img", "els => els.map(e => e.style.transform)")
    assert len(set(transforms)) == 1 and "scale(2)" in transforms[0]
    assert page.locator(".fc-zoom-level").text_content() == "2×"
    # Drag the difference cutout: every panel pans with it.
    a = _frame_point(page, 2, 0.5, 0.5)
    page.mouse.move(a["x"], a["y"])
    page.mouse.down()
    page.mouse.move(a["x"] + 40, a["y"] + 30, steps=5)
    page.mouse.up()
    after = page.eval_on_selector_all(".fc-img", "els => els.map(e => e.style.transform)")
    assert len(set(after)) == 1 and after[0] != transforms[0]
    # Under the pointer after the pan: the readout still matches astropy.
    pt = _frame_point(page, 1, 0.5, 0.5)
    page.mouse.move(pt["x"], pt["y"])
    (_ra, _dec, x, y), text = _readout(page)
    assert "Reference" in text and 24.5 < x < 72.5 and 24.5 < y < 72.5
    page.click(".fc-btn[data-fc='reset']")
    assert page.eval_on_selector_all(".fc-img", "els => els.map(e => e.style.transform)")[0] \
        == "translate(0%, 0%) scale(1)"
    # Keyboard: a focused cutout moves its crosshair with the arrow keys.
    page.keyboard.press("Tab")
    page.focus(".fc-frame >> nth=0")
    page.keyboard.press("ArrowRight")
    (_ra2, _dec2, x2, _y2), _ = _readout(page)
    assert page.evaluate("document.activeElement.classList.contains('fc-frame')")
    page.keyboard.press("ArrowRight")
    (_ra3, _dec3, x3, _y3), _ = _readout(page)
    assert abs((x3 - x2) - 1.0) < 1e-6
    # The answer keys still reach the radio while a cutout has focus.
    page.keyboard.press("u")
    page.wait_for_timeout(300)
    assert page.is_checked("form#vetting input[value='Unsure']")
    assert not page.errors, page.errors


def _shown(page, name):
    return page.locator(f'[data-display-logic-target="true"][data-schema-name="{name}"]').is_visible()


def test_keys_label_tree_and_persistence(server, page):
    page.set_viewport_size({"width": 1280, "height": 1000})
    _login(page, server, "astro_keys")
    page.mouse.click(10, 300)                      # focus the page, not a field
    page.keyboard.press("r")
    page.wait_for_timeout(500)
    assert page.is_checked("form#vetting input[value='Real']")
    assert _shown(page, "host") and not _shown(page, "bogus_reason")
    page.click("form#host label:has-text('A galaxy')")
    page.wait_for_timeout(500)
    assert _shown(page, "host_shape") and not _shown(page, "edge_on")
    page.click("form#host_shape label:has-text('Features or a disk')")
    page.wait_for_timeout(500)
    assert _shown(page, "edge_on")
    # Bogus closes the whole host branch, not only its first question.
    page.keyboard.press("b")
    page.wait_for_timeout(500)
    assert page.is_checked("form#vetting input[value='Bogus']")
    assert _shown(page, "bogus_reason")
    assert not any(_shown(page, n) for n in ("host", "host_shape", "edge_on", "spiral"))
    page.keyboard.press("r")
    page.wait_for_timeout(1700)                    # autosave debounce
    page.screenshot(path=os.path.join(SHOTS, "fits_tree.png"), full_page=True)

    page.click("#next-btn")
    page.wait_for_function("document.getElementById('instance_id').value === 'cand-002'")
    page.wait_for_function(READY, timeout=30000)
    assert not page.is_checked("form#vetting input[value='Real']")
    page.click("#prev-btn")
    page.wait_for_function("document.getElementById('instance_id').value === 'cand-001'")
    page.wait_for_function(READY, timeout=30000)
    page.wait_for_timeout(500)
    assert page.is_checked("form#vetting input[value='Real']")
    assert page.is_checked("form#host input[value='A galaxy']")
    assert _shown(page, "edge_on")
    stored = page.evaluate("fetch('/get_annotations?instance_id=cand-001').then(r => r.json())")
    assert stored["label_annotations"]["vetting"] == ["Real"]
    assert stored["label_annotations"]["host_shape"] == ["Features or a disk"]
    state_path = os.path.join(server.work, "annotation_output", "astro_keys", "user_state.json")
    on_disk = json.dumps(json.load(open(state_path)))
    assert "cand-001" in on_disk and "Features or a disk" in on_disk
    assert not page.errors, page.errors


def test_triplet_stacks_on_a_phone(server, browser_instance):
    context = browser_instance.new_context(**PHONE)
    page = context.new_page()
    try:
        _login(page, server, "astro_phone")
        page.wait_for_selector(".fc-lightcurve[data-plotted='true']", timeout=15000)
        boxes = page.eval_on_selector_all(".fc-frame", "els => els.map(e => { const r = e.getBoundingClientRect(); "
                                          "return [r.left, r.top, r.width]; })")
        lefts = {round(b[0]) for b in boxes}
        assert len(lefts) == 1, boxes                          # one column
        assert boxes[0][1] < boxes[1][1] < boxes[2][1]
        assert boxes[0][2] > 0.55 * PHONE["viewport"]["width"]   # big enough to judge
        # A tap pins the crosshair and fills the readout.
        page.locator(".fc-frame").nth(2).scroll_into_view_if_needed()
        pt = _frame_point(page, 2, 0.5, 0.5)
        page.touchscreen.tap(pt["x"], pt["y"])
        assert "Difference" in page.locator(".fc-readout").text_content()
        problems = layout_problems(page, reachable=["form#vetting", "#next-btn", ".fc-lightcurve"])
        page.screenshot(path=os.path.join(SHOTS, "fits_phone.png"), full_page=True)
        assert not problems, problems
        assert not page.errors, page.errors
    finally:
        context.close()


def test_dark_mode(server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1280, "height": 1000}, color_scheme="dark")
    page = context.new_page()
    try:
        _login(page, server, "astro_dark")
        page.wait_for_selector(".fc-lightcurve[data-plotted='true']", timeout=15000)
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
        colours = page.evaluate("""(() => {
            const cs = getComputedStyle(document.documentElement);
            const cap = getComputedStyle(document.querySelector('.fc-caption')).color;
            const lc = document.querySelector('.fc-lightcurve');
            return {fg: cs.getPropertyValue('--foreground').trim(), cap: cap,
                    plotFont: lc.layout.font.color,
                    btn: getComputedStyle(document.querySelector('.fc-btn')).backgroundColor,
                    card: cs.getPropertyValue('--card').trim()};
        })()""")
        assert colours["plotFont"] == colours["fg"]
        # Light text on the dark card.
        rgb = [int(v) for v in re.findall(r"\d+", colours["cap"])[:3]]
        assert sum(rgb) / 3 > 180, colours
        # The toggle re-themes the plot without a reload.
        page.click("[data-theme-toggle]")
        page.wait_for_function("document.documentElement.getAttribute('data-theme') === 'light'")
        page.wait_for_timeout(300)
        light_fg = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--foreground').trim()")
        assert page.evaluate("document.querySelector('.fc-lightcurve').layout.font.color") == light_fg
        page.click("[data-theme-toggle]")
        page.wait_for_timeout(300)
        page.screenshot(path=os.path.join(SHOTS, "fits_dark.png"), full_page=True)
        assert not page.errors, page.errors
    finally:
        context.close()


def test_a_file_without_an_image_says_so(broken_server, page):
    page.set_viewport_size({"width": 1280, "height": 1000})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    req = page.context.request
    req.post(f"{broken_server.base_url}/register", form={"action": "signup", "email": "astro_err", "pass": "pass"})
    req.post(f"{broken_server.base_url}/auth", form={"action": "login", "email": "astro_err", "pass": "pass"})
    page.goto(f"{broken_server.base_url}/annotate")
    page.wait_for_function(READY, timeout=30000)
    msg = page.locator(".fc-panel[data-panel='reference'] .fc-panel-error").text_content()
    assert "no image HDU" in msg and "CATALOG (table)" in msg
    # The other two cutouts still show, and the question can still be answered.
    assert page.locator(".fc-img").count() == 2
    page.click("form#vetting label:has-text('Bogus')")
    assert page.is_checked("form#vetting input[value='Bogus']")
    page.screenshot(path=os.path.join(SHOTS, "fits_error.png"), full_page=True)
    assert not page.errors, page.errors
