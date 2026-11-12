"""
Ontology-backed labels (`label_source`) in a real browser, on the example
project (examples/classification/ontology-labels, a synthetic OBO sample).

* radio: typing searches the file, Down/Enter picks, Escape closes then clears
* multiselect: a mouse click on a match adds a ticked checkbox
* span: a picked term becomes the active chip; a real drag draws a span whose
  chip reads the term name and whose stored label is the term id
* image_annotation: a picked term becomes a label button the drawing uses
* everything survives Next and Previous (checked state and visible text, then
  the server's copy and the user_state file on disk)
* a required picker-only radio blocks Next until a term is picked
* phone width: no sideways scroll, the results list fits the screen, taps work
* no console errors

Set ONTOLOGY_SCREENSHOT_DIR to keep light/dark/phone screenshots.
"""

import glob
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
EXAMPLE = os.path.join(REPO, "examples", "classification", "ontology-labels")
OBO = os.path.join(REPO, "tests", "data", "ontology", "scl-sample.obo")
SHOTS = os.environ.get("ONTOLOGY_SCREENSHOT_DIR")

RADIO = "#ontology-main_cell_type-input"
MULTI = "#ontology-other_cell_types-input"
SPAN = "#ontology-immune_cell_mentions-input"


def _copy_example(name):
    work = os.path.join(create_test_directory(name), "onto")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache"))
    return work


@pytest.fixture(scope="module")
def server():
    work = _copy_example("ontology_labels_ui")
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the ontology-labels example")
    srv.work_dir = work
    yield srv
    srv.stop()


def _login(page, server, user):
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})


def _open(page, server, user):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    _login(page, server, user)
    page.goto(f"{server.base_url}/annotate")
    page.wait_for_selector(RADIO)
    return errors


def _search(page, box, text):
    page.click(box)
    page.keyboard.type(text, delay=20)
    listbox = box.replace("-input", "-list")
    page.wait_for_selector(f"{listbox} [role=option]", state="visible")
    return listbox


def _stored(page, server, instance_id):
    r = page.context.request.get(f"{server.base_url}/get_annotations?instance_id={instance_id}")
    return r.json()


def _instance(page):
    return page.input_value("#instance_id")


def _next(page):
    before = _instance(page)
    page.click("#next-btn")
    page.wait_for_function("b => document.querySelector('#instance_id') && "
                           "document.querySelector('#instance_id').value !== b", arg=before)
    page.wait_for_selector(RADIO)


def _prev(page):
    before = _instance(page)
    page.click("#prev-btn")
    page.wait_for_function("b => document.querySelector('#instance_id') && "
                           "document.querySelector('#instance_id').value !== b", arg=before)
    page.wait_for_selector(RADIO)


def _drag_over_word(page, word):
    """Select `word` in #instance-text with a real mouse drag."""
    box = page.evaluate("""(word) => {
        const root = document.getElementById('instance-text');
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
            const i = node.textContent.indexOf(word);
            if (i >= 0) {
                const r = document.createRange();
                r.setStart(node, i); r.setEnd(node, i + word.length);
                const b = r.getBoundingClientRect();
                return {x0: b.left + 1, x1: b.right - 1, y: b.top + b.height / 2};
            }
        }
        return null;
    }""", word)
    assert box, f"{word!r} not found in the item text"
    page.mouse.move(box["x0"], box["y"])
    page.mouse.down()
    page.mouse.move((box["x0"] + box["x1"]) / 2, box["y"], steps=4)
    page.mouse.move(box["x1"], box["y"], steps=4)
    page.mouse.up()


def _user_state(server, user):
    paths = glob.glob(os.path.join(server.work_dir, "annotation_output", "**", "user_state.json"),
                      recursive=True)
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("user_id") == user or os.path.basename(os.path.dirname(p)) == user:
            return data
    return None


def test_radio_and_multiselect_pick_and_survive_navigation(server, page):
    errors = _open(page, server, "onto_radio")
    first = _instance(page)

    # Keyboard: type a synonym, the first match is active, Enter picks it.
    listbox = _search(page, RADIO, "helper")
    first_opt = page.locator(f"{listbox} [role=option]").first
    assert "CD4-positive T cell" in first_opt.inner_text()
    assert "synonym: helper T cell" in first_opt.inner_text()
    assert page.get_attribute(RADIO, "aria-expanded") == "true"
    assert page.get_attribute(RADIO, "aria-activedescendant") == first_opt.get_attribute("id")
    page.keyboard.press("Enter")
    radio = page.locator('input[type=radio][schema="main_cell_type"][label_name="SCL:0000005"]')
    assert radio.is_checked()
    assert page.is_hidden(listbox)
    assert "Selected CD4-positive T cell (SCL:0000005)" in page.inner_text(
        '[data-schema="main_cell_type"] .ontology-picker-status')

    # Picking another replaces the first (it is a radio group).
    _search(page, RADIO, "B-lym")
    page.keyboard.press("Enter")
    b_cell = page.locator('input[type=radio][schema="main_cell_type"][label_name="SCL:0000007"]')
    assert b_cell.is_checked() and not radio.is_checked()

    # Escape closes the list, a second Escape clears the box.
    _search(page, RADIO, "lymph")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Escape")
    assert page.is_hidden(RADIO.replace("-input", "-list"))
    assert page.input_value(RADIO) == "lymph"
    page.keyboard.press("Escape")
    assert page.input_value(RADIO) == ""

    # Mouse: click a match in the multiselect picker.
    listbox = _search(page, MULTI, "macro")
    page.locator(f"{listbox} [role=option]").first.click()
    macro = page.locator('input[type=checkbox][schema="other_cell_types"][label_name="SCL:0000011"]')
    assert macro.is_checked()
    _search(page, MULTI, "neutro")
    page.keyboard.press("Enter")
    page.wait_for_timeout(1600)  # autosave debounce

    stored = _stored(page, server, first)["label_values"]
    assert set(stored["main_cell_type"]) == {"SCL:0000007"}
    rec = json.loads(stored["main_cell_type"]["SCL:0000007"])
    assert rec == {"obo_id": "SCL:0000007", "label": "B cell",
                   "iri": "http://purl.obolibrary.org/obo/SCL_0000007",
                   "ontology_version": "scl/releases/2026-10-01"}
    assert set(stored["other_cell_types"]) == {"SCL:0000011", "SCL:0000012"}

    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        _search(page, MULTI, "cell")
        page.screenshot(path=os.path.join(SHOTS, "ontology_light.png"), full_page=True)
        page.keyboard.press("Escape")
        page.keyboard.press("Escape")

    _next(page)
    assert _instance(page) != first
    # The new item starts empty: no term options carried over.
    assert page.locator('input[schema="main_cell_type"][label_name="SCL:0000007"]').count() == 0
    _prev(page)
    assert _instance(page) == first

    # Visual state after coming back: the options exist, are ticked and read
    # as the term names.
    b_cell = page.locator('input[type=radio][schema="main_cell_type"][label_name="SCL:0000007"]')
    assert b_cell.is_checked()
    # The server-rendered option carries the string the picker stored, so a
    # resave writes back what was loaded.
    assert b_cell.get_attribute("value") == stored["main_cell_type"]["SCL:0000007"]
    assert page.locator('label[for="main_cell_type__onto__SCL_0000007"]').inner_text() \
        .split() == ["B", "cell", "SCL:0000007"]
    for oid in ("SCL:0000011", "SCL:0000012"):
        assert page.locator(f'input[type=checkbox][schema="other_cell_types"]'
                            f'[label_name="{oid}"]').is_checked()
    assert page.locator('[data-ontology-term="SCL:0000005"]').count() == 0  # replaced earlier

    # On disk, not just in memory.
    state = _user_state(server, "onto_radio")
    assert state is not None, "user_state.json not written"
    assert "SCL:0000007" in json.dumps(state)
    assert errors == []


def test_required_picker_only_radio_blocks_next(server, page):
    errors = _open(page, server, "onto_required")
    first = _instance(page)
    page.click("#next-btn")
    page.wait_for_timeout(600)
    assert _instance(page) == first
    assert page.is_visible("#required-fields-error")
    assert "Which cell type" in page.inner_text("#required-fields-error")
    _search(page, RADIO, "neuron")
    page.keyboard.press("Enter")
    assert page.get_attribute(".ontology-required-sentinel", "value") == "1"
    _next(page)
    assert _instance(page) != first
    assert errors == []


def test_span_term_draws_a_span_named_by_the_term(server, page):
    errors = _open(page, server, "onto_span")
    first = _instance(page)
    _search(page, RADIO, "T cell")
    page.keyboard.press("Enter")
    # Subtree: the span picker searches only immune cells.
    listbox = _search(page, SPAN, "cell")
    names = page.locator(f"{listbox} [role=option] .ontology-result-label").all_inner_texts()
    assert "epithelial cell" not in names and "neuron" not in names and "cell" not in names
    assert "T cell" in names
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    _search(page, SPAN, "helper")
    page.keyboard.press("Enter")
    chip = page.locator('input.shadcn-span-checkbox[value="SCL:0000005"]')
    assert chip.is_checked()
    _drag_over_word(page, "CD4")
    overlay = page.locator('.span-overlay-pure[data-label="SCL:0000005"]')
    overlay.first.wait_for(state="attached")
    page.wait_for_function(
        "() => { const c = document.querySelector('.span-overlay-pure[data-label=\"SCL:0000005\"] .span-label');"
        " return c && c.textContent === 'CD4-positive T cell'; }")
    page.wait_for_timeout(1600)

    spans = _stored(page, server, first)["span_annotations"]
    assert any("SCL:0000005" in k for k in spans), spans

    _next(page)
    _prev(page)
    page.wait_for_function(
        "() => { const c = document.querySelector('.span-overlay-pure[data-label=\"SCL:0000005\"] .span-label');"
        " return c && c.textContent === 'CD4-positive T cell'; }", timeout=8000)
    assert errors == []


def test_phone_width_layout_and_tap(server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 390, "height": 844},
                                           device_scale_factor=3, is_mobile=True,
                                           has_touch=True)
    page = context.new_page()
    try:
        errors = _open(page, server, "onto_phone")
        assert not layout_problems(page, reachable=[RADIO, MULTI, "#next-btn"])
        listbox = _search(page, RADIO, "cell")
        box = page.locator(listbox).bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 390 + 0.5, box
        option = page.locator(f"{listbox} [role=option]").nth(1)
        assert option.bounding_box()["height"] >= 43.5   # a tappable target
        text = option.locator(".ontology-result-label").inner_text()
        option.tap()
        checked = page.locator('input[type=radio][schema="main_cell_type"]:checked')
        assert checked.count() == 1
        assert text in page.locator('.ontology-term-option').first.inner_text()
        assert not layout_problems(page, reachable=[RADIO, "#next-btn"])
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            _search(page, MULTI, "lym")
            page.screenshot(path=os.path.join(SHOTS, "ontology_phone.png"), full_page=False)
        assert errors == []
    finally:
        context.close()


def test_dark_mode_reads(server, browser_instance):
    context = browser_instance.new_context(viewport={"width": 1280, "height": 900},
                                           color_scheme="dark")
    page = context.new_page()
    try:
        errors = _open(page, server, "onto_dark")
        listbox = _search(page, RADIO, "cell")
        colors = page.evaluate("""(sel) => {
            const list = getComputedStyle(document.querySelector(sel));
            const opt = getComputedStyle(document.querySelector(sel + ' .ontology-result-label'));
            return {bg: list.backgroundColor, fg: opt.color,
                    theme: document.documentElement.dataset.theme};
        }""", listbox)
        assert colors["theme"] == "dark"
        # Dark list background, light text.
        bg = [int(x) for x in colors["bg"][colors["bg"].index("(") + 1:-1].split(",")[:3]]
        fg = [int(x) for x in colors["fg"][colors["fg"].index("(") + 1:-1].split(",")[:3]]
        assert sum(bg) < 200 and sum(fg) > 500, colors
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            page.screenshot(path=os.path.join(SHOTS, "ontology_dark.png"), full_page=True)
        assert errors == []
    finally:
        context.close()


IMAGE_SCHEMES = [{
    "annotation_type": "image_annotation", "name": "cells_in_image",
    "description": "Box each cell and name its type",
    "tools": ["bbox"], "labels": [],
    "label_source": {"ontology": "scl", "service": "file", "file": "scl-sample.obo"},
}]


@pytest.fixture(scope="module")
def image_server():
    import yaml
    from tests.helpers.test_utils import TestConfigManager
    with TestConfigManager("ontology_image_ui", IMAGE_SCHEMES, num_items=2) as cfg:
        shutil.copy(OBO, os.path.join(cfg.task_dir, "scl-sample.obo"))
        # Items need an image for the canvas.
        png = os.path.join(REPO, "potato", "static", "favicon.png")
        if not os.path.exists(png):
            png = next(iter(glob.glob(os.path.join(REPO, "examples", "image", "**", "*.png"),
                                      recursive=True)), None)
        rows = []
        if png:
            shutil.copy(png, os.path.join(cfg.task_dir, "cells.png"))
        for i in range(2):
            rows.append({"id": f"img_{i}", "text": "cells.png", "image_url": "cells.png"})
        with open(cfg.data_file, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        with open(cfg.config_path) as fh:
            conf = yaml.safe_load(fh)
        conf["item_properties"] = {"id_key": "id", "text_key": "text"}
        with open(cfg.config_path, "w") as fh:
            yaml.safe_dump(conf, fh)
        srv = FlaskTestServer(config_file=cfg.config_path)
        if not srv.start():
            pytest.fail("could not start the image server")
        yield srv
        srv.stop()


def test_image_label_button_from_a_term(image_server, page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    _login(page, image_server, "onto_image")
    page.goto(f"{image_server.base_url}/annotate")
    box = "#ontology-cells_in_image-input"
    page.wait_for_selector(box)
    _search(page, box, "macro")
    page.keyboard.press("Enter")
    btn = page.locator('.label-btn[data-label="SCL:0000011"]')
    assert btn.inner_text().strip() == "macrophage"
    assert btn.get_attribute("aria-pressed") == "true"
    current = page.evaluate("""() => {
        const c = document.querySelector('.image-annotation-container[data-schema="cells_in_image"]');
        return c && c.annotationManager ? c.annotationManager.currentLabel : null;
    }""")
    assert current == "SCL:0000011"
    assert errors == []
