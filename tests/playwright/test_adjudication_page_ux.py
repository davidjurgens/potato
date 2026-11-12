"""Adjudication page: defaults, keyboard access and form gestures.

Each test drives the real page with real clicks and keys. Every one of these
failed against the page as it was on 2026-10-08:

* the confidence select was reset to "medium" on every item, so
  ``require_confidence`` never fired and every decision went out with a
  confidence nobody chose;
* reopening a decided item wiped the metadata saved with it, because the
  reset ran after the restore;
* queue entries were ``<div>``s, so Tab never reached the queue;
* clicking an error-type tag's text toggled its checkbox twice -- once in a
  click handler and once by the label itself -- and left it unchanged.

Runs against a copy of ``examples/advanced/machine-annotators``, whose
adjudicator (``lead_curator``) logs in without a password and whose queue is
populated by its setup script.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "machine-annotators")


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("adjudication_page_ux"), "machine-annotators")
    if os.path.exists(work):
        shutil.rmtree(work)
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "project.sqlite*", "test_config_port_*"))
    subprocess.run([sys.executable, os.path.join(work, "setup_demo.py")],
                   check=True, capture_output=True)
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the example server")
    yield srv
    srv.stop()


@pytest.fixture()
def page(server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.request.post(f"{server.base_url}/auth",
                             form={"email": "lead_curator", "pass": ""})
        pg = context.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"{server.base_url}/adjudicate")
        # The first pending item opens on its own on a wide screen; click it
        # if it did not, so the remaining tests check one thing each.
        try:
            pg.wait_for_selector("#adj-item-view .adj-radio-option", timeout=4000)
        except Exception:
            pg.locator(".adj-queue-item").first.click()
            pg.wait_for_selector("#adj-item-view .adj-radio-option")
        pg.errors = errors
        yield pg
        browser.close()


def _open_item_id(page):
    return page.inner_text("#adj-item-id").replace("Item:", "").strip()


def test_confidence_starts_empty_and_blocks_submit(page, server):
    item_id = _open_item_id(page)
    assert page.eval_on_selector("#adj-confidence", "e => e.value") == "", \
        "confidence must not be preselected; it was reset to 'medium' on every item"

    page.locator(".adj-radio-option").first.click()
    page.click("#adj-btn-submit")

    error = page.locator("#adj-confidence-error")
    error.wait_for()
    assert "require_confidence" in error.inner_text()
    assert page.get_attribute("#adj-confidence", "aria-invalid") == "true"
    assert page.evaluate("document.activeElement.id") == "adj-confidence"
    # Nothing reached the server: the item still has no decision.
    detail = page.context.request.get(
        f"{server.base_url}/adjudicate/api/item/{item_id}").json()
    assert not detail.get("decision"), "a decision was saved without a confidence"
    assert _open_item_id(page) == item_id, "the page moved on without saving"


def test_reopened_decision_keeps_its_metadata(page, server):
    item_id = _open_item_id(page)
    page.locator(".adj-radio-option").first.click()
    page.select_option("#adj-confidence", "low")
    page.fill("#adj-notes", "checked against the reference")
    page.click("#adj-btn-submit")
    page.wait_for_function(
        "id => !document.querySelector('#adj-item-id').textContent.includes(id)",
        arg=item_id)

    saved = page.context.request.get(
        f"{server.base_url}/adjudicate/api/item/{item_id}").json()["decision"]
    assert saved["confidence"] == "low"

    # Back to it: the saved confidence and notes must be on screen.
    page.click("#adj-btn-prev")
    page.wait_for_function(
        "id => document.querySelector('#adj-item-id').textContent.includes(id)",
        arg=item_id)
    page.wait_for_function(
        "() => document.querySelector('#adj-confidence').value === 'low'")
    assert page.input_value("#adj-notes") == "checked against the reference"


def test_queue_is_reachable_and_walkable_by_keyboard(page):
    entries = page.locator(".adj-queue-item")
    assert entries.count() >= 2
    assert page.evaluate(
        "[...document.querySelectorAll('.adj-queue-item')].every(e => e.tagName === 'BUTTON')")

    # Tab from the last filter button lands in the queue, on the open item.
    page.locator(".adj-filter-btn").last.focus()
    page.keyboard.press("Tab")
    focused = page.evaluate("document.activeElement.className")
    assert "adj-queue-item" in focused, f"Tab went to {focused!r}, not the queue"
    assert "active" in focused

    # One Tab stop for the whole queue; arrows move within it.
    assert page.evaluate(
        "[...document.querySelectorAll('.adj-queue-item')].filter(e => e.tabIndex === 0).length") == 1
    target = page.evaluate(
        "document.querySelectorAll('.adj-queue-item')[1].dataset.instanceId")
    page.keyboard.press("ArrowDown")
    assert page.evaluate("document.activeElement.dataset.instanceId") == target
    page.keyboard.press("Enter")
    page.wait_for_function(
        "id => document.querySelector('#adj-item-id').textContent.includes(id)", arg=target)


def test_clicking_an_error_tag_label_checks_it(page):
    tag = page.locator(".adj-error-tag").first
    tag.scroll_into_view_if_needed()
    box = tag.bounding_box()
    # Click the words, well away from the checkbox itself.
    page.mouse.click(box["x"] + box["width"] - 20, box["y"] + box["height"] / 2)
    assert tag.locator("input").is_checked(), \
        "the label's own toggle undid the click handler's toggle"
    assert "selected" in (tag.get_attribute("class") or "")


def test_queue_entries_carry_a_text_preview(page, server):
    queue = page.context.request.get(f"{server.base_url}/adjudicate/api/queue").json()
    previews = [i.get("text_preview") for i in queue["items"]]
    assert previews and all(isinstance(t, str) and t for t in previews)
    first = page.locator(".adj-queue-item .adj-queue-item-preview").first
    assert first.inner_text().strip()
    assert not page.errors, page.errors


def test_each_annotator_is_listed_once(page):
    cards = page.locator(".adj-annotator-card")
    names = [cards.nth(i).get_attribute("data-annotator") for i in range(cards.count())]
    assert names and len(names) == len(set(names)), \
        f"an annotator appears more than once in the overview: {names}"
    # Signal flags therefore appear at most once per annotator.
    for i in range(cards.count()):
        assert cards.nth(i).locator(".adj-signal-flags").count() <= 1
