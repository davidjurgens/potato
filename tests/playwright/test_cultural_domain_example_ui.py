"""
The cultural-domain example in a real browser.

The free list sits on a prestudy phase page (which posts ``instance_id:
__phase_page__``), so this checks that it saves there and comes back on a
reload; the triad test takes its domain from the item (``items_field``),
which the page fetches from ``/api/instance_data``; and both pages fit a
phone.
"""

import json
import os
import shutil

import pytest

pytest.importorskip("playwright.sync_api")

from potato.cultural_domain.triads import shown_plan  # noqa: E402
from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems, mobile_page  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "cultural-domain")
SCRATCH = os.environ.get("POTATO_SCREENSHOT_DIR")
VEGETABLES = ["carrot", "potato", "onion", "garlic", "lettuce", "spinach", "cabbage"]
FRUIT = ["apple", "banana", "cherry", "grape", "lemon", "lime", "mango", "orange", "pear"]


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("cultural_domain_example_ui"), "cultural-domain")
    if os.path.exists(work):
        shutil.rmtree(work)
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache", "layouts"))
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the cultural-domain example")
    yield srv
    srv.stop()


def _login(page, server, user):
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})


def test_phase_page_free_list_then_item_triads(server):
    from playwright.sync_api import sync_playwright
    user = "ex_user"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(base_url=server.base_url)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        _login(page, server, user)
        page.goto("/")
        page.wait_for_selector(".fl-entry")
        assert page.evaluate("window.config.is_annotation_page") is False
        page.click(".fl-entry")
        for word in ["mango", "apple", "pear"]:
            page.keyboard.type(word)
            page.keyboard.press("Enter")
        page.wait_for_timeout(1500)
        page.reload()
        page.wait_for_selector(".fl-item")
        assert page.eval_on_selector_all(".fl-item-text", "els => els.map(e => e.textContent)") == \
            ["mango", "apple", "pear"]

        page.click("#next-btn")
        page.wait_for_selector("form.triad-test .tt-option")
        page.wait_for_function("document.getElementById('instance_id').value === 'fruit'")
        _design, expected = shown_plan(FRUIT, "triads", user, "fruit")
        page.wait_for_function("document.querySelector('.tt-progress').textContent.startsWith('Triad 1 of 12')")
        first = page.eval_on_selector_all(".tt-option .tt-item", "els => els.map(e => e.textContent)")
        assert first == expected[0]
        # The card sort on the same page still gets its items.
        assert page.locator(".card-sort-card").count() == 9
        if SCRATCH:
            page.screenshot(path=os.path.join(SCRATCH, "cd_item_desktop.png"), full_page=True)

        # The example makes the triads required, so Next waits for all twelve.
        page.click(".tt-option[data-position='1']")
        page.click("#next-btn")
        page.wait_for_timeout(500)
        assert page.evaluate("document.getElementById('instance_id').value") == "fruit"
        for _ in range(11):
            page.wait_for_timeout(350)
            page.click(".tt-option[data-position='0']")
        page.wait_for_selector(".tt-done:not([hidden])")
        page.wait_for_timeout(1500)
        page.click("#next-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'vegetables'")
        page.wait_for_function("document.querySelector('.tt-progress').textContent.startsWith('Triad 1 of 7')")
        veg = page.eval_on_selector_all(".tt-option .tt-item", "els => els.map(e => e.textContent)")
        assert veg == shown_plan(VEGETABLES, "triads", user, "vegetables")[1][0]
        page.click("#prev-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'fruit'")
        page.wait_for_function("document.querySelector('.tt-progress').textContent.includes('12 answered')")
        stored = json.loads(page.eval_on_selector(".triad-test-input", "e => e.value"))
        assert stored["design"] == "steiner" and stored["triads"][0][3] == expected[0][1]
        assert not errors, errors
        browser.close()


@pytest.mark.parametrize("device", ["iPhone 13"])
def test_pages_fit_a_phone(server, device):
    with mobile_page(device, server.base_url) as page:
        _login(page, server, "ex_phone")
        page.goto("/")
        page.wait_for_selector(".fl-entry")
        page.click(".fl-entry")
        for word in ["a very long name for a kind of fruit that wraps", "fig", "kiwi"]:
            page.keyboard.type(word)
            page.keyboard.press("Enter")
        assert not layout_problems(page, reachable=[".fl-entry", ".fl-add", ".fl-item:nth-child(1) .fl-delete"])
        if SCRATCH:
            page.screenshot(path=os.path.join(SCRATCH, "cd_freelist_phone.png"), full_page=True)
        page.wait_for_timeout(1200)
        page.click("#next-btn")
        page.wait_for_selector(".tt-option")
        page.wait_for_function("document.querySelector('.tt-progress').textContent.startsWith('Triad')")
        assert not layout_problems(page, reachable=[".tt-option[data-position='0']",
                                                    ".tt-option[data-position='2']", ".tt-next"])
        if SCRATCH:
            page.screenshot(path=os.path.join(SCRATCH, "cd_triads_phone.png"), full_page=True)
