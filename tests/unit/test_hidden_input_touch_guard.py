"""Every widget that writes a hidden input must mark it touched.

`syncAnnotationsFromDOM` and the display-logic DOM fallback both skip
`input[type=hidden].annotation-input` unless it carries `data-modified` or
`data-server-set`. That guard is deliberate -- browsers restore a hidden input's
`.value` across a reload, so an unmarked input can be holding the previous
instance's answer -- but it means a widget that sets `.value` and nothing else
has written an answer neither collector can see.

Pairwise was that widget: `selectPairwiseTile`, `selectPairwiseOption`, and the
restore paths all assigned `.value` and stopped there, which is why a
display_logic gate reading a pairwise answer saw nothing on any page that falls
back to the DOM.

This scans the source rather than driving a browser: the failure is a missing
line, and a missing line is exactly what a source guard catches cheaply.
"""

import re
from pathlib import Path

import pytest

import potato


ANNOTATION_JS = Path(potato.__file__).parent / "static" / "annotation.js"

# Functions that assign to a hidden annotation input. Add new ones here when you
# add a widget in this family.
FUNCTIONS_THAT_WRITE_HIDDEN_INPUTS = [
    "selectPairwiseTile",
    "selectPairwiseOption",
    "restorePairwiseAnnotations",
    "restoreBwsAnnotations",
    "restoreRankingAnnotations",
]


def _function_body(source, name):
    """The text of `function name(...) { ... }`, matched by brace depth."""
    match = re.search(r"\nfunction %s\s*\([^)]*\)\s*\{" % re.escape(name), source)
    assert match, f"{name} not found in annotation.js"
    depth, i = 0, match.end() - 1
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[match.end():i]
        i += 1
    raise AssertionError(f"unbalanced braces in {name}")


@pytest.fixture(scope="module")
def source():
    return ANNOTATION_JS.read_text()


@pytest.mark.parametrize("name", FUNCTIONS_THAT_WRITE_HIDDEN_INPUTS)
def test_function_marks_its_hidden_input_touched(source, name):
    body = _function_body(source, name)

    assert ".value = " in body, (
        f"{name} no longer writes an input value -- update this guard's list"
    )
    assert "data-modified" in body or "data-server-set" in body, (
        f"{name} writes a hidden input's value without marking it touched. "
        "syncAnnotationsFromDOM and the display-logic DOM fallback both skip "
        "unmarked hidden inputs, so the answer would be invisible to them."
    )


def test_the_collectors_still_require_the_mark(source):
    """If the guard is ever dropped, this test's premise is gone -- say so."""
    sync = _function_body(source, "syncAnnotationsFromDOM")

    assert 'input[type="hidden"].annotation-input' in sync
    assert "data-modified" in sync and "data-server-set" in sync


def test_display_logic_fallback_reads_hidden_inputs():
    display_logic = (
        Path(potato.__file__).parent / "static" / "display-logic.js"
    ).read_text()

    # The definition, not the call in getCurrentAnnotations above it.
    collector = display_logic.split("getAnnotationsFromDOM() {")[1]
    collector = collector.split("transformRawAnnotations(raw)")[0]

    assert 'input[type="hidden"].annotation-input' in collector, (
        "getAnnotationsFromDOM no longer collects hidden inputs, so no "
        "tile-based schema (pairwise, bws, ranking, triage) can gate a "
        "display_logic condition on a page that reaches this fallback."
    )
    assert "data-modified" in collector and "data-server-set" in collector
