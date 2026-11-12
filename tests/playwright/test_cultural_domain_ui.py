"""
free_list and triad_test in a real browser.

free_list: typing and Enter add items in order, a repeat is refused, delete
and undo put the item back where it was with its time, a timed list cannot
be typed into before Start and locks when the time runs out, and the list
survives navigating to the next item and back (the rendered list, not just
the hidden input).

triad_test: real clicks and the 1/2/3 keys answer every triad of a Steiner
design (7 items, 7 triads, every pair once), the page shows the same triads
in the same order as potato/cultural_domain/triads.py computes for this
participant, and the answers survive navigating away and back.
"""

import itertools
import json
import os
import shutil

import pytest
import yaml

pytest.importorskip("playwright.sync_api")

from potato.cultural_domain.triads import shown_plan  # noqa: E402
from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "cultural-domain")
FRUIT = ["apple", "banana", "cherry", "grape", "lemon", "lime", "mango"]


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("cultural_domain_ui"), "project")
    if os.path.exists(work):
        shutil.rmtree(work)
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache", "layouts"))
    with open(os.path.join(work, "config.yaml")) as f:
        config = yaml.safe_load(f)
    config.pop("phases", None)
    config["output_annotation_dir"] = "annotation_output/"
    config["annotation_schemes"] = [
        {"annotation_type": "free_list", "name": "fruit_list",
         "description": "List all the kinds of fruit you can think of.", "min_items": 2},
        {"annotation_type": "free_list", "name": "timed_list",
         "description": "List as many vegetables as you can.", "time_limit_s": 2},
        {"annotation_type": "triad_test", "name": "triads",
         "description": "Triads", "labels": FRUIT},
    ]
    with open(os.path.join(work, "config.yaml"), "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the cultural domain config")
    yield srv
    srv.stop()


def _open(server, user):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch()
    page = browser.new_page(base_url=server.base_url)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto("/annotate")
    page.wait_for_selector("form#fruit_list .fl-entry")
    page.wait_for_selector("form#triads .tt-option")
    return p, browser, page, errors


def _value(page, form):
    raw = page.eval_on_selector(f"form#{form} input[type=hidden].annotation-input", "e => e.value")
    return json.loads(raw) if raw else {}


def _listed(page, form):
    return page.eval_on_selector_all(f"form#{form} .fl-item-text", "els => els.map(e => e.textContent)")


def _go(page, direction, instance):
    page.click(f"#{direction}-btn")
    page.wait_for_function(f"document.getElementById('instance_id').value === '{instance}'")
    page.wait_for_selector("form#triads .tt-option")


def test_free_list_enter_delete_undo_and_restore(server):
    p, browser, page, errors = _open(server, "fl_user")
    try:
        form = "form#fruit_list"
        assert page.get_attribute(form, "data-incomplete-reason")
        page.click(f"{form} .fl-entry")
        for word in ["apple", "banana", "Apple "]:
            page.keyboard.type(word)
            page.keyboard.press("Enter")
        assert "already on your list" in page.text_content(f"{form} .fl-status")
        # The refused text stays selected, so typing replaces it.
        page.keyboard.type("cherry")
        page.keyboard.press("Enter")
        assert _listed(page, "fruit_list") == ["apple", "banana", "cherry"]
        page.fill(f"{form} .fl-entry", "date")
        page.click(f"{form} .fl-add")
        before = _value(page, "fruit_list")
        assert before["items"] == ["apple", "banana", "cherry", "date"]
        assert before["timings_ms"] == sorted(before["timings_ms"])

        page.click(f"{form} .fl-item:nth-child(2) .fl-delete")
        assert _listed(page, "fruit_list") == ["apple", "cherry", "date"]
        assert page.is_visible(f"{form} .fl-undo")
        page.click(f"{form} .fl-undo")
        assert _listed(page, "fruit_list") == ["apple", "banana", "cherry", "date"]
        assert _value(page, "fruit_list")["timings_ms"] == before["timings_ms"]
        assert page.get_attribute(form, "data-incomplete-reason") is None
        # The list's numbers are the ranks.
        assert page.text_content(f"{form} .fl-count").startswith("4 items")
        page.wait_for_timeout(1500)

        _go(page, "next", "vegetables")
        assert _listed(page, "fruit_list") == []
        _go(page, "prev", "fruit")
        page.wait_for_selector(f"{form} .fl-item")
        assert _listed(page, "fruit_list") == ["apple", "banana", "cherry", "date"]
        assert page.text_content(f"{form} .fl-count").startswith("4 items")
        # A delete after the round trip still works and is saved.
        page.click(f"{form} .fl-item:nth-child(1) .fl-delete")
        assert _value(page, "fruit_list")["items"] == ["banana", "cherry", "date"]
        assert not errors, errors
    finally:
        browser.close()
        p.stop()


def test_timed_free_list_locks_when_time_runs_out(server):
    p, browser, page, errors = _open(server, "fl_timed")
    try:
        form = "form#timed_list"
        assert page.is_disabled(f"{form} .fl-entry")
        assert "start the timer" in page.get_attribute(form, "data-incomplete-reason")
        page.click(f"{form} .fl-start")
        assert page.is_enabled(f"{form} .fl-entry")
        page.keyboard.type("carrot")
        page.keyboard.press("Enter")
        assert _listed(page, "timed_list") == ["carrot"]
        page.wait_for_selector(f"{form} .fl-timeup", timeout=5000)
        assert page.is_disabled(f"{form} .fl-entry")
        assert page.is_disabled(f"{form} .fl-add")
        assert page.is_disabled(f"{form} .fl-delete")
        answer = _value(page, "timed_list")
        assert answer["time_up"] is True and answer["items"] == ["carrot"]
        assert answer["elapsed_ms"] == 2000
        page.wait_for_timeout(1500)

        _go(page, "next", "vegetables")
        assert not page.is_visible(f"{form} .fl-timeup")
        _go(page, "prev", "fruit")
        page.wait_for_selector(f"{form} .fl-timeup")
        assert _listed(page, "timed_list") == ["carrot"]
        assert page.is_disabled(f"{form} .fl-entry")
        assert page.text_content(f"{form} .fl-clock-value") == "0:00"
        assert not errors, errors
    finally:
        browser.close()
        p.stop()


def test_triads_answered_by_clicks_and_keys_then_restored(server):
    user = "tt_user"
    p, browser, page, errors = _open(server, user)
    try:
        form = "form#triads"
        design, expected = shown_plan(FRUIT, "triads", user, "fruit")
        assert design == "steiner" and len(expected) == 7
        shown = []
        for i in range(7):
            page.wait_for_function(
                f"document.querySelector('{form} .tt-progress').textContent.startsWith('Triad {i + 1} of 7')")
            trio = page.eval_on_selector_all(f"{form} .tt-option .tt-item", "els => els.map(e => e.textContent)")
            shown.append(trio)
            if i % 2:
                page.click(f"{form} .tt-option[data-position='{i % 3}']")
            else:
                page.focus(f"{form} .tt-option[data-position='0']")
                page.keyboard.press(str(i % 3 + 1))
            assert page.get_attribute(f"{form} .tt-option[data-position='{i % 3}']", "aria-checked") == "true"
        assert shown == expected
        # A Steiner triple system: every pair of the seven items exactly once.
        pairs = [frozenset(pr) for t in shown for pr in itertools.combinations(t, 2)]
        assert sorted(map(sorted, pairs)) == sorted(map(sorted, map(frozenset, itertools.combinations(FRUIT, 2))))

        page.wait_for_selector(f"{form} .tt-done:not([hidden])")
        assert page.get_attribute(form, "data-incomplete-reason") is None
        answer = _value(page, "triads")
        assert [t[3] for t in answer["triads"]] == [shown[i][i % 3] for i in range(7)]
        page.wait_for_timeout(1500)

        _go(page, "next", "vegetables")
        page.wait_for_timeout(300)
        assert "0 answered" in page.text_content(f"{form} .tt-progress")
        _go(page, "prev", "fruit")
        page.wait_for_function(
            f"document.querySelector('{form} .tt-progress').textContent.includes('7 answered')")
        page.click(f"{form} .tt-prev")
        assert page.text_content(f"{form} .tt-progress").startswith("Triad 6 of 7")
        assert page.get_attribute(f"{form} .tt-option[data-position='2']", "aria-checked") == "true"
        assert page.locator(f"{form} .tt-option[aria-checked='true']").count() == 1
        # Changing an answer replaces it.
        page.click(f"{form} .tt-option[data-position='0']")
        assert _value(page, "triads")["triads"][5][3] == shown[5][0]
        assert not errors, errors
    finally:
        browser.close()
        p.stop()
