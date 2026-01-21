"""
Unit tests for HTML sanitizer module.

These tests verify that the sanitizer:
1. Allows legitimate span annotation HTML
2. Blocks dangerous XSS patterns
3. Returns Markup objects for Jinja2 compatibility (prevents double-escaping)

BUG CAUGHT: The sanitize_html function must return a Markup object, not a plain
string. Without this, Jinja2's auto-escape will escape the output again, causing
span annotation HTML like <span> to be rendered as literal text &lt;span&gt;.
"""

import pytest
from markupsafe import Markup
from jinja2 import Environment

from potato.server_utils.html_sanitizer import (
    sanitize_html,
    _sanitize_attributes,
    _sanitize_style,
    _sanitize_class,
    escape_for_attribute,
    ALLOWED_ELEMENTS,
    ALLOWED_ATTRIBUTES,
)


class TestSanitizeHtmlReturnType:
    """
    Test that sanitize_html returns Markup objects.

    BUG CAUGHT: If sanitize_html returns a plain string instead of Markup,
    Jinja2's auto-escape will escape the output again, breaking span annotation.
    """

    def test_returns_markup_object(self):
        """sanitize_html must return a Markup object, not a plain string."""
        result = sanitize_html("Hello world")
        assert isinstance(result, Markup), \
            "sanitize_html must return Markup to prevent Jinja2 double-escaping"

    def test_returns_markup_for_empty_string(self):
        """Empty input should return empty Markup."""
        result = sanitize_html("")
        assert isinstance(result, Markup)
        assert result == ""

    def test_returns_markup_for_none(self):
        """None input should return empty Markup."""
        result = sanitize_html(None)
        assert isinstance(result, Markup)
        assert result == ""

    def test_jinja2_does_not_double_escape(self):
        """
        When used as a Jinja2 filter, output should NOT be double-escaped.

        This test would have caught the bug where span annotation HTML was
        being rendered as literal text instead of actual HTML elements.
        """
        env = Environment(autoescape=True)
        env.filters['sanitize_html'] = sanitize_html

        template = env.from_string('{{ instance | sanitize_html }}')

        # Span tags should be preserved, not escaped
        result = template.render(instance='<span class="test">hello</span>')
        assert '<span class="test">hello</span>' in result
        assert '&lt;span' not in result, \
            "Span tags should NOT be escaped - sanitize_html must return Markup"

    def test_jinja2_attribute_rendering(self):
        """
        HTML output should work correctly in both content and attributes.

        This tests the data-original-text pattern used for span annotation.
        """
        env = Environment(autoescape=True)
        env.filters['sanitize_html'] = sanitize_html

        template = env.from_string(
            '<div data-original-text="{{ instance | sanitize_html }}">'
            '{{ instance | sanitize_html }}</div>'
        )

        result = template.render(instance='Hello <b>world</b>')

        # Content should have <b> preserved
        assert '>Hello <b>world</b><' in result, \
            "HTML content should preserve allowed tags"


class TestSanitizeHtmlAllowedElements:
    """Test that allowed elements are preserved."""

    def test_span_preserved(self):
        """Span tags should be preserved (used for annotations)."""
        result = sanitize_html('<span class="highlight">text</span>')
        assert '<span' in result
        assert '</span>' in result

    def test_span_with_style_preserved(self):
        """Span with style should be preserved."""
        result = sanitize_html('<span style="background-color: red;">text</span>')
        assert '<span style="background-color: red">' in result

    def test_span_with_data_attributes_preserved(self):
        """Span with data attributes should be preserved."""
        result = sanitize_html(
            '<span data-annotation-id="123" data-label="test">text</span>'
        )
        assert 'data-annotation-id="123"' in result
        assert 'data-label="test"' in result

    def test_bold_preserved(self):
        """Bold tags should be preserved."""
        result = sanitize_html('<b>bold</b>')
        assert '<b>bold</b>' in result

    def test_italic_preserved(self):
        """Italic tags should be preserved."""
        result = sanitize_html('<i>italic</i>')
        assert '<i>italic</i>' in result

    def test_br_preserved(self):
        """Line break tags should be preserved."""
        result = sanitize_html('line1<br>line2')
        assert '<br>' in result or '<br />' in result


class TestSanitizeHtmlBlockedElements:
    """Test that dangerous elements are escaped."""

    def test_script_escaped(self):
        """Script tags should be escaped."""
        result = sanitize_html('<script>alert("xss")</script>')
        assert '&lt;script&gt;' in result
        assert '<script>' not in result

    def test_iframe_escaped(self):
        """Iframe tags should be escaped."""
        result = sanitize_html('<iframe src="evil.com"></iframe>')
        assert '&lt;iframe' in result
        assert '<iframe' not in result

    def test_img_escaped(self):
        """Image tags should be escaped (can execute JS via onerror)."""
        result = sanitize_html('<img src="x" onerror="alert(1)">')
        assert '&lt;img' in result
        assert '<img' not in result

    def test_object_escaped(self):
        """Object tags should be escaped."""
        result = sanitize_html('<object data="evil.swf"></object>')
        assert '&lt;object' in result

    def test_onclick_attribute_removed(self):
        """Onclick attributes should be removed even from allowed elements."""
        result = sanitize_html('<span onclick="alert(1)">text</span>')
        assert 'onclick' not in result
        assert '<span>' in result  # Tag kept, attribute removed


class TestSanitizeHtmlDangerousPatterns:
    """Test that dangerous URL patterns are blocked."""

    def test_javascript_url_blocked(self):
        """javascript: URLs should be blocked."""
        result = sanitize_html('<a href="javascript:alert(1)">link</a>')
        assert 'javascript:' not in result

    def test_vbscript_url_blocked(self):
        """vbscript: URLs should be blocked."""
        result = sanitize_html('<a href="vbscript:msgbox(1)">link</a>')
        assert 'vbscript:' not in result

    def test_data_url_blocked(self):
        """data: URLs should be blocked."""
        result = sanitize_html('<a href="data:text/html,<script>alert(1)</script>">link</a>')
        assert 'data:' not in result


class TestSanitizeStyle:
    """Test CSS style sanitization."""

    def test_background_color_allowed(self):
        """background-color should be allowed."""
        result = _sanitize_style('background-color: #FF0000;')
        assert 'background-color: #FF0000' in result

    def test_color_allowed(self):
        """color should be allowed."""
        result = _sanitize_style('color: blue;')
        assert 'color: blue' in result

    def test_url_in_style_blocked(self):
        """url() in styles should be blocked."""
        result = _sanitize_style('background: url(evil.com);')
        assert 'url(' not in result

    def test_expression_blocked(self):
        """CSS expression() should be blocked (IE-specific XSS)."""
        result = _sanitize_style('width: expression(alert(1));')
        assert result == ""  # Dangerous pattern blocks entire style


class TestSanitizeClass:
    """Test class attribute sanitization."""

    def test_valid_class_preserved(self):
        """Valid class names should be preserved."""
        result = _sanitize_class('highlight span-annotation')
        assert result == 'highlight span-annotation'

    def test_class_with_hyphen_preserved(self):
        """Class names with hyphens should be preserved."""
        result = _sanitize_class('my-class-name')
        assert result == 'my-class-name'

    def test_class_with_underscore_preserved(self):
        """Class names with underscores should be preserved."""
        result = _sanitize_class('my_class_name')
        assert result == 'my_class_name'


class TestEscapeForAttribute:
    """Test attribute escaping."""

    def test_quotes_escaped(self):
        """Quotes should be escaped in attributes."""
        result = escape_for_attribute('test "value"')
        assert '&quot;' in result

    def test_backticks_escaped(self):
        """Backticks should be escaped to prevent template injection."""
        result = escape_for_attribute('test `value`')
        assert '&#96;' in result

    def test_dollar_escaped(self):
        """Dollar signs should be escaped to prevent template injection."""
        result = escape_for_attribute('test $value')
        assert '&#36;' in result


class TestSpanAnnotationIntegration:
    """
    Integration tests for span annotation HTML patterns.

    These test the specific HTML patterns used by the span annotation system.
    """

    def test_server_rendered_span_annotation(self):
        """
        Test the HTML pattern used for server-rendered span annotations.

        The server renders span annotations like:
        <span style="background-color: rgba(110,86,207,0.4);" data-annotation-id="span_0_5">text</span>
        """
        html = (
            '<span style="background-color: rgba(110,86,207,0.4);" '
            'data-annotation-id="span_0_5" data-label="label">annotated</span>'
        )
        result = sanitize_html(html)

        assert '<span' in result
        assert 'background-color: rgba(110,86,207,0.4)' in result
        assert 'data-annotation-id="span_0_5"' in result
        assert 'data-label="label"' in result

    def test_nested_span_annotations(self):
        """Test overlapping/nested span annotations."""
        html = (
            '<span style="background-color: red;">outer '
            '<span style="background-color: blue;">inner</span> outer</span>'
        )
        result = sanitize_html(html)

        assert result.count('<span') == 2
        assert result.count('</span>') == 2

    def test_plain_text_with_special_chars(self):
        """Plain text with HTML special characters should be escaped."""
        result = sanitize_html('Compare: x < y and a > b')
        assert '&lt;' in result
        assert '&gt;' in result

    def test_mixed_content(self):
        """Test mix of plain text, allowed HTML, and dangerous HTML."""
        html = 'Hello <b>bold</b> and <script>bad</script> text'
        result = sanitize_html(html)

        assert '<b>bold</b>' in result  # Allowed tag preserved
        assert '&lt;script&gt;' in result  # Dangerous tag escaped
        assert '<script>' not in result
