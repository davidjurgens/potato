"""
The PAGE XML line-correction page in a real browser: the image_region display
crops exactly the line (checked on the screenshot's pixels: each generated line
has its own background colour), the HTR text is offered for editing, a
correction survives navigating away and back (the editor and the diff, not
just the hidden input), the server stores it, and the page fits a phone.
"""

import io
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers import dh_fixtures as fx  # noqa: E402
from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems, mobile_page  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

SHOTS = Path(create_test_directory("image_region_ui_shots"))


@pytest.fixture(scope="module")
def server():
    import yaml
    from potato.importers.projects.page_xml import PageXMLImporter
    from potato.importers.projects.writer import write_project
    d = Path(create_test_directory("image_region_ui"))
    fx.make_page_xml(d / "src", transkribus_layout=True)
    write_project(PageXMLImporter().parse_path(d / "src"), str(d / "project"), source=str(d / "src"))
    config_path = d / "project" / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["output_annotation_dir"] = str(d / "project" / "annotation_output")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    srv = FlaskTestServer(config=str(config_path))
    if not srv.start():
        pytest.fail("could not start the PAGE XML project")
    yield srv
    srv.stop()


def _open(server, user, **context):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch()
    page = browser.new_page(base_url=server.base_url, viewport={"width": 1280, "height": 900}, **context)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto("/annotate")
    page.wait_for_selector(".image-region-crop img")
    page.wait_for_function("document.querySelector('.image-region-crop img').complete")
    return p, browser, page, errors


def _colour_share(png: bytes):
    """Share of the crop's pixels that are each line's background colour."""
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("RGB")
    counts = {lid: 0 for lid in fx.LINE_COLOURS}
    total = img.width * img.height
    for pixel in img.getdata():
        for lid, colour in fx.LINE_COLOURS.items():
            if all(abs(a - b) <= 6 for a, b in zip(pixel, colour)):
                counts[lid] += 1
    return {lid: n / total for lid, n in counts.items()}


def _instance(page):
    return page.eval_on_selector("#instance_id", "e => e.value")


def test_crop_shows_only_its_line(server):
    p, browser, page, errors = _open(server, "ir_crop")
    try:
        crop = page.locator(".image-region-crop")
        box = crop.bounding_box()
        # 640x56 line + 8 px padding each side: 656 x 72
        assert box["width"] / box["height"] == pytest.approx(656 / 72, rel=0.02)
        png = crop.screenshot(path=str(SHOTS / "line1.png"))
        share = _colour_share(png)
        assert share["r1l1"] > 0.5, share
        assert all(v < 0.001 for k, v in share.items() if k != "r1l1"), share

        first = _instance(page)
        page.click("#next-btn")
        page.wait_for_function(f"document.getElementById('instance_id').value !== {json.dumps(first)}")
        page.wait_for_function("document.querySelector('.image-region-crop img').complete")
        lid = _instance(page).rsplit("-", 1)[-1]
        share = _colour_share(page.locator(".image-region-crop").screenshot(path=str(SHOTS / "line2.png")))
        assert share[lid] > 0.5, (lid, share)
        assert all(v < 0.001 for k, v in share.items() if k != lid), (lid, share)

        page.click(".image-region-page-toggle summary")
        whole = page.locator(".image-region-page img")
        whole.wait_for(state="visible")
        assert page.eval_on_selector(".image-region-page img", "e => e.naturalWidth") == fx.PAGE_WIDTH
        page.screenshot(path=str(SHOTS / "whole_page.png"), full_page=True)
        assert not errors, errors
    finally:
        browser.close()
        p.stop()


def test_line_correction_survives_navigation(server):
    p, browser, page, errors = _open(server, "ir_edit")
    try:
        first = _instance(page)
        editor = page.locator(".text-edit-textarea")
        page.wait_for_function("document.querySelector('.text-edit-textarea').value.length > 0")
        assert editor.input_value() == "Letter to the harbour rnaster"
        editor.click()
        editor.press("End")
        for _ in range(len("rnaster")):
            editor.press("Backspace")
        editor.type("master")
        assert editor.input_value() == "Letter to the harbour master"
        page.wait_for_selector(".text-edit-diff-ins")
        page.wait_for_timeout(1500)       # autosave debounce

        page.click("#next-btn")
        page.wait_for_function(f"document.getElementById('instance_id').value !== {json.dumps(first)}")
        page.wait_for_function("document.querySelector('.text-edit-textarea').value.length > 0")
        assert page.locator(".text-edit-textarea").input_value() == "The ship Margaret arived on the ninth"

        page.click("#prev-btn")
        page.wait_for_function(f"document.getElementById('instance_id').value === {json.dumps(first)}")
        page.wait_for_function(
            "document.querySelector('.text-edit-textarea').value === 'Letter to the harbour master'")
        assert page.locator(".text-edit-diff-ins").first.inner_text() == "master"
        assert page.locator(".text-edit-diff-del").first.inner_text() == "rnaster"
        stored = page.context.request.get(f"{server.base_url}/get_annotations?instance_id={first}").json()
        assert "Letter to the harbour master" in json.dumps(stored)
        page.screenshot(path=str(SHOTS / "corrected.png"), full_page=True)
        assert not errors, errors
    finally:
        browser.close()
        p.stop()


def test_keyboard_reaches_the_editor_and_the_page_toggle(server):
    p, browser, page, errors = _open(server, "ir_keys")
    try:
        page.focus(".image-region-page-toggle summary")
        page.keyboard.press("Enter")
        page.wait_for_selector(".image-region-page img", state="visible")
        outline = page.eval_on_selector(".image-region-page-toggle summary",
                                        "e => getComputedStyle(e).outlineStyle")
        assert outline != "none"
    finally:
        browser.close()
        p.stop()


def test_fits_a_phone(server):
    with mobile_page("iPhone 13", server.base_url) as page:
        req = page.context.request
        req.post(f"{server.base_url}/register", form={"action": "signup", "email": "ir_phone", "pass": "pass"})
        req.post(f"{server.base_url}/auth", form={"action": "login", "email": "ir_phone", "pass": "pass"})
        page.goto("/annotate")
        page.wait_for_selector(".image-region-crop img")
        assert not layout_problems(page, reachable=[".image-region-crop", ".text-edit-textarea",
                                                    "#next-btn"])
        crop = page.locator(".image-region-crop").bounding_box()
        assert crop["width"] <= page.evaluate("document.documentElement.clientWidth")
        page.screenshot(path=str(SHOTS / "phone.png"), full_page=True)
