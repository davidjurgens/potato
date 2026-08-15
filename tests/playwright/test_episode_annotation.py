"""
The embodied episode surface, in a real browser.

What can only be checked here: does the manifest reach the timeline, do the
video streams stay synchronized, does a drag on the phase lane produce a
segment in the hidden input, and does any of it survive navigating away and
back. The arithmetic is in `episode-timeline.js` statics and covered by Jest.

**Assertions read the manager state and the hidden input, never a screenshot.**
A timeline that draws convincingly while writing nothing is the failure mode
these are written against.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

EXAMPLE = Path("examples/embodied/lerobot-episode").resolve()
MEDIA = EXAMPLE / "media"

SCHEMES = [{
    "annotation_type": "episode_annotation",
    "name": "review",
    "description": "Mark the phases",
    "source_field": "episode",
    "layers": ["phases", "outcome", "reward", "instruction"],
    "phases": [
        {"name": "reach", "color": "#4ECDC4", "key_value": "1"},
        {"name": "grasp", "color": "#FFD93D", "key_value": "2"},
    ],
    "outcomes": ["success", "partial", "failure"],
    "failure_causes": ["missed grasp", "object slipped"],
    "reward_range": [0.0, 1.0],
    "series_shown": ["gripper", "wrist_force"],
}]


def episode_items():
    return [
        {"id": "episode_0000",
         "episode": "episodes/episode_0000/episode.json",
         "note": "the successful attempt"},
        {"id": "episode_0001",
         "episode": "episodes/episode_0001/episode.json",
         "note": "the failed attempt"},
    ]


@pytest.fixture
def episode_server(make_server):
    if not (MEDIA / "episodes" / "episode_0000" / "episode.json").is_file():
        pytest.skip(
            "run examples/embodied/lerobot-episode/generate_episode.py first")
    return make_server(
        SCHEMES,
        items=episode_items(),
        extra_config={
            "media_directory": str(MEDIA),
            "item_properties": {"id_key": "id", "text_key": "note"},
        },
    )


def open_episode(test, page, server):
    test.register_and_login(page, server)
    page.goto(f"{server.base_url}/annotate")
    page.wait_for_selector(".episode-annotation-container", timeout=30000)
    page.wait_for_function(
        """() => {
            const c = document.querySelector('.episode-annotation-container');
            return c && c.annotationManager && c.annotationManager.episode;
        }""", timeout=30000)


def manager_eval(page, expression):
    return page.evaluate(
        "() => { const m = document.querySelector("
        "'.episode-annotation-container').annotationManager; return ("
        + expression + "); }")


def draw_phase(page, label, from_fraction, to_fraction, lane_y=30):
    """Drag on the phase lane, through the real pointer path."""
    page.evaluate(
        """([label, a, b, y]) => {
            const m = document.querySelector(
                '.episode-annotation-container').annotationManager;
            m.setPhase(label);
            const rect = m.canvas.getBoundingClientRect();
            const mk = (type, x) => new MouseEvent(type, {
                bubbles: true, clientX: rect.left + rect.width * x,
                clientY: rect.top + y});
            m.canvas.dispatchEvent(mk('mousedown', a));
            m.canvas.dispatchEvent(mk('mousemove', (a + b) / 2));
            m.canvas.dispatchEvent(mk('mousemove', b));
            m.canvas.dispatchEvent(mk('mouseup', b));
        }""", [label, from_fraction, to_fraction, lane_y])
    page.wait_for_timeout(150)


class TestTheEpisodeLoads(BasePlaywrightTest):
    def test_the_manifest_reaches_the_timeline(self, episode_server, page):
        open_episode(self, page, episode_server)
        assert manager_eval(page, "m.episode.num_frames") == 120
        assert manager_eval(page, "m.episode.fps") == 20
        assert manager_eval(page, "m.duration") == pytest.approx(6.0)

    def test_the_episode_path_comes_from_the_item_not_the_page(
            self, episode_server, page):
        # `text_key` points at a human-readable note, so scraping the instance
        # text fetches the note and gets a 403 from the traversal guard — for a
        # configuration that was entirely correct.
        open_episode(self, page, episode_server)
        assert manager_eval(page, "m.episode.episode_id") == "episode_0000"

    def test_both_video_streams_are_present(self, episode_server, page):
        open_episode(self, page, episode_server)
        assert manager_eval(page, "m._videos.length") == 2
        assert page.locator(".episode-stream").count() == 2

    def test_the_configured_lanes_are_drawn_and_the_rest_reported(
            self, episode_server, page):
        # Silently dropping channels is how an annotator concludes the data
        # does not contain something it does.
        open_episode(self, page, episode_server)
        assert manager_eval(page, "m._lanes.map(s => s.name)") == [
            "gripper", "wrist_force"]
        assert manager_eval(page, "m._hiddenLaneCount") > 0
        assert "not shown" in page.text_content(".episode-status")

    def test_the_instruction_is_shown(self, episode_server, page):
        open_episode(self, page, episode_server)
        assert "red block" in page.text_content(".episode-instruction")

    def test_the_canvas_is_actually_painted(self, episode_server, page):
        # A blank canvas and a correctly drawn one look the same to every
        # selector-based check, so this reads pixels.
        open_episode(self, page, episode_server)
        page.wait_for_timeout(400)
        assert page.evaluate(
            """() => {
                const c = document.querySelector('.episode-canvas');
                const ctx = c.getContext('2d');
                const d = ctx.getImageData(0, 0, c.width, c.height).data;
                const first = [d[0], d[1], d[2]];
                for (let i = 4; i < d.length; i += 4) {
                    if (d[i] !== first[0] || d[i + 1] !== first[1]
                        || d[i + 2] !== first[2]) return true;
                }
                return false;
            }""")


class TestPhases(BasePlaywrightTest):
    def test_a_drag_creates_a_phase_in_seconds(self, episode_server, page):
        open_episode(self, page, episode_server)
        draw_phase(page, "grasp", 0.2, 0.5)

        stored = json.loads(page.input_value("#input-review"))
        assert len(stored["phases"]) == 1
        phase = stored["phases"][0]
        assert phase["label"] == "grasp"
        # Seconds, matching the temporal-segment convention audio and video
        # already use, so the agreement measure needs no conversion.
        assert phase["start"] == pytest.approx(1.2, abs=0.2)
        assert phase["end"] == pytest.approx(3.0, abs=0.2)

    def test_a_click_creates_nothing(self, episode_server, page):
        # A stray click must not leave a zero-width segment that exports as a
        # degenerate row.
        open_episode(self, page, episode_server)
        draw_phase(page, "grasp", 0.4, 0.4)
        assert json.loads(page.input_value("#input-review"))["phases"] == []

    def test_overlapping_phases_are_truncated_not_stacked(
            self, episode_server, page):
        # The invariant the temporal-IoU agreement depends on: at any instant
        # the robot was doing one thing.
        open_episode(self, page, episode_server)
        draw_phase(page, "reach", 0.1, 0.6)
        draw_phase(page, "grasp", 0.4, 0.8)

        phases = json.loads(page.input_value("#input-review"))["phases"]
        assert len(phases) == 2
        ordered = sorted(phases, key=lambda p: p["start"])
        assert ordered[0]["end"] <= ordered[1]["start"] + 1e-6

    def test_delete_removes_the_selected_phase(self, episode_server, page):
        open_episode(self, page, episode_server)
        draw_phase(page, "grasp", 0.2, 0.5)
        page.evaluate(
            """() => {
                const m = document.querySelector(
                    '.episode-annotation-container').annotationManager;
                m.canvas.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'Delete', bubbles: true}));
            }""")
        page.wait_for_timeout(150)
        assert json.loads(page.input_value("#input-review"))["phases"] == []

    def test_picking_a_phase_arms_the_phase_tool(self, episode_server, page):
        open_episode(self, page, episode_server)
        page.click('.episode-phase-buttons .label-btn[data-label="reach"]')
        assert manager_eval(page, "m.currentTool") == "phase"
        # aria-pressed on the same path as the class: driving the toolbar from
        # the keyboard while every button reports "not pressed" is WCAG 4.1.2.
        assert page.get_attribute(
            '.episode-phase-buttons .label-btn[data-label="reach"]',
            "aria-pressed") == "true"


class TestOutcome(BasePlaywrightTest):
    def test_choosing_an_outcome_reaches_the_input(self, episode_server, page):
        open_episode(self, page, episode_server)
        page.check('.episode-outcome input[value="failure"]')
        page.wait_for_timeout(150)
        stored = json.loads(page.input_value("#input-review"))
        assert stored["outcome"]["result"] == "failure"

    def test_the_cause_is_disabled_until_it_applies(self, episode_server, page):
        # Present but inert rather than absent: a control that materialises on
        # selection shifts the layout under the pointer.
        open_episode(self, page, episode_server)
        assert page.is_disabled(".episode-cause")
        page.check('.episode-outcome input[value="failure"]')
        page.wait_for_timeout(150)
        assert not page.is_disabled(".episode-cause")

    def test_going_back_to_success_clears_the_cause(self, episode_server, page):
        # A stored cause on a success is a contradiction no consumer knows how
        # to read.
        open_episode(self, page, episode_server)
        page.check('.episode-outcome input[value="failure"]')
        page.select_option(".episode-cause", "object slipped")
        page.wait_for_timeout(150)
        page.check('.episode-outcome input[value="success"]')
        page.wait_for_timeout(150)

        stored = json.loads(page.input_value("#input-review"))
        assert stored["outcome"]["result"] == "success"
        assert not stored["outcome"]["cause"]
        assert page.is_disabled(".episode-cause")


class TestPersistence(BasePlaywrightTest):
    def test_a_phase_survives_navigating_away_and_back(self, episode_server,
                                                       page):
        # Never `page.reload()`: browsers cache form state across refresh and
        # the test passes even when the server never stored anything.
        open_episode(self, page, episode_server)
        draw_phase(page, "grasp", 0.2, 0.5)
        page.wait_for_timeout(1600)

        page.click("#next-btn")
        page.wait_for_timeout(1200)
        page.click("#prev-btn")
        page.wait_for_function(
            """() => {
                const c = document.querySelector(
                    '.episode-annotation-container');
                return c && c.annotationManager && c.annotationManager.episode;
            }""", timeout=30000)
        page.wait_for_timeout(600)

        stored = json.loads(page.input_value("#input-review") or "{}")
        assert stored.get("phases"), "the phase should have come back"
        assert stored["phases"][0]["label"] == "grasp"

    def test_switching_items_does_not_leak_annotations(self, episode_server,
                                                       page):
        # Nothing here is owned by a canvas or a scene graph, so a generic
        # clear reaches none of it — three cross-instance corruption bugs in
        # the image manager came from exactly that gap.
        open_episode(self, page, episode_server)
        draw_phase(page, "grasp", 0.2, 0.5)
        page.wait_for_timeout(1600)

        page.click("#next-btn")
        page.wait_for_timeout(1500)

        stored = json.loads(page.input_value("#input-review") or "{}")
        assert not stored.get("phases"), (
            "the second episode must not inherit the first's phases")

    def test_clear_annotations_resets_every_layer(self, episode_server, page):
        open_episode(self, page, episode_server)
        draw_phase(page, "grasp", 0.2, 0.5)
        page.check('.episode-outcome input[value="failure"]')
        page.wait_for_timeout(200)

        page.evaluate(
            """() => {
                document.querySelector('.episode-annotation-container')
                    .annotationManager.clearAnnotations();
            }""")
        page.wait_for_timeout(150)

        stored = json.loads(page.input_value("#input-review"))
        assert stored["phases"] == []
        assert stored["reward"] == []
        assert not stored["outcome"]["result"]
        assert manager_eval(page, "m._drag") is None
        assert page.is_disabled(".episode-cause")
        assert not page.is_checked('.episode-outcome input[value="failure"]')


class TestHindsightRelabelling(BasePlaywrightTest):
    """
    Relabelling turns a discarded episode into training data: a failed attempt
    at "put the block in the bowl" is a perfect demonstration of "push the
    block to the left".
    """

    def test_the_datasets_own_instruction_is_not_overwritten(
            self, episode_server, page):
        # Overwriting it would destroy the pairing that makes the relabel
        # informative -- "it was asked to X and actually did Y".
        open_episode(self, page, episode_server)
        page.fill(".episode-relabel", "pushed the block off the table")
        page.wait_for_timeout(200)
        assert "red block" in page.text_content(".episode-instruction")

    def test_the_relabel_reaches_the_input(self, episode_server, page):
        open_episode(self, page, episode_server)
        page.fill(".episode-relabel", "pushed the block off the table")
        page.wait_for_timeout(200)
        stored = json.loads(page.input_value("#input-review"))
        assert stored["instructions"][0]["text"] == (
            "pushed the block off the table")

    def test_an_empty_relabel_is_not_an_annotation(self, episode_server, page):
        # Storing one would make every untouched episode look answered.
        open_episode(self, page, episode_server)
        page.fill(".episode-relabel", "x")
        page.wait_for_timeout(200)
        page.fill(".episode-relabel", "")
        page.wait_for_timeout(200)
        assert json.loads(page.input_value("#input-review"))["instructions"] == []

    def test_aligning_to_a_phase_stamps_its_range(self, episode_server, page):
        # Typed timestamps get guessed or read off the transport; a button is
        # both faster and exact.
        open_episode(self, page, episode_server)
        draw_phase(page, "grasp", 0.2, 0.5)
        page.fill(".episode-relabel", "closed on nothing")
        page.wait_for_timeout(150)
        page.click(".episode-relabel-align")
        page.wait_for_timeout(200)

        entry = json.loads(page.input_value("#input-review"))["instructions"][0]
        phase = json.loads(page.input_value("#input-review"))["phases"][0]
        assert entry["start"] == pytest.approx(phase["start"])
        assert entry["end"] == pytest.approx(phase["end"])
        assert "s" in page.text_content(".episode-relabel-span")

    def test_aligning_with_nothing_selected_says_so(self, episode_server, page):
        # Silently doing nothing reads as a broken button.
        open_episode(self, page, episode_server)
        page.click(".episode-relabel-align")
        page.wait_for_timeout(200)
        assert "Select a phase" in page.text_content(".episode-status")

    def test_the_relabel_survives_navigating_away_and_back(
            self, episode_server, page):
        open_episode(self, page, episode_server)
        page.fill(".episode-relabel", "pushed it left")
        page.wait_for_timeout(1600)

        page.click("#next-btn")
        page.wait_for_timeout(1200)
        page.click("#prev-btn")
        page.wait_for_function(
            """() => {
                const c = document.querySelector(
                    '.episode-annotation-container');
                return c && c.annotationManager && c.annotationManager.episode;
            }""", timeout=30000)
        page.wait_for_timeout(600)

        assert page.input_value(".episode-relabel") == "pushed it left"
