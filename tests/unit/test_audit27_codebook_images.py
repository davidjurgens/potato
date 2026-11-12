"""
Markdown images did not render in a codebook definition.

Audit 27 (d). `![street](/media/street1.png)` came out as a literal `!`
followed by a link reading "street". There was no image rule at all: the link
pattern matched the `[street](/media/street1.png)` tail of the image syntax and
left the bang behind as text.

Bold, italic, inline code, bullet lists and links all rendered, which is what
made it look like a path problem rather than a missing rule -- and the same
`/media/` path works everywhere else on the page.

`img` and its `src`/`alt` are already in the sanitizer's allowlist, so nothing
else had to move.
"""

import pytest

from potato.codebook.markdown import render_markdown


class TestImagesInDefinitions:

    def test_an_image_renders_as_an_image(self):
        html = render_markdown("![street](/media/street1.png)")
        assert '<img src="/media/street1.png"' in html, html
        assert 'alt="street"' in html, html
        assert "!" not in html, html

    def test_an_image_inline_with_text(self):
        html = render_markdown("See ![x](/media/a.png) for the layout.")
        assert '<img src="/media/a.png"' in html, html
        assert "See " in html and "for the layout." in html, html

    def test_an_empty_alt_is_allowed(self):
        """A decorative screenshot has no useful alt text, and `![](...)` is
        how markdown says so."""
        html = render_markdown("![](https://example.com/a.png)")
        assert '<img src="https://example.com/a.png"' in html, html

    def test_a_link_to_an_image_is_still_a_link(self):
        """The control. Without the `!` it must not become an image."""
        html = render_markdown("[a link](/media/a.png)")
        assert "<a href=" in html, html
        assert "<img" not in html, html

    def test_an_unsafe_target_is_refused_the_same_way_a_link_is(self):
        """Images and links share one URL check so they cannot drift: an
        image pointing at `javascript:` has to be refused on the same terms."""
        html = render_markdown("![bad](javascript:alert(1))")
        assert "<img" not in html, html
        assert "javascript:" not in html, html

    def test_the_other_inline_rules_still_work(self):
        """Images are substituted before links, so the ordering change had to
        leave everything else alone."""
        html = render_markdown(
            "**bold** and *italic* and `code` and [link](/a).")
        assert "<strong>bold</strong>" in html, html
        assert "<em>italic</em>" in html, html
        assert "<code>code</code>" in html, html
        assert '<a href="/a"' in html, html
