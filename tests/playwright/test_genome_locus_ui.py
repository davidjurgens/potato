"""
genome_locus in a real browser, on the variant-review example: igv.js loads
the synthetic FASTA + .fai, the bgzipped VCF + .tbi, the BAM + .bai and the
BED from /media with range requests and nothing from the internet; the locus
opens where the item says; clicking the call selects it; and the radio answer
and the selection survive navigating away and back. Plus the phone layout.
"""

import json
import os
import shutil
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems, mobile_page  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "variant-review")
SCRATCH = os.environ.get("POTATO_SCREENSHOT_DIR") or create_test_directory("genome_locus_screens")

READY = "document.querySelector('.potato-viewer').getAttribute('data-viewer-state') === 'ready'"


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("genome_locus_ui"), "variants")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache"))
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the variant-review example")
    yield srv
    srv.stop()


def _open(server, user):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch()
    page = browser.new_page(base_url=server.base_url, viewport={"width": 1280, "height": 1100})
    page.errors, page.requests = [], []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
    page.on("request", lambda r: page.requests.append((r.url, r.headers.get("range"))))
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto("/annotate")
    page.wait_for_function(READY, timeout=30000)
    return p, browser, page


def _variant_point(page, position, row="site"):
    """Where to click the call at `position`: its site bar, or the first
    sample's genotype cell below it."""
    return page.evaluate("""([pos, row]) => {
        const b = window.potatoViewers.locus.engine;
        const tv = b.trackViews.find(t => t.track.type === 'variant');
        const vp = tv.viewports[0];
        const r = vp.viewportElement.getBoundingClientRect();
        const rf = vp.referenceFrame;
        const y = row === 'genotype' ? tv.track.variantBandHeight + tv.track.sampleHeight / 2 : 12;
        return {x: r.left + (pos - 1 + 0.5 - rf.start) / rf.bpPerPixel, y: r.top + y};
    }""", [position, row])


def _stored(page):
    raw = page.eval_on_selector("form.viewer-selection .viewer-selection-input", "e => e.value")
    return json.loads(raw) if raw else {}


def test_loads_locus_and_tracks_from_media_only(server):
    p, browser, page = _open(server, "igv_load")
    try:
        # igv.js draws inside a shadow root; Playwright's locators reach into it.
        page.locator(".igv-track-label").nth(2).wait_for(timeout=15000)
        labels = page.locator(".igv-track-label").evaluate_all("els => els.map(e => e.textContent.trim())")
        assert {"Calls (sample1)", "Reads (sample1)", "Regions"} <= set(labels)
        locus = page.evaluate("[].concat(window.potatoViewers.locus.engine.currentLoci())[0]")
        chrom, span = locus.split(":")
        start, end = (float(v.replace(",", "")) for v in span.split("-"))
        assert chrom == "chr1" and start <= 1201 <= end and end - start < 200
        assert page.locator(".igv-search-input").input_value().startswith("chr1:1,141")
        # Alignments were read: the coverage track has data under the call.
        assert page.evaluate("""() => {
            const tv = window.potatoViewers.locus.engine.trackViews.find(t => t.track.type === 'alignment');
            return !!(tv && tv.viewports[0].cachedFeatures);
        }""")
        hosts = {urlparse(u).netloc for u, _ in page.requests}
        assert hosts == {urlparse(server.base_url).netloc}, hosts
        ranged = {urlparse(u).path for u, r in page.requests if r}
        assert {"/media/reads/sample1.bam", "/media/calls/sample1.vcf.gz",
                "/media/genome/synthetic.fa"} <= ranged
        # The selection starts as the item's locus, and opening it is not an answer.
        assert page.evaluate("window.potatoViewers.locus.getSelection().locus") == "chr1:1141-1261"
        assert _stored(page) == {}
        assert not page.errors, page.errors
    finally:
        browser.close()
        p.stop()


def test_radio_answer_and_selection_persist(server):
    p, browser, page = _open(server, "igv_persist")
    try:
        page.wait_for_timeout(800)
        pt = _variant_point(page, 1201)
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_function("window.potatoViewers.locus.getSelection().items.length === 1")
        item = _stored(page)["items"][0]
        assert item == {"chr": "chr1", "start": 1201, "end": 1201, "kind": "variant",
                        "name": "call_1", "ref": "C", "alt": "G", "track": "Calls (sample1)"}
        # igv's popup is replaced by the selection, not shown on top of it.
        assert not page.is_visible(".igv-popover")
        page.click("form#call_review label:has-text('Artifact')")
        page.wait_for_timeout(1600)       # autosave debounce
        page.screenshot(path=os.path.join(SCRATCH, "genome_selected.png"), full_page=True)

        page.click("#next-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'call_2'")
        page.wait_for_function(READY, timeout=30000)
        assert page.evaluate("window.potatoViewers.locus.getSelection().locus") == "chr1:1991-2111"
        assert not page.is_checked("form#call_review input[value='Artifact']")
        page.click("#prev-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'call_1'")
        page.wait_for_function(READY, timeout=30000)
        assert page.is_checked("form#call_review input[value='Artifact']")
        assert page.eval_on_selector_all(".vs-item .vs-desc", "els => els.map(e => e.textContent)") == [
            "chr1:1,201 call_1 C>G (Calls (sample1))"]
        page.wait_for_timeout(800)
        # The selected call is drawn as a shaded region of interest.
        assert page.locator(".igv-roi-region").count() >= 1
        server_side = page.evaluate("fetch('/get_annotations?instance_id=call_1').then(r => r.json())")
        assert server_side["label_annotations"]["call_review"] == ["Artifact"]
        stored = json.loads(server_side["label_values"]["evidence"]["evidence"])
        assert stored["items"][0]["name"] == "call_1" and stored["locus"] == "chr1:1141-1261"
        assert not page.errors, page.errors
    finally:
        browser.close()
        p.stop()


def test_a_click_on_the_genotype_selects_the_call(server):
    """The genotype cell is the bigger target, and its popup has no Chr/Pos."""
    p, browser, page = _open(server, "igv_genotype")
    try:
        page.wait_for_timeout(800)
        pt = _variant_point(page, 1201, row="genotype")
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_function("window.potatoViewers.locus.getSelection().items.length === 1")
        assert _stored(page)["items"][0] == {
            "chr": "chr1", "start": 1201, "end": 1201, "kind": "variant", "name": "call_1",
            "ref": "C", "alt": "G", "track": "Calls (sample1)"}
        assert not page.is_visible(".igv-popover")
        # The same call clicked on its site bar is the same item, so it toggles off.
        pt = _variant_point(page, 1201)
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_function("window.potatoViewers.locus.getSelection().items.length === 0")
        assert not page.errors, page.errors
    finally:
        browser.close()
        p.stop()


def test_fits_a_phone(server):
    with mobile_page("Pixel 7", server.base_url) as page:
        req = page.context.request
        req.post(f"{server.base_url}/register", form={"action": "signup", "email": "igv_phone", "pass": "pass"})
        req.post(f"{server.base_url}/auth", form={"action": "login", "email": "igv_phone", "pass": "pass"})
        page.goto("/annotate")
        page.wait_for_function(READY, timeout=30000)
        page.wait_for_timeout(800)
        problems = layout_problems(page, reachable=["form#call_review", "#next-btn"])
        page.screenshot(path=os.path.join(SCRATCH, "genome_phone.png"), full_page=True)
        assert not problems, problems
