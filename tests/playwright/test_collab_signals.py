"""Two members on a time-series item in a live session.

The signal viewer fetches its samples from /api/signals/window, which checked
the annotator's own assignment; in a session the item is the team user's, so a
member's plot stayed empty (403). Here both members' plots draw, an interval
one member drags with the mouse appears on the other's page without a reload,
and showing it sends no save back from the other page.
"""

import json
import os
import shutil

import pytest
import yaml

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SID = "LAB"


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("collab_signals"), "example")
    shutil.copytree(os.path.join(REPO, "examples/advanced/time-series-intervals"), work,
                    ignore=shutil.ignore_patterns("annotation_output", "project.sqlite*"))
    path = os.path.join(work, "config.yaml")
    with open(path) as f:
        config = yaml.safe_load(f)
    config["user_config"] = {"allow_all_users": True, "users": []}
    config["require_password"] = False
    config["collab"] = {"enabled": True, "default_mode": "free", "teams": [
        {"id": "lab", "members": ["ana", "ben"], "leader": "ana", "items": ["psg-01"]}]}
    with open(path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        pytest.fail("could not start the example server")
    yield srv
    srv.stop()


def member(browser, server, name):
    ctx = browser.new_context(base_url=server.base_url, viewport={"width": 1280, "height": 900})
    ctx.request.post(f"{server.base_url}/auth", form={"email": name, "pass": ""})
    page = ctx.new_page()
    signal_status = []
    page.on("response", lambda r: "/api/signals/" in r.url and signal_status.append(r.status))
    saves = []
    page.on("request", lambda r: "/updateinstance" in r.url and saves.append(r.url))
    page.goto(f"/collab/s/{SID}/i/psg-01")
    page.wait_for_function(
        "(() => { const v = document.querySelector('.potato-viewer[data-viewer-kind=\"time_series\"]');"
        " return window.potatoCollabClient && window.potatoCollabClient.state.session"
        " && v && v.getAttribute('data-ts-state') === 'drawn'"
        " && [...document.querySelectorAll('form.interval-label')].every(f => f.getAttribute('data-il-ready')); })()",
        timeout=30000)
    page.wait_for_timeout(400)
    return ctx, page, signal_status, saves


def intervals(page):
    raw = page.eval_on_selector("form.interval-label .interval-label-input", "e => e.value")
    return json.loads(raw)["intervals"] if raw else []


def drag(page, t0, t1, lane):
    pos = page.evaluate("""([t0, t1, lane]) => {
        const p = window.PotatoTimeSeries.get('signal');
        p.u.over.scrollIntoView({block: 'center'});
        const r = p.u.over.getBoundingClientRect();
        const y = r.y + p.u.valToPos(p.laneCentre(p.channelNames().indexOf(lane)), 'y');
        return [r.x + p.u.valToPos(t0, 'x'), r.x + p.u.valToPos(t1, 'x'), y]; }""", [t0, t1, lane])
    x0, x1, y = pos
    page.mouse.move(x0, y)
    page.mouse.down()
    page.mouse.move((x0 + x1) / 2, y, steps=4)
    page.mouse.move(x1, y, steps=4)
    page.mouse.up()


def test_an_interval_drawn_by_one_member_appears_on_the_others_plot(browser_instance, server):
    a_ctx, ana, ana_signals, ana_saves = member(browser_instance, server, "ana")
    b_ctx, ben, ben_signals, _ = member(browser_instance, server, "ben")
    try:
        # Both plots drew from the signal routes.
        assert ana_signals and set(ana_signals) == {200}, ana_signals
        assert ben_signals and set(ben_signals) == {200}, ben_signals

        ben.keyboard.press("2")                                 # spindle
        drag(ben, 5.0, 11.0, "EEG Fpz-Cz")
        assert [iv["label"] for iv in intervals(ben)] == ["spindle"]

        before = len(ana_saves)
        ana.wait_for_function(
            "(() => { const raw = document.querySelector('form.interval-label .interval-label-input').value;"
            " return raw && JSON.parse(raw).intervals.some(i => i.label === 'spindle'); })()",
            timeout=10000)
        iv = intervals(ana)[0]
        assert abs(iv["start"] - 5.0) < 0.15 and abs(iv["end"] - 11.0) < 0.15
        # Listed on ana's page, not only held in her hidden input.
        rows = ana.locator("form.interval-label tr.il-row").all_inner_texts()
        assert any("spindle" in r for r in rows), rows
        ana.wait_for_timeout(1500)
        assert len(ana_saves) == before, "showing ben's interval sent a save from ana's page"
    finally:
        a_ctx.close()
        b_ctx.close()
