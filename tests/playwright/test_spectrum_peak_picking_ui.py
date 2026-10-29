"""
spectrum display + peak_picking scheme in a real browser, on the
spectrum-peak-picking example: Plotly loads from /static/vendor, the ppm axis
runs high to low, a click picks a peak (and a second click removes it),
suggested peaks are accepted from the plot and from the list, a dragged region
is integrated on the server, and everything survives navigating away and
back. Plus zoom-to-full-resolution, keyboard entry, the range route's
refusals, a phone layout and dark mode.
"""

import json
import os
import shutil
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems  # noqa: E402
from tests.helpers.port_manager import find_free_port  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "spectrum-peak-picking")
SCRATCH = os.environ.get("POTATO_SCREENSHOT_DIR") or create_test_directory("spectrum_screens")

READY = "document.querySelector('.potato-viewer').getAttribute('data-viewer-state') === 'ready'"

# Screen position of a data point (x, y) on the plot.
POINT = """([x, y]) => {
    const gd = document.querySelector('.potato-viewer .pv-stage');
    const fl = gd._fullLayout;
    const r = gd.querySelector('.nsewdrag').getBoundingClientRect();
    return {x: r.left + fl.xaxis.l2p(x), y: r.top + fl.yaxis.l2p(y)};
}"""

# Playwright's "Pixel 7" descriptor, written out: a test may not start its own
# sync_playwright() to read p.devices once the session browser runs.
PIXEL_7 = {
    "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"),
    "viewport": {"width": 412, "height": 839}, "screen": {"width": 412, "height": 915},
    "device_scale_factor": 2.625, "is_mobile": True, "has_touch": True,
}


def _start(required):
    work = os.path.join(create_test_directory("spectrum_ui"), "spectra")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache", "__pycache__"))
    config_path = os.path.join(work, "config.yaml")
    if not required:
        # The persistence tests move on with suggestions still pending, which
        # the example (rightly) does not allow.
        import yaml
        cfg = yaml.safe_load(open(config_path))
        for scheme in cfg["annotation_schemes"]:
            scheme.pop("label_requirement", None)
        with open(config_path, "w") as fh:
            yaml.safe_dump(cfg, fh, sort_keys=False)
    srv = FlaskTestServer(port=find_free_port(), config_file=config_path)
    if not srv.start():
        pytest.fail("could not start the spectrum-peak-picking example")
    return srv


@pytest.fixture(scope="module")
def server():
    srv = _start(required=False)
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def example_server():
    """The example exactly as shipped."""
    srv = _start(required=True)
    yield srv
    srv.stop()


def _login(page, server, user):
    page.errors, page.requests = [], []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
    page.on("request", lambda r: page.requests.append(r.url))
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto(f"{server.base_url}/annotate")
    page.wait_for_function(READY, timeout=30000)
    page.wait_for_timeout(300)


def _at(page, x, y):
    return page.evaluate(POINT, [x, y])


def _click(page, x, y):
    pt = _at(page, x, y)
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_timeout(250)


def _drag(page, a, b, y):
    p, q = _at(page, a, y), _at(page, b, y)
    page.mouse.move(p["x"], p["y"])
    page.mouse.down()
    page.mouse.move(q["x"], q["y"], steps=10)
    page.mouse.up()


def _selection(page):
    return page.evaluate("window.potatoViewers.spectrum.getSelection()")


def _stored(page):
    raw = page.eval_on_selector("form.peak-picking .peak-picking-input", "e => e.value")
    return json.loads(raw) if raw else {}


def _rows(page):
    return page.eval_on_selector_all(
        ".pp-peak-table tbody tr",
        "rows => rows.map(r => [...r.children].slice(0, 3).map(td => td.textContent.trim()))")


def _plot_peaks(page):
    """x of the picked-peak markers Plotly drew (trace 2)."""
    return page.evaluate("[...document.querySelector('.pv-stage')._fullData[2].x]")


def test_draws_the_spectrum_from_the_server(server, page):
    _login(page, server, "sp_load")
    # ppm runs high to low.
    lo, hi = page.evaluate("document.querySelector('.pv-stage')._fullLayout.xaxis.range")
    assert lo > 9.9 and hi < 0.1
    assert page.locator(".pp-sugg").count() == 8
    assert page.text_content(".pp-sugg-count") == "8 of 8 to review"
    status = page.text_content(".pv-status")
    assert "16,384 points" in status and "Ethyl acetate" in status
    assert page.text_content(".potato-viewer .xtitle") == "Chemical shift (ppm)"
    assert any(urlparse(u).path == "/static/vendor/plotly-2.27.0.min.js" for u in page.requests)
    hosts = {urlparse(u).netloc for u in page.requests if u.startswith("http")}
    assert hosts == {urlparse(server.base_url).netloc}, hosts
    # The incomplete reason names the review the config requires.
    reason = page.get_attribute("form.peak-picking", "data-incomplete-reason")
    assert "pick at least 1 peak" in reason and "8 left" in reason
    page.screenshot(path=os.path.join(SCRATCH, "spectrum_loaded.png"), full_page=True)
    assert not page.errors, page.errors


def test_click_to_pick_and_click_again_to_remove(server, page):
    _login(page, server, "sp_click")
    _click(page, 7.26, 60)        # the CHCl3 line, below the detection threshold
    sel = _selection(page)
    assert len(sel["items"]) == 1
    peak = sel["items"][0]
    assert peak["kind"] == "peak" and peak["source"] == "manual"
    assert abs(peak["x"] - 7.26) < 0.002 and peak["y"] > 100      # snapped to the line's top
    assert _rows(page) == [["7.260", fmt_y(peak["y"]), "added"]]
    assert _plot_peaks(page) == [peak["x"]]
    assert _stored(page)["items"][0]["source"] == "manual"
    assert page.text_content(".pp-message") == "Picked a peak at 7.260 ppm."
    _click(page, 7.26, 60)
    assert _selection(page)["items"] == []
    assert page.is_visible(".pp-empty") and _plot_peaks(page) == []
    assert _stored(page) == {}
    assert not page.errors, page.errors


def fmt_y(y):
    return str(int(y)) if float(y).is_integer() else str(y)


def test_the_example_holds_next_until_every_suggestion_is_reviewed(example_server, page):
    """The example's comment promises this; min_peaks and require_review
    only count while the scheme is required, which the example now sets."""
    _login(page, example_server, "sp_required")
    first = page.input_value("#instance_id")
    page.click("#next-btn")
    page.wait_for_timeout(800)
    assert page.input_value("#instance_id") == first
    page.locator(".pp-sugg .pp-accept").first.click()
    while page.locator(".pp-sugg").count():
        page.locator(".pp-sugg .pp-reject").first.click()
        page.wait_for_timeout(50)
    page.wait_for_timeout(1600)       # autosave debounce
    page.click("#next-btn")
    page.wait_for_function(
        "f => document.getElementById('instance_id').value !== f", arg=first)


def test_accept_reject_label_integrate_and_persist(server, page):
    _login(page, server, "sp_persist")
    page.click(".pp-sugg:has-text('2.040 ppm') .pp-accept")          # from the list
    _click(page, 1.26, 1500)                                         # from the plot marker
    page.click(".pp-sugg:has-text('4.146 ppm') .pp-reject")
    sel = _selection(page)
    peaks = {round(it["x"], 2): it for it in sel["items"]}
    assert set(peaks) == {2.04, 1.26} and all(p["source"] == "auto" for p in peaks.values())
    assert [round(x, 3) for x in sel["rejected"]] == [4.146]
    assert page.text_content(".pp-sugg-count") == "5 of 8 to review"

    row = page.locator(".pp-peak-table tbody tr", has_text="2.040")
    row.locator("input[data-field=assignment]").fill("CH3CO")
    row.locator("select[data-field=multiplicity]").select_option("s")
    # The label is drawn beside the peak on the plot.
    assert page.locator(".potato-viewer .annotation-text", has_text="CH3CO · s").count() == 1

    page.click("button.sp-mode[data-mode=integrate]")
    _drag(page, 2.12, 1.96, 1500)
    page.wait_for_function("window.potatoViewers.spectrum.getSelection().items.some(i => i.kind === 'region')")
    region = [it for it in _selection(page)["items"] if it["kind"] == "region"][0]
    assert 1.95 < region["from"] < 1.98 and 2.11 < region["to"] < 2.13
    assert page.text_content(".pp-region-table tbody tr td:nth-child(3)") == "1.00"
    page.locator(".pp-region-table input[data-field=protons]").fill("3")
    page.wait_for_timeout(1600)       # autosave debounce
    page.screenshot(path=os.path.join(SCRATCH, "spectrum_picked.png"), full_page=True)

    page.click("#next-btn")
    page.wait_for_function("document.getElementById('instance_id').value === 'nmr_ethanol'")
    page.wait_for_function(READY, timeout=30000)
    assert page.locator(".pp-peak-table tbody tr").count() == 0
    assert page.locator(".pp-sugg").count() > 0
    page.click("#prev-btn")
    page.wait_for_function("document.getElementById('instance_id').value === 'nmr_ethyl_acetate'")
    page.wait_for_function(READY, timeout=30000)
    page.wait_for_timeout(300)

    # What the annotator sees: the table, the fields, the rejected chip, the plot.
    assert _rows(page) == [["2.040", "3003", "suggested"], ["1.260", "1506", "suggested"]]
    row = page.locator(".pp-peak-table tbody tr", has_text="2.040")
    assert row.locator("input[data-field=assignment]").input_value() == "CH3CO"
    assert row.locator("select[data-field=multiplicity]").input_value() == "s"
    assert page.locator(".pp-restore").all_text_contents() == ["↺ 4.146"]
    assert page.locator(".pp-sugg").count() == 5
    assert sorted(round(x, 2) for x in _plot_peaks(page)) == [1.26, 2.04]
    assert page.evaluate("document.querySelector('.pv-stage')._fullLayout.shapes.length") == 1
    assert page.locator(".pp-region-table input[data-field=protons]").input_value() == "3"

    # What the server stored.
    server_side = page.evaluate("fetch('/get_annotations?instance_id=nmr_ethyl_acetate').then(r => r.json())")
    stored = json.loads(server_side["label_values"]["peaks"]["peaks"])
    assert stored["viewer"] == "spectrum"
    assert [round(x, 3) for x in stored["rejected"]] == [4.146]
    kinds = sorted((it["kind"], it.get("source")) for it in stored["items"])
    assert kinds == [("peak", "auto"), ("peak", "auto"), ("region", None)]
    s_region = [it for it in stored["items"] if it["kind"] == "region"][0]
    assert s_region["fields"] == {"protons": "3"}
    # The integral is the server's, over every original point.
    from potato.science.converters.jcamp import read_jcamp
    from potato.science.spectra import integrate
    truth = integrate(read_jcamp(os.path.join(EXAMPLE, "media", "spectra", "ethyl_acetate_1h.jdx")),
                      s_region["from"], s_region["to"])
    assert s_region["integral"] == pytest.approx(truth, rel=1e-9)
    assert not page.errors, page.errors


def test_zoom_fetches_full_resolution(server, page):
    _login(page, server, "sp_zoom")
    _drag(page, 4.6, 3.6, 900)
    page.wait_for_function("window.potatoViewers.spectrum.spectrum.detail !== null")
    lo, hi = page.evaluate("document.querySelector('.pv-stage')._fullLayout.xaxis.range")
    assert 4.5 < lo < 4.7 and 3.5 < hi < 3.7
    detail = page.evaluate("window.potatoViewers.spectrum.spectrum.detail.x.length")
    assert detail > 1500           # every point of the range, not the overview's few dozen
    assert any("/api/spectrum/range" in u for u in page.requests)
    # A click on a quartet line, zoomed in, snaps to that line.
    _click(page, 4.111, 700)
    xs = [round(it["x"], 3) for it in _selection(page)["items"]]
    assert xs == [4.111]
    page.click(".sp-reset")
    page.wait_for_function("window.potatoViewers.spectrum.spectrum.detail === null")
    assert not page.errors, page.errors


def test_keyboard_entry(server, page):
    _login(page, server, "sp_keys")
    page.fill(".pp-add-x", "2.04")
    page.press(".pp-add-x", "Enter")
    page.fill(".pp-add-x", "7.26")
    page.click(".pp-add-btn")
    assert [(round(i["x"], 2), i["source"]) for i in _selection(page)["items"]] == [(2.04, "auto"), (7.26, "manual")]
    page.fill(".pp-add-x", "12")
    page.press(".pp-add-x", "Enter")
    assert page.text_content(".pp-message") == "Type a position between 0.000 and 10.000."
    # Accept and reject are buttons, so the whole review works from the keyboard.
    page.focus(".pp-sugg .pp-accept")
    page.keyboard.press("Enter")
    assert len(_selection(page)["items"]) == 3
    assert page.evaluate("document.activeElement.classList.contains('pp-accept')")
    assert not page.errors, page.errors


def test_range_route_refusals(server, page):
    req = page.context.request
    url = f"{server.base_url}/api/spectrum/range"
    assert req.get(url + "?instance_id=nmr_ethanol&field=spectrum&x0=1&x1=2").status == 401
    _login(page, server, "sp_route")
    ok = req.get(url + "?instance_id=nmr_ethanol&field=spectrum&x0=1&x1=2")
    assert ok.status == 200 and ok.json()["points"] > 1000
    assert req.get(url + "?instance_id=nmr_ethanol&field=note&x0=1&x1=2").status == 404
    assert req.get(url + "?instance_id=nmr_ethanol&field=spectrum&x0=a&x1=2").status == 400
    assert req.get(url + "?instance_id=not_an_item&field=spectrum&x0=1&x1=2").status == 403


def test_fits_a_phone(server, browser_instance):
    context = browser_instance.new_context(**PIXEL_7)
    page = context.new_page()
    try:
        _login(page, server, "sp_phone")
        problems = layout_problems(page, reachable=["form#peaks", "#next-btn", ".sp-toolbar",
                                                    ".pp-add-btn"])
        page.screenshot(path=os.path.join(SCRATCH, "spectrum_phone.png"), full_page=True)
        assert not problems, problems
        # A tap on the plot picks a peak, as a click does.
        page.locator(".potato-viewer .pv-stage").scroll_into_view_if_needed()
        pt = _at(page, 2.04, 1500)
        page.touchscreen.tap(pt["x"], pt["y"])
        page.wait_for_timeout(400)
        assert [round(i["x"], 2) for i in _selection(page)["items"]] == [2.04]
        assert not page.errors, page.errors
    finally:
        context.close()


def _luminance(css):
    nums = [float(v) for v in css[css.index("(") + 1:-1].split(",")[:3]]

    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in nums)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _rgb(page, colour):
    return page.evaluate("""(c) => { const d = document.createElement('div'); d.style.color = c;
        document.body.appendChild(d); const v = getComputedStyle(d).color; d.remove(); return v; }""", colour)


def test_dark_mode(server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1280, "height": 1000}, color_scheme="dark")
    page = context.new_page()
    try:
        _login(page, server, "sp_dark")
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        layout = page.evaluate("""() => { const fl = document.querySelector('.pv-stage')._fullLayout;
            const d = document.querySelector('.pv-stage')._fullData;
            return {paper: fl.paper_bgcolor, line: d[0].line.color, sugg: d[1].marker.color,
                    font: fl.font.color}; }""")
        card = page.evaluate("getComputedStyle(document.querySelector('.potato-viewer .pv-stage-wrap')).backgroundColor")
        assert _rgb(page, layout["paper"]) == card
        assert _contrast(_rgb(page, layout["line"]), card) > 7
        assert _contrast(_rgb(page, layout["font"]), card) > 7
        assert _contrast(_rgb(page, layout["sugg"]), card) >= 4.5
        # Switching back to light repaints the plot.
        page.evaluate("document.documentElement.dataset.theme = 'light'")
        page.wait_for_timeout(300)
        light = page.evaluate("document.querySelector('.pv-stage')._fullLayout.paper_bgcolor")
        assert _luminance(_rgb(page, light)) > 0.8
        page.evaluate("document.documentElement.dataset.theme = 'dark'")
        page.wait_for_timeout(300)
        page.click(".pp-sugg .pp-accept")
        page.screenshot(path=os.path.join(SCRATCH, "spectrum_dark.png"), full_page=True)
        assert not page.errors, page.errors
    finally:
        context.close()
