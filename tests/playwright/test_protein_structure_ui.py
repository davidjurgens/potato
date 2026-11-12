"""
protein_structure + viewer_selection in a real browser, WebGL off.

The viewer says WebGL is missing, the 3D library is never fetched, and the
residue table still selects residues by mouse and keyboard; the selection and
its labels survive navigating away and back (visual state, and the stored JSON
on the server). Plus max_selections and the phone layout. The drawing itself
is tested in test_protein_structure_webgl.py.
"""

import importlib.util
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
EXAMPLE = os.path.join(REPO, "examples", "advanced", "protein-binding-site")
SCRATCH = os.environ.get("POTATO_SCREENSHOT_DIR") or create_test_directory("protein_structure_screens")

NO_WEBGL = ["--disable-gpu", "--disable-webgl", "--disable-3d-apis"]
SWIFTSHADER = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def _generator():
    spec = importlib.util.spec_from_file_location(
        "generate_structures", os.path.join(EXAMPLE, "generate_structures.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def example_server():
    work = os.path.join(create_test_directory("protein_structure_ui"), "pbs")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache"))
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the protein-binding-site example")
    yield srv
    srv.stop()


def _open(server, user, args):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(args=args)
    page = browser.new_page(base_url=server.base_url, viewport={"width": 1280, "height": 1000})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
    page.requested = []
    page.on("request", lambda r: page.requested.append(r.url))
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto("/annotate")
    page.wait_for_function(
        "document.querySelector('.potato-viewer') && "
        "document.querySelector('.potato-viewer').getAttribute('data-viewer-state') !== 'loading'",
        timeout=30000)
    return p, browser, page


def _close(p, browser):
    browser.close()
    p.stop()


def _stored(page):
    raw = page.eval_on_selector("form.viewer-selection .viewer-selection-input", "e => e.value")
    return json.loads(raw) if raw else {}


def _pressed(page):
    return page.eval_on_selector_all(
        ".pv-res[aria-pressed='true']",
        "els => els.map(e => e.dataset.chain + ':' + e.dataset.resi)")


def _wait_for_instance(page, iid):
    page.wait_for_function(f"document.getElementById('instance_id').value === '{iid}'")
    page.wait_for_function(
        "document.querySelector('.potato-viewer').getAttribute('data-viewer-state') !== 'loading'",
        timeout=30000)


# ---------------------------------------------------------------------------
# (a) No WebGL
# ---------------------------------------------------------------------------

def test_without_webgl_the_table_selects_and_the_selection_persists(example_server):
    p, browser, page = _open(example_server, "pv_nogl", NO_WEBGL)
    try:
        assert page.get_attribute(".potato-viewer", "data-viewer-state") == "no-webgl"
        message = page.text_content(".potato-viewer .pv-message")
        assert "needs WebGL" in message and "residue table" in message
        assert page.is_visible(".potato-viewer .pv-message")
        assert not [u for u in page.requested if "3Dmol" in u], "the 3D library was fetched anyway"
        form = "form.viewer-selection"
        assert "select at least 1" in page.get_attribute(form, "data-incomplete-reason")

        # Mouse: HIS 8 with the default label.
        page.click(".pv-res[data-chain='A'][data-resi='8']")
        # Keyboard: choose the second label, then Tab into chain B and move.
        page.click(".vs-label[data-label='interface']")
        page.focus(".pv-res[data-chain='B'][data-resi='1']")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("Space")
        # The arrow keys moved within the table, not to the next item.
        assert page.eval_on_selector("#instance_id", "e => e.value") == "zinc_site_complex"
        assert sorted(_pressed(page)) == ["A:8", "B:3"]
        assert _stored(page)["items"] == [
            {"chain": "A", "resi": 8, "resn": "HIS", "label": "zinc ligand"},
            {"chain": "B", "resi": 3, "resn": "LYS", "label": "interface"}]
        assert page.get_attribute(form, "data-incomplete-reason") is None
        # Relabel from the list.
        page.select_option(".vs-item:nth-child(2) .vs-item-label", "zinc ligand")
        page.wait_for_timeout(1600)       # autosave debounce

        page.click("#next-btn")
        _wait_for_instance(page, "predicted_tail_model")
        assert _pressed(page) == [] and not _stored(page)
        page.click("#prev-btn")
        _wait_for_instance(page, "zinc_site_complex")
        page.wait_for_function("document.querySelectorAll('.pv-res[aria-pressed=\"true\"]').length === 2")
        assert sorted(_pressed(page)) == ["A:8", "B:3"]
        assert page.eval_on_selector_all(".vs-item .vs-desc", "els => els.map(e => e.textContent)") == [
            "HIS 8, chain A", "LYS 3, chain B"]
        assert page.eval_on_selector_all(".vs-item-label", "els => els.map(e => e.value)") == [
            "zinc ligand", "zinc ligand"]
        # The table cell carries the label's colour, not the default.
        colour = page.eval_on_selector(".pv-res[data-chain='B'][data-resi='3']",
                                       "e => getComputedStyle(e).backgroundColor")
        assert colour == "rgb(194, 37, 92)"
        server_side = page.evaluate(
            "fetch('/get_annotations?instance_id=zinc_site_complex').then(r => r.json())")
        stored = json.loads(server_side["label_values"]["binding_site"]["binding_site"])
        assert [i["resi"] for i in stored["items"]] == [8, 3]

        # Remove from the list puts focus somewhere sensible and updates the table.
        page.click(".vs-item:nth-child(1) .vs-remove")
        assert _pressed(page) == ["B:3"]
        assert page.evaluate("document.activeElement.classList.contains('vs-remove')")
        page.screenshot(path=os.path.join(SCRATCH, "protein_no_webgl.png"), full_page=True)
        assert not page.errors, page.errors
    finally:
        _close(p, browser)


def test_max_selections_is_enforced(example_server):
    p, browser, page = _open(example_server, "pv_max", NO_WEBGL)
    try:
        for resi in range(1, 14):
            page.click(f".pv-res[data-chain='A'][data-resi='{resi}']")
        assert len(_pressed(page)) == 12
        assert "At most 12" in page.text_content(".vs-message")
        assert len(_stored(page)["items"]) == 12
    finally:
        _close(p, browser)


# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------

def test_fits_a_phone(example_server):
    with mobile_page("iPhone 13", example_server.base_url) as page:
        req = page.context.request
        req.post(f"{example_server.base_url}/register", form={"action": "signup", "email": "pv_phone", "pass": "pass"})
        req.post(f"{example_server.base_url}/auth", form={"action": "login", "email": "pv_phone", "pass": "pass"})
        page.goto("/annotate")
        page.wait_for_selector(".pv-res")
        problems = layout_problems(page, reachable=[".pv-res[data-chain='A'][data-resi='1']",
                                                    ".vs-label[data-label='interface']", "#next-btn"])
        page.screenshot(path=os.path.join(SCRATCH, "protein_phone.png"), full_page=True)
        assert not problems, problems
