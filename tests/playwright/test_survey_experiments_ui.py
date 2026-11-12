"""
list_experiment and randomized_response in a real browser, as annotation
items: the count and both randomized-response answers survive
navigate-away-and-back (the visible inputs, not just the stored answer), the
control group's page does not contain the sensitive statement, and the
layout fits a phone.
"""

import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems, mobile_page  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    create_test_config, create_test_data_file, create_test_directory)

pytestmark = pytest.mark.playwright

SENSITIVE = "Driven a car after drinking alcohol"
SCHEMES = [
    {"annotation_type": "list_experiment", "name": "lists",
     "description": "How many of these have you done in the last year?",
     "items": ["Gone to a concert", "Bought a book", "Volunteered"],
     "sensitive_item": SENSITIVE, "treatment": {"factor": "list_group", "level": "treatment"}},
    {"annotation_type": "randomized_response", "name": "cheat", "method": "crosswise",
     "description": "Read both statements.", "question": "I have copied someone's work.",
     "nonsensitive_statement": "My mother was born in January, February or March.",
     "nonsensitive_prevalence": 0.25},
    {"annotation_type": "randomized_response", "name": "tax", "method": "forced_response",
     "description": "A private random rule.", "question": "Have you left income off a tax return?"},
]


@pytest.fixture(scope="module")
def server():
    d = create_test_directory("survey_experiments_ui")
    data = create_test_data_file(d, [{"id": "a", "text": "Item A"}, {"id": "b", "text": "Item B"}])
    cfg = create_test_config(d, annotation_schemes=SCHEMES, data_files=[data])
    import yaml
    with open(cfg) as f:
        config = yaml.safe_load(f)
    config["conditions"] = {"factors": {"list_group": ["control", "treatment"]},
                            "assignment": "round_robin"}
    # Pinned: the in-process harness resolves a relative one against the cwd.
    config["output_annotation_dir"] = os.path.join(d, "annotation_output")
    with open(cfg, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    srv = FlaskTestServer(config_file=cfg)
    if not srv.start():
        pytest.fail("could not start the survey experiments server")
    yield srv
    srv.stop()


def _session(server, user):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    page.goto(f"{server.base_url}/annotate")
    page.wait_for_selector("form[data-schema-name='lists']")
    return p, browser, page, errors


def test_answers_survive_navigate_away_and_back(server):
    p, browser, page, errors = _session(server, "se_ui_1")
    try:
        number = page.locator("input[name='lists:::number']")
        number.click()
        number.fill("2")
        page.get_by_label("Exactly one statement is true").check()
        page.locator("form[data-schema-name='tax']").get_by_label("Yes", exact=True).check()
        page.wait_for_timeout(1600)
        page.click("#next-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'b'")
        assert number.input_value() == ""
        page.click("#prev-btn")
        page.wait_for_function("document.getElementById('instance_id').value === 'a'")
        page.wait_for_selector("form[data-schema-name='lists']")
        assert page.locator("input[name='lists:::number']").input_value() == "2"
        assert page.get_by_label("Exactly one statement is true").is_checked()
        assert page.locator("form[data-schema-name='tax']").get_by_label("Yes", exact=True).is_checked()
        stored = page.context.request.get(f"{server.base_url}/get_annotations?instance_id=a").text()
        assert "Exactly one statement is true" in stored and "Yes" in stored
        assert not errors, errors
    finally:
        browser.close()
        p.stop()


def test_control_page_lacks_the_sensitive_statement(server):
    """round_robin gives the two levels to successive participants; whichever
    page lacks the statement must lack it in the HTML, not just visually."""
    pages = []
    for user in ("se_ui_2", "se_ui_3"):
        p, browser, page, _ = _session(server, user)
        try:
            pages.append(page.content())
        finally:
            browser.close()
            p.stop()
    with_item = [SENSITIVE in html for html in pages]
    assert sorted(with_item) == [False, True], with_item


def test_fits_a_phone(server):
    with mobile_page("iPhone 13", server.base_url) as page:
        req = page.context.request
        req.post(f"{server.base_url}/register", form={"action": "signup", "email": "se_ph", "pass": "pass"})
        req.post(f"{server.base_url}/auth", form={"action": "login", "email": "se_ph", "pass": "pass"})
        page.goto("/annotate")
        page.wait_for_selector("form[data-schema-name='lists']")
        assert layout_problems(page) == []
