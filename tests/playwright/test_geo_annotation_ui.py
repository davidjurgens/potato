"""
geo_annotation in a real browser, driven with real mouse clicks on the map:

* draw a polygon and a point, label and name them, navigate away and back ->
  both are redrawn (feature list, hidden input, map source, screenshot);
* a freehand outline from a mouse drag;
* classify_region: clicking a region labels it, clicking again clears it, and
  the region list does the same from the keyboard;
* pin: a click places the pin where it was clicked;
* the map keeps arrow keys (Potato's item navigation does not fire);
* the page fits a phone.
"""

import json
import os
import shutil

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems, mobile_page  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIALECT = os.path.join(REPO, "examples", "advanced", "dialect-map")
IMAGES = os.path.join(REPO, "examples", "image", "geo-annotation")
SCRATCH = os.environ.get("GEO_SCREENSHOT_DIR") or create_test_directory("geo_annotation_screens")
IGNORE = shutil.ignore_patterns("annotation_output", "*.sqlite*", ".potato_cache", "layouts")


def _copy(src, name, mutate=None):
    import yaml
    work = os.path.join(create_test_directory(name), "project")
    if os.path.exists(work):
        shutil.rmtree(work)
    shutil.copytree(src, work, ignore=IGNORE)
    if mutate:
        path = os.path.join(work, "config.yaml")
        with open(path) as f:
            config = yaml.safe_load(f)
        mutate(config, work)
        with open(path, "w") as f:
            yaml.safe_dump(config, f, sort_keys=False)
    return work


def _dialect_two_items(config, work):
    with open(os.path.join(work, "data", "dialect-map.json"), "w") as f:
        json.dump([{"id": "map_1", "text": "First map."}, {"id": "map_2", "text": "Second map."}], f)
    draw = config["annotation_schemes"][0]
    draw["tools"] = ["point", "line", "polygon", "freehand"]
    draw["feature_text"] = {"prompt": "Name", "required": False}


@pytest.fixture(scope="module")
def server():
    work = _copy(DIALECT, "geo_annotation_ui", _dialect_two_items)
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the dialect-map project")
    yield srv
    srv.stop()


class Browser:
    def __init__(self, base_url, user, viewport=(1280, 1400)):
        from playwright.sync_api import sync_playwright
        self.p = sync_playwright().start()
        self.browser = self.p.chromium.launch()
        self.page = self.browser.new_page(base_url=base_url,
                                          viewport={"width": viewport[0], "height": viewport[1]})
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text)
                     if m.type == "error" and "[geo]" in m.text else None)
        req = self.page.context.request
        req.post(f"{base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
        req.post(f"{base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
        self.page.goto("/annotate")
        self.wait_ready()

    def wait_ready(self):
        self.page.wait_for_function(
            "[...document.querySelectorAll('form.geo-annotation')].every("
            "f => f.getAttribute('data-geo-ready') === 'true')")
        self.page.wait_for_timeout(300)

    def close(self):
        self.browser.close()
        self.p.stop()

    def px(self, schema, lon, lat):
        """Viewport pixel of a longitude/latitude on a scheme's map."""
        self.page.locator(f"form#{schema} .geo-map").scroll_into_view_if_needed()
        return self.page.evaluate(
            """([schema, lon, lat]) => {
                const st = window.PotatoGeoAnnotation.state(schema);
                const p = st.map.getPixelFromCoordinate(ol.proj.fromLonLat([lon, lat], st.proj));
                const r = st.mapEl.querySelector('.ol-viewport').getBoundingClientRect();
                return [r.left + p[0], r.top + p[1]];
            }""", [schema, lon, lat])

    def click(self, schema, lon, lat):
        x, y = self.px(schema, lon, lat)
        self.page.mouse.click(x, y)
        self.page.wait_for_timeout(350)   # keep clicks apart: two quick ones are a double-click

    def answer(self, schema):
        raw = self.page.eval_on_selector(f"form#{schema} .geo-annotation-input", "e => e.value")
        return json.loads(raw) if raw else None

    def instance(self):
        return self.page.eval_on_selector("#instance_id", "e => e.value")

    def shot(self, name):
        path = os.path.join(SCRATCH, name)
        self.page.screenshot(path=path, full_page=True)
        return path


def _signed_area(ring):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring[:-1], ring[1:])) / 2


def test_polygon_and_point_survive_navigating_away_and_back(server):
    b = Browser(server.base_url, "geo_draw")
    try:
        page = b.page
        form = "form#dialect_areas"
        assert page.get_attribute(form, "data-incomplete-reason")
        page.click(f"{form} .geo-tool[data-tool='polygon']")
        for lon, lat in [(-29.0, -38.3), (-28.2, -38.3), (-28.6, -37.5), (-29.0, -38.3)]:
            b.click("dialect_areas", lon, lat)
        page.wait_for_selector(f"{form} .geo-feature")
        page.select_option(f"{form} .geo-feature[data-feature-id='f1'] .geo-feature-label", "Very different")
        page.fill(f"{form} .geo-feature[data-feature-id='f1'] .geo-feature-text", "Coast talk")
        page.click(f"{form} .geo-tool[data-tool='point']")
        b.click("dialect_areas", -26.0, -37.0)
        page.wait_for_function(f"document.querySelectorAll('{form} .geo-feature').length === 2")

        answer = b.answer("dialect_areas")
        poly, point = answer["features"]
        assert poly["geometry"]["type"] == "Polygon" and point["geometry"]["type"] == "Point"
        ring = poly["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1] and len(ring) == 4
        assert _signed_area(ring) > 0, "exterior ring must be counter-clockwise (RFC 7946)"
        for lon, lat in ring:
            assert -29.1 < lon < -28.1 and -38.4 < lat < -37.4   # [lon, lat], where it was clicked
        assert abs(point["geometry"]["coordinates"][0] + 26.0) < 0.05
        assert abs(point["geometry"]["coordinates"][1] + 37.0) < 0.05
        assert poly["properties"]["label"] == "Very different" and poly["properties"]["text"] == "Coast talk"
        assert point["properties"]["label"] == "A little different"
        assert page.get_attribute(form, "data-incomplete-reason") is None
        b.shot("geo_draw_before.png")
        page.wait_for_timeout(1500)   # autosave debounce

        page.click("#next-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'map_2'")
        b.wait_ready()
        assert page.locator(f"{form} .geo-feature").count() == 0
        assert b.answer("dialect_areas") is None
        page.click("#prev-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'map_1'")
        b.wait_ready()

        rows = page.locator(f"{form} .geo-feature")
        assert rows.count() == 2
        assert page.input_value(f"{form} .geo-feature[data-feature-id='f1'] .geo-feature-label") == "Very different"
        assert page.input_value(f"{form} .geo-feature[data-feature-id='f1'] .geo-feature-text") == "Coast talk"
        assert page.input_value(f"{form} .geo-feature[data-feature-id='f2'] .geo-feature-label") == "A little different"
        on_map = page.evaluate("""() => window.PotatoGeoAnnotation.state('dialect_areas').source
            .getFeatures().map(f => f.getGeometry().getType()).sort()""")
        assert on_map == ["Point", "Polygon"]
        restored = b.answer("dialect_areas")
        assert restored["features"][0]["geometry"] == poly["geometry"]
        assert page.get_attribute(f"{form} .geo-annotation-input", "data-server-set") == "true"
        b.shot("geo_draw_after.png")
        assert not b.errors, b.errors
    finally:
        b.close()


def test_freehand_drag_draws_an_outline(server):
    import math
    b = Browser(server.base_url, "geo_freehand")
    try:
        page = b.page
        page.click("form#dialect_areas .geo-tool[data-tool='freehand']")
        pts = [b.px("dialect_areas", -28.6 + 0.5 * math.cos(t / 20 * 2 * math.pi),
                    -37.9 + 0.4 * math.sin(t / 20 * 2 * math.pi)) for t in range(21)]
        page.mouse.move(*pts[0])
        page.mouse.down()
        for x, y in pts[1:]:
            page.mouse.move(x, y, steps=2)
        page.mouse.up()
        page.wait_for_selector("form#dialect_areas .geo-feature")
        feat = b.answer("dialect_areas")["features"][0]
        assert feat["properties"]["tool"] == "freehand"
        ring = feat["geometry"]["coordinates"][0]
        assert len(ring) >= 12 and ring[0] == ring[-1] and _signed_area(ring) > 0
        assert not b.errors, b.errors
    finally:
        b.close()


def test_classify_region_by_click_and_by_list(server):
    b = Browser(server.base_url, "geo_regions")
    try:
        page = b.page
        form = "form#province_speech"
        page.click(f"{form} .geo-assign[data-label='Sounds different']")
        b.click("province_speech", -28.6, -37.9)   # inside Middlemarch
        ans = b.answer("province_speech")
        assert [(f["properties"]["region"], f["properties"]["label"]) for f in ans["features"]] == \
            [("middlemarch", "Sounds different")]
        assert ans["features"][0]["geometry"] is None
        assert page.input_value(f"{form} .geo-feature[data-feature-id='middlemarch'] select") == "Sounds different"
        b.shot("geo_regions.png")
        b.click("province_speech", -28.6, -37.9)   # same label again: cleared
        assert b.answer("province_speech") is None
        # Keyboard route: the region list.
        sel = f"{form} .geo-feature[data-feature-id='westfold'] select"
        page.focus(sel)
        page.select_option(sel, "Sounds like home")
        ans = b.answer("province_speech")
        assert ans["features"][0]["properties"] == {"region": "westfold", "region_name": "Westfold",
                                                    "label": "Sounds like home"}
        assert not b.errors, b.errors
    finally:
        b.close()


def test_pin_goes_where_it_was_clicked(server):
    b = Browser(server.base_url, "geo_pin")
    try:
        page = b.page
        b.click("home", -27.5, -38.9)
        ans = b.answer("home")
        lon, lat = ans["features"][0]["geometry"]["coordinates"]
        assert abs(lon + 27.5) < 0.05 and abs(lat + 38.9) < 0.05
        assert ans["features"][0]["properties"]["label"] == "Where you grew up"
        assert "Not placed" not in page.inner_text("form#home .geo-features")
        assert page.get_attribute("form#home", "data-incomplete-reason") is None
        assert not b.errors, b.errors
    finally:
        b.close()


def test_map_keys_pan_without_changing_item(server):
    b = Browser(server.base_url, "geo_keys")
    try:
        page = b.page
        before = page.evaluate("() => window.PotatoGeoAnnotation.state('dialect_areas').map.getView().getCenter()")
        page.focus("form#dialect_areas .geo-map")
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(600)
        after = page.evaluate("() => window.PotatoGeoAnnotation.state('dialect_areas').map.getView().getCenter()")
        assert after[0] > before[0], "ArrowRight should pan the map east"
        assert b.instance() == "map_1", "ArrowRight on the map must not move to the next item"
        # Keyboard-only point: Tab to the button and press Enter.
        page.focus("form#dialect_areas .geo-add-centre")
        page.keyboard.press("Enter")
        page.wait_for_selector("form#dialect_areas .geo-feature")
        assert b.answer("dialect_areas")["features"][0]["geometry"]["type"] == "Point"
        page.focus("form#dialect_areas .geo-feature .geo-delete")
        page.keyboard.press("Enter")
        page.wait_for_function("!document.querySelector('form#dialect_areas .geo-feature')")
        assert not b.errors, b.errors
    finally:
        b.close()


def test_fits_a_phone(server):
    with mobile_page("iPhone 13", server.base_url) as page:
        req = page.context.request
        req.post(f"{server.base_url}/register", form={"action": "signup", "email": "geo_phone", "pass": "pass"})
        req.post(f"{server.base_url}/auth", form={"action": "login", "email": "geo_phone", "pass": "pass"})
        page.goto("/annotate")
        page.wait_for_selector("form#dialect_areas[data-geo-ready='true']")
        page.wait_for_selector("form#province_speech .geo-region-label")
        problems = layout_problems(page, reachable=[
            "form#dialect_areas .geo-map", "form#dialect_areas .geo-tool[data-tool='polygon']",
            "form#dialect_areas .geo-current-label", "form#home .geo-place",
            "form#province_speech .geo-region-label"])
        page.screenshot(path=os.path.join(SCRATCH, "geo_phone.png"), full_page=True)
        assert not problems, problems
        # A tap places the pin, the same as a click.
        page.locator("form#home .geo-map").scroll_into_view_if_needed()
        x, y = page.evaluate("""() => {
            const st = window.PotatoGeoAnnotation.state('home');
            const p = st.map.getPixelFromCoordinate(ol.proj.fromLonLat([-28.6, -37.9], st.proj));
            const r = st.mapEl.querySelector('.ol-viewport').getBoundingClientRect();
            return [r.left + p[0], r.top + p[1]];
        }""")
        page.touchscreen.tap(x, y)
        page.wait_for_function("!!document.querySelector('form#home .geo-annotation-input').value")
        lon, lat = json.loads(page.eval_on_selector("form#home .geo-annotation-input", "e => e.value")) \
            ["features"][0]["geometry"]["coordinates"]
        assert abs(lon + 28.6) < 0.1 and abs(lat + 37.9) < 0.1
