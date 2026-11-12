"""
Label shortcuts (annotation.js installLabelKeyShortcuts) in a real browser,
with a radio, a select and a card sort on one page.

The shortcuts fire on keyup, so before the fix nothing a widget did on keydown
could stop them: a digit on a focused card moved the card and also ticked the
radio bound to that digit, Ctrl+C ticked the label bound to `c`, and typing in
a <select> ran shortcuts. tests/jest/label-key-shortcuts.test.js covers each
rule with synthetic events; this drives real key presses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

SCHEMES = [
    {"annotation_type": "radio", "name": "sentiment", "description": "Sentiment",
     "labels": [{"name": "positive", "key_value": "c"},
                {"name": "negative", "key_value": "1"}]},
    {"annotation_type": "select", "name": "category", "description": "Category",
     "labels": ["alpha", "cat", "dog"]},
    {"annotation_type": "card_sort", "name": "sorting", "description": "Sort",
     "mode": "closed", "groups": ["Group A", "Group B"], "items_field": "items"},
]
ITEMS = [{"id": f"instance_{i}", "text": f"Text {i}", "items": ["apple", "pear"]}
         for i in range(2)]


def radio_checked(page, value):
    return page.is_checked(f'input[type="radio"][name="sentiment"][value="{value}"]')


class TestLabelKeyShortcuts(BasePlaywrightTest):
    @pytest.fixture
    def server(self, make_server):
        return make_server(SCHEMES, items=ITEMS)

    def test_keys_another_control_handles_do_not_tick_a_label(self, server, page):
        self.register_and_login(page, server)
        page.wait_for_selector(".card-sort-card")

        # Typing in a select picks an option; it is not a shortcut.
        page.focus('select[name*="category"]')
        page.keyboard.press("c")
        assert not radio_checked(page, "positive")

        page.click("#instance-text")
        page.keyboard.press("Control+c")
        assert not radio_checked(page, "positive")

        # A digit on a focused card moves it to that group (card_sort calls
        # preventDefault); the radio bound to the digit stays as it was.
        page.focus(".card-sort-card")
        page.keyboard.press("1")
        assert page.locator('[data-drop-group="Group A"] .card-sort-card').count() == 1
        assert not radio_checked(page, "negative")

        # The plain key still works.
        page.click("#instance-text")
        page.keyboard.press("c")
        assert radio_checked(page, "positive")


SLIDER = [{"annotation_type": "range_slider", "name": "span", "description": "Range",
           "min_value": 0, "max_value": 100}]


class TestArrowNavigation(BasePlaywrightTest):
    def test_an_arrow_a_control_uses_does_not_change_the_item(self, make_server, page):
        server = make_server(SLIDER, num_items=3)
        self.register_and_login(page, server)
        first = page.input_value("#instance_id")

        # On a focused slider thumb the arrow moves the thumb, and only that.
        page.focus(".range-slider-thumb-low")
        page.keyboard.press("ArrowRight")
        assert page.get_attribute(".range-slider-thumb-low", "aria-valuenow") != "0"
        page.wait_for_timeout(500)
        assert page.input_value("#instance_id") == first

        # Elsewhere on the page it still changes the item.
        page.click("#instance-text")
        page.keyboard.press("ArrowRight")
        page.wait_for_function(
            f"() => document.getElementById('instance_id').value !== '{first}'",
            timeout=10000)


IMAGE_MEDIA = Path("examples/image/geometry-primitives/media").resolve()


def sequential_radio(name, n):
    return {"annotation_type": "radio", "name": name, "description": name,
            "labels": [f"{name}{i}" for i in range(n)], "sequential_key_binding": True}


class TestKeysBesideAnImage(BasePlaywrightTest):
    def test_every_radio_key_ticks_its_label_and_picks_no_tool(self, make_server, page):
        # The allocator used to give the second radio q w e r t, and the
        # canvas took r for the bounding-box tool before the radio saw it.
        if not (IMAGE_MEDIA / "street.jpg").is_file():
            pytest.skip("examples/image/geometry-primitives media is missing")
        image = {"annotation_type": "image_annotation", "name": "shapes",
                 "description": "Box things", "source_field": "image_url",
                 "tools": ["bbox"], "labels": [{"name": "car", "color": "#E74C3C"}]}
        server = make_server(
            [image, sequential_radio("first", 10), sequential_radio("second", 5)],
            items=[{"id": "img_1", "image_url": "/media/street.jpg"}],
            extra_config={"media_directory": str(IMAGE_MEDIA),
                          "item_properties": {"id_key": "id", "text_key": "image_url"}})
        self.register_and_login(page, server)
        self.image_manager_ready(page, "shapes")
        tool = """() => document.querySelector('.image-annotation-container')
                          .annotationManager.currentTool"""
        before = page.evaluate(tool)

        for i in range(5):
            radio = page.locator(f'input[type="radio"][name*="second"][value="second{i}"]')
            key = radio.get_attribute("data-key")
            page.evaluate("() => document.activeElement && document.activeElement.blur()")
            page.keyboard.press(key)
            assert radio.is_checked(), f"{key} did not tick second{i}"
            assert page.evaluate(tool) == before, f"{key} picked a tool"

