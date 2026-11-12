"""A video display whose file will not load must say so.

The video example's clip answered 404 and the item showed an empty player
with no message, so the annotator saw a blank item and nothing to act on.
Runs a copy of ``examples/video/video-annotation`` with item 1 pointed at a
file that is not there and item 2 at a real one.
"""

import json
import os
import shutil

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "video", "video-annotation")


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("video_load_failure"), "video-annotation")
    if os.path.exists(work):
        shutil.rmtree(work)
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns("annotation_output"))
    data = os.path.join(work, "data", "video-as-input.json")
    rows = [json.loads(line) for line in open(data) if line.strip()]
    rows[0]["video"] = "/media/no-such-clip.mp4"
    with open(data, "w") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the example server")
    yield srv
    srv.stop()


def _open(server, p, user):
    browser = p.chromium.launch()
    context = browser.new_context()
    context.request.post(f"{server.base_url}/register", form={"email": user, "pass": "pw"})
    context.request.post(f"{server.base_url}/auth", form={"email": user, "pass": "pw"})
    page = context.new_page()
    page.goto(f"{server.base_url}/annotate")
    return browser, page


def test_a_missing_file_is_reported_with_the_server_answer(server):
    with sync_playwright() as p:
        browser, page = _open(server, p, "video_missing")
        note = page.locator(".display-type-video .video-error")
        note.wait_for(timeout=8000)
        text = note.inner_text()
        hidden = page.locator("video.display-video").get_attribute("hidden")
        browser.close()
    assert "could not be loaded" in text
    assert "404" in text
    assert hidden is not None


def test_a_playable_file_shows_no_error(server):
    with sync_playwright() as p:
        browser, page = _open(server, p, "video_ok")
        page.locator("#next-btn").click()
        page.wait_for_load_state()
        page.wait_for_function(
            "() => { const v = document.querySelector('video.display-video');"
            " return v && v.readyState >= 1; }", timeout=8000)
        count = page.locator(".display-type-video .video-error").count()
        browser.close()
    assert count == 0
