"""
price_list, bdm and belief_elicitation in a real browser.

* price_list: clicking picks one option per row; with single_switch a click
  fills the later (B) or earlier (A) rows and the page shows it; without it a
  second switch is recorded and flagged; choices survive navigating away and
  back (visual state: aria-checked on the buttons); the arrow keys choose
  without moving to another item; the list fits a phone.
* belief_elicitation bins: the total indicator follows the entries, the
  question reports itself incomplete until the points sum to 100, and the bars
  and values survive navigating away and back.
* bdm and the point report store what was entered.
* The phase-page path (the example project's post-study page) renders and
  saves a price list too.

Set POTATO_SHOTS=<dir> to also write screenshots there.
"""

import json
import os
import shutil

import pytest
import yaml

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems, mobile_page  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "incentivized-elicitation")
SHOTS = os.environ.get("POTATO_SHOTS")

SCHEMES = [
    {"annotation_type": "price_list", "name": "risk", "preset": "holt_laury",
     "single_switch": True, "description": "Choose the option you prefer in each decision."},
    {"annotation_type": "price_list", "name": "free", "description": "Free price list",
     "rows": [{"a": "$1 now", "b": "$2 later"}, {"a": "$1 now", "b": "$3 later"},
              {"a": "$1 now", "b": "$4 later"}, {"a": "$1 now", "b": "$5 later"}]},
    {"annotation_type": "belief_elicitation", "name": "dist", "mode": "bins",
     "description": "Spread 100 points over the ranges.",
     "bins": ["0 to 9", "10 to 19", "20 to 29", "30 or more"],
     "label_requirement": {"required": True}},
    {"annotation_type": "belief_elicitation", "name": "chance",
     "description": "How likely is it?"},
    {"annotation_type": "bdm", "name": "wtp", "max": 10,
     "description": "What is the most you would pay for the mug?"},
]


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, f"{name}.png"), full_page=True)


@pytest.fixture(scope="module")
def server():
    work = create_test_directory("incentive_elicitation_ui")
    data = os.path.join(work, "data.jsonl")
    with open(data, "w") as f:
        for i in range(1, 4):
            f.write(json.dumps({"id": f"item_{i}", "text": f"Item number {i}."}) + "\n")
    config = {
        "annotation_task_name": "Incentive widgets UI test",
        "task_dir": work,
        "output_annotation_dir": os.path.join(work, "annotation_output"),
        "data_files": [data],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "annotation_schemes": SCHEMES,
        "user_config": {"allow_all_users": True},
        "alert_time_each_instance": 0,
        "site_dir": "default",
    }
    path = os.path.join(work, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        pytest.fail("could not start the incentive widgets config")
    yield srv
    srv.stop()


def _login(page, base_url, user):
    req = page.context.request
    req.post(f"{base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})


def _open(server, user, viewport=None):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch()
    page = browser.new_page(base_url=server.base_url, viewport=viewport or {"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    _login(page, server.base_url, user)
    page.goto("/annotate")
    page.wait_for_selector("form#risk .pl-row")
    return p, browser, page, errors


def _answer(page, schema):
    raw = page.eval_on_selector(f"form#{schema} .incentive-input", "e => e.value")
    return json.loads(raw) if raw else {}


def _checked(page, schema):
    return page.eval_on_selector_all(
        f"form#{schema} .pl-row",
        "rows => rows.map(r => { const b = r.querySelector('.pl-choice[aria-checked=\"true\"]');"
        " return b ? b.dataset.choice : null; })")


def test_single_switch_fills_rows_and_survives_navigation(server):
    p, browser, page, errors = _open(server, "ie_switch")
    try:
        assert page.get_attribute("form#risk", "data-incomplete-reason")
        page.click("form#risk .pl-choice[data-row='5'][data-choice='B']")
        assert _checked(page, "risk") == [None] * 5 + ["B"] * 5
        page.click("form#risk .pl-choice[data-row='3'][data-choice='A']")
        assert _checked(page, "risk") == ["A"] * 4 + [None] + ["B"] * 5
        assert "decision 5" in page.get_attribute("form#risk", "data-incomplete-reason")
        page.click("form#risk .pl-choice[data-row='4'][data-choice='B']")
        assert _checked(page, "risk") == ["A"] * 4 + ["B"] * 6
        # A later A pushes the switch point down: there is still one switch.
        page.click("form#risk .pl-choice[data-row='6'][data-choice='A']")
        assert _checked(page, "risk") == ["A"] * 7 + ["B"] * 3
        assert page.get_attribute("form#risk", "data-incomplete-reason") is None
        assert "switch to Option B at decision 8" in page.inner_text("form#risk .iw-status")
        answer = _answer(page, "risk")
        assert answer == {"choices": ["A"] * 7 + ["B"] * 3, "switches": 1, "multiple_switching": False}
        _shot(page, "desktop_price_list")

        page.fill("form#dist .be-bin-input[data-bin='0']", "100")   # the required question
        page.wait_for_timeout(1500)   # autosave debounce
        page.click("#next-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'item_2'")
        page.wait_for_selector("form#risk .pl-row")
        assert _checked(page, "risk") == [None] * 10
        page.fill("form#dist .be-bin-input[data-bin='0']", "100")
        page.wait_for_timeout(300)
        page.click("#prev-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'item_1'")
        page.wait_for_selector("form#risk .pl-row")
        page.wait_for_function(
            "document.querySelectorAll('form#risk .pl-choice[aria-checked=\"true\"]').length === 10")
        assert _checked(page, "risk") == ["A"] * 7 + ["B"] * 3
        assert page.get_attribute("form#risk", "data-incomplete-reason") is None
        stored = page.context.request.get(f"{server.base_url}/get_annotations?instance_id=item_1").json()
        assert "risk" in json.dumps(stored)
        assert not errors, errors
    finally:
        browser.close()
        p.stop()


def test_free_list_records_multiple_switching(server):
    p, browser, page, errors = _open(server, "ie_free")
    try:
        for row, choice in enumerate("ABAB"):
            page.click(f"form#free .pl-choice[data-row='{row}'][data-choice='{choice}']")
        assert _checked(page, "free") == list("ABAB")
        answer = _answer(page, "free")
        assert answer["switches"] == 3 and answer["multiple_switching"] is True
        assert not errors, errors
    finally:
        browser.close()
        p.stop()


def test_arrow_keys_choose_without_leaving_the_item(server):
    p, browser, page, errors = _open(server, "ie_keys")
    try:
        page.focus("form#free .pl-choice[data-row='0'][data-choice='A']")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("ArrowLeft")
        assert _checked(page, "free")[:2] == ["B", "A"]
        assert page.evaluate("document.activeElement.dataset.row") == "1"
        assert page.eval_on_selector("#instance_id", "e => e.value") == "item_1"
        focus = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
        assert focus != "none"
    finally:
        browser.close()
        p.stop()


def test_bins_total_indicator_and_persistence(server):
    p, browser, page, errors = _open(server, "ie_bins")
    try:
        form = "form#dist"
        assert page.get_attribute(f"{form} .be-total", "data-state") == "empty"
        page.fill(f"{form} .be-bin-input[data-bin='0']", "30")
        page.fill(f"{form} .be-bin-input[data-bin='1']", "50")
        assert page.inner_text(f"{form} .be-sum") == "80"
        assert page.get_attribute(f"{form} .be-total", "data-state") == "under"
        assert "20 left" in page.inner_text(f"{form} .be-left")
        assert "now 80" in page.get_attribute(form, "data-incomplete-reason")
        page.fill(f"{form} .be-bin-input[data-bin='2']", "40")
        assert page.get_attribute(f"{form} .be-total", "data-state") == "over"
        assert "20 too many" in page.inner_text(f"{form} .be-left")
        # Next is refused while the total is wrong.
        page.click("#next-btn")
        page.wait_for_timeout(500)
        assert page.eval_on_selector("#instance_id", "e => e.value") == "item_1"
        _shot(page, "desktop_bins_over")
        page.fill(f"{form} .be-bin-input[data-bin='2']", "20")
        assert page.get_attribute(f"{form} .be-total", "data-state") == "done"
        assert page.get_attribute(form, "data-incomplete-reason") is None
        assert _answer(page, "dist") == {"bins": [30, 50, 20, 0]}
        width = page.eval_on_selector(f"{form} .be-bin[data-bin='1'] .be-bar-fill", "e => e.style.width")
        assert width == "50%"
        # The point report and the bid, while we are here.
        # A click on the untouched thumb at 50% is an answer, though no input event fires.
        page.click("form#chance .be-slider")
        assert _answer(page, "chance") == {"report": 50}
        assert page.inner_text("form#chance .be-value") == "50%"
        page.eval_on_selector("form#chance .be-slider",
                              "e => { e.value = 70; e.dispatchEvent(new Event('input', {bubbles: true})); }")
        assert _answer(page, "chance") == {"report": 70}
        assert page.inner_text("form#chance .be-value") == "70%"
        page.fill("form#wtp .bdm-number", "12")
        assert page.get_attribute("form#wtp", "data-incomplete-reason")
        assert _answer(page, "wtp") == {}
        page.fill("form#wtp .bdm-number", "4.5")
        assert _answer(page, "wtp") == {"bid": 4.5}
        _shot(page, "desktop_all")
        if SHOTS:
            page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
            _shot(page, "desktop_all_dark")
            page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")

        page.wait_for_timeout(1500)
        page.click("#next-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'item_2'")
        page.wait_for_selector(f"{form} .be-bin")
        assert page.inner_text(f"{form} .be-sum") == "0"
        page.click("#prev-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'item_1'")
        page.wait_for_function("document.querySelector('form#dist .be-sum').textContent === '100'")
        values = page.eval_on_selector_all(f"{form} .be-bin-input", "els => els.map(e => e.value)")
        assert values == ["30", "50", "20", "0"]
        assert page.get_attribute(f"{form} .be-total", "data-state") == "done"
        assert page.eval_on_selector(f"{form} .be-bin[data-bin='0'] .be-bar-fill",
                                     "e => e.style.width") == "30%"
        assert page.inner_text("form#chance .be-value") == "70%"
        assert page.input_value("form#wtp .bdm-number") == "4.5"
        assert not errors, errors
    finally:
        browser.close()
        p.stop()


def test_fits_a_phone(server):
    with mobile_page("iPhone 13", server.base_url) as page:
        _login(page, server.base_url, "ie_phone")
        page.goto("/annotate")
        page.wait_for_selector("form#risk .pl-row")
        page.tap("form#risk .pl-choice[data-row='4'][data-choice='B']")
        assert _checked(page, "risk")[4:] == ["B"] * 6
        _shot(page, "phone")
        assert not layout_problems(page, reachable=[
            "form#risk .pl-choice[data-row='0'][data-choice='A']",
            "form#risk .pl-choice[data-row='9'][data-choice='B']",
            "form#dist .be-bin-input[data-bin='3']", "form#wtp .bdm-number",
            "form#chance .be-slider"])
        small = page.eval_on_selector_all(
            "form#risk .pl-choice", "els => els.filter(e => e.getBoundingClientRect().height < 44).length")
        assert small == 0


@pytest.fixture(scope="module")
def example_server():
    work = os.path.join(create_test_directory("incentive_elicitation_example"), "example")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", "layouts", ".potato_cache"))
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the incentivized-elicitation example")
    srv.work_dir = work
    yield srv
    srv.stop()


def test_example_runs_through_to_the_phase_page(example_server):
    """Items carry the belief question; the price list and the bid are on a
    post-study phase page, the other render path."""
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch()
    page = browser.new_page(base_url=example_server.base_url)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        _login(page, example_server.base_url, "ie_example")
        page.goto("/annotate")
        page.wait_for_selector("#next-btn")
        page.click("#next-btn")                 # the instructions page
        page.wait_for_selector("form#forecast .be-slider")
        # The outcome that settles the payment never reaches the page.
        assert '"outcome"' not in page.content()
        _shot(page, "example_forecast")
        for i in range(4):
            page.wait_for_selector("form#forecast .be-slider")
            current = page.eval_on_selector("#instance_id", "e => e.value")
            page.eval_on_selector("form#forecast .be-slider",
                                  "(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); }",
                                  20 + 10 * i)
            page.wait_for_timeout(300)
            page.click("#next-btn")
            page.wait_for_function(
                "prev => { const e = document.getElementById('instance_id');"
                " return !document.querySelector('form#forecast') || (e && e.value !== prev); }",
                arg=current)
        page.wait_for_selector("form#risk .pl-row", timeout=10000)
        page.click("form#risk .pl-choice[data-row='5'][data-choice='B']")
        page.click("form#risk .pl-choice[data-row='4'][data-choice='A']")
        page.fill("form#voucher .bdm-number", "3")
        _shot(page, "example_decisions")
        assert page.get_attribute("form#risk", "data-incomplete-reason") is None
        assert json.loads(page.eval_on_selector("form#risk .incentive-input", "e => e.value"))["choices"] \
            == ["A"] * 5 + ["B"] * 5
        page.wait_for_timeout(1500)
        page.click("#next-btn")
        page.wait_for_function("!document.querySelector('form#risk')")
        _shot(page, "example_after")
        assert not errors, errors
    finally:
        browser.close()
        p.stop()

    # The finished participant's answers, paid from what was stored.
    from potato.export.cli import build_export_context
    from potato.export.incentives_exporter import IncentivesExporter
    config_path = os.path.join(example_server.work_dir, "config.yaml")
    context = build_export_context(config_path)
    out = os.path.join(os.path.dirname(config_path), "export")
    result = IncentivesExporter().export(context, out)
    assert result.success, result.errors
    import csv
    with open(os.path.join(out, "bonuses.csv")) as f:
        rows = [r for r in csv.DictReader(f) if r["user_id"] == "ie_example"]
    assert {r["rule"] for r in rows} == {"forecast", "risk", "voucher"}
    assert len([r for r in rows if r["rule"] == "forecast"]) == 4
    assert all(r["finished"] == "1" for r in rows)
    assert sum(int(r["paid"]) for r in rows) == 1          # pay: one_random_item
    voucher = next(r for r in rows if r["rule"] == "voucher")
    assert json.loads(voucher["draws"])["bought"] == (3 >= json.loads(voucher["draws"])["price"])
