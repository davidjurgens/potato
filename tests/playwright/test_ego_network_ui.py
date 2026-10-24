"""
ego_network in a real browser, on a survey page and on annotation items.

Survey page: name three people (typed, Enter and the Add button), add one of
them to a second name generator, answer the per-person questions, complete
the dyad census, then on the sociogram draw a tie with two real mouse clicks,
drag a node, and remove and re-add a tie from the keyboard list. After a
reload (a survey page has no Previous/Next item), every stage shows the
saved state, and the answer is in the participant's user_state.json on disk.

Annotation items: the network drawn on item 1 is gone on item 2 and back,
visibly, after Previous.

Phone: the page and the sociogram fit an iPhone-sized screen.
"""

import glob
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
EXAMPLE = os.path.join(REPO, "examples", "advanced", "ego-network")
IGNORE = shutil.ignore_patterns("annotation_output", "*.sqlite*", ".potato_cache", "layouts")


def _copy(name):
    work = os.path.join(create_test_directory(name), "ego-network")
    shutil.copytree(EXAMPLE, work, ignore=IGNORE)
    return work


@pytest.fixture(scope="module")
def survey_server():
    work = _copy("ego_network_ui")
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the ego network example")
    srv.work = work
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def item_server():
    work = _copy("ego_network_items")
    path = os.path.join(work, "config.yaml")
    with open(path) as f:
        config = yaml.safe_load(f)
    config.pop("phases")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        pytest.fail("could not start the item config")
    yield srv
    srv.stop()


def _browser(server, user):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch()
    page = browser.new_page(base_url=server.base_url, viewport={"width": 1200, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    return p, browser, page, errors


def _answer(page, form="form.ego-network"):
    raw = page.eval_on_selector(f"{form} .ego-network-input", "e => e.value")
    return json.loads(raw) if raw else {}


def _chips(page, form="form.ego-network"):
    return page.eval_on_selector_all(f"{form} .en-chip-name", "els => els.map(e => e.textContent)")


def _node_center(page, alter):
    box = page.locator(f".en-node[data-alter='{alter}'] .en-node-circle").bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _step(page, title):
    page.click(f".en-step:has-text('{title}')")
    page.wait_for_selector(f".en-stage-title:has-text('{title}')")


def test_survey_page_full_network_and_reload(survey_server):
    p, browser, page, errors = _browser(survey_server, "en_survey")
    try:
        page.goto("/")
        page.wait_for_selector(".en-name-input")
        form = "form.ego-network"
        # Empty and required: the page says what is missing.
        assert "name at least 1 person" in page.get_attribute(form, "data-incomplete-reason")

        page.click(".en-name-input")
        page.keyboard.type("Ann")
        page.keyboard.press("Enter")
        page.keyboard.type("Bob")
        page.click(".en-add-btn")
        page.fill(".en-name-input", "Cy")
        page.keyboard.press("Enter")
        assert _chips(page) == ["Ann", "Bob", "Cy"]
        # The same name twice is refused with a message, not added.
        page.fill(".en-name-input", "ann")
        page.keyboard.press("Enter")
        assert page.inner_text(".en-msg") == "Ann is already on this list."
        assert _chips(page) == ["Ann", "Bob", "Cy"]

        page.click(".en-next")
        page.wait_for_selector(".en-stage-title:has-text('Practical help')")
        # Typing someone named in the first list points at the button instead.
        page.fill(".en-name-input", "Bob")
        page.keyboard.press("Enter")
        assert "You already named Bob" in page.inner_text(".en-msg")
        assert _chips(page) == []
        page.click(".en-chip-add:has-text('Ann')")
        assert _chips(page) == ["Ann"]

        page.click(".en-next")
        for alter, rel, close in (("a1", "family", "very"), ("a2", "friend", "somewhat"), ("a3", "coworker", "not")):
            card = f".en-card[data-alter='{alter}']"
            page.click(f"{card} [data-question=relationship] .en-option[data-value={rel}]")
            page.click(f"{card} [data-question=closeness] .en-option[data-value={close}]")
        page.fill(".en-card[data-alter='a1'] [data-question=years_known] input", "12")
        assert page.locator(".en-card.en-card-done").count() == 1

        page.click(".en-next")
        for choice in ("yes", "no", "yes"):          # Ann-Bob, Ann-Cy, Bob-Cy
            page.click(f".en-pair-options .en-option[data-answer={choice}]")
        assert page.inner_text(".en-census-head .en-count") == "3 answered"

        page.click(".en-next")
        page.wait_for_selector(".en-sociogram")
        assert page.locator(".en-tie").count() == 2  # the census ties
        # A tie drawn with two real clicks: Ann, then Cy.
        page.mouse.click(*_node_center(page, "a1"))
        assert page.get_attribute(".en-node[data-alter='a1']", "aria-pressed") == "true"
        page.mouse.click(*_node_center(page, "a3"))
        assert page.locator(".en-tie").count() == 3
        assert page.locator(".en-node-selected").count() == 0
        # Drag Bob somewhere else.
        x, y = _node_center(page, "a2")
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x - 80, y - 120, steps=8)
        page.mouse.up()
        moved = _answer(page)["positions"]["a2"]
        # Keyboard: select Cy, remove and re-add the tie to Ann from the list.
        page.focus(".en-node[data-alter='a3']")
        page.keyboard.press("Enter")
        toggle = ".en-tie-panel .en-tie-toggle[data-alter='a1']"
        assert page.get_attribute(toggle, "aria-checked") == "true"
        page.click(toggle)
        assert page.locator(".en-tie").count() == 2
        page.click(toggle)
        assert page.locator(".en-tie").count() == 3
        page.keyboard.press("Escape")
        assert page.locator(".en-tie-panel").count() == 0

        answer = _answer(page)
        assert sorted(map(tuple, answer["ties"])) == [("a1", "a2"), ("a1", "a3"), ("a2", "a3")]
        assert answer["census"]["a1|a3"] is True       # the census follows the drawn tie
        assert answer["attributes"]["a1"] == {"discuss": True, "help": True, "relationship": "family",
                                              "closeness": "very", "years_known": 12}
        assert page.get_attribute(form, "data-incomplete-reason") is None
        page.wait_for_timeout(1500)

        # What the server stored, read from disk.
        states = glob.glob(os.path.join(survey_server.work, "annotation_output", "**", "en_survey",
                                        "user_state.json"), recursive=True)
        assert states, "no user_state.json for the participant"
        with open(states[0]) as f:
            stored = json.dumps(json.load(f))
        assert '\\"name\\": \\"Cy\\"' in stored or '\\"name\\":\\"Cy\\"' in stored

        page.reload()
        page.wait_for_selector(".en-chip-name")
        assert _chips(page) == ["Ann", "Bob", "Cy"]
        _step(page, "About each person")
        checked = page.eval_on_selector_all(".en-option[aria-checked=true]", "els => els.map(e => e.dataset.value)")
        assert checked == ["family", "very", "friend", "somewhat", "coworker", "not"]
        assert page.input_value(".en-card[data-alter='a1'] [data-question=years_known] input") == "12"
        _step(page, "Who knows whom")
        page.click(".en-pairs summary")
        states = page.eval_on_selector_all(".en-pair-state", "els => els.map(e => e.textContent)")
        assert states == ["Yes", "Yes", "Yes"]      # Ann-Cy was switched to a tie on the map
        _step(page, "Your network map")
        assert page.locator(".en-tie").count() == 3
        transform = page.get_attribute(".en-node[data-alter='a2']", "transform")
        assert transform == f"translate({moved[0] * 1000} {moved[1] * 1000})"
        assert all(s.endswith("(done)") for s in page.eval_on_selector_all(
            ".en-step", "els => els.slice(0, 4).map(e => e.getAttribute('aria-label'))"))
        assert not errors, errors

        page.screenshot(path=os.path.join(survey_server.work, "sociogram.png"), full_page=True)
    finally:
        browser.close()
        p.stop()


def test_fits_a_phone(survey_server):
    with mobile_page("iPhone 13", survey_server.base_url) as page:
        req = page.context.request
        req.post(f"{survey_server.base_url}/register", form={"action": "signup", "email": "en_phone", "pass": "pass"})
        req.post(f"{survey_server.base_url}/auth", form={"action": "login", "email": "en_phone", "pass": "pass"})
        page.goto("/")
        page.wait_for_selector(".en-name-input")
        assert not layout_problems(page, reachable=[".en-name-input", ".en-add-btn", ".en-next", "#next-btn"])
        for name in ("Alexandra", "Bartholomew", "Christopher", "Dee"):
            page.fill(".en-name-input", name)
            page.keyboard.press("Enter")
        page.click(".en-step:has-text('Your network map')")
        page.wait_for_selector(".en-sociogram")
        assert not layout_problems(page, reachable=[".en-sociogram", ".en-back"])
        page.tap(".en-node[data-alter='a1'] .en-node-circle")
        page.tap(".en-node[data-alter='a2'] .en-node-circle")
        assert page.locator(".en-tie").count() == 1
        page.screenshot(path=os.path.join(survey_server.work, "phone.png"), full_page=True)


# Runs last: FlaskTestServer servers share one process, so starting the item
# config replaces the survey config for every server in this module.
def test_annotation_items_navigate_away_and_back(item_server):
    p, browser, page, errors = _browser(item_server, "en_items")
    try:
        page.goto("/annotate")
        form = "form#described_network"
        page.wait_for_selector(f"{form} .en-name-input")
        first = page.input_value("#instance_id")
        for name in ("Mara", "Theo"):
            page.fill(f"{form} .en-name-input", name)
            page.keyboard.press("Enter")
        page.click(f"{form} .en-card[data-alter='a1'] .en-option[data-value=family]")
        page.click(f"{form} .en-card[data-alter='a2'] .en-option[data-value=friend]")
        page.click(f"{form} .en-pair-options .en-option[data-answer=yes]")
        assert page.get_attribute(form, "data-incomplete-reason") is None
        page.wait_for_timeout(1500)

        page.click("#next-btn")
        page.wait_for_function(f"document.getElementById('instance_id').value !== '{first}'")
        page.wait_for_selector(f"{form} .en-name-input")
        assert _chips(page, form) == []
        assert not _answer(page, form)

        page.click("#prev-btn")
        page.wait_for_function(f"document.getElementById('instance_id').value === '{first}'")
        page.wait_for_selector(f"{form} .en-chip-name")
        assert _chips(page, form) == ["Mara", "Theo"]
        checked = page.eval_on_selector_all(f"{form} .en-card .en-option[aria-checked=true]",
                                            "els => els.map(e => e.dataset.value)")
        assert checked == ["family", "friend"]
        assert page.get_attribute(f"{form} .en-pair-options .en-option[data-answer=yes]", "aria-checked") == "true"
        assert page.get_attribute(form, "data-incomplete-reason") is None

        stored = page.context.request.get(f"{item_server.base_url}/get_annotations?instance_id={first}").text()
        assert "Mara" in stored
        assert not errors, errors
    finally:
        browser.close()
        p.stop()
