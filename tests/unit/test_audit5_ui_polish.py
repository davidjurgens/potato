"""Three defects the impeccable:audit pass found in the audit-5 fixes themselves.

Each was invisible to the unit suite and visible the moment the page was driven:
a state class that was set and never cleared, a CSS fallback selector that also
matched the case it was a fallback for, and a status message with no role.
"""

import re
from pathlib import Path

import potato


STATIC = Path(potato.__file__).parent / "static"
TREE_CSS = (STATIC / "css" / "conversation-tree.css").read_text(encoding="utf-8")
ANNOTATION_JS = (STATIC / "annotation.js").read_text(encoding="utf-8")


class TestOneCheckmarkPerAnsweredNode:
    """`.has-annotation` marks a node that already carries an answer.

    The rule listed the node's header and the node itself, so the tick would
    land whichever the display emitted. Both matched, and an answered node grew
    two ticks -- which reads as two things marked, not one.
    """

    def test_the_node_fallback_only_applies_without_a_header(self):
        rule = TREE_CSS[TREE_CSS.index(".conv-tree-node.has-annotation"):]
        rule = rule[:rule.index("}")]

        assert ":not(:has(> .conv-tree-node-header))" in rule
        assert ".conv-tree-node.has-annotation > .conv-tree-node-header::after" in rule

    def test_a_bare_node_selector_is_not_left_in(self):
        assert not re.search(
            r"\.conv-tree-node\.has-annotation::after", TREE_CSS), (
            "an unconditional node rule renders a second tick beside the header's")


class TestTheRequiredFieldsBannerIsAnnounced:
    """Pressing Next and having nothing happen needs an explanation.

    A banner that only appears on screen is not one. This matters more since
    composite widgets began putting the specific shortfall in it: "3 of 10
    scored" is the useful half, and it was the half nobody heard.
    """

    def _banner_setup(self):
        body = ANNOTATION_JS[ANNOTATION_JS.index("function updateRequiredFieldsError"):]
        return body[:body.index("errorDiv.style.display = 'block';")]

    def test_it_carries_a_live_role(self):
        assert "errorDiv.setAttribute('role', 'alert');" in self._banner_setup()

    def test_the_role_is_set_where_the_element_is_created(self):
        """Setting it after the text is written can miss the announcement."""
        block = self._banner_setup()
        assert block.index("setAttribute('role', 'alert')") < block.index("innerHTML")


class TestTheHeldStateIsCleared:
    """`.card-sort-holding` dashes every drop zone while a card is in the air."""

    CARD_SORT = (Path(potato.__file__).parent / "server_utils" / "schemas"
                 / "card_sort.py").read_text(encoding="utf-8")

    def test_completing_a_move_removes_it(self):
        move = self.CARD_SORT[self.CARD_SORT.index("function moveTo"):]
        move = move[:move.index("/* ---------- keyboard")] if "/* ---------- keyboard" in move else move[:2000]

        assert "classList.remove('card-sort-holding')" in move, (
            "left on, the one signal that means 'choose a target' stays on for "
            "the rest of the item and means nothing")
