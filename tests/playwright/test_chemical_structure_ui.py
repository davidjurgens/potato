"""
chemical_structure + molecule display in a real browser (OpenChemLib only).

Runs the chemical-structure-correction example with no RDKit.js installed:

* the editor starts from the recognised SMILES and that untouched structure
  is the saved answer (changed: false);
* a real hover + key press over the wrong atom in the editor's canvas fixes
  it (N -> O), and the answer, readout and changed flag follow;
* a click on an atom in the molecule drawing, and Space in the atom list,
  select atoms for the viewer_selection scheme;
* navigating away and back restores the editor's structure, the readout and
  the selected atoms (visual state), and the server holds the same JSON;
* drawing from an empty canvas with clicks and a drag, pasting a SMILES,
  the required-answer reason, a valence problem;
* the phone layout and dark mode.

RDKit.js (InChIKey, engine: rdkit) is in test_chemical_structure_rdkit.py.
"""

import json
import os
import shutil

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "chemical-structure-correction")
SCRATCH = os.environ.get("POTATO_SCREENSHOT_DIR") or create_test_directory("chemical_structure_screens")

IPHONE_13 = {
    "viewport": {"width": 390, "height": 664}, "device_scale_factor": 3,
    "is_mobile": True, "has_touch": True,
    "user_agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 "
                   "(KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"),
}

# The editor's molecule coordinates are pixels in its drawing canvas (the
# second canvas in its shadow root), so atoms can be targeted with the mouse.
EDITOR_ATOMS = """() => {
  const form = document.querySelector('form.chemical-structure');
  const st = window.PotatoChemicalStructure._states.get(form);
  const m = st.editor.getMolecule();
  const all = [];
  const walk = (n) => { if (!n) return; if (n.shadowRoot) walk(n.shadowRoot);
    for (const c of n.children || []) { if (c.tagName === 'CANVAS') all.push(c); walk(c); } };
  walk(form.querySelector('.cs-editor'));
  const r = all[all.length - 1].getBoundingClientRect();
  const atoms = [];
  for (let i = 0; i < m.getAllAtoms(); i++) atoms.push([m.getAtomLabel(i), r.x + m.getAtomX(i), r.y + m.getAtomY(i)]);
  return {atoms, area: [r.x, r.y, r.width, r.height]};
}"""


@pytest.fixture(scope="module")
def example_server():
    work_root = create_test_directory("chemical_structure_ui")
    work = os.path.join(work_root, "csc")
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache", "__pycache__"))
    # No RDKit.js: an empty vendor directory for this module.
    empty = os.path.join(work_root, "no_vendor")
    os.makedirs(empty, exist_ok=True)
    old = os.environ.get("POTATO_VENDOR_DIR")
    os.environ["POTATO_VENDOR_DIR"] = empty
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the chemical-structure-correction example")
    yield srv
    srv.stop()
    if old is None:
        os.environ.pop("POTATO_VENDOR_DIR", None)
    else:
        os.environ["POTATO_VENDOR_DIR"] = old


def _login(page, server, user):
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto(f"{server.base_url}/annotate")
    _ready(page)


def _ready(page):
    page.wait_for_function(
        "window.PotatoChemicalStructure && document.querySelector('form.chemical-structure .cs-loading').hidden "
        "&& window.PotatoChemicalStructure._states.get(document.querySelector('form.chemical-structure')).editor",
        timeout=30000)
    page.wait_for_function(
        "document.querySelector('.potato-viewer').getAttribute('data-viewer-state') === 'ready'",
        timeout=30000)


def _answer(page):
    raw = page.eval_on_selector(".chemical-structure-input", "e => e.value")
    return json.loads(raw) if raw else {}


def _selection(page):
    raw = page.eval_on_selector("form.viewer-selection .viewer-selection-input", "e => e.value")
    return json.loads(raw) if raw else {}


def _editor_smiles(page):
    return page.evaluate(
        "window.PotatoChemicalStructure._states.get(document.querySelector('form.chemical-structure'))"
        ".editor.getMolecule().toIsomericSmiles()")


def _pressed(page):
    return page.eval_on_selector_all(".mv-atom[aria-pressed='true']", "els => els.map(e => e.textContent)")


def _disc_atoms(page):
    """Atoms with a selection disc drawn under them, by the disc's position."""
    return page.evaluate("""() => {
      const hits = [...document.querySelectorAll('.mv-hit')].map(h => [+h.dataset.atom, +h.getAttribute('cx'), +h.getAttribute('cy')]);
      return [...document.querySelectorAll('.mv-selected')].map(d => {
        const x = +d.getAttribute('cx'), y = +d.getAttribute('cy');
        const h = hits.find(a => Math.abs(a[1] - x) < 0.5 && Math.abs(a[2] - y) < 0.5);
        return h ? h[0] : null; }).sort((a, b) => a - b);
    }""")


def _wait_for_instance(page, iid):
    page.wait_for_function(f"document.getElementById('instance_id').value === '{iid}'")
    _ready(page)


def _fix_atom_with_key(page, element, key):
    """Hover the first `element` atom in the editor, type `key`, move on."""
    page.locator("form.chemical-structure .cs-editor-wrap").scroll_into_view_if_needed()
    info = page.evaluate(EDITOR_ATOMS)
    x, y = next((a[1], a[2]) for a in info["atoms"] if a[0] == element)
    page.mouse.move(x, y, steps=4)
    page.wait_for_timeout(150)
    page.keyboard.press(key)
    # The editor applies a key at its next pointer event, as a hand would give it.
    page.mouse.move(x + 40, y + 40, steps=4)
    page.wait_for_timeout(600)


def test_correcting_and_marking_persist_across_navigation(example_server, page):
    page.set_viewport_size({"width": 1400, "height": 1100})
    _login(page, example_server, "chem_fix")
    form = "form.chemical-structure"

    # The untouched recognised structure is the saved answer.
    first = _answer(page)
    assert first["smiles"] == "CC(Oc1ccccc1C(N)=O)=O"
    assert first["changed"] is False and first["formula"] == "C9H9NO3"
    assert first["molfile"].count("V3000") == 1 and "M  END" in first["molfile"]
    assert "inchikey" not in first           # no RDKit.js here
    assert page.text_content(f"{form} .cs-smiles") == "CC(Oc1ccccc1C(N)=O)=O"
    assert "potato vendor fetch rdkit" in page.text_content(f"{form} .cs-inchikey")
    assert page.is_disabled(f"{form} .cs-reset")

    # Fix the amide N to the acid O with the mouse and a key, in the canvas.
    _fix_atom_with_key(page, "N", "o")
    fixed = _answer(page)
    assert fixed["smiles"] == "CC(Oc1ccccc1C(O)=O)=O" and fixed["formula"] == "C9H8O4"
    assert fixed["changed"] is True
    assert page.text_content(f"{form} .cs-formula") == "C9H8O4"
    assert page.is_enabled(f"{form} .cs-reset")

    # Mark the misread atom by clicking it in the drawing (atom 13 = index 12).
    page.locator(".potato-viewer .pv-stage").scroll_into_view_if_needed()
    box = page.locator(".mv-hit[data-atom='12']").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    # ...and another from the keyboard: Tab into the atom list, move, Space.
    page.click(".vs-label[data-label='wrong bond or charge']")
    page.focus(".mv-atom[data-atom='0']")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Space")
    assert page.eval_on_selector("#instance_id", "e => e.value") == "fig1_aspirin"
    assert _selection(page)["items"] == [
        {"atom": 12, "element": "N", "label": "wrong element"},
        {"atom": 2, "element": "O", "label": "wrong bond or charge"}]
    assert sorted(_pressed(page)) == ["N13", "O3"]
    assert _disc_atoms(page) == [2, 12]
    page.click("text=Minor Errors")
    page.wait_for_timeout(1700)        # autosave debounce

    stored = page.evaluate("fetch('/get_annotations?instance_id=fig1_aspirin').then(r => r.json())")
    on_server = json.loads(stored["label_values"]["corrected"]["corrected"])
    assert on_server["smiles"] == "CC(Oc1ccccc1C(O)=O)=O" and on_server["changed"] is True

    # Away: the next item has its own prefill and nothing selected.
    page.click("#next-btn")
    _wait_for_instance(page, "fig2_paracetamol")
    assert _answer(page)["smiles"] == "CC(Nc(cc1)ccc1O)=O"
    assert _pressed(page) == [] and _disc_atoms(page) == []
    # ...and back: the corrected structure, its readout and the marks return.
    page.click("#prev-btn")
    _wait_for_instance(page, "fig1_aspirin")
    page.wait_for_function("document.querySelectorAll('.mv-atom[aria-pressed=\"true\"]').length === 2")
    assert _editor_smiles(page) == "CC(Oc1ccccc1C(O)=O)=O"
    assert page.text_content(f"{form} .cs-smiles") == "CC(Oc1ccccc1C(O)=O)=O"
    assert page.text_content(f"{form} .cs-formula") == "C9H8O4"
    assert _answer(page)["changed"] is True
    assert page.is_enabled(f"{form} .cs-reset")
    assert sorted(_pressed(page)) == ["N13", "O3"]
    assert _disc_atoms(page) == [2, 12]
    assert page.eval_on_selector_all(".vs-item .vs-desc", "els => els.map(e => e.textContent)") == [
        "N13", "O3"]

    # Restore the given structure brings the recognised one back, unchanged.
    page.click(f"{form} .cs-reset")
    assert _answer(page)["smiles"] == "CC(Oc1ccccc1C(N)=O)=O"
    assert _answer(page)["changed"] is False
    page.screenshot(path=os.path.join(SCRATCH, "chem_light.png"), full_page=True)
    assert not page.errors, page.errors


def test_drawing_from_empty_pasting_and_valence(example_server, page):
    page.set_viewport_size({"width": 1400, "height": 1100})
    _login(page, example_server, "chem_draw")
    form = "form.chemical-structure"
    page.click(f"{form} .cs-clear")
    assert _answer(page) == {}
    assert "draw a structure" in page.get_attribute(form, "data-incomplete-reason")

    # Click on the empty canvas: a C-C bond. Drag from its end: one more.
    page.locator(f"{form} .cs-editor-wrap").scroll_into_view_if_needed()
    ax, ay, aw, ah = page.evaluate(EDITOR_ATOMS)["area"]
    page.mouse.click(ax + aw / 2, ay + ah / 2)
    page.wait_for_timeout(500)
    assert _answer(page)["smiles"] == "CC"
    atoms = page.evaluate(EDITOR_ATOMS)["atoms"]
    end = max(atoms, key=lambda a: a[1])
    page.mouse.move(end[1], end[2], steps=3)
    page.mouse.down()
    page.mouse.move(end[1] + 30, end[2] + 30, steps=8)
    page.mouse.up()
    page.wait_for_timeout(500)
    assert _answer(page)["smiles"] == "CCC"
    assert page.get_attribute(form, "data-incomplete-reason") is None

    # Name -> structure from the keyboard: type a SMILES and press Enter.
    page.click(f"{form} .cs-paste")
    page.keyboard.type("OC(=O)c1ccccc1")
    page.keyboard.press("Enter")
    assert page.eval_on_selector("#instance_id", "e => e.value") == "fig1_aspirin"
    assert _answer(page)["smiles"] == "OC(c1ccccc1)=O"
    assert "Loaded" in page.text_content(f"{form} .cs-problems")

    # A carbon with six bonds is reported and keeps the item incomplete.
    page.fill(f"{form} .cs-paste", "CC(C)(C)(C)(C)C")
    page.click(f"{form} .cs-load")
    answer = _answer(page)
    assert answer["problems"] and "has 6 bonds" in answer["problems"][0]
    assert "fix the structure" in page.get_attribute(form, "data-incomplete-reason")
    assert "has 6 bonds" in page.text_content(f"{form} .cs-problems")
    # Text that is not a structure is refused and changes nothing.
    page.fill(f"{form} .cs-paste", "not a molecule ((")
    page.click(f"{form} .cs-load")
    assert "not a SMILES" in page.text_content(f"{form} .cs-problems")
    assert _answer(page)["problems"]
    assert not page.errors, page.errors


def test_phone_layout_and_dark_mode(example_server, browser_instance):
    ctx = browser_instance.new_context(**IPHONE_13, color_scheme="dark")
    try:
        page = ctx.new_page()
        _login(page, example_server, "chem_phone")
        problems = layout_problems(page, reachable=[
            ".mv-atom[data-atom='0']", "form.chemical-structure .cs-load",
            "form.chemical-structure .cs-editor-wrap", "#next-btn"])
        page.screenshot(path=os.path.join(SCRATCH, "chem_phone_dark.png"), full_page=True)
        assert not problems, problems
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        # Bonds follow the theme's text colour, which is light on the dark card.
        bond = page.evaluate("""() => {
            const l = document.querySelector('.mv-svg line');
            return getComputedStyle(l).stroke; }""")
        channels = [int(c) for c in bond[bond.index("(") + 1:-1].split(",")[:3]]
        assert min(channels) > 150, bond
        # The editor is inverted, so its canvas is dark too.
        assert "invert" in page.eval_on_selector(
            "form.chemical-structure .cs-editor-wrap", "e => getComputedStyle(e).filter")
        # The editor fits the phone.
        width = page.eval_on_selector("form.chemical-structure .cs-editor-wrap",
                                      "e => e.getBoundingClientRect().width")
        assert width <= 390
        assert not page.errors, page.errors
    finally:
        ctx.close()


@pytest.fixture(scope="module")
def molfile_server(example_server):
    """A molecule display fed a .mol file from the media directory whose
    hydrogen is the file's second atom (OpenChemLib moves it last)."""
    import yaml
    work = create_test_directory("chemical_structure_molfile_ui")
    media = os.path.join(work, "media")
    os.makedirs(media, exist_ok=True)
    shutil.copy(os.path.join(REPO, "tests", "data", "chemistry", "h_first_halomethane.mol"), media)
    with open(os.path.join(work, "items.json"), "w") as f:
        json.dump([{"id": "m1", "note": "Molfile order", "mol": "h_first_halomethane.mol"}], f)
    config = {
        "annotation_task_name": "Molfile order", "task_dir": ".", "media_directory": "media",
        "output_annotation_dir": "annotation_output", "data_files": ["items.json"],
        "item_properties": {"id_key": "id", "text_key": "note"},
        "user_config": {"allow_all_users": True},
        "instance_display": {"fields": [{"key": "mol", "type": "molecule",
                                         "display_options": {"show_atom_numbers": True}}]},
        "annotation_schemes": [{"annotation_type": "viewer_selection", "name": "site",
                                "description": "Mark atoms", "viewer_field": "mol",
                                "max_selections": 2}],
    }
    path = os.path.join(work, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        pytest.fail("could not start the molfile server")
    yield srv
    srv.stop()


def test_molfile_atom_indices_follow_the_file(molfile_server, page):
    page.set_viewport_size({"width": 1200, "height": 900})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    req = page.context.request
    base = molfile_server.base_url
    req.post(f"{base}/register", form={"action": "signup", "email": "mf", "pass": "pass"})
    req.post(f"{base}/auth", form={"action": "login", "email": "mf", "pass": "pass"})
    page.goto(f"{base}/annotate")
    page.wait_for_function(
        "document.querySelector('.potato-viewer').getAttribute('data-viewer-state') === 'ready'")
    # The list follows the file's atom block, hydrogen second.
    assert page.eval_on_selector_all(".mv-atom", "els => els.map(e => e.textContent)") == [
        "C1", "H2", "Cl3", "Br4", "F5"]
    # Clicking the drawn H selects source index 1, whatever OpenChemLib's own order.
    box = page.locator(".mv-hit[data-atom='1']").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    box = page.locator(".mv-hit[data-atom='4']").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    stored = json.loads(page.eval_on_selector(".viewer-selection-input", "e => e.value"))
    assert stored["items"] == [{"atom": 1, "element": "H"}, {"atom": 4, "element": "F"}]
    # The drawn hit targets sit on the atoms OpenChemLib drew for them: H is
    # straight above C in the file, so its target is above C's.
    pos = page.evaluate("Object.fromEntries([...document.querySelectorAll('.mv-hit')]"
                        ".map(h => [h.dataset.atom, [+h.getAttribute('cx'), +h.getAttribute('cy')]]))")
    assert abs(pos["1"][0] - pos["0"][0]) < 1 and pos["1"][1] < pos["0"][1]
    assert pos["2"][0] > pos["0"][0] and pos["3"][0] < pos["0"][0]      # Cl right, Br left
    # max_selections: a third is refused.
    page.click(".mv-atom[data-atom='2']")
    assert "At most 2" in page.text_content(".vs-message")
    assert len(json.loads(page.eval_on_selector(".viewer-selection-input", "e => e.value"))["items"]) == 2
    assert not page.errors, page.errors
