"""
geo_annotation on a phase page (a prestudy survey), which renders through
get_current_page_html rather than the annotation page: the map loads, a pin
click is saved, and it is back after a reload.
"""

import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.playwright.test_geo_annotation_ui import DIALECT, Browser, _copy  # noqa: E402

pytestmark = pytest.mark.playwright


def _with_survey(config, work):
    os.makedirs(os.path.join(work, "surveys"), exist_ok=True)
    pin = next(s for s in config["annotation_schemes"] if s["name"] == "home")
    with open(os.path.join(work, "surveys", "home.json"), "w") as f:
        json.dump([dict(pin, name="birthplace")], f)
    config["phases"] = {"order": ["about_you", "annotation"],
                        "about_you": {"type": "prestudy", "file": "surveys/home.json"},
                        "annotation": {"type": "annotation"}}


@pytest.fixture(scope="module")
def server():
    work = _copy(DIALECT, "geo_annotation_phase", _with_survey)
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the phase-page project")
    yield srv
    srv.stop()


def test_pin_on_a_survey_page_saves_and_restores(server):
    b = Browser(server.base_url, "geo_phase")
    try:
        page = b.page
        assert page.evaluate("window.config.is_annotation_page") is False
        assert page.locator("form#birthplace").count() == 1
        b.click("birthplace", -28.6, -37.9)
        ans = b.answer("birthplace")
        lon, lat = ans["features"][0]["geometry"]["coordinates"]
        assert abs(lon + 28.6) < 0.05 and abs(lat + 37.9) < 0.05
        page.wait_for_timeout(1600)
        page.reload()
        b.wait_ready()
        restored = b.answer("birthplace")
        assert restored and restored["features"][0]["geometry"]["coordinates"] == [lon, lat]
        assert "Not placed" not in page.inner_text("form#birthplace .geo-features")
        b.shot("geo_phase_page.png")
        page.click("#next-btn")
        page.wait_for_selector("form#dialect_areas[data-geo-ready='true']")
        assert not b.errors, b.errors
    finally:
        b.close()
