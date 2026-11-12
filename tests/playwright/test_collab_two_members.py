"""Two members in one live session, in two real browsers.

Each member gets their own browser context (their own cookies), the way two
people on two machines would. Everything is driven with real clicks and
checked on screen: a checked radio, a page that moved, a note that is or is
not in the panel. Persistence is checked by navigating away and back, not by
reloading -- browsers restore form state across a reload.

Runs against a copy of ``examples/advanced/collaborative-sessions``: team
"red" is ana (leader), ben and chen on items cs01-cs05.
"""

import os
import re
import shutil

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import expect  # noqa: E402

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import PHONES, layout_problems  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "collaborative-sessions")


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("collab_two_members"), "collaborative-sessions")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "project.sqlite*", "layouts", "test_config_port_*"))
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the example server")
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def playwright_handle(playwright_instance, browser_instance):
    # The session's Playwright: the sync API refuses to start a second one
    # while one is running, so the phone tests use its devices.
    return playwright_instance, browser_instance


@pytest.fixture(scope="module")
def browser(browser_instance):
    return browser_instance


def member(browser, server, name):
    context = browser.new_context(base_url=server.base_url, viewport={"width": 1280, "height": 900})
    context.request.post(f"{server.base_url}/auth", form={"email": name, "pass": ""})
    page = context.new_page()
    return context, page


def radio(page, schema, label):
    return page.locator(f'input[type=radio][schema="{schema}"][label_name="{label}"]')


def checkbox(page, schema, label):
    return page.locator(f'input[type=checkbox][schema="{schema}"][label_name="{label}"]')


@pytest.fixture
def pair(browser, server):
    a_ctx, ana = member(browser, server, "ana")
    b_ctx, ben = member(browser, server, "ben")
    yield ana, ben
    a_ctx.close()
    b_ctx.close()


def open_item(page, iid, sid="RED"):
    page.goto(f"/collab/s/{sid}/i/{iid}")
    page.wait_for_function("window.potatoCollabClient && window.potatoCollabClient.state.session")


class TestLiveSharing:
    def test_a_teammates_choice_appears_without_a_reload(self, pair):
        ana, ben = pair
        open_item(ana, "cs01")
        open_item(ben, "cs01")
        ben.evaluate("window.__sameDocument = true")

        radio(ana, "stance", "critical").click()
        expect(radio(ben, "stance", "critical")).to_be_checked(timeout=8000)
        assert ben.evaluate("window.__sameDocument === true"), "ben's page reloaded"

        checkbox(ben, "frames", "health").click()
        expect(checkbox(ana, "frames", "health")).to_be_checked(timeout=8000)

    def test_the_shared_answer_survives_navigating_away_and_back(self, pair):
        ana, ben = pair
        open_item(ana, "cs01")
        open_item(ben, "cs01")
        radio(ana, "stance", "neutral").click()
        expect(radio(ben, "stance", "neutral")).to_be_checked(timeout=8000)

        # Free mode, so ben's own moves are his.
        ben.locator("#next-btn").click()
        ben.wait_for_url(re.compile(r"/collab/s/RED/i/cs02$"))
        ben.locator("#prev-btn").click()
        ben.wait_for_url(re.compile(r"/collab/s/RED/i/cs01$"))
        expect(radio(ben, "stance", "neutral")).to_be_checked()
        expect(checkbox(ben, "frames", "health")).to_be_checked()

    def test_the_activity_panel_names_who_changed_what(self, pair):
        ana, _ = pair
        open_item(ana, "cs01")
        ana.locator("#collab-rail-toggle").click()
        ana.get_by_role("tab", name="Activity").click()
        activity = ana.locator("#collab-activity-list")
        expect(activity).to_contain_text("ana")
        expect(activity).to_contain_text("ben")
        expect(activity).to_contain_text("frames: added health")


class TestFollowing:
    def test_a_member_goes_where_the_leader_goes_until_they_drift(self, pair):
        ana, ben = pair
        open_item(ana, "cs03")
        # Earlier tests moved ben by hand; start him following again.
        ben.request.post("/collab/api/RED/navigate", data={"action": "follow"})
        open_item(ben, "cs03")
        ana.locator("#next-btn").click()
        ana.wait_for_url(re.compile(r"/i/cs04$"))
        ben.wait_for_url(re.compile(r"/i/cs04$"), timeout=10000)

        # Ben moves on his own: he stops following and is offered the way back.
        ben.locator("#next-btn").click()
        ben.wait_for_url(re.compile(r"/i/cs05$"))
        back = ben.locator("#collab-bar-return")
        expect(back).to_be_visible(timeout=8000)
        expect(back).to_have_text("Go to ana's item")
        back.click()
        ben.wait_for_url(re.compile(r"/i/cs04$"))
        expect(ben.locator("#collab-bar-follow")).to_have_text("Following ana", timeout=8000)


class TestNotes:
    def test_a_personal_note_is_only_the_authors(self, pair):
        ana, ben = pair
        open_item(ana, "cs02")
        ana.locator("#collab-rail-toggle").click()
        ana.get_by_role("tab", name="My notes").click()
        ana.locator("#collab-note-input").fill("only for me: check the figure")
        ana.get_by_role("button", name="Save note").click()
        expect(ana.locator("#collab-notes-list")).to_contain_text("only for me", timeout=8000)

        # Ana navigates away and back: still there.
        open_item(ana, "cs03")
        open_item(ana, "cs02")
        if ana.locator("#collab-rail").is_hidden():
            ana.locator("#collab-rail-toggle").click()
        ana.get_by_role("tab", name="My notes").click()
        expect(ana.locator("#collab-notes-list")).to_contain_text("only for me", timeout=8000)

        open_item(ben, "cs02")
        if ben.locator("#collab-rail").is_hidden():
            ben.locator("#collab-rail-toggle").click()
        ben.get_by_role("tab", name="My notes").click()
        ben.wait_for_timeout(1500)
        expect(ben.locator("#collab-notes-list")).not_to_contain_text("only for me")
        ben.get_by_role("tab", name="Discussion").click()
        expect(ben.locator("#collab-discussion-list")).not_to_contain_text("only for me")


class TestBlindFirst:
    """Team "blue" (dana, eli): each answers on their own, then the answers open."""

    def test_the_team_answer_holds_only_what_both_agreed(self, browser, server):
        d_ctx, dana = member(browser, server, "dana")
        e_ctx, eli = member(browser, server, "eli")
        try:
            for page, note in ((dana, "dana's own reason"), (eli, "eli's own reason")):
                page.goto("/annotate")                  # past the opening pages
                open_item(page, "cs06", sid="BLUE")
                expect(page.locator("#collab-bar-stage")).to_contain_text("Answer on your own first")
                radio(page, "stance", "supportive").click()
                page.locator('[schema="rationale"]').first.fill(note)
                page.wait_for_timeout(1500)             # the autosave
            # Neither sees the other's answer.
            expect(radio(dana, "stance", "supportive")).to_be_checked()
            assert "eli's own reason" not in dana.content()

            dana.locator("#collab-blind-done").click()
            expect(dana.locator("#collab-bar-stage")).to_contain_text("waiting for 1 more")
            eli.locator("#collab-blind-done").click()

            for page in (dana, eli):
                expect(page.locator("#collab-revealed")).to_be_visible(timeout=10000)
                expect(page.locator("#collab-revealed-body")).to_contain_text("Agreed")
            dana.wait_for_timeout(2500)
            answer = dana.request.get("/collab/api/BLUE/item/cs06").json()["answer"]
            # Only the agreed stance: neither member's own text was carried
            # into the team's answer by the reload at the reveal.
            assert answer == {"L:stance:::supportive": "supportive"}, answer
            expect(radio(eli, "stance", "supportive")).to_be_checked()
            expect(eli.locator('[schema="rationale"]').first).to_have_value("")
            # A reload of the same page must not bring the private text back.
            # Chrome restores form fields on reload unless told not to; that
            # is how a drawing input carried a member's own shapes into the
            # team answer. Headless Chromium does not restore them, so check
            # that the page opts every field out.
            restorable = dana.eval_on_selector_all(
                "input, textarea, select",
                "els => els.filter(e => e.getAttribute('autocomplete') !== 'off')"
                ".map(e => e.name || e.id || e.tagName)")
            assert not restorable, restorable
            for page in (dana, eli):
                page.reload()
                page.wait_for_selector("#collab-revealed:not([hidden])")
                expect(page.locator('[schema="rationale"]').first).to_have_value("")
            dana.wait_for_timeout(2500)
            answer = dana.request.get("/collab/api/BLUE/item/cs06").json()["answer"]
            assert answer == {"L:stance:::supportive": "supportive"}, answer
        finally:
            d_ctx.close()
            e_ctx.close()


@pytest.mark.parametrize("device", PHONES)
def test_the_session_page_fits_a_phone(playwright_handle, server, device):
    """Same check as tests/helpers/mobile.py, on this module's Playwright."""
    p, b = playwright_handle
    context = b.new_context(**dict(p.devices[device]), base_url=server.base_url)
    try:
        page = context.new_page()
        context.request.post(f"{server.base_url}/auth", form={"email": "chen", "pass": ""})
        page.goto("/collab/s/RED/i/cs01")
        page.wait_for_selector("#collab-bar")
        problems = layout_problems(page, reachable=["#collab-rail-toggle", "#collab-bar-name"])
        assert not problems, "\n".join(problems)
        page.tap("#collab-rail-toggle")
        page.wait_for_selector("#collab-rail:not([hidden])")
        problems = layout_problems(page, reachable=["#collab-rail-close", "#collab-tab-discussion"])
        assert not problems, "\n".join(problems)
    finally:
        context.close()


@pytest.mark.parametrize("device", PHONES)
def test_the_comparison_table_fits_a_phone(playwright_handle, server, device):
    """After TestBlindFirst opened cs06: the answers table and its controls."""
    p, b = playwright_handle
    context = b.new_context(**dict(p.devices[device]), base_url=server.base_url)
    try:
        page = context.new_page()
        context.request.post(f"{server.base_url}/auth", form={"email": "dana", "pass": ""})
        page.goto("/collab/s/BLUE/i/cs06")
        page.wait_for_selector("#collab-revealed:not([hidden])")
        problems = layout_problems(page, reachable=["#collab-revealed-toggle", "#collab-signoff"])
        assert not problems, "\n".join(problems)
    finally:
        context.close()
