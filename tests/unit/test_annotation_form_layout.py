"""Layout regressions in the annotation form CSS.

Three defects, all found by looking at a screenshot of the event-annotation
example rather than by any failing test:

1. A blanket `border-left: none; padding-left: 0` reset carried an id in its
   selector, so it outranked every schema container's own card and stripped the
   LEFT side of its border and padding. Panels rendered bordered on three sides
   with their content flush against the missing edge, and the red
   `required-unfilled` outline lost its left edge on every schema.

2. `.shadcn-span-container` used `align-items: center` on a column flex
   container, which shrank its `<fieldset>` to content width. The label grid
   (`repeat(auto-fill, minmax(180px, 1fr))`) is sized against that fieldset, so
   it could only ever produce one column: five labels stacked in a narrow centred
   strip inside an 860px box.

3. `fieldset[schema] { width: fit-content }` appears later in the file with the
   same specificity as a plain `.shadcn-span-container > fieldset`, so the fix
   for (2) has to out-specify it or it silently loses. The pre-existing
   `.shadcn-textbox-container fieldset { width: 100% }` is an example of a rule
   that lost exactly this way.

CSS cannot be unit-tested for rendering, but these are all textual properties of
the stylesheet, and each one is the thing that actually broke.
"""
import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[2] / "potato" / "static" / "styles.css"


@pytest.fixture(scope="module")
def css():
    return CSS.read_text(encoding="utf-8")


def _rule_body(css_text, selector):
    """Return the declaration block for an exact selector, or None."""
    idx = css_text.find(selector)
    while idx != -1:
        # Make sure we matched a selector, not a mention inside a comment.
        line_start = css_text.rfind("\n", 0, idx) + 1
        prefix = css_text[line_start:idx]
        brace = css_text.find("{", idx)
        end = css_text.find("}", brace)
        # The selector must start the line, or `fieldset[schema]` also matches
        # inside `.shadcn-span-container > fieldset[schema]`.
        if prefix.strip() == "" and brace != -1:
            between = css_text[idx + len(selector):brace]
            if between.strip() in ("", ","):
                return css_text[brace + 1:end]
        idx = css_text.find(selector, idx + 1)
    return None


class TestNoBlanketLeftReset:
    def test_reset_is_gone(self, css):
        body = _rule_body(css, "#annotation-forms > .annotation_schema > .annotation-form")
        if body is None:
            return  # rule removed entirely — the intended state
        assert "border-left: none" not in body, (
            "the blanket left reset is back; it outranks every schema "
            "container's own border and strips its left edge")
        assert "padding-left: 0" not in body

    def test_schema_containers_still_declare_their_own_card(self, css):
        """The reset was only harmful because these carry real borders."""
        for selector in (".shadcn-span-container",):
            body = _rule_body(css, selector)
            assert body is not None, f"{selector} rule vanished"
            assert "border:" in body, f"{selector} no longer declares a border"

    def test_required_unfilled_outline_is_intact(self, css):
        body = _rule_body(css, ".annotation-form.required-unfilled")
        assert body is not None
        assert "border: 2px solid" in body, (
            "the required-question outline must be a complete box; it is the "
            "only cue that an answer is missing")


class TestSpanLabelGridCanUseItsWidth:
    def test_container_does_not_centre_its_children(self, css):
        body = _rule_body(css, ".shadcn-span-container")
        assert body is not None
        m = re.search(r"align-items:\s*([a-z-]+)", body)
        assert m, ".shadcn-span-container no longer sets align-items"
        assert m.group(1) != "center", (
            "align-items:center collapses the fieldset to content width, so the "
            "auto-fill label grid gets exactly one column")

    def test_fieldset_rule_outranks_the_fit_content_default(self, css):
        """Specificity, not source order, has to win this."""
        assert ".shadcn-span-container > fieldset[schema]" in css, (
            "the span fieldset rule must carry [schema] or "
            "`fieldset[schema] { width: fit-content }` — same specificity, "
            "later in the file — beats it and the grid stays one column")

        body = _rule_body(css, ".shadcn-span-container > fieldset[schema]")
        assert body is not None and "width: 100%" in body

    def test_the_rule_it_must_outrank_still_exists(self, css):
        """If this default ever goes away, the [schema] hack can be dropped."""
        body = _rule_body(css, "fieldset[schema]")
        assert body is not None
        assert "fit-content" in body


class TestEventAnnotationPairsWithItsSpanSchema:
    def test_two_column_pairing_rule_exists(self, css):
        assert ":has(.event-annotation-container)" in css, (
            "event_annotation and the span schema it references should share a "
            "row; otherwise the full-width label box pushes the event panel "
            "below it and the two halves of one task are never on screen "
            "together")

    def test_pairing_overrides_the_span_full_width_rule(self, css):
        """.shadcn-span-container is in the 'needs full width' list, which would
        otherwise force it onto its own row."""
        idx = css.find(":has(.event-annotation-container)")
        block = css[idx:css.find("}", idx)]
        assert "width: auto" in block
        assert "flex:" in block
