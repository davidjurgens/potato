"""
Regression tests for the option-highlighting template wiring.

Option highlighting dims the less-likely *discrete options* of a radio,
multiselect, likert or select scheme so an annotator facing ten labels can see
the three the model considers plausible. Nothing about it is visual.

It was nevertheless loaded from inside a condition that also required the
project to have an `image_annotation` or `video_annotation` scheme, because the
script tag had been added next to `visual_ai_assistant.js` and inherited that
tag's `{% if %}`. The result: `examples/advanced/option-highlight`, a plain text
radio task that exists *only* to demonstrate the feature, never loaded the
manager at all. The server answered `/api/option_highlights/<i>` correctly and
no client ever asked, so every option rendered at full opacity under a prompt
reading "AI will highlight the 3 most likely options".

That failure is invisible to the server tests (the endpoint is fine) and to a
screenshot harness (the page is a healthy annotation form). It is only visible
in the template, which is what these tests read.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_TEMPLATE = REPO_ROOT / "potato" / "templates" / "base_template_v2.html"

#: The real script tag, not a mention of the filename in a comment.
MANAGER_TAG = "filename='option_highlight_manager.js'"

#: Flags that mean "this project has a visual scheme". A non-visual feature
#: must not be gated on any of them.
VISUAL_FLAGS = ("image_annotation", "video_annotation", "has_image_annotation")


@pytest.fixture(scope="module")
def template_source():
    return BASE_TEMPLATE.read_text(encoding="utf-8")


def _enclosing_if(source: str, needle: str) -> str:
    """Return the `{% if %}` condition governing the line containing `needle`.

    Walks backwards from the tag, tracking `{% endif %}` depth, so a nested or
    sibling block between the tag and its own `{% if %}` cannot be mistaken for
    the governing condition.
    """
    idx = source.index(needle)
    head = source[:idx]
    stack = []
    for match in re.finditer(r"\{%-?\s*(if|elif|else|endif)\b([^%]*?)-?%\}", head):
        kind, cond = match.group(1), match.group(2).strip()
        if kind == "if":
            stack.append(cond)
        elif kind == "endif":
            if stack:
                stack.pop()
        elif kind in ("elif", "else") and stack:
            stack[-1] = cond or stack[-1]
    return stack[-1] if stack else ""


class TestOptionHighlightWiring:
    def test_the_manager_is_still_included(self, template_source):
        assert MANAGER_TAG in template_source, (
            "base_template_v2.html no longer loads option_highlight_manager.js — "
            "option highlighting cannot work without it.")

    def test_it_is_not_gated_on_a_visual_scheme(self, template_source):
        """The whole point. Option highlighting is a discrete-option feature."""
        condition = _enclosing_if(template_source, MANAGER_TAG)
        offenders = [f for f in VISUAL_FLAGS if f in condition]
        assert not offenders, (
            "option_highlight_manager.js is gated on "
            f"{offenders} — so a text-only radio task (the exact shape of "
            "examples/advanced/option-highlight) never loads it and the feature "
            f"silently does nothing.\n  condition: {condition!r}")

    def test_it_is_gated_on_ai_support(self, template_source):
        """Not free either: no AI configured means no highlights to fetch."""
        condition = _enclosing_if(template_source, MANAGER_TAG)
        assert "ai_enabled" in condition, (
            "option_highlight_manager.js should load when ai_support is enabled; "
            f"condition is {condition!r}")

    def test_visual_assistant_keeps_its_visual_gate(self, template_source):
        """Separating the two tags must not drag the visual one out with it."""
        condition = _enclosing_if(template_source, "filename='visual_ai_assistant.js'")
        assert any(f in condition for f in VISUAL_FLAGS), (
            "visual_ai_assistant.js genuinely is image/video-only and should stay "
            f"gated on a visual scheme; condition is {condition!r}")
