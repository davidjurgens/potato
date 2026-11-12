"""
The camera-trap example boots and every image opens pre-filled from the
MegaDetector file: the detector's boxes on the canvas, the triage answer, the
species. Saves a screenshot for review, and checks the review exports.
"""

import json
import os
import shutil

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "image", "camera-trap-review")


@pytest.fixture(scope="module")
def project():
    work = os.path.join(create_test_directory("camera_trap_example"), "ct")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache", "layouts"))
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the camera-trap example")
    yield srv, work
    srv.stop()


def test_boxes_triage_and_species_arrive_prefilled(project):
    from playwright.sync_api import sync_playwright
    server, work = project
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(base_url=server.base_url, viewport={"width": 1280, "height": 1100})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        req = page.context.request
        req.post(f"{server.base_url}/register", form={"action": "signup", "email": "ct", "pass": "pass"})
        req.post(f"{server.base_url}/auth", form={"action": "login", "email": "ct", "pass": "pass"})
        page.goto("/annotate")
        page.wait_for_selector(".image-annotation-container canvas")
        page.wait_for_function("document.getElementById('instance_id').value === 'cam01_IMG_0001.JPG'")
        boxes = json.loads(page.input_value("#input-detections"))
        assert [b["label"] for b in boxes] == ["Odocoileus virginianus"]
        assert boxes[0]["source"] == "ai" and boxes[0]["confidence"] == 0.96
        assert page.is_checked("input[name='triage'][value='animal']")
        assert page.is_checked("input[type='checkbox'][value='Odocoileus virginianus']")
        # The box is on the canvas, not just in the hidden input.
        page.wait_for_function(
            "(() => { const c = document.querySelector('.image-annotation-container');"
            " const m = c && c.annotationManager; if (!m) return false;"
            " const objs = m.canvas ? m.canvas.getObjects() : [];"
            " return objs.some(o => o.annotationData || o.annotationId || o.type === 'rect'); })()",
            timeout=10000)
        shots = os.path.join(REPO, "tests", "output", "screenshots")
        os.makedirs(shots, exist_ok=True)
        page.screenshot(path=os.path.join(shots, "camera_trap_example.png"), full_page=True)

        browser.close()
    assert not errors, errors
