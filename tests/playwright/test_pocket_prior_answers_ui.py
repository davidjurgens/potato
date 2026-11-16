"""prior_answers on a phone: /annotate routes the phone to /pocket, and the
participant's own prestudy definition shows there above the card stack, as
text, through a card change."""

import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems, mobile_page  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    cleanup_test_directory, create_test_config, create_test_data_file, create_test_directory)

ANSWER = "Corrupt elites vs. <b>the people</b> <script>window.__pwned=1</script>\nSecond line"


@pytest.fixture(scope="module")
def server():
    d = create_test_directory("pocket_prior_answers_ui")
    data = create_test_data_file(d, [{"id": "i1", "text": "First item."},
                                     {"id": "i2", "text": "Second item."}])
    page = os.path.join(d, "pre.json")
    with open(page, "w") as f:
        json.dump([{"name": "concept_definition", "annotation_type": "text",
                    "description": "Define the concept.",
                    "label_requirement": {"required": True}}], f)
    cfg = create_test_config(
        d, annotation_schemes=[{"name": "fits", "annotation_type": "radio",
                                "labels": ["yes", "no"], "description": "Does it fit?"}],
        data_files=[data],
        phases={"order": ["definition", "annotation"],
                "definition": {"type": "prestudy", "file": page}},
        additional_config={"pocket": {"enabled": True},
                           "prior_answers": [{"schema": "concept_definition",
                                              "title": "Definition"}]})
    srv = FlaskTestServer(config_file=cfg)
    if not srv.start():
        pytest.fail("could not start the pocket prior_answers server")
    yield srv
    srv.stop()
    cleanup_test_directory(d)


@pytest.mark.parametrize("device", ["iPhone 13", "Pixel 7"])
def test_phone_sees_own_definition_on_pocket(server, device):
    user = "pk_ui_" + device.replace(" ", "")
    with mobile_page(device, server.base_url) as page:
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        req = page.context.request
        req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
        req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
        req.post(f"{server.base_url}/updateinstance", data={
            "instance_id": "__phase_page__",
            "annotations": {"concept_definition:::text_box": ANSWER},
            "span_annotations": []})
        req.post(f"{server.base_url}/annotate", data={"action": "next_instance"})

        page.goto("/annotate")
        page.wait_for_url("**/pocket")
        box = page.wait_for_selector(".pk-prior-answers .prior-answer-block")
        summary = page.locator(".pk-prior-answers summary")
        content = page.locator(".pk-prior-answers .prior-answer-content")
        assert summary.inner_text() == "Definition"
        assert not content.is_visible()          # closed by default

        summary.tap()
        assert content.is_visible()
        # The answer is text: the tags are characters, nothing ran.
        assert content.text_content() == ANSWER
        assert page.locator(".pk-prior-answers b, .pk-prior-answers script").count() == 0
        assert page.evaluate("window.__pwned") is None
        assert layout_problems(page, reachable=[".pk-prior-answers summary", "#pk-next"]) == []

        # Answering a card replaces #pk-main; the box stays.
        page.locator(".pk-opt", has_text="yes").first.tap()
        page.locator("#pk-next").tap()
        page.wait_for_function(
            "document.querySelector('#pk-count') && /2/.test(document.querySelector('#pk-count').textContent)")
        assert box.is_visible()
        assert content.text_content() == ANSWER
        assert errors == []


# Contrast of a text element against the first opaque background behind it.
_CONTRAST_JS = r"""
(sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const rgb = (c) => (c.match(/[\d.]+/g) || []).map(Number);
    const lum = ([r, g, b]) => {
        const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    let bgEl = el, bg;
    while (bgEl) {
        const c = rgb(getComputedStyle(bgEl).backgroundColor);
        if (c.length >= 3 && (c.length < 4 || c[3] > 0.9)) { bg = c; break; }
        bgEl = bgEl.parentElement;
    }
    bg = bg || [255, 255, 255];
    const a = lum(rgb(getComputedStyle(el).color)), b = lum(bg);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
"""

TEXT_SLOTS = [".pk-text", ".pk-scheme-title", ".pk-opt", ".pk-opt.selected",
              ".pk-prior-answers summary", ".pk-prior-answers .prior-answer-content"]


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_pocket_text_is_readable_in_both_themes(server, scheme):
    """A phone in dark mode got dark cards with the light theme's dark ink on
    them: the item, the question and the options were unreadable."""
    user = "pk_theme_" + scheme
    with mobile_page("iPhone 13", server.base_url) as page:
        page.emulate_media(color_scheme=scheme)
        req = page.context.request
        req.post(f"{server.base_url}/register", form={"action": "signup", "email": user, "pass": "pass"})
        req.post(f"{server.base_url}/auth", form={"action": "login", "email": user, "pass": "pass"})
        req.post(f"{server.base_url}/updateinstance", data={
            "instance_id": "__phase_page__",
            "annotations": {"concept_definition:::text_box": "A definition"},
            "span_annotations": []})
        req.post(f"{server.base_url}/annotate", data={"action": "next_instance"})
        page.goto("/pocket")
        page.wait_for_selector(".pk-prior-answers summary")
        assert page.evaluate("document.documentElement.style.colorScheme") == scheme
        page.locator(".pk-prior-answers summary").tap()
        # Select without advancing: the card auto-advances on a lone radio,
        # so mark the option the way the page does, then read it.
        page.evaluate("document.querySelector('.pk-opt').classList.add('selected')")
        low = {sel: round(r, 2) for sel in TEXT_SLOTS
               if (r := page.evaluate(_CONTRAST_JS, sel)) is not None and r < 4.5}
        missing = [sel for sel in TEXT_SLOTS if page.evaluate(_CONTRAST_JS, sel) is None]
        assert missing == []
        assert low == {}
