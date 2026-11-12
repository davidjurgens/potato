"""
time_series display + interval_label scheme in a real browser.

Runs the examples/advanced/time-series-intervals example:

* the plot draws from decimated windows (the page never fetches the file);
* the EDF+ file's "Arousal" annotation appears as a pending pre-annotation;
* a real mouse drag labels an interval on all channels, and with "the
  channel I drag on" on one channel; a click marks a point event; Delete
  removes a selected entry; the [ / ] keys move the window;
* navigating away (#next-btn) and back (#prev-btn) redraws the overlays,
  the list and the canvas tint, and the server holds the same JSON;
* epoch mode (config-epochs.yaml): the hypnogram from the file is cut into
  30 s epochs, a stage key labels the epoch and moves on, the overview strip
  shows the labelled epochs, and the answer survives navigation;
* the signal routes refuse anonymous and unassigned requests;
* the phone layout and dark mode.
"""

import json
import os
import shutil

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "time-series-intervals")
SCRATCH = os.environ.get("POTATO_SCREENSHOT_DIR") or create_test_directory("time_series_screens")

IPHONE_13 = {
    "viewport": {"width": 390, "height": 664}, "device_scale_factor": 3,
    "is_mobile": True, "has_touch": True,
    "user_agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 "
                   "(KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"),
}


def _start(config_name, tag):
    work = os.path.join(create_test_directory("time_series_ui"), tag)
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output*", "*.sqlite*", ".potato_cache", "__pycache__"))
    srv = FlaskTestServer(config_file=os.path.join(work, config_name))
    if not srv.start():
        pytest.fail(f"could not start the time-series-intervals example ({config_name})")
    return srv


@pytest.fixture(scope="module")
def free_server():
    srv = _start("config.yaml", "free")
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def epoch_server():
    srv = _start("config-epochs.yaml", "epochs")
    yield srv
    srv.stop()


def _login(page, server, user):
    page.errors = []
    page.requests = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
    page.on("request", lambda r: page.requests.append(r.url))
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto(f"{server.base_url}/annotate")
    _ready(page)


def _ready(page):
    page.wait_for_function(
        "(() => { const v = document.querySelector('.potato-viewer[data-viewer-kind=\"time_series\"]');"
        " return v && v.getAttribute('data-viewer-state') === 'ready' && v.getAttribute('data-ts-state') === 'drawn'"
        " && [...document.querySelectorAll('form.interval-label')].every(f => f.getAttribute('data-il-ready')); })()",
        timeout=30000)
    page.wait_for_timeout(400)      # pre-annotations arrive after the plot


def _answer(page, schema):
    raw = page.eval_on_selector(f"form.interval-label[data-schema-name='{schema}'] .interval-label-input",
                                "e => e.value")
    return json.loads(raw) if raw else None


def _server_answer(page, server, iid, schema):
    r = page.context.request.get(f"{server.base_url}/get_annotations?instance_id={iid}")
    vals = r.json().get("label_values", {}).get(schema, {})
    raw = vals.get(schema)
    return json.loads(raw) if raw else None


def _plot_box(page):
    return page.eval_on_selector(".potato-viewer[data-viewer-kind='time_series'] .u-over",
                                 "e => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")


def _lane_y(page, name):
    """Page y of a lane's centre."""
    return page.evaluate(f"""() => {{
        const p = window.PotatoTimeSeries.get('signal');
        // Mouse coordinates are viewport coordinates: bring the plot into view first.
        p.u.over.scrollIntoView({{block: 'center'}});
        const i = p.channelNames().indexOf({json.dumps(name)});
        const r = p.u.over.getBoundingClientRect();
        return r.y + p.u.valToPos(p.laneCentre(i), 'y'); }}""")


def _x_at(page, t):
    return page.evaluate(f"""() => {{
        const p = window.PotatoTimeSeries.get('signal');
        return p.u.over.getBoundingClientRect().x + p.u.valToPos({t}, 'x'); }}""")


def _drag(page, t0, t1, y):
    page.mouse.move(_x_at(page, t0), y)
    page.mouse.down()
    page.mouse.move(_x_at(page, (t0 + t1) / 2), y, steps=4)
    page.mouse.move(_x_at(page, t1), y, steps=4)
    page.mouse.up()
    page.wait_for_timeout(150)


def _view(page):
    return page.get_attribute(".potato-viewer[data-viewer-kind='time_series']", "data-ts-view")


def _rows(page, schema):
    return page.eval_on_selector_all(
        f"form.interval-label[data-schema-name='{schema}'] .il-list tbody tr",
        "rows => rows.map(r => [...r.cells].slice(0, 3).map(c => c.textContent.trim()))")


def _tint(page, t, lane):
    """The canvas colour at time t in the middle of a lane, as (r, g, b)."""
    return page.evaluate(f"""() => {{
        const p = window.PotatoTimeSeries.get('signal');
        const dpr = window.devicePixelRatio || 1;
        const i = p.channelNames().indexOf({json.dumps(lane)});
        const x = p.u.valToPos({t}, 'x', true);
        const y = p.u.valToPos(p.laneCentre(i) + 0.42, 'y', true);
        const d = p.u.ctx.getImageData(Math.round(x), Math.round(y), 1, 1).data;
        return [d[0], d[1], d[2]]; }}""")


# ---------------------------------------------------------------------------


def test_brush_click_keys_and_persistence(free_server, page):
    _login(page, free_server, "ts_free")
    assert _view(page) == "0.000-30.000"
    # Only decimated windows were fetched, never the EDF file itself.
    assert any("/api/signals/window" in u for u in page.requests)
    assert not any(u.endswith(".edf") for u in page.requests), page.requests
    # The file's Arousal (mapped to "arousal") waits as a pre-annotation.
    assert page.is_visible("form.interval-label .il-pre")
    assert _answer(page, "segments") is None
    assert _rows(page, "segments") == [["3:20.5", "arousal (event) · from file", "all"]]

    eeg_y = _lane_y(page, "EEG Fpz-Cz")
    background = _tint(page, 8.0, "EEG Fpz-Cz")
    page.keyboard.press("2")                                   # spindle
    _drag(page, 5.0, 11.0, eeg_y)
    a = _answer(page, "segments")
    assert len(a["intervals"]) == 1 and a["events"][0]["label"] == "arousal"
    iv = a["intervals"][0]
    assert iv["label"] == "spindle" and iv["channel"] is None
    assert abs(iv["start"] - 5.0) < 0.15 and abs(iv["end"] - 11.0) < 0.15
    assert not page.is_visible("form.interval-label .il-pre")    # first change saved the file's too
    assert _tint(page, 8.0, "EEG Fpz-Cz") != background         # the lane is tinted now

    # One channel: the EOG lane, with "the channel I drag on".
    page.check("form.interval-label .il-scope input[value='channel']")
    page.keyboard.press("1")                                   # artefact
    _drag(page, 12.0, 14.0, _lane_y(page, "EOG"))
    a = _answer(page, "segments")
    eog = [x for x in a["intervals"] if x["label"] == "artefact"]
    assert len(eog) == 1 and eog[0]["channel"] == "EOG"

    # A click with an event label marks a point on the channel clicked.
    page.keyboard.press("4")
    page.mouse.click(_x_at(page, 20.0), _lane_y(page, "EMG chin"))
    page.wait_for_timeout(150)
    ev = [e for e in _answer(page, "segments")["events"] if e.get("source") != "file"]
    assert len(ev) == 1 and abs(ev[0]["time"] - 20.0) < 0.1 and ev[0]["channel"] == "EMG chin"

    # With an interval label picked, a click selects what is under it; Delete removes it.
    page.keyboard.press("1")
    page.mouse.click(_x_at(page, 13.0), _lane_y(page, "EOG"))
    page.keyboard.press("Delete")
    page.wait_for_timeout(150)
    assert not [x for x in _answer(page, "segments")["intervals"] if x["label"] == "artefact"]

    # ] moves one window; [ moves back.
    page.keyboard.press("]")
    page.wait_for_function("document.querySelector('.potato-viewer').getAttribute('data-ts-view') === '30.000-60.000'")
    page.keyboard.press("[")
    page.wait_for_function("document.querySelector('.potato-viewer').getAttribute('data-ts-view') === '0.000-30.000'")
    saved = _answer(page, "segments")

    # Away and back.
    page.click("#next-btn")
    page.wait_for_function("document.getElementById('instance_id').value === 'accel-01'")
    _ready(page)
    # The accelerometer item's BIDS events.tsv is its pre-annotation.
    assert _rows(page, "segments") == [["0:40.0–1:20.0", "walking · from file", "all"]]
    page.click("#prev-btn")
    page.wait_for_function("document.getElementById('instance_id').value === 'psg-01'")
    _ready(page)
    assert _answer(page, "segments") == saved
    assert not page.is_visible("form.interval-label .il-pre")
    rows = _rows(page, "segments")
    assert [r[1] for r in rows] == ["spindle", "arousal (event)", "arousal (event) · from file"]
    assert page.evaluate("window.PotatoTimeSeries.get('signal').overlays.intervals.length") == 1
    assert _tint(page, 8.0, "EEG Fpz-Cz") != background
    assert _server_answer(page, free_server, "psg-01", "segments") == saved
    page.screenshot(path=os.path.join(SCRATCH, "time_series_free.png"), full_page=True)
    assert not page.errors, page.errors


def test_epoch_keys_overview_and_persistence(epoch_server, page):
    _login(page, epoch_server, "ts_epochs")
    form = "form.interval-label[data-schema-name='stage']"
    # The hypnogram (W 0-60, N1, N2 90-180, N3 180-270, N2) is cut into 10 epochs.
    assert "10 annotations from the file" in page.text_content(f"{form} .il-pre-text")
    assert "Epoch 1 of 10" in page.text_content(f"{form} .il-epoch-text")
    assert page.get_attribute(f"{form} .il-label[data-label='W']", "aria-pressed") == "true"
    assert page.is_hidden(".ts-zoom-in")                       # fixed windows in epoch mode

    page.keyboard.press("3")                                   # epoch 1 -> N2, advance
    page.wait_for_function("document.querySelector('.potato-viewer').getAttribute('data-ts-view') === '30.000-60.000'")
    a = _answer(page, "stage")
    first = [x for x in a["intervals"] if x["start"] == 0.0]
    assert first == [{"start": 0.0, "end": 30.0, "label": "N2", "channel": None}]
    assert len(a["intervals"]) == 10
    assert "Epoch 2 of 10" in page.text_content(f"{form} .il-epoch-text")
    page.keyboard.press("PageDown")
    page.wait_for_function("document.querySelector('.potato-viewer').getAttribute('data-ts-view') === '60.000-90.000'")
    page.keyboard.press("5")                                   # epoch 3 -> REM, advance
    page.wait_for_function("document.querySelector('.potato-viewer').getAttribute('data-ts-view') === '90.000-120.000'")
    labels = [x["label"] for x in _answer(page, "stage")["intervals"]]
    assert labels == ["N2", "W", "REM", "N2", "N2", "N2", "N3", "N3", "N3", "N2"]
    assert page.evaluate("window.PotatoTimeSeries.get('signal').marks.length") == 10
    assert page.get_attribute(form, "data-incomplete-reason") is None

    # Clear epoch 4: the scheme now says what is missing.
    page.click(f"{form} .il-clear-epoch")
    assert "1 of 10 unlabelled" in page.get_attribute(form, "data-incomplete-reason")
    page.keyboard.press("2")                                   # epoch 4 -> N1, advance
    page.wait_for_function("document.querySelector('.potato-viewer').getAttribute('data-ts-view') === '120.000-150.000'")
    assert page.get_attribute(form, "data-incomplete-reason") is None

    # The arousal scheme on the same plot: pick it, click inside the epoch.
    page.keyboard.press("a")
    eeg_y = _lane_y(page, "EEG Fpz-Cz")
    page.mouse.click(_x_at(page, 130.0), eeg_y)
    page.wait_for_timeout(150)
    ar = _answer(page, "arousals")
    assert len(ar["events"]) == 1 and abs(ar["events"][0]["time"] - 130.0) < 0.1
    saved_stage, saved_ar = _answer(page, "stage"), _answer(page, "arousals")
    # Overlays from both schemes coexist.
    assert page.evaluate("window.PotatoTimeSeries.get('signal').overlays.events.length") == 1

    page.click("#next-btn")
    page.wait_for_function("document.getElementById('instance_id').value === 'psg-02'")
    _ready(page)
    page.click("#prev-btn")
    page.wait_for_function("document.getElementById('instance_id').value === 'psg-01'")
    _ready(page)
    assert _answer(page, "stage") == saved_stage
    assert _answer(page, "arousals") == saved_ar
    assert not page.is_visible(f"{form} .il-pre")
    assert page.evaluate("window.PotatoTimeSeries.get('signal').marks.length") == 11   # 10 epochs + 1 event
    assert page.get_attribute(f"{form} .il-label[data-label='N2']", "aria-pressed") == "true"   # epoch 1
    assert _server_answer(page, epoch_server, "psg-01", "stage") == saved_stage
    # Clicking the overview strip jumps to that epoch.
    box = page.eval_on_selector(".ts-overview", "e => { e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
    page.mouse.click(box[0] + box[2] * 0.95, box[1] + box[3] / 2)
    page.wait_for_function("document.querySelector('.potato-viewer').getAttribute('data-ts-view') === '270.000-300.000'")
    page.screenshot(path=os.path.join(SCRATCH, "time_series_epochs.png"), full_page=True)
    assert not page.errors, page.errors


def test_signal_routes_refuse_strangers(free_server, page):
    req = page.context.request
    base = free_server.base_url
    r = req.get(f"{base}/api/signals/window?instance_id=psg-01&field=signal&start=0&end=10&px=100")
    assert r.status == 401
    req.post(f"{base}/register", form={"action": "signup", "email": "ts_routes", "pass": "pass"})
    req.post(f"{base}/auth", form={"action": "login", "email": "ts_routes", "pass": "pass"})
    page.goto(f"{base}/annotate")
    _ready(page)
    ok = req.get(f"{base}/api/signals/window?instance_id=psg-01&field=signal&start=0&end=300&px=200")
    assert ok.status == 200
    body = ok.json()
    eeg = body["channels"][0]
    assert eeg["name"] == "EEG Fpz-Cz" and len(eeg["t"]) <= 200 and "lo" in eeg
    assert set(body["ranges"]) == {"EEG Fpz-Cz", "EOG", "EMG chin", "Resp"}
    # A field that is not a time_series display, and an unknown item.
    assert req.get(f"{base}/api/signals/window?instance_id=psg-01&field=note").status == 404
    assert req.get(f"{base}/api/signals/window?instance_id=nope&field=signal").status in (403, 404)
    assert req.get(f"{base}/api/signals/window?instance_id=psg-01&field=signal&start=5&end=1").status == 400


def test_phone_layout_and_dark_mode(epoch_server, browser_instance):
    ctx = browser_instance.new_context(**IPHONE_13, color_scheme="dark")
    try:
        page = ctx.new_page()
        _login(page, epoch_server, "ts_phone")
        problems = layout_problems(page, reachable=[
            ".ts-toolbar .ts-next", "form.interval-label .il-label[data-label='W']",
            "form.interval-label .il-step[data-step='1']", "#next-btn"])
        page.screenshot(path=os.path.join(SCRATCH, "time_series_phone_dark.png"), full_page=True)
        assert not problems, problems
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        # The plot fits the phone and the labels are tappable.
        width = page.eval_on_selector(".potato-viewer .uplot", "e => e.getBoundingClientRect().width")
        assert width <= 390
        page.tap("form.interval-label[data-schema-name='stage'] .il-label[data-label='N3']")
        page.wait_for_timeout(200)
        assert _answer(page, "stage")["intervals"][0]["label"] == "N3"
        assert not page.errors, page.errors
    finally:
        ctx.close()
