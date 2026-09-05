"""
The pairwise tile is a control, and has to announce itself as one.

Found in the impeccable audit pass over the widget repaired for audit 25. A
tile is a ``<div>`` with ``tabindex="0"`` and an Enter/Space handler: it takes
focus and it carries the answer. It shipped with no role and no checked state,
so a screen reader announced two unlabeled focusable things and never said
which one was chosen -- WCAG 4.1.2.

The focus ring is the other half, and it is measured in a browser rather than
here -- see ``test_the_focus_ring_is_visible`` in
``tests/selenium/test_audit25_pairwise_shapes.py``.
"""

import re

import pytest

from potato.server_utils.schemas.pairwise import generate_pairwise_layout


def _binary_html():
    html, _ = generate_pairwise_layout({
        "annotation_type": "pairwise",
        "name": "preference",
        "description": "Which is better?",
        "mode": "binary",
        "labels": ["A", "B"],
        "allow_tie": True,
    })
    return html


class TestPairwiseTileSemantics:

    def test_every_tile_is_a_radio_with_a_checked_state(self):
        html = _binary_html()
        tiles = re.findall(r'<div class="pairwise-tile"[^>]*>', html)
        assert len(tiles) == 2, tiles
        for tile in tiles:
            assert 'role="radio"' in tile, tile
            assert 'aria-checked="false"' in tile, tile

    def test_the_tiles_sit_in_a_named_radiogroup(self):
        """An unnamed radiogroup is announced as "group", which says nothing.

        The name comes from the legend, which is the question being asked.
        """
        html = _binary_html()
        group = re.search(
            r'<div class="pairwise-selection-container"[^>]*>', html)
        assert group, html[:400]
        assert 'role="radiogroup"' in group.group(0)
        assert 'aria-labelledby="preference-question"' in group.group(0)
        assert 'id="preference-question"' in html

    def test_the_tie_button_announces_whether_it_is_pressed(self):
        html = _binary_html()
        button = re.search(r'<button[^>]*class="pairwise-tie-btn"[^>]*>', html)
        assert button, html
        assert 'aria-pressed="false"' in button.group(0)
