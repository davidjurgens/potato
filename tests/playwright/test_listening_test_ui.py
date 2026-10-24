"""
listening_test in a real browser: the MUSHRA player loads every stimulus,
a played-and-rated trial is complete, ratings survive navigating away and
back (visual state, not just the hidden input), the number keys play samples,
and the page fits a phone.
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
EXAMPLE = os.path.join(REPO, "examples", "audio", "listening-test-mushra")


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("listening_test_ui"), "mushra")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache"))
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the listening test example")
    yield srv
    srv.stop()


def _desktop(server, user):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    page = browser.new_page(base_url=server.base_url)
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto("/annotate")
    page.wait_for_selector(".lt-row")
    return p, browser, page


def _answer(page):
    raw = page.eval_on_selector(".listening-test-input", "e => e.value")
    return json.loads(raw) if raw else {}


def test_play_rate_complete_and_restore(server):
    p, browser, page = _desktop(server, "lt_ui")
    try:
        form = "form.listening-test"
        assert page.locator(".lt-row").count() == 5
        assert page.get_attribute(form, "data-incomplete-reason")
        for i in range(1, 6):
            page.click(f".lt-play[data-slot='s{i}']")
            # A slot counts as heard after 1 s of playback; wait for that,
            # not a fixed delay (the audio clock can start late on a busy machine).
            page.wait_for_selector(f".lt-play.lt-heard[data-slot='s{i}']", timeout=15000)
        page.click(".lt-stop")
        for i, value in enumerate((100, 30, 15, 75, 60), start=1):
            page.eval_on_selector(f".lt-slider[data-slot='s{i}']",
                                  "(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); }",
                                  value)
        assert page.get_attribute(form, "data-incomplete-reason") is None
        answer = _answer(page)
        assert answer["ratings"]["s2"] == 30 and set(answer["played"]) >= {f"s{i}" for i in range(1, 6)}
        page.wait_for_timeout(1500)   # autosave debounce

        page.click("#next-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'excerpt_2'")
        page.wait_for_selector(".lt-row")
        assert not _answer(page)
        page.click("#prev-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'excerpt_1'")
        page.wait_for_selector(".lt-row .lt-value")
        page.wait_for_function("document.querySelectorAll('.lt-play.lt-heard').length === 5")
        values = page.eval_on_selector_all(".lt-value", "els => els.map(e => e.textContent)")
        assert values == ["100", "30", "15", "75", "60"]
        rated = page.eval_on_selector_all(".lt-slider.lt-rated", "els => els.length")
        assert rated == 5
        assert page.get_attribute(form, "data-incomplete-reason") is None
    finally:
        browser.close()
        p.stop()


def test_number_keys_play_samples(server):
    p, browser, page = _desktop(server, "lt_keys")
    try:
        page.focus(".lt-root")
        page.keyboard.press("3")
        page.wait_for_function(
            "document.querySelector(\".lt-play[data-slot='s3']\").getAttribute('aria-pressed') === 'true'")
        page.keyboard.press(" ")
        page.wait_for_function("!document.querySelector(\".lt-play[aria-pressed='true']\")")
    finally:
        browser.close()
        p.stop()


def test_fits_a_phone(server):
    with mobile_page("iPhone 13", server.base_url) as page:
        req = page.context.request
        req.post(f"{server.base_url}/register", form={"action": "signup", "email": "lt_phone", "pass": "pass"})
        req.post(f"{server.base_url}/auth", form={"action": "login", "email": "lt_phone", "pass": "pass"})
        page.goto("/annotate")
        page.wait_for_selector(".lt-row")
        assert not layout_problems(page, reachable=[".lt-play[data-slot='s1']", ".lt-slider[data-slot='s5']",
                                                    ".lt-stop"])


@pytest.fixture(scope="module")
def all_methods_server():
    import yaml
    work = os.path.join(create_test_directory("listening_test_methods"), "methods")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "*.sqlite*", ".potato_cache"))
    with open(os.path.join(work, "config.yaml")) as f:
        config = yaml.safe_load(f)
    config["annotation_schemes"] = [
        {"annotation_type": "listening_test", "name": m, "method": m, "description": m}
        for m in ("acr", "dcr", "ccr", "abx", "p835", "bs1116")]
    with open(os.path.join(work, "config.yaml"), "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the methods config")
    yield srv
    srv.stop()


def test_every_method_renders_and_gates_on_playback(all_methods_server):
    p, browser, page = _desktop(all_methods_server, "lt_methods")
    try:
        for m in ("acr", "dcr", "ccr", "abx", "p835", "bs1116"):
            page.wait_for_selector(f"form#{m} .lt-transport")
        # Categories stay disabled until every sample has played to the end.
        assert page.locator("form#acr .lt-category").first.is_disabled()
        page.click("form#acr .lt-play[data-slot='s1']")
        page.wait_for_function("!document.querySelector('form#acr .lt-category').disabled",
                               timeout=6000)
        page.click("form#acr .lt-category[data-index='1']")
        acr = json.loads(page.eval_on_selector("form#acr .listening-test-input", "e => e.value"))
        assert acr["rating"] == 1 and acr["played"] == ["s1"]
        assert page.get_attribute("form#acr", "data-incomplete-reason") is None
        for slot in ("A", "B", "X"):
            page.click(f"form#abx .lt-play[data-slot='{slot}']")
            page.wait_for_timeout(2300)
        page.click("form#abx .lt-category[data-index='0']")
        abx = json.loads(page.eval_on_selector("form#abx .listening-test-input", "e => e.value"))
        assert abx["choice"] == "A"
        assert page.locator("form#p835 .lt-categories").count() == 3
        assert page.locator("form#bs1116 .lt-slider").count() == 2
        assert page.locator("form#dcr .lt-play[data-slot='ref']").count() == 1
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.reload()
        page.wait_for_selector("form#abx .lt-transport")
        assert not errors
        assert page.get_attribute("form#abx .lt-category[data-index='0']", "aria-checked") == "true"
    finally:
        browser.close()
        p.stop()
