"""Pocket starts with no connection after one online visit.

Two bugs kept it from ever doing so:

* The service worker was registered at /pocket/sw.js with the default scope,
  /pocket/ (with the slash), so it never controlled the page at /pocket. Its
  cache filled and was never used; an offline reload was a browser error page.
* boot()'s offline fallback needed the task description, which only arrived
  from /pocket/api/task -- the request that had just failed.
"""

import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import mobile_page  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    cleanup_test_directory, create_test_config, create_test_data_file, create_test_directory)

ANSWER = "Unmistakable-definition-text"


@pytest.fixture(scope="module")
def server():
    d = create_test_directory("pocket_offline_ui")
    data = create_test_data_file(d, [{"id": f"i{n}", "text": f"Item number {n}."}
                                     for n in range(1, 5)])
    page = os.path.join(d, "pre.json")
    with open(page, "w") as f:
        json.dump([{"name": "concept_definition", "annotation_type": "text",
                    "description": "Define the concept."}], f)
    cfg = create_test_config(
        d, annotation_schemes=[{"name": "fits", "annotation_type": "radio",
                                "labels": ["yes", "no"], "description": "Does it fit?"}],
        data_files=[data],
        phases={"order": ["definition", "annotation"],
                "definition": {"type": "prestudy", "file": page}},
        additional_config={"pocket": {"enabled": True},
                           "prior_answers": [{"schema": "concept_definition"}]})
    srv = FlaskTestServer(config_file=cfg)
    if not srv.start():
        pytest.fail("could not start the pocket offline server")
    yield srv
    srv.stop()
    cleanup_test_directory(d)


def _signed_in(page, server, user):
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/updateinstance", data={
        "instance_id": "__phase_page__",
        "annotations": {"concept_definition:::text_box": ANSWER},
        "span_annotations": []})
    req.post(f"{server.base_url}/annotate", data={"action": "next_instance"})


def _controlled(page):
    page.goto("/pocket")
    page.wait_for_selector(".pk-card")
    # `ready` waits for a worker whose scope covers this page and never
    # settles when none does, so it is raced against a timer: a wrong scope
    # has to fail the test, not hang it.
    page.evaluate("Promise.race([navigator.serviceWorker.ready,"
                  " new Promise(r => setTimeout(r, 5000))])")
    if not page.evaluate("!!navigator.serviceWorker.controller"):
        page.reload()
        page.wait_for_selector(".pk-card")
    return page.evaluate("!!navigator.serviceWorker.controller")


def test_service_worker_controls_the_pocket_page(server):
    with mobile_page("Pixel 7", server.base_url) as page:
        _signed_in(page, server, "off_scope")
        assert _controlled(page)
        assert page.evaluate(
            "navigator.serviceWorker.getRegistration('/pocket').then(r => r && r.scope)"
        ).endswith("/pocket")


def test_reload_with_no_connection_shows_the_queue(server):
    with mobile_page("Pixel 7", server.base_url) as page:
        _signed_in(page, server, "off_reload")
        assert _controlled(page)
        first = page.locator(".pk-text").text_content()

        page.context.set_offline(True)
        page.reload()
        page.wait_for_selector(".pk-card, .pk-message")
        assert page.locator(".pk-message").count() == 0
        assert page.locator(".pk-text").text_content() == first

        # The answer box needs the server and the answer is not kept on the
        # device, so offline there is no box and nothing stored.
        assert page.locator("#pk-prior-answers").is_hidden()
        stored = page.evaluate("JSON.stringify(Object.assign({}, localStorage))")
        assert ANSWER not in stored


def test_signed_out_is_not_answered_with_the_cached_queue(server):
    with mobile_page("Pixel 7", server.base_url) as page:
        _signed_in(page, server, "off_signed_out")
        assert _controlled(page)
        page.route("**/pocket/api/task", lambda route: route.fulfill(status=401, body="{}"))
        page.reload()
        page.wait_for_selector(".pk-message")
        assert "signed out" in page.locator(".pk-message").inner_text()
        assert page.locator(".pk-card").count() == 0


def test_signed_out_visit_still_reaches_the_login_page(server):
    """Once the worker controls /pocket, a cache-first page would hand the
    cached shell to a signed-out visitor instead of the server's redirect."""
    with mobile_page("Pixel 7", server.base_url) as page:
        _signed_in(page, server, "off_logout")
        assert _controlled(page)
        page.context.clear_cookies()
        page.goto("/pocket")
        assert page.url.split("?")[0].endswith("/login")
        assert page.locator(".pk-card").count() == 0


def _queue(page):
    return page.evaluate("JSON.parse(localStorage.getItem('pocket_save_queue_v1') || '[]')")


def _stored(page, server, instance_id):
    body = page.context.request.get(
        f"{server.base_url}/get_annotations?instance_id={instance_id}").json()
    return (body.get("label_annotations") or {}).get("fits")


def test_a_queued_save_goes_up_as_the_person_who_made_it(server):
    """The save queue is one list per phone. A queued answer was posted under
    whichever session flushed it, so on a shared phone the next person to sign
    in sent the first person's answers as their own."""
    with mobile_page("Pixel 7", server.base_url) as page:
        _signed_in(page, server, "share_a")
        assert _controlled(page)

        page.context.set_offline(True)
        page.locator(".pk-opt", has_text="yes").first.tap()
        page.wait_for_function("JSON.parse(localStorage.getItem('pocket_save_queue_v1') || '[]').length === 1")
        [record] = _queue(page)
        assert record["user"] == "share_a"

        # A signs out and B signs in on the same phone before the save went up.
        page.context.clear_cookies()
        page.context.set_offline(False)
        _signed_in(page, server, "share_b")
        page.goto("/pocket")
        page.wait_for_selector(".pk-card")
        chip = page.locator("#pk-sync")
        chip.wait_for(state="visible")
        assert "another account" in chip.inner_text()
        assert _queue(page) == [record]
        assert _stored(page, server, record["instance_id"]) is None

        # A signs back in: the answer goes up, as A's.
        page.context.clear_cookies()
        page.context.request.post(f"{server.base_url}/auth",
                                  form={"action": "login", "email": "share_a", "pass": "pass"})
        page.goto("/pocket")
        page.wait_for_function("JSON.parse(localStorage.getItem('pocket_save_queue_v1') || '[]').length === 0")
        assert _stored(page, server, record["instance_id"])


def _account_cookie(page):
    return next((c["value"] for c in page.context.cookies() if c["name"] == "pocket_user"), None)


def test_a_signed_out_phone_does_not_open_the_last_batch_offline(server):
    """Once Pocket could start offline, a phone that had signed out still
    opened the last account's batch and queued answers under it."""
    with mobile_page("Pixel 7", server.base_url) as page:
        _signed_in(page, server, "off_signout")
        assert _controlled(page)
        assert _account_cookie(page) == "off_signout"
        page.goto("/logout")
        assert _account_cookie(page) is None

        page.context.set_offline(True)
        page.goto("/pocket")
        page.wait_for_selector(".pk-message")
        assert "signed out" in page.locator(".pk-message").inner_text()
        assert page.locator(".pk-card").count() == 0


def test_another_account_does_not_get_the_last_batch_offline(server):
    """Someone else signing in through the desktop page leaves the first
    account's task and batch on the phone; offline they must not open."""
    with mobile_page("Pixel 7", server.base_url) as page:
        _signed_in(page, server, "off_first")
        assert _controlled(page)
        page.context.request.get(f"{server.base_url}/logout")
        _signed_in(page, server, "off_second")
        assert _account_cookie(page) == "off_second"

        page.context.set_offline(True)
        page.goto("/pocket")
        page.wait_for_selector(".pk-card, .pk-message")
        assert page.locator(".pk-card").count() == 0


def test_the_other_account_notice_does_not_hide_a_real_queue(server):
    """The notice hid the chip after 5 s whatever it said by then, including
    this person's own "Offline -- 1 save queued"."""
    with mobile_page("Pixel 7", server.base_url) as page:
        _signed_in(page, server, "off_chip")
        assert _controlled(page)
        page.evaluate("localStorage.setItem('pocket_save_queue_v1', JSON.stringify("
                      "[{user: 'someone_else', instance_id: 'zz', annotations: {}, ts: 1}]))")
        page.reload()
        chip = page.locator("#pk-sync")
        chip.wait_for(state="visible")
        assert "another account" in chip.inner_text()

        page.context.set_offline(True)
        page.locator(".pk-opt", has_text="yes").first.tap()
        page.wait_for_timeout(6000)
        assert chip.is_visible()
        assert "1 save" in chip.inner_text()


def test_offline_start_survives_a_browser_restart(server):
    """pocket_user was a browser-session cookie while the Potato session is
    permanent: after a restart the session still worked online and Pocket
    said "signed out" offline. A restart keeps only the persistent cookies."""
    with mobile_page("Pixel 7", server.base_url) as page:
        _signed_in(page, server, "off_restart")
        assert _controlled(page)
        first = page.locator(".pk-text").text_content()

        kept = [c for c in page.context.cookies() if c.get("expires", -1) != -1]
        page.context.clear_cookies()
        page.context.add_cookies(kept)
        assert _account_cookie(page) == "off_restart"

        page.context.set_offline(True)
        page.goto("/pocket")
        page.wait_for_selector(".pk-card, .pk-message")
        assert page.locator(".pk-message").count() == 0
        assert page.locator(".pk-text").text_content() == first
