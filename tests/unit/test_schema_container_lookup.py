"""
`ImageAnnotationManager` has no `this.container`, and three features died of it.

Each time, the code read `this.container`, got `undefined`, took the guard's
early exit, and did nothing — while its unit tests passed against a callback or
a mock. The three were the segmentation status line (every model-loading and
error message invisible), the reveal-annotation scroll (silently never
scrolled), and the text-prompt controls (the Find button bound to nothing).

The class looks its root element up by schema instead, through
`_schemaContainer()`. This test fails the build if a fourth attempt appears.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "potato" / "static" / "image-annotation.js"

#: `this.container` inside a comment is fine — the explanation lives in one.
CODE_USE = re.compile(r"^(?!\s*(?://|\*|/\*)).*\bthis\.container\b")


def _offending_lines(text: str):
    return [(i + 1, line.strip())
            for i, line in enumerate(text.splitlines())
            if CODE_USE.search(line)]


class TestNoContainerProperty:
    def test_the_manager_never_reads_a_container_property(self):
        offenders = _offending_lines(SOURCE.read_text(encoding="utf-8"))
        assert not offenders, (
            "image-annotation.js reads `this.container`, which does not exist. "
            "Use `this._schemaContainer()`. Offending lines: "
            + "; ".join(f"{n}: {t}" for n, t in offenders)
        )

    def test_the_helper_exists_and_scopes_by_schema(self):
        text = SOURCE.read_text(encoding="utf-8")
        assert "_schemaContainer()" in text
        match = re.search(
            r"_schemaContainer\(\)\s*\{(.*?)\}", text, re.DOTALL)
        assert match, "the helper's body could not be read"
        body = match.group(1)
        assert "data-schema" in body, (
            "the lookup must be scoped by schema: a page can carry several "
            "image schemas, and an unscoped query returns the first one"
        )

    def test_the_guard_would_catch_a_regression(self):
        """The pattern has to actually match, or this test proves nothing."""
        sample = "        if (this.container && this.container.scrollIntoView) {"
        assert _offending_lines(sample), "the detector does not detect"
        commented = "        // `this.container` does not exist on this class"
        assert not _offending_lines(commented), "comments must stay allowed"


@pytest.mark.parametrize("feature,marker", [
    ("segmentation status", ".segmentation-status"),
    ("text prompt controls", ".text-prompt-run"),
])
def test_each_feature_that_died_of_it_uses_the_helper(feature, marker):
    """Every one of these looked up an element and found nothing."""
    text = SOURCE.read_text(encoding="utf-8")
    index = text.find(marker)
    assert index > 0, f"{feature}: marker {marker} is gone"
    window = text[max(0, index - 600):index]
    assert "_schemaContainer()" in window, (
        f"{feature} looks its element up some other way; the helper exists "
        f"because three features silently did nothing without it"
    )


class TestEveryToolIsPresentable:
    """A tool with no icon or label renders as "? sam", which shipped.

    `sam` was in VALID_TOOLS and in both keybinding profiles, and in neither
    TOOL_ICONS nor TOOL_LABELS, so its toolbar button showed a fallback
    question mark and the raw config key. Nothing failed; it was found by
    looking at a screenshot. These two tables are the third and fourth
    hand-maintained lists keyed on tool name, so they get the same treatment as
    the keybinding profiles: adding a tool means adding it everywhere, and the
    build says so.
    """

    def test_every_tool_has_an_icon(self):
        from potato.server_utils.schemas.image_annotation import (
            TOOL_ICONS, VALID_TOOLS)

        missing = [tool for tool in VALID_TOOLS if tool not in TOOL_ICONS]
        assert not missing, f"tools with no icon: {missing}"

    def test_every_tool_has_a_label(self):
        from potato.server_utils.schemas.image_annotation import (
            TOOL_LABELS, VALID_TOOLS)

        missing = [tool for tool in VALID_TOOLS if tool not in TOOL_LABELS]
        assert not missing, f"tools with no label: {missing}"

    def test_no_button_renders_the_fallback_glyph(self):
        """The symptom itself, end to end."""
        from potato.server_utils.schemas.image_annotation import (
            VALID_TOOLS, generate_image_annotation_layout)

        html, _ = generate_image_annotation_layout({
            "annotation_type": "image_annotation",
            "name": "every_tool",
            "description": "all of them",
            "tools": list(VALID_TOOLS),
            "labels": ["thing"],
        })
        assert '>?<' not in html and '">?' not in html, (
            "a tool button rendered the fallback '?' glyph")
