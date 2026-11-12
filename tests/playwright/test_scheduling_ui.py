"""
Scheduled sessions in a browser: enrol with consent to contact, the
out-of-window page in the participant's time zone, a resume link opened in a
fresh browser, answering an experience-sampling prompt, and a Delphi round 2
that shows the panel's round-1 feedback. Admin schedule page tables scroll
rather than clip. Every page is checked at phone width and for console errors.

The server runs in-process with the scheduler thread off; the test moves the
manager's clock and calls tick() instead of waiting days.
"""

from __future__ import annotations

import os
import re
import shutil

import pytest
import yaml

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems  # noqa: E402
from tests.helpers.port_manager import find_free_port  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHOTS = os.environ.get("POTATO_SCHEDULING_SHOTS")   # a folder to save screenshots in
ADMIN_KEY = "scheduling-ui-admin-key"
NY = "America/New_York"
PHONE_CTX = dict(viewport={"width": 390, "height": 844}, device_scale_factor=3,
                 is_mobile=True, has_touch=True)


def _copy_example(name: str, test_name: str, edit) -> tuple:
    src = os.path.join(REPO, "examples", "advanced", name)
    work = create_test_directory(test_name)
    for sub in ("data", "surveys"):
        if os.path.isdir(os.path.join(src, sub)):
            shutil.copytree(os.path.join(src, sub), os.path.join(work, sub), dirs_exist_ok=True)
    cfg = yaml.safe_load(open(os.path.join(src, "config.yaml")))
    cfg["task_dir"] = os.path.abspath(work)
    cfg["output_annotation_dir"] = os.path.join(os.path.abspath(work), "annotation_output")
    cfg["schedule"]["scheduler"] = False
    cfg["admin_api_key"] = ADMIN_KEY
    edit(cfg)
    path = os.path.join(work, "config.yaml")
    with open(path, "w") as fh:
        yaml.safe_dump(cfg, fh)
    srv = FlaskTestServer(port=find_free_port(), config_file=path)
    if not srv.start():
        pytest.fail(f"could not start {name}")
    return srv, work


def _manager():
    from potato.scheduling import manager as m
    return m._LATEST


def _shot(page, name):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    for theme in ("light", "dark"):
        page.evaluate("t => { document.documentElement.setAttribute('data-theme', t);"
                      " document.documentElement.setAttribute('data-bs-theme', t);"
                      " document.documentElement.style.colorScheme = t; }", theme)
        page.screenshot(path=os.path.join(SHOTS, f"{name}_{theme}.png"), full_page=True)
    page.evaluate("() => document.documentElement.setAttribute('data-theme', 'light')")


def _watch(page, errors):
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))


def _sign_in(context, base, user):
    context.request.post(f"{base}/register", form={"email": user, "pass": "pw"})
    context.request.post(f"{base}/auth", form={"email": user, "pass": "pw"})


def _consent(page, answers):
    for schema, label in answers:
        page.locator(f'input[schema="{schema}"][label_name="{label}"]').click()
    page.wait_for_timeout(300)
    page.locator("#next-btn").click()
    page.wait_for_load_state("networkidle")


def _phone_check(browser, base, path, user_cookies, reachable):
    ctx = browser.new_context(**PHONE_CTX, timezone_id=NY)
    try:
        ctx.add_cookies(user_cookies)
        pg = ctx.new_page()
        pg.goto(base + path)
        return layout_problems(pg, reachable=reachable)
    finally:
        ctx.close()


# --------------------------------------------------------------------------
# Waves and prompts
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def panel_server():
    def edit(cfg):
        cfg["schedule"]["experience_sampling"] = {
            "title": "Right now", "days": 2, "start_day": 1,
            "interval": {"times": ["10:00", "16:00"]}, "expires_after": "1h",
            "questions": [
                {"name": "mood", "annotation_type": "likert", "description": "How do you feel?",
                 "size": 5, "min_label": "Bad", "max_label": "Good", "required": True},
                {"name": "energy", "annotation_type": "slider", "description": "Energy?",
                 "min_value": 0, "max_value": 100, "required": True},
                {"name": "company", "annotation_type": "multiselect", "description": "With whom?",
                 "labels": ["Alone", "Family", "Friends"]}]}
        with open(os.path.join(cfg["task_dir"], "data", "statements.jsonl"), "w") as fh:
            fh.write('{"id": "s1", "text": "Most news outlets report events accurately."}\n')
    srv, work = _copy_example("two-wave-panel", "scheduling_ui_panel", edit)
    yield srv
    srv.stop()
    shutil.rmtree(work, ignore_errors=True)


def test_enrol_out_of_window_resume_link_and_prompt(panel_server, browser_instance):
    base = panel_server.base_url
    errors = []
    ctx = browser_instance.new_context(viewport={"width": 1280, "height": 900}, timezone_id=NY)
    page = ctx.new_page()
    _watch(page, errors)
    _sign_in(ctx, base, "walker")
    page.goto(f"{base}/")
    _consent(page, [("study_consent", "I agree"), ("contact_consent", "Yes, you may contact me")])
    # The regular flow: one statement to rate.
    page.locator('input[schema="agreement"]').first.click()
    page.wait_for_timeout(300)
    page.locator("#next-btn").click()
    page.wait_for_url(re.compile(r".*/schedule/enrol$"))

    # Enrolment: the browser's zone is filled in; give both addresses.
    assert page.locator("#timezone").input_value() == NY
    assert page.locator("#email").is_visible() and page.locator("#phone").is_visible()
    _shot(page, "enrol")
    page.fill("#email", "walker@example.org")
    page.fill("#phone", "+1 212 555 0147")
    page.click("#schedule-enrol-submit")
    page.wait_for_url(re.compile(r".*/schedule\?enrolled=1$"))

    # Nothing is open yet: the page names the next window in New York time.
    assert page.locator("#schedule-heading").inner_text() == "Your next session is not open yet"
    next_text = page.locator("#schedule-next").inner_text()
    m = _manager()
    first = min(m.sessions("walker"), key=lambda s: s["opens_at"])
    assert first["kind"] == "prompt"
    # Fixed-time prompts may be announced; the wave a week on is listed too.
    assert "10:00" in next_text and ("EDT" in next_text or "EST" in next_text)
    _shot(page, "status_out_of_window")
    cookies = ctx.cookies()
    assert _phone_check(browser_instance, base, "/schedule", cookies,
                        ["#schedule-heading", "#schedule-finish"]) == []

    # Out-of-window page for the wave.
    page.goto(f"{base}/schedule/session/wave:followup")
    assert "is not open yet" in page.locator("#schedule-heading").inner_text()
    assert "09:00 EST" in page.locator("#schedule-window-opens").inner_text()

    # The first prompt opens; its message carries a resume link.
    m.clock = lambda: first["opens_at"] + 30
    m.tick(first["opens_at"] + 30)
    note = [n for n in m.store.notifications(participant="walker", session_id=first["id"])
            if n["channel"] == "log" and n["status"] == "sent"][0]
    path = re.search(r"http://\S+?(/s/\S+)", note["preview"]).group(1)

    fresh = browser_instance.new_context(viewport={"width": 1280, "height": 900}, timezone_id=NY)
    try:
        p2 = fresh.new_page()
        _watch(p2, errors)
        p2.goto(base + path)
        p2.wait_for_url(re.compile(r".*/schedule/session/prompt:1:1$"))
        assert p2.locator("#schedule-heading").inner_text() == "Right now"
        m.clock = lambda: first["opens_at"] + 75
        p2.locator('fieldset[data-question="mood"] input[value="4"]').click()
        slider = p2.locator('fieldset[data-question="energy"] input[type=range]')
        box = slider.bounding_box()
        p2.mouse.click(box["x"] + box["width"] * 0.7, box["y"] + box["height"] / 2)
        p2.locator('fieldset[data-question="company"] input[value="Friends"]').click()
        _shot(p2, "prompt")
        assert _phone_check(browser_instance, base, "/schedule/session/prompt:1:1",
                            fresh.cookies(), ["#schedule-submit"]) == []
        m.clock = lambda: first["opens_at"] + 140
        p2.click("#schedule-submit")
        p2.wait_for_selector("#schedule-saved")
    finally:
        fresh.close()
    stored = m.session("walker", "prompt:1:1")
    assert stored["status"] == "answered"
    assert stored["answers"]["mood"] == 4 and stored["answers"]["company"] == ["Friends"]
    assert 55 <= stored["answers"]["energy"] <= 85
    # The beacon fired on the first click, before the submit.
    assert stored["first_answer_at"] == pytest.approx(first["opens_at"] + 75)
    assert stored["submitted_at"] == pytest.approx(first["opens_at"] + 140)
    ctx.close()
    assert not errors, errors


# --------------------------------------------------------------------------
# Delphi
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def delphi_server():
    srv, work = _copy_example("delphi-study", "scheduling_ui_delphi", lambda cfg: None)
    yield srv
    srv.stop()
    shutil.rmtree(work, ignore_errors=True)


def test_delphi_round_two_shows_round_one_feedback(delphi_server, browser_instance):
    base = delphi_server.base_url
    errors = []
    m = _manager()
    items = [i["id"] for i in m.spec.delphi.items]
    for other in ("panel_a", "panel_b"):
        m.enrol(other, "UTC", "browser", consent=False)

    ctx = browser_instance.new_context(viewport={"width": 1280, "height": 900}, timezone_id=NY)
    page = ctx.new_page()
    _watch(page, errors)
    _sign_in(ctx, base, "rater")
    page.goto(f"{base}/")
    _consent(page, [("panel_consent", "I agree"), ("contact_consent", "Yes")])
    page.locator('input[schema="read_instructions"]').first.click()
    page.wait_for_timeout(300)
    page.locator("#next-btn").click()
    page.wait_for_load_state("networkidle")
    page.locator('input[schema="role"][label_name="I write them"]').click()
    page.locator('input[schema="years"][label_name="2 to 5"]').click()
    page.wait_for_timeout(300)
    page.locator("#next-btn").click()
    page.wait_for_url(re.compile(r".*/schedule/enrol$"))
    page.click("#schedule-enrol-submit")
    page.wait_for_url(re.compile(r".*/schedule/session/round:1$"))
    assert page.locator(".delphi-feedback").count() == 0        # nothing to show yet
    for iid in items:
        page.locator(f'input[name="rating__{iid}"][value="3"]').click()
    page.fill("#comment-c1", "my own note")
    page.click("#schedule-submit")
    page.wait_for_selector("#schedule-saved")
    for other, rating in (("panel_a", 7), ("panel_b", 8)):
        assert m.submit(other, "round:1", {i: {"rating": rating, "comment": f"{other} on {i}"}
                                           for i in items})

    # The admin closes round 1 from the schedule page.
    admin = browser_instance.new_context(viewport={"width": 760, "height": 900},
                                         extra_http_headers={"X-API-Key": ADMIN_KEY})
    try:
        ap = admin.new_page()
        ap.goto(f"{base}/admin")          # stores the key in the session
        ap.wait_for_load_state("networkidle")
        _watch(ap, errors)                # the schedule page's own errors only
        ap.goto(f"{base}/admin/schedule")
        ap.click("#schedule-close-round")
        ap.wait_for_selector("#schedule-delphi-stats")
        _shot(ap, "admin")
        # Wide tables scroll inside their box; the page itself does not.
        wraps = ap.evaluate("""[...document.querySelectorAll('.sched-table-wrap')].map(w =>
            ({o: getComputedStyle(w).overflowX, scrolls: w.scrollWidth > w.clientWidth}))""")
        assert wraps and all(w["o"] == "auto" for w in wraps)
        assert any(w["scrolls"] for w in wraps)
        assert ap.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    finally:
        admin.close()
    rounds = m.store.rounds()
    assert [r["status"] for r in rounds] == ["closed", "scheduled"]
    # The example leaves 12 hours between rounds: until then the panelist
    # is told when round 2 opens.
    page.goto(f"{base}/")
    page.wait_for_url(re.compile(r".*/schedule$"))
    assert "Guideline criteria: round 2" in page.locator("#schedule-next").inner_text()
    m.clock = lambda: rounds[1]["opens_at"] + 10
    m.tick()
    page.goto(f"{base}/")
    page.wait_for_url(re.compile(r".*/schedule/session/round:2$"))
    fb = page.locator('.delphi-feedback[data-feedback-for="c1"]')
    assert fb.locator(".delphi-median-value").inner_text() == "7"
    assert fb.locator(".delphi-iqr-value").inner_text() == "5–7.5"
    assert fb.locator(".delphi-own-value").inner_text() == "3"
    fb.locator("summary").click()
    comments = fb.locator("li").all_inner_texts()
    assert sorted(comments) == ["panel_a on c1", "panel_b on c1"]     # not the rater's own
    _shot(page, "delphi_round2")
    assert _phone_check(browser_instance, base, "/schedule/session/round:2", ctx.cookies(),
                        ["#schedule-submit"]) == []
    ctx.close()
    assert not errors, errors
