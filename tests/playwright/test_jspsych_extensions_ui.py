"""A jsPsych phase with the mouse-tracking extension, in a real browser:
the extension loads under the page's CSP, records the pointer during a
trial, and its samples reach the stored run."""

import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    create_test_config, create_test_data_file, create_test_directory)

pytestmark = pytest.mark.playwright

TIMELINE = """window.potatoTimeline = [{
  type: jsPsychHtmlButtonResponse,
  stimulus: '<p id="stim">Click a button</p>',
  choices: ['Left', 'Right'],
  extensions: [{type: jsPsychExtensionMouseTracking, params: {targets: ['#stim']}}]
}];
"""


@pytest.fixture(scope="module")
def server():
    d = create_test_directory("jspsych_mouse_tracking_ui")
    data = create_test_data_file(d, [{"id": "1", "text": "hello"}])
    with open(os.path.join(d, "task.js"), "w") as f:
        f.write(TIMELINE)
    config = create_test_config(
        d, annotation_schemes=[{"name": "r", "annotation_type": "radio", "labels": ["a", "b"],
                                "description": "R"}],
        data_files=[data],
        phases={"order": ["task", "annotation"],
                "task": {"type": "jspsych", "timeline": os.path.join(d, "task.js"),
                         "plugins": ["html-button-response"], "extensions": ["mouse-tracking"]}})
    srv = FlaskTestServer(config=config)
    if not srv.start():
        pytest.fail("could not start")
    yield srv
    srv.stop()


def test_mouse_samples_are_stored(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(base_url=server.base_url)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        req = page.context.request
        req.post(f"{server.base_url}/register", form={"action": "signup", "email": "mt", "pass": "pass"})
        req.post(f"{server.base_url}/auth", form={"action": "login", "email": "mt", "pass": "pass"})
        page.goto("/")
        page.wait_for_selector("#stim")
        for x, y in ((100, 100), (220, 160), (340, 220), (300, 260)):
            page.mouse.move(x, y, steps=5)
            page.wait_for_timeout(60)
        page.get_by_role("button", name="Left").click()
        page.wait_for_selector('[data-schema-name="r"]', timeout=10000)
        browser.close()
    assert not errors, errors
    from potato.flask_server import config as live
    from potato.runtimes import store
    runs = [r for r in store.list_runs(live["task_dir"], live["annotation_task_name"], with_data=True)
            if r["user_id"] == "mt"]
    trial = runs[-1]["trials"][0]
    assert runs[-1]["status"] == "complete"
    assert len(trial["mouse_tracking_data"]) >= 3 and "#stim" in trial["mouse_tracking_targets"]
