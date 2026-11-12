"""
Annotator-chosen names cannot run script on the admin dashboard.

Usernames have no character restrictions, and the dashboard's Annotators,
Behavioral and crowd tables put them into innerHTML. A name like
``<img src=x onerror=...>`` ran in the researcher's session, which also holds
the admin API key in page JS.
"""

import pytest

pytest.importorskip("playwright.sync_api")

import requests  # noqa: E402

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.port_manager import find_free_port  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory)

pytestmark = pytest.mark.playwright

ADMIN_KEY = "untrusted-names-admin-key"
NAMES = [
    "<img src=x onerror=\"window.__pwned='img'\">",
    "x\" onmouseover=\"window.__pwned='attr'\" data-x=\"",
]


#: A scheme description reaches the admin Questions tab.
DESCRIPTION = "Pick one <img src=x onerror=\"window.__pwned='desc'\">"


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("admin_untrusted_names")
    data_file = create_test_data_file(
        test_dir, [{"id": str(i), "text": f"item {i}"} for i in range(3)])
    config_file = create_test_config(
        test_dir,
        [{"annotation_type": "radio", "name": "s", "description": DESCRIPTION,
          "labels": ["a", "b"]}],
        data_files=[data_file], admin_api_key=ADMIN_KEY)
    srv = FlaskTestServer(port=find_free_port(), config_file=config_file)
    if not srv.start():
        pytest.fail("Failed to start server")
    for name in NAMES:
        s = requests.Session()
        s.post(f"{srv.base_url}/register", data={"email": name, "pass": "pw"})
        s.post(f"{srv.base_url}/auth", data={"email": name, "pass": "pw"})
        s.get(f"{srv.base_url}/annotate")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def test_annotators_tab_shows_names_as_text(server, page):
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.route(f"{server.base_url}/**", lambda route: route.continue_(
        headers={**route.request.headers, "x-api-key": ADMIN_KEY}))
    page.goto(f"{server.base_url}/admin")
    page.click('[data-tab="annotators"]')
    body = page.locator("#annotatorsTableBody")
    page.wait_for_function(
        "document.querySelectorAll('#annotatorsTableBody tr').length >= 2")
    cells = body.locator("tr td:first-child")
    cells.first.hover()
    cells.nth(1).hover()
    page.wait_for_timeout(300)

    assert page.evaluate("typeof window.__pwned") == "undefined"
    assert dialogs == []
    assert body.locator("img").count() == 0
    assert body.locator("[onmouseover]").count() == 0
    shown = cells.all_inner_texts()
    for name in NAMES:
        assert name in shown


def test_questions_tab_shows_the_description_as_text(server, page):
    page.route(f"{server.base_url}/**", lambda route: route.continue_(
        headers={**route.request.headers, "x-api-key": ADMIN_KEY}))
    page.goto(f"{server.base_url}/admin")
    page.click('[data-tab="questions"]')
    desc = page.locator("#questions .question-description").first
    desc.wait_for(state="attached", timeout=10_000)
    page.wait_for_timeout(300)
    assert page.evaluate("typeof window.__pwned") == "undefined"
    assert page.locator("#questions .question-description img").count() == 0
    assert "<img" in desc.inner_text()
