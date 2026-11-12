"""
Model output reached the page unescaped, with its markdown showing.

Audit 27, widened from (a). `visual_ai_assistant.js` interpolated the hint,
the suggested label, the reasoning and error text straight into `innerHTML`.

Two problems in one place. A hint is generated from the item under annotation,
so a document containing markup could put it on the page unescaped -- the model
is repeating text it was given. And the model writes markdown: the auditor saw
`**Identify the 'Pain Points':**` and `**one-line summary**` rendered with
their asterisks, and the only lever an author has over that is asking the model
in the prompt not to format its answer, which is a strange thing to have to do.

Escaping happens first and markdown is applied to the escaped text, so every
tag in the output is one this function put there.

Asserted against the JavaScript source because this runs in the browser and
there is no Python entry point. `node` executes the function directly rather
than the test matching on strings -- a source-literal assertion would pass on a
renamed function that no longer does anything.
"""

import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The helper lives in ai_assistant_manager.js, which loads FIRST and publishes
# it on `window`. That file is the one a TEXT study uses -- the "visual" manager
# serves image and video tasks -- and it had the identical raw-innerHTML hint
# branch, in a file whose own rationale branch already escaped.
JS = os.path.join(ROOT, "potato", "static", "ai_assistant_manager.js")
VISUAL_JS = os.path.join(ROOT, "potato", "static", "visual_ai_assistant.js")


def _extract_helper():
    with open(JS, encoding="utf-8") as handle:
        source = handle.read()
    match = re.search(r"^function aiTextToSafeHtml\(text\) \{.*?^\}",
                      source, re.MULTILINE | re.DOTALL)
    assert match, "aiTextToSafeHtml is gone from ai_assistant_manager.js"
    return match.group(0)


def _render(value):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    script = (_extract_helper() + "\nprocess.stdout.write("
              "aiTextToSafeHtml(" + json.dumps(value) + "));")
    return subprocess.run([node, "-e", script], capture_output=True,
                          text=True, check=True).stdout


class TestModelOutputIsEscaped:

    def test_markup_in_model_output_does_not_become_markup(self):
        out = _render("a <img src=x onerror=alert(1)> b")
        assert "<img" not in out, out
        assert "&lt;img" in out, out

    def test_a_quote_cannot_break_out_of_an_attribute(self):
        out = _render('" onmouseover="alert(1)')
        assert 'onmouseover="' not in out, out

    def test_an_ampersand_is_escaped_once(self):
        out = _render("Ben & Jerry")
        assert "&amp;" in out and "&amp;amp;" not in out, out


class TestModelMarkdownRenders:

    def test_bold_renders(self):
        assert "<strong>Pain Points</strong>" in _render("**Pain Points**")

    def test_italic_and_code_render(self):
        assert "<em>maybe</em>" in _render("*maybe*")
        assert "<code>label</code>" in _render("`label`")

    def test_newlines_become_breaks(self):
        """A hint is several sentences and arrives with real newlines, which
        collapse to one run of text in HTML."""
        assert "<br>" in _render("one\ntwo")

    def test_markdown_is_applied_to_the_escaped_text(self):
        """Order matters: escaping after rendering would escape the tags this
        function just produced, and rendering markdown found inside escaped
        markup would re-open the hole."""
        out = _render("**<b>x</b>**")
        assert "<strong>" in out, out
        assert "<b>" not in out, out


class TestNothing:

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_input_is_empty_output(self, value):
        assert _render(value) == ""


class TestEveryModelPathUsesIt:
    """The hint branch was the only raw one in a file that already escaped.

    `renderRationale` called `this.escapeHtml` and `renderHint` interpolated
    `data.hint` directly, three hundred lines apart -- the same question
    answered twice in one file, once wrongly. Pinning every model-output site
    here so the next one added has to be deliberate.
    """

    def _source(self, path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    @pytest.mark.parametrize("field", [
        "data.hint", "data.suggestive_choice", "data.res",
        "r.label", "r.reasoning",
    ])
    def test_the_field_is_not_interpolated_raw(self, field):
        source = self._source(JS)
        raw = "${" + field + "}"
        assert raw not in source, (
            f"{field} reaches innerHTML unescaped; wrap it in "
            f"aiTextToSafeHtml()")

    def test_the_visual_manager_reuses_the_shared_helper(self):
        """Two files, one question. Both render MODEL output, so they get one
        answer -- unlike the author-authored markdown surfaces, which
        deliberately differ."""
        source = self._source(VISUAL_JS)
        assert "window.aiTextToSafeHtml" in source, source[:200]
