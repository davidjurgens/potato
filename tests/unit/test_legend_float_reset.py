"""Bootstrap's `legend { float: left; width: 100% }` crushed flex schema bodies.

`triage` renders its buttons inside `<div class="triage-container">`, a flex
container, directly after the fieldset's `<legend>`. A flex container
establishes a block formatting context, and a BFC does not overlap a float --
it takes whatever width is left beside it. Beside a 100%-wide float that is
nothing, so the container computed to width 0 and its three buttons were laid
out past the right edge of the card, where two of the three were clipped and
could not be clicked at all.

Any schema whose body is a flex or grid wrapper sits in the same position, so
the fix is to drop the float for annotation-form legends rather than to add a
`clear` to one widget.
"""

import re
from pathlib import Path

import potato


STYLES = (Path(potato.__file__).parent / "static" / "styles.css").read_text(encoding="utf-8")

#: Comments are stripped before matching: this file's own explanation quotes
#: `legend { float: left; width: 100% }`, and a brace inside a comment would
#: end the declaration block as far as a regex is concerned.
STYLES_NO_COMMENTS = re.sub(r"/\*.*?\*/", "", STYLES, flags=re.S)


def _rule(selector, source=None):
    """The declaration block of the first rule with this exact selector."""
    source = STYLES_NO_COMMENTS if source is None else source
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert match, f"no rule for {selector!r} in styles.css"
    return match.group(1)


class TestAnnotationLegendsDoNotFloat:
    def test_the_float_is_undone(self):
        body = _rule(".annotation-form legend")

        assert re.search(r"float:\s*none", body), (
            "Without this, Bootstrap's legend reset floats the legend at 100% "
            "width and any flex/grid schema body beside it computes to zero."
        )

    def test_the_width_is_undone_too(self):
        """`float: none` alone leaves `width: 100%`, which is not the reset."""
        body = _rule(".annotation-form legend")

        assert re.search(r"width:\s*auto", body)

    def test_the_rule_beats_bootstrap_on_specificity(self):
        """`.annotation-form legend` is (0,1,1) against Bootstrap's (0,0,1).

        Load order between the two stylesheets then does not matter.
        """
        assert ".annotation-form legend" in STYLES

    def test_the_reason_is_recorded_next_to_the_declaration(self):
        """Read from the uncommented source, since the reason IS the comment."""
        start = STYLES.index(".annotation-form legend")
        body = STYLES[start:STYLES.index("float: none", start)]

        assert "Bootstrap" in body


class TestTheSchemasThatSitInThatPosition:
    """A flex wrapper straight after the legend is the exposed shape."""

    def test_triage_still_renders_one(self):
        from potato.server_utils.schemas.triage import generate_triage_layout

        html, _ = generate_triage_layout({
            "annotation_type": "triage", "name": "q", "description": "d"})

        legend_at = html.index("<legend")
        container_at = html.index('class="triage-container"')
        assert container_at > legend_at
        assert "<fieldset" in html
