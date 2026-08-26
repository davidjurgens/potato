"""
Grounding evaluation, driven through the real interface.

The binding between an expression and a region is a **swap**: the canvas holds
only the active expression's regions, and selecting another captures, clears
and restores. That design is only checkable in a browser, and its failure mode
is the worst kind — an annotation silently attributed to the wrong phrase,
which looks like a correct annotation of a different thing.

So the load-bearing test here is `test_each_expression_keeps_its_own_region`:
draw for one phrase, switch, draw for another, and verify each kept its own.
"""

import json
import os

import pytest
import yaml

from tests.playwright.test_base import BasePlaywrightTest

GROUNDING = "grounding"
IMAGE = "regions"


@pytest.fixture(scope="module")
def grounding_server():
    pytest.importorskip("PIL", reason="the fixture image needs Pillow")

    from PIL import Image, ImageDraw

    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.port_manager import find_free_port
    from tests.helpers.test_utils import create_test_directory

    test_dir = create_test_directory("playwright_grounding")
    media = os.path.join(test_dir, "media")
    os.makedirs(media, exist_ok=True)
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([50, 50, 300, 400], fill="#c0392b")     # "the red shape"
    draw.rectangle([500, 100, 750, 450], fill="#2980b9")   # "the blue shape"
    image.save(os.path.join(media, "scene.png"))

    items = [{
        "id": f"scene_{index}",
        # The plain (non-tiled) viewer loads this URL directly, so it has to
        # be one the server actually serves — /media/<path> is the media route.
        "image": "/media/scene.png",
        "expressions": [
            {"id": "e1", "text": "the red shape on the left"},
            {"id": "e2", "text": "the blue shape on the right"},
            {"id": "e3", "text": "the green triangle"},
        ],
    # Three items, not two: Next from the LAST item completes the task and
    # renders the thank-you page, so a two-item fixture cannot navigate away
    # and back.
    } for index in range(3)]
    data_file = os.path.join(test_dir, "items.json")
    with open(data_file, "w", encoding="utf-8") as handle:
        json.dump(items, handle)

    config = {
        "port": 0,
        "annotation_task_name": "Grounding",
        "task_dir": test_dir,
        "media_directory": media,
        "output_annotation_dir": os.path.join(test_dir, "out"),
        "data_files": [data_file],
        "item_properties": {"id_key": "id", "text_key": "image"},
        "user_config": {"allow_all_users": True},
        "annotation_schemes": [
            {
                "annotation_type": "image_annotation",
                "name": IMAGE,
                "description": "Draw the region",
                "source_field": "image",
                "tools": ["bbox", "landmark"],
                "labels": [{"name": "referent", "color": "#FF0000"}],
            },
            {
                "annotation_type": "grounding_eval",
                "name": GROUNDING,
                "description": "What does each phrase refer to?",
                "region_type": "box",
            },
        ],
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle)

    srv = FlaskTestServer(port=find_free_port(), debug=False,
                          config_file=config_path)
    if not srv.start():
        raise RuntimeError("Failed to start the grounding Playwright server")
    yield srv
    srv.stop()


@pytest.mark.playwright
class TestGroundingEval(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        page.wait_for_function(
            """(schema) => {
                const c = document.querySelector(
                    `.grounding-eval-container[data-schema="${schema}"]`);
                const m = c && c.groundingManager;
                return !!(m && m.expressions.length && m.imageManager);
            }""", arg=GROUNDING, timeout=20_000)
        self.image_manager_ready(page, IMAGE)
        return page

    def _state(self, page):
        return page.evaluate(
            """(schema) => {
                const m = document.querySelector(
                    `.grounding-eval-container[data-schema="${schema}"]`)
                    .groundingManager;
                return {active: m.activeId,
                        answers: m.serialize(),
                        unanswered: m.unanswered()};
            }""", arg=GROUNDING)

    def _select(self, page, expression_id):
        page.click(f'.grounding-expression-btn[data-expression="{expression_id}"]')

    # -- the list ------------------------------------------------------------

    def test_the_expressions_are_listed(self, page, grounding_server):
        self._open(page, grounding_server)
        assert page.locator(".grounding-expression-btn").count() == 3
        assert "the red shape on the left" in page.inner_text(".grounding-list")

    def test_the_first_expression_is_selected_on_load(self, page, grounding_server):
        self._open(page, grounding_server)
        assert self._state(page)["active"] == "e1"

    def test_every_expression_starts_unanswered(self, page, grounding_server):
        self._open(page, grounding_server)
        assert self._state(page)["unanswered"] == ["e1", "e2", "e3"]

    # -- binding -------------------------------------------------------------

    def test_a_region_is_stored_against_the_active_expression(self, page,
                                                              grounding_server):
        self._open(page, grounding_server)
        self._select(page, "e1")
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.7,
                                label="referent")
        state = self._state(page)
        assert "e1" in state["answers"]["regions"]
        assert "e2" not in state["answers"]["regions"]

    def test_each_expression_keeps_its_own_region(self, page, grounding_server):
        """
        The load-bearing test. A mis-attribution here looks exactly like a
        correct annotation of a different thing.
        """
        self._open(page, grounding_server)
        self._select(page, "e1")
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.7,
                                label="referent")
        self._select(page, "e2")
        self.draw_bbox_on_image(page, IMAGE, 0.6, 0.15, 0.95, 0.75,
                                label="referent")

        regions = self._state(page)["answers"]["regions"]
        assert set(regions) == {"e1", "e2"}
        left = regions["e1"][0]["coordinates"]
        right = regions["e2"][0]["coordinates"]
        assert left["x"] < 0.3, f"e1 kept the wrong region: {left}"
        assert right["x"] > 0.5, f"e2 kept the wrong region: {right}"

    def test_switching_back_puts_the_region_on_the_canvas_again(self, page,
                                                                grounding_server):
        self._open(page, grounding_server)
        self._select(page, "e1")
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.7,
                                label="referent")
        self._select(page, "e2")
        assert self.read_annotation_data(page, IMAGE) == []
        self._select(page, "e1")
        restored = self.read_annotation_data(page, IMAGE)
        assert len(restored) == 1, "the region did not come back on the canvas"

    # -- the three states ----------------------------------------------------

    def test_not_present_is_recorded_as_its_own_answer(self, page,
                                                       grounding_server):
        """
        Not as an empty region. An annotator who judged nothing matches and one
        who never reached the phrase support opposite conclusions about a model
        that also produced nothing.
        """
        self._open(page, grounding_server)
        self._select(page, "e3")
        page.click(".grounding-absent-btn")
        state = self._state(page)
        assert "e3" in state["answers"]["absent"]
        assert "e3" not in state["answers"]["regions"]
        assert "e3" not in state["unanswered"]

    def test_drawing_withdraws_an_absent_claim(self, page, grounding_server):
        """Both set at once would make the stored value contradict itself."""
        self._open(page, grounding_server)
        self._select(page, "e1")
        page.click(".grounding-absent-btn")
        self._select(page, "e1")
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.7,
                                label="referent")
        state = self._state(page)
        assert "e1" in state["answers"]["regions"]
        assert "e1" not in state["answers"]["absent"]

    def test_clearing_returns_an_expression_to_unanswered(self, page,
                                                          grounding_server):
        self._open(page, grounding_server)
        self._select(page, "e1")
        page.click(".grounding-absent-btn")
        self._select(page, "e1")
        page.click(".grounding-clear-btn")
        state = self._state(page)
        assert "e1" in state["unanswered"]
        assert "e1" not in state["answers"]["absent"]

    def test_the_progress_line_names_what_is_left(self, page, grounding_server):
        self._open(page, grounding_server)
        self._select(page, "e1")
        page.click(".grounding-absent-btn")
        text = page.inner_text(f"#grounding-progress-{GROUNDING}")
        assert "1 of 3" in text
        assert "the blue shape on the right" in text

    # -- accessibility -------------------------------------------------------

    def test_the_state_is_in_the_accessible_name(self, page, grounding_server):
        """
        Not only in the fill colour. "located" and "not present" are the
        answer, and a screen-reader user needs them without the styling.
        """
        self._open(page, grounding_server)
        self._select(page, "e3")
        page.click(".grounding-absent-btn")
        label = page.get_attribute(
            '.grounding-expression-btn[data-expression="e3"]', "aria-label")
        assert "not present" in label

    # -- persistence ---------------------------------------------------------

    def test_answers_survive_navigating_away_and_back(self, page,
                                                      grounding_server):
        self._open(page, grounding_server)
        self._select(page, "e1")
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.7,
                                label="referent")
        self._select(page, "e3")
        page.click(".grounding-absent-btn")
        self.wait_for_debounce(page)

        self.click_next(page)
        page.wait_for_timeout(500)
        self.click_prev(page)
        page.wait_for_function(
            """(schema) => {
                const c = document.querySelector(
                    `.grounding-eval-container[data-schema="${schema}"]`);
                return !!(c && c.groundingManager
                          && c.groundingManager.expressions.length);
            }""", arg=GROUNDING, timeout=20_000)

        state = self._state(page)
        assert "e1" in state["answers"]["regions"], state
        assert "e3" in state["answers"]["absent"], state


CAPTION = "A red bicycle leans against a blue wall beside a small dog."


@pytest.fixture(scope="module")
def caption_server():
    """A hallucination-localization project: phrases come out of the caption."""
    pytest.importorskip("PIL", reason="the fixture image needs Pillow")

    from PIL import Image, ImageDraw

    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.port_manager import find_free_port
    from tests.helpers.test_utils import create_test_directory

    test_dir = create_test_directory("playwright_caption_grounding")
    media = os.path.join(test_dir, "media")
    os.makedirs(media, exist_ok=True)
    image = Image.new("RGB", (800, 600), "white")
    ImageDraw.Draw(image).rectangle([100, 100, 400, 500], fill="#2980b9")
    image.save(os.path.join(media, "scene.png"))

    items = [{"id": f"cap_{index}", "image": "/media/scene.png",
              "caption": CAPTION} for index in range(3)]
    data_file = os.path.join(test_dir, "items.json")
    with open(data_file, "w", encoding="utf-8") as handle:
        json.dump(items, handle)

    config = {
        "port": 0,
        "annotation_task_name": "Caption grounding",
        "task_dir": test_dir,
        "media_directory": media,
        "output_annotation_dir": os.path.join(test_dir, "out"),
        "data_files": [data_file],
        "item_properties": {"id_key": "id", "text_key": "image"},
        "user_config": {"allow_all_users": True},
        "annotation_schemes": [
            {
                "annotation_type": "image_annotation",
                "name": IMAGE,
                "description": "Draw the region",
                "source_field": "image",
                "tools": ["bbox"],
                "labels": [{"name": "referent", "color": "#FF0000"}],
            },
            {
                "annotation_type": "grounding_eval",
                "name": GROUNDING,
                "description": "Ground each phrase of the caption",
                "expression_source": "spans",
                "caption_field": "caption",
                "region_type": "box",
            },
        ],
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle)

    srv = FlaskTestServer(port=find_free_port(), debug=False,
                          config_file=config_path)
    if not srv.start():
        raise RuntimeError("Failed to start the caption-grounding server")
    yield srv
    srv.stop()


@pytest.mark.playwright
class TestCaptionGrounding(BasePlaywrightTest):
    """
    Hallucination localization: the phrases are whatever the model said, so
    they are selected out of the caption rather than given in advance.
    """

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        page.wait_for_function(
            """(schema) => {
                const c = document.querySelector(
                    `.grounding-eval-container[data-schema="${schema}"]`);
                const m = c && c.groundingManager;
                return !!(m && m.caption && m.imageManager);
            }""", arg=GROUNDING, timeout=20_000)
        self.image_manager_ready(page, IMAGE)
        return page

    def _select_phrase(self, page, phrase):
        """Select `phrase` inside the caption with a real DOM range."""
        page.evaluate(
            """({schema, phrase}) => {
                const el = document.getElementById('grounding-caption-' + schema);
                const node = el.firstChild;
                const start = node.textContent.indexOf(phrase);
                if (start < 0) throw new Error('phrase not in caption: ' + phrase);
                const range = document.createRange();
                range.setStart(node, start);
                range.setEnd(node, start + phrase.length);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                document.dispatchEvent(new Event('selectionchange'));
            }""", {"schema": GROUNDING, "phrase": phrase})

    def _state(self, page):
        return page.evaluate(
            """(schema) => {
                const m = document.querySelector(
                    `.grounding-eval-container[data-schema="${schema}"]`)
                    .groundingManager;
                return {answers: m.serialize(),
                        expressions: m.expressions.map((e) => e.text),
                        coverage: m.captionCoverage()};
            }""", arg=GROUNDING)

    def test_the_caption_is_shown(self, page, caption_server):
        self._open(page, caption_server)
        assert CAPTION in page.inner_text(f"#grounding-caption-{GROUNDING}")

    def test_no_phrases_exist_until_one_is_selected(self, page, caption_server):
        self._open(page, caption_server)
        assert self._state(page)["expressions"] == []

    def test_selecting_a_phrase_creates_an_expression(self, page, caption_server):
        self._open(page, caption_server)
        self._select_phrase(page, "A red bicycle")
        page.click(".grounding-add-span-btn")
        assert "A red bicycle" in self._state(page)["expressions"]

    def test_the_phrase_id_carries_its_offsets(self, page, caption_server):
        """
        What makes an answer reload-safe, and what lets two annotators who
        picked the same phrase produce the same id.
        """
        self._open(page, caption_server)
        self._select_phrase(page, "a blue wall")
        page.click(".grounding-add-span-btn")
        expected = CAPTION.index("a blue wall")
        ids = page.evaluate(
            """(schema) => document.querySelector(
                `.grounding-eval-container[data-schema="${schema}"]`)
                .groundingManager.expressions.map((e) => e.id)""", arg=GROUNDING)
        assert f"span:{expected}-{expected + len('a blue wall')}" in ids

    def test_a_phrase_can_be_grounded_to_a_region(self, page, caption_server):
        self._open(page, caption_server)
        self._select_phrase(page, "a blue wall")
        page.click(".grounding-add-span-btn")
        self.draw_bbox_on_image(page, IMAGE, 0.15, 0.2, 0.5, 0.8,
                                label="referent")
        state = self._state(page)
        assert len(state["answers"]["regions"]) == 1
        assert state["coverage"]["grounded_chars"] == len("a blue wall")

    def test_an_ungrounded_phrase_is_recorded_as_such(self, page, caption_server):
        """The whole point: a phrase naming something that is not there."""
        self._open(page, caption_server)
        self._select_phrase(page, "a small dog")
        page.click(".grounding-add-span-btn")
        page.click(".grounding-absent-btn")
        state = self._state(page)
        assert len(state["answers"]["absent"]) == 1
        assert state["coverage"]["ungrounded_chars"] == len("a small dog")

    def test_coverage_reports_both_rates(self, page, caption_server):
        self._open(page, caption_server)
        self._select_phrase(page, "A red bicycle")
        page.click(".grounding-add-span-btn")
        page.click(".grounding-absent-btn")
        coverage = self._state(page)["coverage"]
        assert coverage["caption_chars"] == len(CAPTION)
        assert 0 < coverage["ungrounded_fraction"] < 1
        assert coverage["grounded_fraction"] == 0

    def test_the_phrase_is_marked_in_the_caption(self, page, caption_server):
        self._open(page, caption_server)
        self._select_phrase(page, "a small dog")
        page.click(".grounding-add-span-btn")
        page.click(".grounding-absent-btn")
        assert page.locator(f"#grounding-caption-{GROUNDING} mark.state-absent"
                            ).count() == 1

    def test_selected_phrases_survive_navigation(self, page, caption_server):
        self._open(page, caption_server)
        self._select_phrase(page, "a small dog")
        page.click(".grounding-add-span-btn")
        page.click(".grounding-absent-btn")
        self.wait_for_debounce(page)

        self.click_next(page)
        page.wait_for_timeout(500)
        self.click_prev(page)
        page.wait_for_function(
            """(schema) => {
                const c = document.querySelector(
                    `.grounding-eval-container[data-schema="${schema}"]`);
                return !!(c && c.groundingManager && c.groundingManager.caption);
            }""", arg=GROUNDING, timeout=20_000)
        page.wait_for_timeout(500)

        state = self._state(page)
        assert "a small dog" in state["expressions"], state
        assert len(state["answers"]["absent"]) == 1, state
