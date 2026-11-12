"""
interlinear_gloss in a real browser: typing into the segmentation and gloss
cells, the per-word misalignment marker appearing and clearing, Tab and Enter
moving between cells, a misaligned required item blocking Next, glosses
surviving navigate-away-and-back (the cells and markers, not just the hidden
input), an imported analysis kept when the annotator presses Next without
editing, and the columns wrapping on a phone with no sideways scroll.
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
EXAMPLE = os.path.join(REPO, "examples", "span", "interlinear-gloss")
SHOTS = os.environ.get("IGT_SCREENSHOT_DIR")

LONG = {"id": "long_1",
        "text": "Gallia est omnis divisa in partes tres, quarum unam incolunt Belgae",
        "morphemes": ["Galli-a", "es-t", "omn-is", "divis-a", "in", "part-es", "tr-es",
                      "qu-arum", "un-am", "incol-unt", "Belg-ae"],
        "glosses": ["Gaul-NOM.SG", "be-3SG", "all-NOM.SG", "divide.PTCP-NOM.SG", "in",
                    "part-ACC.PL", "three-ACC.PL", "which-GEN.PL", "one-ACC.SG",
                    "inhabit-3PL", "Belgian-NOM.PL"],
        "translation": "All Gaul is divided into three parts, one of which the Belgae inhabit"}


def _copy_example(name, rows=None):
    work = os.path.join(create_test_directory(name), "igt")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache"))
    if rows is not None:
        with open(os.path.join(work, "data", "interlinear-gloss-example.jsonl"), "w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
    return os.path.join(work, "config.yaml")


@pytest.fixture(scope="module")
def server():
    srv = FlaskTestServer(config_file=_copy_example("igt_ui"))
    if not srv.start():
        pytest.fail("could not start the interlinear gloss example")
    yield srv
    srv.stop()


def _login(page, server, user):
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})


def _desktop(server, user):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch()
    page = browser.new_page(base_url=server.base_url, viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    _login(page, server, user)
    page.goto("/annotate")
    page.wait_for_selector(".igt-word[data-index='0']")
    return p, browser, page, errors


def _cell(page, word, tier):
    return page.locator(f".igt-input[data-index='{word}'][data-tier='{tier}']")


def _status(page, word):
    return page.get_attribute(f".igt-word[data-index='{word}']", "data-status")


def _answer(page):
    raw = page.eval_on_selector(".interlinear-gloss-input", "e => e.value")
    return json.loads(raw) if raw else None


def _stored(page, server, instance_id):
    r = page.context.request.get(f"{server.base_url}/get_annotations?instance_id={instance_id}")
    values = (r.json().get("label_values") or {}).get("igt") or {}
    return json.loads(values["igt"]) if "igt" in values else None


def _retype(page, word, tier, text):
    cell = _cell(page, word, tier)
    cell.click()
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.press("Backspace")
    page.keyboard.type(text, delay=15)


def test_typing_marks_and_clears_misalignment_and_restores(server):
    p, browser, page, errors = _desktop(server, "igt_ui")
    try:
        assert page.input_value("#instance_id") == "latin_1"
        form = "form.interlinear-gloss"
        assert [_status(page, i) for i in range(3)] == ["ok", "ok", "ok"]
        assert page.get_attribute(form, "data-incomplete-reason") is None
        # Category labels print in small caps.
        cat = page.locator(".igt-word[data-index='1'] .igt-cat").first
        assert cat.text_content() == "ACC"
        assert cat.evaluate("e => getComputedStyle(e).fontVariantCaps") == "all-small-caps"

        # A "-" typed where Leipzig wants "." gives the gloss one boundary too many.
        _retype(page, 1, "gloss", "rose-ACC-SG")
        assert _status(page, 1) == "misaligned"
        issue = page.locator(".igt-word[data-index='1'] .igt-issue-error")
        assert "segmentation has 1 boundary (-), gloss has 2 boundaries (- -)" in issue.text_content()
        assert _cell(page, 1, "gloss").get_attribute("aria-invalid") == "true"
        assert "word 2" in page.get_attribute(form, "data-incomplete-reason")
        if SHOTS:
            page.screenshot(path=os.path.join(SHOTS, "igt_misaligned.png"), full_page=True)

        # The scheme is required: a misaligned item does not advance.
        page.click("#next-btn")
        page.wait_for_timeout(800)
        assert page.input_value("#instance_id") == "latin_1"

        # Fix it with real keys: click after the text, delete "-SG", type ".SG".
        box = _cell(page, 1, "gloss").bounding_box()
        _cell(page, 1, "gloss").click(position={"x": box["width"] - 4, "y": box["height"] / 2})
        for _ in range(3):
            page.keyboard.press("Backspace")
        page.keyboard.type(".SG", delay=15)
        assert _cell(page, 1, "gloss").input_value() == "rose-ACC.SG"
        assert _status(page, 1) == "ok"
        assert page.locator(".igt-word[data-index='1'] .igt-issue-error").count() == 0
        assert _cell(page, 1, "gloss").get_attribute("aria-invalid") is None
        assert page.get_attribute(form, "data-incomplete-reason") is None

        # An unknown category label is a warning, not an error.
        _retype(page, 2, "gloss", "love-3SG.EVID")
        assert _status(page, 2) == "ok"
        assert "EVID" in page.locator(".igt-word[data-index='2'] .igt-issue-warn").text_content()

        # Tab walks down a word's lines, then on to the next word.
        _cell(page, 0, "morphemes").click()
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.dataset.tier") == "gloss"
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        assert page.evaluate("[document.activeElement.dataset.index, document.activeElement.dataset.tier]") \
            == ["1", "morphemes"]
        # Enter moves along one line, from word to word.
        page.keyboard.press("Enter")
        assert page.evaluate("[document.activeElement.dataset.index, document.activeElement.dataset.tier]") \
            == ["2", "morphemes"]
        _retype(page, 0, "notes", "subject")
        page.fill(".igt-translation", "")
        page.click(".igt-translation")
        page.keyboard.type("The girl loves the rose.", delay=5)

        answer = _answer(page)
        assert answer["words"][1]["gloss"] == "rose-ACC.SG"
        assert answer["words"][2]["gloss"] == "love-3SG.EVID"
        assert answer["words"][0]["notes"] == "subject"
        page.wait_for_timeout(1600)   # autosave debounce
        assert _stored(page, server, "latin_1")["words"][2]["gloss"] == "love-3SG.EVID"

        page.click("#next-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'latin_2'")
        page.wait_for_selector(".igt-word[data-index='2']")
        # A blank item starts each segmentation as the word itself.
        assert _cell(page, 1, "morphemes").input_value() == "virumque"
        assert _cell(page, 1, "gloss").input_value() == ""
        assert _status(page, 1) == "incomplete"

        page.click("#prev-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'latin_1'")
        page.wait_for_selector(".igt-word[data-index='2'] .igt-issue-warn")
        page.wait_for_timeout(300)
        assert _cell(page, 1, "gloss").input_value() == "rose-ACC.SG"
        assert _cell(page, 2, "gloss").input_value() == "love-3SG.EVID"
        assert _cell(page, 0, "notes").input_value() == "subject"
        assert page.input_value(".igt-translation") == "The girl loves the rose."
        assert [_status(page, i) for i in range(3)] == ["ok", "ok", "ok"]
        assert page.locator(".igt-word[data-index='1'] .igt-cat").count() == 2
        assert not [e for e in errors if "favicon" not in e], errors
    finally:
        browser.close()
        p.stop()


def test_imported_analysis_is_kept_without_edits(server):
    p, browser, page, errors = _desktop(server, "igt_accept")
    try:
        assert page.input_value("#instance_id") == "latin_1"
        page.click("#next-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'latin_2'")
        stored = _stored(page, server, "latin_1")
        assert [w["gloss"] for w in stored["words"]] == ["girl-NOM.SG", "rose-ACC.SG", "love-3SG"]
        assert stored["translation"] == "The girl loves the rose."
    finally:
        browser.close()
        p.stop()


@pytest.fixture(scope="module")
def latin4_server():
    with open(os.path.join(EXAMPLE, "data", "interlinear-gloss-example.jsonl")) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    srv = FlaskTestServer(config_file=_copy_example("igt_latin4", rows=[r for r in rows if r["id"] == "latin_4"]))
    if not srv.start():
        pytest.fail("could not start the latin_4 config")
    yield srv
    srv.stop()


def test_pre_filled_misalignment_is_shown(latin4_server):
    """latin_4 ships with "-and" for the clitic "=que": that word is marked on load."""
    p, browser, page, errors = _desktop(latin4_server, "igt_latin4")
    try:
        assert page.input_value("#instance_id") == "latin_4"
        assert [_status(page, i) for i in range(3)] == ["ok", "misaligned", "ok"]
        assert "(- =)" in page.locator(".igt-word[data-index='1'] .igt-issue-error").text_content()
        # Retyping the gloss with the clitic boundary clears it.
        _retype(page, 1, "gloss", "people-NOM.SG=and")
        assert _status(page, 1) == "ok"
        assert page.get_attribute("form.interlinear-gloss", "data-incomplete-reason") is None
    finally:
        browser.close()
        p.stop()


@pytest.fixture(scope="module")
def phone_server():
    srv = FlaskTestServer(config_file=_copy_example("igt_phone", rows=[LONG]))
    if not srv.start():
        pytest.fail("could not start the phone config")
    yield srv
    srv.stop()


def test_columns_wrap_on_a_phone(phone_server):
    with mobile_page("iPhone 13", phone_server.base_url) as page:
        _login(page, phone_server, "igt_phone")
        page.goto("/annotate")
        page.wait_for_selector(".igt-word[data-index='10']")
        assert not layout_problems(page, reachable=[
            ".igt-input[data-index='0'][data-tier='morphemes']",
            ".igt-input[data-index='10'][data-tier='gloss']", ".igt-translation", "#next-btn"])
        tops = page.eval_on_selector_all(
            ".igt-word[data-index]", "els => els.map(e => Math.round(e.getBoundingClientRect().top))")
        assert len(set(tops)) >= 3, f"columns did not wrap: {tops}"
        # Each column keeps its lines stacked: the gloss sits under its segmentation.
        m = _cell(page, 3, "morphemes").bounding_box()
        g = _cell(page, 3, "gloss").bounding_box()
        assert abs(m["x"] - g["x"]) < 1 and g["y"] > m["y"]
        if SHOTS:
            page.screenshot(path=os.path.join(SHOTS, "igt_phone.png"), full_page=True)
