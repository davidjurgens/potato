"""Two display options were documented by an example and read by nobody.

`_reject_unknown_display_options` (see `test_display_options_validation.py`)
found four dead keys in the repo's own shipped configs. Two were typos. The
other two were real gaps: an example asked for behaviour the renderer never
implemented, and because nothing validated option names, the config looked fine
and the page quietly ignored it.

  examples/custom-layouts/dialogue-qa       text.collapsed_by_default
  examples/agent-traces/complex-annotation  dialogue.max_height

Deleting the keys would have removed the authors' intent along with the dead
config, so both are implemented.
"""

import re

import pytest

from potato.server_utils.displays.dialogue_display import DialogueDisplay
from potato.server_utils.displays.text_display import TextDisplay


class TestCollapsibleTextCanStartCollapsed:
    """`collapsible: true` could only ever open expanded.

    A long case file therefore sat between the instructions and the questions on
    every item, which is what the example was trying to avoid.
    """

    def render(self, **options):
        options.setdefault("collapsible", True)
        return TextDisplay().render(
            {"key": "context", "label": "Case Context", "display_options": options},
            "a long case file")

    def test_the_option_is_declared(self):
        assert "collapsed_by_default" in TextDisplay.optional_fields

    def test_it_still_opens_expanded_by_default(self):
        html = self.render()
        assert '<div class="collapse show"' in html
        assert 'aria-expanded="true"' in html

    def test_collapsed_by_default_starts_it_closed(self):
        html = self.render(collapsed_by_default=True)
        assert '<div class="collapse"' in html
        assert 'aria-expanded="false"' in html

    def test_the_toggle_and_the_panel_agree(self):
        """A button saying "expanded" over a closed panel is worse than either."""
        for collapsed in (True, False):
            html = self.render(collapsed_by_default=collapsed)
            expanded = re.search(r'aria-expanded="(\w+)"', html).group(1)
            shown = 'class="collapse show"' in html
            assert (expanded == "true") is shown

    def test_it_does_nothing_without_collapsible(self):
        html = TextDisplay().render(
            {"key": "context", "display_options": {"collapsed_by_default": True}},
            "plain text")
        assert "collapse" not in html


class TestDialogueCanScrollInsteadOfPushingTheFormDown:
    """A long agent trace pushed the annotation form off the bottom of the page."""

    def render(self, **options):
        return DialogueDisplay().render(
            {"key": "conversation", "display_options": options},
            [{"speaker": "A", "text": "hello"}, {"speaker": "B", "text": "hi"}])

    def test_the_option_is_declared(self):
        assert "max_height" in DialogueDisplay.optional_fields

    def test_no_cap_by_default(self):
        assert "max-height" not in self.render()

    def test_a_number_is_read_as_pixels(self):
        assert "max-height: 600px" in self.render(max_height=600)

    def test_it_scrolls_rather_than_clipping(self):
        """Clipped rows are unreachable; the admin IAA table shipped that bug."""
        assert "overflow-y: auto" in self.render(max_height=600)

    def test_a_css_length_is_passed_through(self):
        assert "max-height: 40vh" in self.render(max_height="40vh")

    def test_the_value_is_escaped(self):
        html = self.render(max_height='600px" onload="alert(1)')
        assert 'onload="alert(1)' not in html

    def test_the_cap_is_on_the_container_not_the_turns(self):
        """Turn markup is what span offsets are computed from; it must not move."""
        html = self.render(max_height=600)
        container = html[:html.index("dialogue-turn")]
        assert "max-height" in container
