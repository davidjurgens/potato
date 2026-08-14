"""Character references must survive sanitisation — without weakening it.

``sanitize_html`` ran every text node through ``html.escape``, which rewrites
*every* ``&``. An admin who wrote ``&mdash;`` in ``annotation_instructions``, in
a ``pure_display`` block, or in instance text got the literal seven characters
``&mdash;`` on screen. It also made the function non-idempotent: sanitising
twice turned ``&amp;`` into ``&amp;amp;``, so any content that passes through
the sanitizer on the way in and again on the way out decays a little each time.

The fix preserves well-formed character references in text nodes and in ordinary
attribute values. It deliberately does NOT preserve them in href/src/style,
where a reference can reconstitute a blocked URL scheme
(``java&Tab;script:``) that the raw-text pattern scan cannot see. The tests
below pin both halves of that: the entities that must survive, and the ones
that must not.
"""
import re

import pytest

from potato.server_utils.html_sanitizer import sanitize_html


def clean(s):
    return str(sanitize_html(s))


class TestEntitiesSurvive:
    @pytest.mark.parametrize("entity", [
        "&mdash;", "&ndash;", "&ldquo;", "&rdquo;", "&eacute;", "&nbsp;",
        "&hellip;", "&amp;", "&lt;", "&gt;", "&#8212;", "&#x2014;",
    ])
    def test_named_and_numeric_references_pass_through(self, entity):
        out = clean(f"<p>a {entity} b</p>")
        assert out == f"<p>a {entity} b</p>", (
            f"{entity} was rewritten; annotators would see it literally")

    def test_bare_ampersand_is_still_escaped(self):
        # Not a character reference, so it must become &amp; or the markup is
        # malformed.
        assert clean("AT&T") == "AT&amp;T"
        assert clean("a & b") == "a &amp; b"

    def test_incomplete_reference_is_escaped(self):
        # No semicolon: not a reference. Must not be left as a bare &.
        assert clean("<p>a &mdash b</p>") == "<p>a &amp;mdash b</p>"

    def test_ordinary_attribute_values_keep_references(self):
        out = clean('<span data-label="A&amp;B">t</span>')
        assert out == '<span data-label="A&amp;B">t</span>'

    def test_idempotent_for_text_and_ordinary_attributes(self):
        for src in ["<p>a &mdash; b</p>", "AT&T", '<span title="x &amp; y">t</span>',
                    "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"]:
            once = clean(src)
            assert clean(once) == once, f"sanitising {src!r} twice changed it"


class TestSanitisationIsNotWeakened:
    def test_real_tags_are_still_escaped(self):
        out = clean('<script>alert("xss")</script>')
        assert "<script" not in out
        assert out.startswith("&lt;script&gt;")

    def test_escaped_script_stays_inert(self):
        """`&lt;script&gt;` renders as visible text, never as an element."""
        out = clean("<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>")
        assert "<script" not in out
        # Only the wrapping <p> is a real tag.
        assert re.findall(r"</?(\w+)", out) == ["p", "p"]

    def test_event_handler_attribute_is_dropped(self):
        assert "onerror" not in clean('<img src=x onerror=alert(1)>')

    def test_javascript_scheme_is_stripped(self):
        assert "javascript:" not in clean('<a href="javascript:alert(1)">x</a>')

    def test_reference_cannot_rebuild_a_url_scheme(self):
        """The reason href/src/style keep the blunt escape.

        `java&Tab;script:` is resolved to `javascript:` by the browser's URL
        parser, so preserving the reference here would reopen the hole that
        DANGEROUS_PATTERNS closes.
        """
        out = clean('<a href="java&Tab;script:alert(1)">x</a>')
        assert "&Tab;" not in out
        assert 'href="java&amp;Tab;script:alert(1)"' in out

    def test_reference_cannot_rebuild_a_css_function(self):
        out = clean('<p style="color: expression&#40;alert(1)&#41;">x</p>')
        assert "&#40;" not in out

    @pytest.mark.parametrize("attr", ["href", "src", "style"])
    def test_url_and_css_attributes_never_keep_references(self, attr):
        from potato.server_utils.html_sanitizer import _UNESCAPED_ATTRS
        assert attr in _UNESCAPED_ATTRS


class TestPureDisplayNeedsAllowHtml:
    """The other half of the bug this surfaced.

    `pure_display` escapes its content unless `allow_html: true` is set, so a
    survey page that writes HTML without the flag shows raw tags. Two shipped
    examples did exactly that.
    """

    def test_examples_that_write_html_set_allow_html(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / "examples"
        offenders = []
        for path in sorted(root.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            entries = data if isinstance(data, list) else [data]
            if not all(isinstance(e, dict) for e in entries):
                continue
            for e in entries:
                if e.get("annotation_type") != "pure_display":
                    continue
                content = str(e.get("description") or "") + "".join(
                    str(x) for x in (e.get("labels") or []))
                if "<" in content and ">" in content and not e.get("allow_html"):
                    offenders.append(f"{path.relative_to(root)} ({e.get('name')})")
        assert not offenders, (
            "pure_display blocks with HTML but no allow_html: true — these render "
            "raw tags to annotators: " + ", ".join(offenders))
