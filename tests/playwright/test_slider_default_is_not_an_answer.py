"""A slider nobody moved is not an answer, and one they moved is.

A range input always reports a value. `slider`, `vas` and `soft_label` all
render at a starting position -- mid-scale, or an even split -- so the DOM of an
untouched item is indistinguishable from a considered one unless something
records the interaction. Nothing did, in either direction:

* `syncAnnotationsFromDOM` collected every range unconditionally, so merely
  opening an item stored the default as that annotator's answer. Walking a
  corpus without answering produced a complete-looking dataset of midpoints, and
  `require_fully_annotated` could not tell, because the scheme was always full.
* The required-scheme check asked for `data-modified`, which nothing ever set on
  a range. A required slider could not be satisfied by dragging it: the
  annotator moved it, pressed Next, and was refused with no way forward.

Both now hang off the same signal, marked scheme-wide because `soft_label` and
`constant_sum` move their sibling sliders in code when one is dragged.

The first test is the control. Without it a naive fix -- marking everything
touched on load -- passes every other test here.
"""

from __future__ import annotations

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

SCHEMES = [
    {"annotation_type": "slider", "name": "s_slider", "description": "Slider?",
     "min_value": 0, "max_value": 100, "starting_value": 50},
    {"annotation_type": "vas", "name": "s_vas", "description": "VAS?",
     "min_value": 0, "max_value": 100},
    {"annotation_type": "soft_label", "name": "s_soft", "description": "Split?",
     "labels": ["x", "y"], "total": 100},
]


@pytest.fixture
def slider_server(make_server):
    return make_server(SCHEMES, num_items=3)


class TestSliderDefaults(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        page.wait_for_selector('input[type="range"].annotation-input')
        page.wait_for_timeout(1200)

    def _ranges(self, page, schema=None):
        selector = 'input[type="range"].annotation-input'
        if schema:
            selector += f'[schema="{schema}"]'
        return page.locator(selector)

    def _instance(self, page):
        """The id the save path uses. `get_instance_id` reads a `#instance-id`
        element this template does not render, and asking `/get_annotations`
        for `None` answers 200 with nothing, so the assertions would pass
        against a server that stored everything."""
        instance = page.evaluate(
            "() => (document.getElementById('instance_id') || {}).value"
            " || (window.currentInstance && window.currentInstance.id) || null")
        assert instance, "no instance id on the page"
        return instance

    def _stored(self, page, server):
        return self.verify_server_annotations(
            page, server, self._instance(page)).get("label_annotations", {})

    def _drag(self, page, schema, value="70"):
        handle = self._ranges(page, schema).first
        handle.fill(value)
        handle.dispatch_event("input")
        self.wait_for_debounce(page, 2000)

    def test_opening_the_item_answers_nothing(self, page, slider_server):
        """The control, and the bug: three schemes used to arrive pre-answered."""
        self._open(page, slider_server)
        page.wait_for_timeout(2500)
        assert self._stored(page, slider_server) == {}

    @pytest.mark.parametrize("schema", ["s_slider", "s_vas", "s_soft"])
    def test_a_dragged_slider_is_stored(self, page, slider_server, schema):
        self._open(page, slider_server)
        self._drag(page, schema)
        assert schema in self._stored(page, slider_server)

    def test_dragging_one_scheme_does_not_answer_the_others(self, page, slider_server):
        """Scheme-wide marking must stay inside the scheme."""
        self._open(page, slider_server)
        self._drag(page, "s_vas")
        stored = self._stored(page, slider_server)
        assert "s_vas" in stored
        assert "s_slider" not in stored and "s_soft" not in stored

    def test_a_constrained_group_stores_every_slider(self, page, slider_server):
        """`soft_label` redistributes its siblings in code, with no event.

        Storing only the slider under the cursor keeps one number out of a
        distribution that means nothing in pieces.
        """
        self._open(page, slider_server)
        self._drag(page, "s_soft", "90")
        stored = self._stored(page, slider_server)
        assert set(stored.get("s_soft", {})) == {"x", "y"}

    def test_the_answer_survives_navigating_away_and_back(self, page, slider_server):
        """Never a refresh: browsers restore form state, so a refresh passes
        even when the server kept nothing."""
        self._open(page, slider_server)
        self._drag(page, "s_slider", "83")
        self.click_next(page)
        page.wait_for_timeout(1500)
        self.click_prev(page)
        page.wait_for_selector('input[type="range"].annotation-input')
        page.wait_for_timeout(1500)
        assert self._ranges(page, "s_slider").first.input_value() == "83"

    def test_visiting_an_item_and_leaving_answers_nothing(self, page, slider_server):
        """The damage the old behaviour did at scale: every item merely passed
        through came back holding a midpoint."""
        self._open(page, slider_server)
        self._drag(page, "s_slider", "83")
        self.click_next(page)
        page.wait_for_selector('input[type="range"].annotation-input')
        page.wait_for_timeout(2500)
        assert self._stored(page, slider_server) == {}

    def test_the_slider_still_renders_at_its_starting_value(self, page, slider_server):
        """`starting_value` is a design choice about where the scale begins.

        Guarded because the obvious fix -- reset to the `min` attribute when the
        instance changes -- silently moved every mid-scale slider to its floor.
        """
        self._open(page, slider_server)
        assert self._ranges(page, "s_slider").first.input_value() == "50"
        self.click_next(page)
        page.wait_for_selector('input[type="range"].annotation-input')
        page.wait_for_timeout(1200)
        assert self._ranges(page, "s_slider").first.input_value() == "50"


REQUIRED_SCHEME = [{
    "annotation_type": "slider", "name": "must_rate", "description": "Rate it.",
    "min_value": 0, "max_value": 100, "starting_value": 50,
    "label_requirement": {"required": True},
}]


@pytest.fixture
def required_slider_server(make_server):
    return make_server(REQUIRED_SCHEME, num_items=3,
                       extra_config={"require_fully_annotated": True})


class TestRequiredSliderCanBeSatisfied(BasePlaywrightTest):
    """A required slider used to be a wall.

    The client-side check asked whether the range carried `data-modified`, and
    nothing set it, so an annotator dragged the slider, pressed Next, and stayed
    on the same item -- with the only feedback a console line. Any task pairing
    `require_fully_annotated` with a slider, vas or soft_label scheme could not
    be completed at all.
    """

    def test_dragging_it_lets_the_annotator_move_on(self, page, required_slider_server):
        self.register_and_login(page, required_slider_server)
        page.goto(f"{required_slider_server.base_url}/annotate")
        page.wait_for_selector('input[type="range"].annotation-input')
        page.wait_for_timeout(1200)

        first = page.evaluate(
            "() => (document.getElementById('instance_id') || {}).value")
        handle = page.locator('input[type="range"].annotation-input').first
        handle.fill("83")
        handle.dispatch_event("input")
        self.wait_for_debounce(page, 2000)

        self.click_next(page)
        page.wait_for_timeout(2500)
        second = page.evaluate(
            "() => (document.getElementById('instance_id') || {}).value")
        assert second and second != first, (
            "Next was refused after the slider was dragged: a required slider "
            "cannot be satisfied, so the task cannot be finished")

    def test_it_still_refuses_when_the_slider_was_never_touched(self, page,
                                                               required_slider_server):
        """The requirement has to still mean something. Without this, marking
        every range answered on load would pass the test above."""
        self.register_and_login(page, required_slider_server)
        page.goto(f"{required_slider_server.base_url}/annotate")
        page.wait_for_selector('input[type="range"].annotation-input')
        page.wait_for_timeout(1500)

        first = page.evaluate(
            "() => (document.getElementById('instance_id') || {}).value")
        self.click_next(page)
        page.wait_for_timeout(2500)
        second = page.evaluate(
            "() => (document.getElementById('instance_id') || {}).value")
        assert second == first, (
            "an untouched required slider let the annotator advance")
