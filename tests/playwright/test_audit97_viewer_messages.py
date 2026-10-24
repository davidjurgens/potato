"""
Audit 97, in a real browser: a refused per-item file is said on the page.

V9  genome_locus: an item whose `bam` field is /etc/hosts or javascript:...
    used to drop the Reads track with no message (or a status line the next
    click replaced). The page now names the track and the reason, and asks for
    nothing outside the server.
V7  geo_annotation: an item whose basemap names external tiles without
    attribution used to load them. The map area now says why it is not shown,
    and the browser asks evil.example for nothing.
"""

import json
import os
import shutil
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VARIANTS = os.path.join(REPO, "examples", "advanced", "variant-review")
DIALECT = os.path.join(REPO, "examples", "advanced", "dialect-map")
IGNORE = shutil.ignore_patterns("annotation_output", "*.sqlite*", ".potato_cache", "layouts")


def _copy(src, name):
    work = os.path.join(create_test_directory(name), "project")
    shutil.copytree(src, work, ignore=IGNORE)
    return work


def _open(server, user, ready):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch()
    page = browser.new_page(base_url=server.base_url, viewport={"width": 1280, "height": 1100})
    page.requests = []
    page.on("request", lambda r: page.requests.append(r.url))
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto("/annotate")
    page.wait_for_function(ready, timeout=30000)
    return p, browser, page


class TestGenomeTrackRefusals:

    @pytest.fixture(scope="class")
    def server(self):
        work = _copy(VARIANTS, "audit97_genome_bam")
        path = os.path.join(work, "data", "calls.json")
        with open(path) as f:
            items = json.load(f)[:2]
        items[0]["bam"] = "/etc/hosts"
        items[1]["bam"] = "javascript:alert(1)"
        with open(path, "w") as f:
            json.dump(items, f)
        srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"), port=9763)
        if not srv.start():
            pytest.fail("could not start the variant-review copy")
        yield srv
        srv.stop()

    def test_a_refused_bam_is_named_and_stays_on_screen(self, server):
        ready = "document.querySelector('.potato-viewer').getAttribute('data-viewer-state') === 'ready'"
        p, browser, page = _open(server, "bam_refused", ready)
        try:
            note = page.locator(".pv-track-note")
            note.wait_for(timeout=15000)
            text = note.text_content()
            assert 'Track "Reads (sample1)" is not shown' in text
            assert "/etc/hosts" in text and "outside the media directory" in text
            assert note.get_attribute("role") == "alert" and note.is_visible()
            # The other tracks still load; nothing asks for /etc/hosts.
            assert not any(urlparse(u).path.startswith("/etc/") for u in page.requests)
            page.click("form#call_review label:has-text('Artifact')")
            page.wait_for_timeout(1600)       # autosave debounce
            page.click("#next-btn")
            page.wait_for_function("document.getElementById('instance_id').value === 'call_2'")
            page.wait_for_function(
                "(document.querySelector('.pv-track-note') || {}).textContent"
                " && document.querySelector('.pv-track-note').textContent.includes('javascript:')",
                timeout=30000)
            assert "is not a file path" in page.locator(".pv-track-note").text_content()
        finally:
            browser.close()
            p.stop()


class TestGeoItemBasemapRefusal:

    @pytest.fixture(scope="class")
    def server(self):
        import yaml
        work = _copy(DIALECT, "audit97_geo_basemap")
        config_path = os.path.join(work, "config.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config["annotation_schemes"] = [dict(config["annotation_schemes"][1], basemap_field="map")]
        with open(config_path, "w") as f:
            yaml.safe_dump(config, f, sort_keys=False)
        with open(os.path.join(work, "data", "dialect-map.json"), "w") as f:
            json.dump([{"id": "evil", "text": "An item with its own tiles.",
                        "map": {"tiles": "https://evil.example/{z}/{x}/{y}.png"}}], f)
        srv = FlaskTestServer(config_file=config_path, port=9764)
        if not srv.start():
            pytest.fail("could not start the dialect-map copy")
        yield srv
        srv.stop()

    def test_the_map_says_why_and_loads_nothing_external(self, server):
        p, browser, page = _open(server, "geo_refused", "!!document.querySelector('.geo-error')")
        try:
            error = page.locator(".geo-error")
            assert error.is_visible() and error.get_attribute("role") == "alert"
            text = error.text_content()
            assert "not loaded" in text and "attribution" in text
            page.wait_for_timeout(500)
            assert not any("evil.example" in u for u in page.requests), page.requests
        finally:
            browser.close()
            p.stop()
