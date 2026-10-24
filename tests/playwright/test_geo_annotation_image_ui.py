"""
geo_annotation over georeferenced images taken from an item field, with
suggested features (preannotation_field) that are not an answer until the
annotator accepts or edits them. A separate module from
test_geo_annotation_ui.py so the two servers never run at once.
"""

import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.playwright.test_geo_annotation_ui import IMAGES, Browser, _copy  # noqa: E402

pytestmark = pytest.mark.playwright


@pytest.fixture(scope="module")
def image_server():
    work = _copy(IMAGES, "geo_annotation_images")
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the geo-annotation image project")
    yield srv
    srv.stop()


def test_image_basemap_and_suggestions(image_server):
    b = Browser(image_server.base_url, "geo_images")
    try:
        page = b.page
        form = "form#land_cover"
        # The image layer is the item's own PNG, placed at the item's extent.
        src = page.evaluate("""() => {
            const st = window.PotatoGeoAnnotation.state('land_cover');
            const layer = st.map.getLayers().getArray().find(l => l instanceof ol.layer.Image);
            return layer && layer.getSource().getUrl();
        }""")
        assert src == "/media/tile_a.png"
        assert "(suggested)" in page.inner_text(f"{form} .geo-features")
        # Suggestions are not an answer until accepted.
        assert b.answer("land_cover") is None or \
            page.get_attribute(f"{form} .geo-annotation-input", "data-modified") is None
        assert "suggested" in (page.get_attribute(form, "data-incomplete-reason") or "")
        b.shot("geo_image_suggested.png")
        page.click(f"{form} .geo-accept")
        ans = b.answer("land_cover")
        assert ans["features"][0]["properties"]["source"] == "preannotation"
        assert ans["features"][0]["properties"]["label"] == "Built-up"
        assert page.get_attribute(form, "data-incomplete-reason") is None
        page.wait_for_timeout(1500)
        page.click("#next-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'tile_b'")
        b.wait_ready()
        src = page.evaluate("""() => window.PotatoGeoAnnotation.state('land_cover').map.getLayers().getArray()
            .find(l => l instanceof ol.layer.Image).getSource().getUrl()""")
        assert src == "/media/tile_b.png"
        assert page.locator(f"{form} .geo-feature").count() == 0
        assert not b.errors, b.errors
    finally:
        b.close()
