"""A failed background save must not take the annotation UI down with it.

`saveAnnotations()` caught a network error and called `showError()`, which sets
`#main-content` to `display: none` and replaces the page with a full-screen
error state. That was survivable while blob schemas only saved on navigation —
the annotator was leaving anyway. It stopped being survivable once the
debounced autosave landed: now a single dropped request, at a moment nobody
asked for anything, blanks the page and takes the visible work off screen.

Measured before the fix, with `/updateinstance` aborted: every step card's
correctness button reported a 0x0 rect and a null `offsetParent`, and the
nearest hidden ancestor was `DIV#main-content`.

Note what these tests assert. Not "an error was reported" — the old behaviour
reported one too. They assert the annotation UI is *still usable*: still laid
out, still clickable, still holding the answer the annotator gave.
"""

from __future__ import annotations

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

SCHEMES = [{
    "annotation_type": "trajectory_eval",
    "name": "step_evaluation",
    "description": "Evaluate each step",
    "steps_key": "steps",
    "step_text_key": "action",
    "error_types": [{"name": "reasoning", "subtypes": ["logical_error"]}],
    "severities": [{"name": "minor", "weight": -1}],
}]

ITEMS = [
    {
        "id": f"trace_{i:03d}",
        "text": f"Task {i}",
        "steps": [{"action": f"step_{j}_of_{i}"} for j in range(3)],
    }
    for i in range(3)
]


class TestASaveFailureLeavesTheWorkOnScreen(BasePlaywrightTest):

    def _open(self, page, make_server):
        srv = make_server(SCHEMES, items=ITEMS)
        self.register_and_login(page, srv)
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".traj-step-card", timeout=15_000)
        return srv

    @staticmethod
    def _button_is_laid_out(page, step, kind="correct"):
        return page.evaluate(
            """([step, kind]) => {
                const sel = `.traj-step-card[data-step-index="${step}"] `
                          + `.traj-correctness-${kind}`;
                const btn = document.querySelector(sel);
                if (!btn) return null;
                const r = btn.getBoundingClientRect();
                return {width: r.width, height: r.height,
                        hasOffsetParent: !!btn.offsetParent};
            }""",
            [str(step), kind],
        )

    def test_the_form_is_still_visible_after_a_dropped_save(self, page, make_server):
        self._open(page, make_server)

        page.route("**/updateinstance", lambda route: route.abort())
        page.click('.traj-step-card[data-step-index="0"] .traj-correctness-incorrect')
        page.wait_for_timeout(2500)   # past the autosave debounce

        assert page.evaluate(
            "getComputedStyle(document.getElementById('main-content')).display"
        ) != "none", "a dropped autosave hid the whole annotation UI"

        laid_out = self._button_is_laid_out(page, 1)
        assert laid_out and laid_out["hasOffsetParent"], (
            "step 1's button has no offsetParent — an ancestor is display:none"
        )
        assert laid_out["height"] > 0 and laid_out["width"] > 0, (
            f"step 1's button collapsed to {laid_out['width']}x{laid_out['height']}"
        )

    def test_the_annotator_can_keep_working_after_a_dropped_save(self, page, make_server):
        """The real cost of the bug: the next click was impossible."""
        self._open(page, make_server)

        page.route("**/updateinstance", lambda route: route.abort())
        page.click('.traj-step-card[data-step-index="0"] .traj-correctness-incorrect')
        page.wait_for_timeout(2500)

        # This is the click that used to time out after 30s on "element is not
        # visible", with the button present in the DOM the whole time.
        page.click('.traj-step-card[data-step-index="1"] .traj-correctness-correct',
                   timeout=5_000)

        selected = page.query_selector(
            '.traj-step-card[data-step-index="1"] .traj-correctness-correct.selected')
        assert selected is not None, "the click landed but the answer was not recorded"

    def test_the_earlier_answer_survives_the_failure(self, page, make_server):
        self._open(page, make_server)

        page.click('.traj-step-card[data-step-index="0"] .traj-correctness-incorrect')
        page.wait_for_timeout(300)
        page.route("**/updateinstance", lambda route: route.abort())
        page.wait_for_timeout(2500)

        still_there = page.query_selector(
            '.traj-step-card[data-step-index="0"] .traj-correctness-incorrect.selected')
        assert still_there is not None, (
            "the answer given before the failure was wiped from the form"
        )

    def test_the_failure_is_still_reported(self, page, make_server):
        """Not hiding the page is not the same as saying nothing."""
        self._open(page, make_server)

        page.route("**/updateinstance", lambda route: route.abort())
        page.click('.traj-step-card[data-step-index="0"] .traj-correctness-incorrect')
        page.wait_for_timeout(2500)

        notified = page.evaluate("""() => {
            const text = document.body.innerText.toLowerCase();
            return text.includes('could not save') || text.includes('failed to save');
        }""")
        assert notified, "a dropped save was swallowed silently"

    def test_a_save_that_succeeds_shows_no_error(self, page, make_server):
        """The control: without this, a test that never saves would pass."""
        self._open(page, make_server)

        page.click('.traj-step-card[data-step-index="0"] .traj-correctness-incorrect')
        page.wait_for_timeout(2500)

        assert page.evaluate(
            "getComputedStyle(document.getElementById('main-content')).display"
        ) != "none"
        complained = page.evaluate(
            "document.body.innerText.toLowerCase().includes('could not save')")
        assert not complained, "a successful save reported a failure"
