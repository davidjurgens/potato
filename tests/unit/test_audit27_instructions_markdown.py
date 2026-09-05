"""
`annotation_instructions` showed markdown source to the annotator.

Audit 27. The template emits the value with `| safe`, so HTML has always
worked and the bundled examples use it. Markdown did not: an author who wrote

    ## Scope

    Mark **only** the sentence that states the outcome.

got exactly that text, hashes and asterisks included, on every page of their
study. The key's own documentation says "inline text" and nothing discourages
markdown, which is the most natural thing a researcher writes.

Two things this must not break.

Existing HTML instructions have to render as they did. Feeding them through the
markdown renderer wraps them in a paragraph and inserts a `<br>` between their
blocks -- nested `<p>`, a stray blank line -- so an existing config would come
out worse than before. Text that already carries block-level HTML is passed
through untouched.

And everything is sanitized, which is what the `long-guidelines` example
already tells authors happens: "HTML is passed through the project sanitizer,
so `<script>` and friends are stripped but formatting survives." That was the
documented contract and the template did not implement it -- `| safe` on an
unsanitized string.
"""

import pytest

from potato.flask_server import render_annotation_instructions as render


class TestMarkdownInstructions:

    def test_a_heading_becomes_a_heading(self):
        html = render("## Scope\n\nMark the outcome sentence.")
        assert "<h2>Scope</h2>" in html, html
        assert "##" not in html, html

    def test_emphasis_and_lists_render(self):
        html = render("Mark **only** the outcome.\n\n- first\n- second")
        assert "<strong>only</strong>" in html, html
        assert "<li>first</li>" in html, html

    def test_a_link_renders(self):
        html = render("See [the guide](https://example.com/guide).")
        assert 'href="https://example.com/guide"' in html, html


class TestExistingHtmlInstructionsAreUntouched:
    """The bundled examples write HTML, and they have to keep working."""

    def test_html_is_not_wrapped_in_a_paragraph(self):
        source = ("<p>Rate how the message lands "
                  "<strong>on the person</strong>.</p>\n"
                  "<ul><li>Polite</li><li>Neutral</li></ul>")
        html = render(source)
        assert "<p><p>" not in html, html
        assert "<br>" not in html, html
        assert "<strong>on the person</strong>" in html, html
        assert "<li>Polite</li>" in html, html

    def test_a_details_banner_survives(self):
        """`long-guidelines` builds a collapsible banner this way."""
        html = render("<details><summary>More</summary><p>Body</p></details>")
        assert "<details>" in html, html
        assert "<summary>More</summary>" in html, html


class TestSanitizing:

    def test_a_script_tag_does_not_survive(self):
        """The example's own comment promises this and `| safe` did not
        deliver it."""
        html = render("<p>hi</p><script>alert(1)</script>")
        assert "<script>" not in html, html
        assert "<p>hi</p>" in html, html

    def test_a_script_in_markdown_input_is_stripped_too(self):
        html = render("Some **text**\n\n<script>alert(1)</script>")
        assert "<script>" not in html, html


class TestEmptyInput:

    @pytest.mark.parametrize("value", ["", "   ", "\n", None])
    def test_nothing_in_nothing_out(self, value):
        """The template gates on truthiness, so whitespace must not become a
        banner containing an empty paragraph."""
        assert render(value) == ""
