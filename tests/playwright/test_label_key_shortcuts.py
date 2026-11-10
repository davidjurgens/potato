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
