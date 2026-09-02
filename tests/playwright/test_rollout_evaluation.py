"""
The rollout evaluation surface, in a real browser.

What can only be checked here: do the videos actually report a length, do all
the panels land on the same frame when the transport moves, does marking a
break write it to the hidden input, and does any of it survive navigating away
and back. The arithmetic is in `rollout-eval.js` statics and covered by Jest.

**Assertions read the manager state, the hidden input and the DOM, never a
screenshot.** A timeline that draws convincingly while writing nothing is the
failure mode these are written against.

Frame lock is the reason this file exists at all. Chrome does not decode media
in a hidden tab, so the Chrome-MCP verification loop can drive every control
and still learn nothing about whether two videos are on the same frame — the
one property the whole surface is built to provide.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

EXAMPLE = Path("examples/agent-traces/world-model-rollouts").resolve()
MEDIA = EXAMPLE / "media"

SCHEMES = [{
    "annotation_type": "rollout_evaluation",
    "name": "rollout_review",
    "description": "Where does each rollout stop making sense?",
    "streams": [
        {"field": "real", "name": "Recording", "role": "real"},
        {"field": "gen_a", "name": "Model A"},
        {"field": "gen_b", "name": "Model B"},
    ],
    "fps": 25,
    "layers": ["violations", "preference", "counterfactual"],
    "blind": True,
    "shuffle": True,
    "require_clean": True,
}]


def rollout_items():
    return [
        {"id": "ball_drop",
         "prompt": "A ball is dropped onto a table and bounces once.",
         "intervention": "",
         "real": "rollouts/ball_drop/real.webm",
         "gen_a": "rollouts/ball_drop/gen_a.webm",
         "gen_b": "rollouts/ball_drop/gen_b.webm",
         "note": "the freeze"},
        {"id": "block_push",
         "prompt": "A block slides to the right and hits a wall.",
         "intervention": "The wall was moved 50 px to the left at 1.5 s.",
         "intervention_t": 1.5,
         "real": "rollouts/block_push/real.webm",
         "gen_a": "rollouts/block_push/gen_a.webm",
         "gen_b": "rollouts/block_push/gen_b.webm",
         "note": "the wall"},
    ]


@pytest.fixture
def rollout_server(make_server):
    if not (MEDIA / "rollouts" / "ball_drop" / "real.webm").is_file():
        pytest.skip("run examples/agent-traces/world-model-rollouts/"
                    "generate_rollouts.py first")
    return make_server(
        SCHEMES,
        items=rollout_items(),
        extra_config={
            "media_directory": str(MEDIA),
            "item_properties": {"id_key": "id", "text_key": "note"},
        },
    )


def open_rollout(test, page, server):
    test.register_and_login(page, server)
    page.goto(f"{server.base_url}/annotate")
    page.wait_for_selector(".rollout-eval-container", timeout=30000)
    page.wait_for_function(
        """() => {
            const c = document.querySelector('.rollout-eval-container');
            return c && c.annotationManager && c.annotationManager.set;
        }""", timeout=30000)


def wait_for_media(page, timeout=30000):
    """Wait until the panels report a length — everything depends on it."""
    page.wait_for_function(
        """() => {
            const c = document.querySelector('.rollout-eval-container');
            const m = c && c.annotationManager;
            return m && m.duration > 0;
        }""", timeout=timeout)


def manager_eval(page, expression):
    return page.evaluate(
        "() => { const m = document.querySelector("
        "'.rollout-eval-container').annotationManager; return ("
        + expression + "); }")


def press(page, key):
    page.evaluate(
        "(k) => document.dispatchEvent(new KeyboardEvent('keydown', "
        "{key: k, bubbles: true, cancelable: true}))", key)


def go_next(page, expect_set_id):
    """
    Move to the next item, absorbing the unanswered-panel warning.

    With `require_clean` on, the first Next press on an item with unanswered
    panels warns instead of navigating (and the second proceeds). A test that
    clicks once and waits is testing the guard, not the thing it meant to test,
    so the intent is spelled out here rather than left as a bare double click.
    """
    page.click("#next-btn")
    page.wait_for_timeout(400)
    if page.evaluate(
            "() => document.querySelector('.rollout-eval-container')"
            ".annotationManager.unresolved().length > 0"):
        page.click("#next-btn")
    page.wait_for_function(
        """(want) => {
            const c = document.querySelector('.rollout-eval-container');
            return c && c.annotationManager && c.annotationManager.set
                && c.annotationManager.set.set_id === want;
        }""", arg=expect_set_id, timeout=30000)


def stored(page, schema="rollout_review"):
    raw = page.evaluate(
        "(id) => (document.getElementById(id) || {}).value || ''",
        f"input-{schema}")
    return json.loads(raw) if raw else None


class TestLoading(BasePlaywrightTest):
    def test_the_panels_load_and_report_a_length(self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        assert manager_eval(page, "m._videos.length") == 3
        assert manager_eval(page, "m.duration") > 4.0
        assert manager_eval(page, "m.fps") == 25

    def test_the_panels_are_blinded_and_permuted(self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        names = manager_eval(page, "m.set.streams.map(s => s.name)")
        assert names == ["A", "B", "C"]
        ids = manager_eval(page, "m.streamIds")
        assert sorted(ids) == ["gen_a", "gen_b", "real"]

    def test_the_counterfactual_block_is_hidden_without_an_intervention(
            self, page, rollout_server):
        # Asking "is the divergence plausible?" about a set with nothing to
        # diverge from produces an answer to a question that was not asked.
        open_rollout(self, page, rollout_server)
        assert page.eval_on_selector(
            ".rollout-counterfactual", "el => el.hidden") is True

    def test_the_counterfactual_block_appears_when_there_is_one(
            self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        go_next(page, "block_push")
        page.wait_for_timeout(400)
        assert manager_eval(page, "m.set.intervention")
        assert page.eval_on_selector(
            ".rollout-counterfactual", "el => el.hidden") is False


class TestFrameLock(BasePlaywrightTest):
    def test_every_panel_lands_on_the_same_frame(self, page, rollout_server):
        # The property the entire surface exists to provide. Without it the
        # annotator compares frame 40 of one rollout against frame 43 of
        # another and has no way to know.
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        page.evaluate(
            "() => document.querySelector('.rollout-eval-container')"
            ".annotationManager.seek(2.5)")
        page.wait_for_timeout(600)
        times = manager_eval(page, "m._videos.map(v => v.el.currentTime)")
        assert max(times) - min(times) < 0.04, times

    def test_stepping_moves_exactly_one_frame(self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        page.evaluate(
            "() => document.querySelector('.rollout-eval-container')"
            ".annotationManager.seek(2.5)")
        before = manager_eval(page, "m.currentTime")
        press(page, ".")
        page.wait_for_timeout(300)
        after = manager_eval(page, "m.currentTime")
        # One frame at 25 fps, within the rounding the mid-frame snap allows.
        assert 0.02 < after - before < 0.06, (before, after)

    def test_the_frame_readout_is_populated_before_anything_is_touched(
            self, page, rollout_server):
        # It was written only on seek and tick, so the readout sat blank until
        # the annotator moved — which reads as the frame rate not being set.
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        assert "frame" in page.text_content(".rollout-frame")


class TestMarking(BasePlaywrightTest):
    def test_marking_writes_a_break_to_the_hidden_input(
            self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        press(page, "2")
        page.evaluate(
            "() => document.querySelector('.rollout-eval-container')"
            ".annotationManager.seek(2.5)")
        press(page, "m")
        page.wait_for_timeout(300)

        data = stored(page)
        assert len(data["violations"]) == 1
        mark = data["violations"][0]
        assert mark["stream"] in ("real", "gen_a", "gen_b")
        assert mark["type"]
        # Snapped to the middle of a frame, so it round-trips exactly.
        assert abs(mark["t"] * 25 - round(mark["t"] * 25 - 0.5) - 0.5) < 1e-9

    def test_marking_without_choosing_a_panel_refuses_and_says_why(
            self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        page.evaluate(
            "() => { const m = document.querySelector("
            "'.rollout-eval-container').annotationManager;"
            " m.selectedStream = null; }")
        press(page, "m")
        page.wait_for_timeout(200)
        assert manager_eval(page, "m.violations.length") == 0
        assert "Choose a panel" in page.text_content(".rollout-status")

    def test_clean_and_a_mark_are_mutually_exclusive(
            self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        press(page, "1")
        press(page, "c")
        page.wait_for_timeout(200)
        assert len(manager_eval(page, "m.clean")) == 1
        press(page, "m")
        page.wait_for_timeout(200)
        # Marking un-cleans: a stream cannot be both "no breaks" and "a break".
        assert manager_eval(page, "m.clean") == []
        assert manager_eval(page, "m.violations.length") == 1

    def test_nudging_moves_the_mark_by_whole_frames(
            self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        press(page, "1")
        page.evaluate(
            "() => document.querySelector('.rollout-eval-container')"
            ".annotationManager.seek(2.5)")
        press(page, "m")
        page.wait_for_timeout(200)
        before = manager_eval(page, "m.violations[0].t")
        press(page, "ArrowRight")
        press(page, "ArrowRight")
        page.wait_for_timeout(200)
        after = manager_eval(page, "m.violations[0].t")
        assert abs((after - before) - 2 / 25) < 1e-6

    def test_deleting_removes_the_mark_and_the_form_goes_quiet(
            self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        press(page, "1")
        press(page, "m")
        page.wait_for_timeout(200)
        press(page, "Delete")
        page.wait_for_timeout(200)
        assert manager_eval(page, "m.violations.length") == 0
        assert "No break selected" in page.text_content(
            ".rollout-violation-where")


class TestTypingDoesNotTriggerShortcuts(BasePlaywrightTest):
    def test_typing_a_note_does_not_mark_breaks_or_move_the_playhead(
            self, page, rollout_server):
        # The exact defect found in image-annotation.js in Wave 0.8: a
        # document-level key handler with no target check turns "mark" into a
        # letter nobody can type.
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        press(page, "1")
        press(page, "m")
        page.wait_for_timeout(200)
        before = manager_eval(page, "m.violations.length")

        page.click(".rollout-violation-note")
        page.keyboard.type("mmm c 1 2 3 comma. brackets []")
        page.wait_for_timeout(400)

        assert manager_eval(page, "m.violations.length") == before
        assert manager_eval(page, "m.clean") == []
        assert page.input_value(".rollout-violation-note").startswith("mmm")


class TestRequireClean(BasePlaywrightTest):
    def test_the_progress_line_names_what_is_left(self, page, rollout_server):
        # `require_clean` was a config option that did nothing at all: the
        # function that computes this was defined and called from nowhere.
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        text = page.text_content(".rollout-progress")
        assert "0 of 3" in text
        press(page, "1")
        press(page, "c")
        page.wait_for_timeout(200)
        assert "1 of 3" in page.text_content(".rollout-progress")

    def test_the_first_next_press_warns_instead_of_navigating(
            self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        before = manager_eval(page, "m.set.set_id")
        page.click("#next-btn")
        page.wait_for_timeout(1200)
        assert manager_eval(page, "m.set.set_id") == before
        assert "no answer yet" in page.text_content(".rollout-status")

    def test_the_second_next_press_proceeds(self, page, rollout_server):
        # Warn and allow, not block: a panel whose video failed to decode can
        # never be answered, and a hard block would trap the annotator.
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        before = manager_eval(page, "m.set.set_id")
        page.click("#next-btn")
        page.wait_for_timeout(800)
        page.click("#next-btn")
        page.wait_for_function(
            """(prev) => {
                const c = document.querySelector('.rollout-eval-container');
                return c && c.annotationManager && c.annotationManager.set
                    && c.annotationManager.set.set_id !== prev;
            }""", arg=before, timeout=30000)
        assert manager_eval(page, "m.set.set_id") != before


class TestPersistence(BasePlaywrightTest):
    def test_everything_survives_navigating_away_and_back(
            self, page, rollout_server):
        # Next then Previous, never a reload: browsers cache form state across
        # reload and produce false-positive persistence passes (invariant 2).
        open_rollout(self, page, rollout_server)
        wait_for_media(page)

        press(page, "1")
        page.evaluate(
            "() => document.querySelector('.rollout-eval-container')"
            ".annotationManager.seek(2.5)")
        press(page, "m")
        press(page, "2")
        press(page, "c")
        press(page, "3")
        press(page, "c")
        page.wait_for_timeout(300)

        page.select_option(".rollout-violation-type", "gravity_violation")
        winner = manager_eval(page, "m.streamIds[2]")
        page.check(f".rollout-winner input[value='{winner}']")
        page.select_option(".rollout-confidence", "2")
        page.wait_for_timeout(400)

        before = stored(page)
        order_before = manager_eval(page, "m.streamIds")
        assert len(before["violations"]) == 1
        assert len(before["clean"]) == 2

        go_next(page, "block_push")
        page.click("#prev-btn")
        page.wait_for_function(
            """() => {
                const c = document.querySelector('.rollout-eval-container');
                return c && c.annotationManager && c.annotationManager.set
                    && c.annotationManager.set.set_id === 'ball_drop';
            }""", timeout=30000)
        page.wait_for_timeout(600)

        after = stored(page)
        assert after["violations"] == before["violations"]
        assert sorted(after["clean"]) == sorted(before["clean"])
        assert after["preference"]["winner"] == winner
        assert after["preference"]["confidence"] == "2"

        # Visual state, not just the manager's memory.
        assert page.is_checked(f".rollout-winner input[value='{winner}']")
        assert page.input_value(".rollout-confidence") == "2"

        # And the panel order is the same, or "panel B" means two things.
        assert manager_eval(page, "m.streamIds") == order_before

    def test_switching_items_does_not_leak_the_previous_answers(
            self, page, rollout_server):
        # Three separate cross-instance corruption bugs in the image manager
        # came from state that no canvas-scoped clear reached.
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        press(page, "1")
        press(page, "m")
        press(page, "2")
        press(page, "c")
        press(page, "3")
        press(page, "c")
        page.wait_for_timeout(300)

        go_next(page, "block_push")
        page.wait_for_timeout(400)

        assert manager_eval(page, "m.violations") == []
        assert manager_eval(page, "m.clean") == []
        assert manager_eval(page, "m.preference.winner") == ""
        assert stored(page) in (None, {}) or not stored(page)["violations"]


class TestAccessibility(BasePlaywrightTest):
    def test_the_timeline_describes_its_marks_rather_than_being_a_dead_canvas(
            self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        label = page.get_attribute(".rollout-canvas", "aria-label")
        assert "not answered" in label

        press(page, "1")
        press(page, "c")
        page.wait_for_timeout(200)
        assert "no breaks" in page.get_attribute(".rollout-canvas", "aria-label")

        press(page, "2")
        press(page, "m")
        page.wait_for_timeout(200)
        assert "break" in page.get_attribute(".rollout-canvas", "aria-label")

    def test_the_timeline_is_not_a_tab_stop_that_does_nothing(
            self, page, rollout_server):
        # Every key is bound at document level and every action has a button,
        # so focusing the canvas would achieve nothing.
        open_rollout(self, page, rollout_server)
        assert page.get_attribute(".rollout-canvas", "tabindex") is None
        assert page.get_attribute(".rollout-canvas", "role") == "img"

    def test_the_panel_shortcut_is_in_the_accessible_name(
            self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        label = page.get_attribute(".rollout-panel-choose", "aria-label")
        assert "shortcut 1" in label

    def test_choosing_a_panel_updates_aria_pressed(self, page, rollout_server):
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        press(page, "2")
        page.wait_for_timeout(200)
        states = page.eval_on_selector_all(
            ".rollout-panel-choose",
            "els => els.map(e => e.getAttribute('aria-pressed'))")
        assert states == ["false", "true", "false"]

    def test_marking_is_announced(self, page, rollout_server):
        # A tick appearing on a canvas is no feedback at all for a screen
        # reader, so this is the entire feedback for the primary action.
        open_rollout(self, page, rollout_server)
        wait_for_media(page)
        press(page, "1")
        press(page, "m")
        page.wait_for_timeout(300)
        assert "frame" in page.text_content(".rollout-announce")
