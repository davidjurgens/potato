"""PairwiseDisplay cell widths have to leave room for the flex gap.

The display is a flex row with `gap: 16px` between cells. Cells sized at a flat
100/N% are collectively wider than the row once the gutters are counted, so the
last one wrapped onto its own line -- a side-by-side display that was never side
by side at any viewport width. Each cell gives back its share of the gutter.

The gap is a CSS custom property (`--pairwise-gap`, defined alongside the
container rule in static/styles.css) rather than a number duplicated here, so
the two cannot drift apart.
"""

import re

import pytest

from potato.server_utils.displays.pairwise_display import PairwiseDisplay


def _render(items, options=None):
    field = {"key": "summaries", "type": "pairwise"}
    if options is not None:
        field["display_options"] = options
    return PairwiseDisplay().render(field, items)


def _cell_widths(html):
    return re.findall(r'<div class="pairwise-cell" style="width: ([^;]+);', html)


class TestPairwiseCellWidth:
    def test_two_cells_subtract_half_the_gap_each(self):
        widths = _cell_widths(_render(["left", "right"]))

        assert len(widths) == 2
        assert widths == ["calc(50% - var(--pairwise-gap, 16px) * 0.5)"] * 2

    def test_three_cells_split_the_row_evenly(self):
        widths = _cell_widths(_render(["a", "b", "c"]))

        assert len(widths) == 3
        for width in widths:
            assert width.startswith("calc(33.3333% - var(--pairwise-gap, 16px)")

    def test_default_is_auto_not_a_hardcoded_half(self):
        """Four items must not each ask for 50%."""
        widths = _cell_widths(_render(["a", "b", "c", "d"]))

        assert len(widths) == 4
        for width in widths:
            assert width.startswith("calc(25% - ")

    def test_explicit_percentage_still_gives_back_the_gutter(self):
        widths = _cell_widths(_render(["a", "b"], {"cell_width": "40%"}))

        assert widths == ["calc(40% - var(--pairwise-gap, 16px) * 0.5)"] * 2

    def test_absolute_width_is_passed_through_verbatim(self):
        """An author who asks for 300px gets 300px, gutter or no gutter."""
        widths = _cell_widths(_render(["a", "b"], {"cell_width": "300px"}))

        assert widths == ["300px", "300px"]

    def test_flex_basis_matches_the_width(self):
        html = _render(["a", "b"])
        styles = re.findall(r'style="width: ([^;]+); flex: 0 0 ([^;]+);"', html)

        assert len(styles) == 2
        for width, basis in styles:
            assert width == basis

    def test_single_item_takes_the_whole_row(self):
        """One cell has no gutter to give back."""
        widths = _cell_widths(_render(["only"]))

        assert widths == ["100%"]


class TestGapVariableIsDefinedInCss:
    def test_stylesheet_declares_the_custom_property(self):
        from pathlib import Path
        import potato

        css = (Path(potato.__file__).parent / "static" / "styles.css").read_text()
        container = css.split(".display-type-pairwise .pairwise-display-content {")[1]
        container = container.split("}")[0]

        assert "--pairwise-gap:" in container
        assert "gap: var(--pairwise-gap)" in container
