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

    def test_img_allowed_but_onerror_stripped(self):
        """Image tags are allowed but event handlers must be stripped."""
        result = sanitize_html('<img src="x" onerror="alert(1)">')
        assert '<img' in str(result)
        assert 'onerror' not in str(result)

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


class TestStructuralElements:
    """Test structural HTML elements added in Issue #120."""

    def test_paragraph_preserved(self):
        """<p> tags should be preserved."""
        result = sanitize_html('<p>A paragraph.</p>')
        assert '<p>A paragraph.</p>' in result

    def test_unordered_list_preserved(self):
        """<ul>/<li> tags should be preserved."""
        result = sanitize_html('<ul><li>Item 1</li><li>Item 2</li></ul>')
        assert '<ul>' in result
        assert '<li>Item 1</li>' in result
        assert '</ul>' in result

    def test_ordered_list_preserved(self):
        """<ol>/<li> tags should be preserved."""
        result = sanitize_html('<ol><li>First</li><li>Second</li></ol>')
        assert '<ol>' in result
        assert '<li>First</li>' in result

    def test_horizontal_rule_preserved(self):
        """<hr> tags should be preserved."""
        result = sanitize_html('Above<hr>Below')
        assert '<hr>' in result or '<hr />' in result

    def test_heading_elements_preserved(self):
        """<h1> through <h6> should be preserved."""
        for level in range(1, 7):
            tag = f'h{level}'
            result = sanitize_html(f'<{tag}>Heading {level}</{tag}>')
            assert f'<{tag}>Heading {level}</{tag}>' in result

    def test_table_elements_preserved(self):
        """<table>, <tr>, <td>, <th> should be preserved."""
        html = '<table><thead><tr><th>Header</th></tr></thead><tbody><tr><td>Cell</td></tr></tbody></table>'
        result = sanitize_html(html)
        assert '<table>' in result
        assert '<thead>' in result
        assert '<tbody>' in result
        assert '<tr>' in result
        assert '<th>Header</th>' in result
        assert '<td>Cell</td>' in result

    def test_table_attributes_preserved(self):
        """colspan, rowspan, scope should be preserved on table cells."""
        result = sanitize_html('<th colspan="2" scope="col">Wide Header</th>')
        assert 'colspan="2"' in result
        assert 'scope="col"' in result

        result = sanitize_html('<td rowspan="3">Tall Cell</td>')
        assert 'rowspan="3"' in result

    def test_code_and_pre_preserved(self):
        """<code>, <pre>, <blockquote> should be preserved."""
        result = sanitize_html('<pre><code>x = 1</code></pre>')
        assert '<pre>' in result
        assert '<code>x = 1</code>' in result

        result = sanitize_html('<blockquote>A quote.</blockquote>')
        assert '<blockquote>A quote.</blockquote>' in result

    def test_inline_semantics_preserved(self):
        """<sub>, <sup>, <small> should be preserved."""
        assert '<sub>2</sub>' in sanitize_html('H<sub>2</sub>O')
        assert '<sup>2</sup>' in sanitize_html('x<sup>2</sup>')
        assert '<small>' in sanitize_html('<small>Fine print</small>')

    def test_issue_120_example(self):
        """The exact example from Issue #120 should render as HTML."""
        html = '<h3>Instructions</h3><p>Please read carefully.</p><ul><li>Step 1</li><li>Step 2</li></ul>'
        result = sanitize_html(html)
        assert '<h3>Instructions</h3>' in result
        assert '<p>Please read carefully.</p>' in result
        assert '<ul>' in result
        assert '<li>Step 1</li>' in result
        assert '<li>Step 2</li>' in result


class TestLinkSanitization:
    """Test <a> link sanitization (Issue #120)."""

    def test_safe_link_preserved(self):
        """<a> with safe https href should be preserved."""
        result = sanitize_html('<a href="https://example.com">Link</a>')
        assert '<a href="https://example.com">Link</a>' in result

    def test_link_with_title_preserved(self):
        """<a> with title attribute should be preserved."""
        result = sanitize_html('<a href="https://example.com" title="Example">Link</a>')
        assert 'href="https://example.com"' in result
        assert 'title="Example"' in result

    def test_javascript_href_blocked(self):
        """<a href="javascript:..."> should have the javascript: protocol stripped."""
        result = sanitize_html('<a href="javascript:alert(1)">Click me</a>')
        assert 'javascript:' not in result

    def test_data_href_blocked(self):
        """<a href="data:..."> should have href stripped."""
        result = sanitize_html('<a href="data:text/html,<script>alert(1)</script>">Bad</a>')
        assert 'data:' not in result

    def test_target_blank_gets_noopener(self):
        """<a target="_blank"> should auto-get rel="noopener noreferrer"."""
        result = sanitize_html('<a href="https://example.com" target="_blank">Link</a>')
        assert 'target="_blank"' in result
        assert 'rel="noopener noreferrer"' in result

    def test_target_blank_with_existing_rel(self):
        """If rel is already present, don't duplicate it."""
        result = sanitize_html('<a href="https://example.com" target="_blank" rel="noopener">Link</a>')
        assert 'target="_blank"' in result
        # Should have rel (either original or auto-added), but not duplicated
        assert result.count('rel=') == 1


class TestExpandedCssProperties:
    """Test expanded CSS properties (Issue #120)."""

    def test_text_align_allowed(self):
        result = _sanitize_style('text-align: center;')
        assert 'text-align: center' in result

    def test_font_size_allowed(self):
        result = _sanitize_style('font-size: 14px;')
        assert 'font-size: 14px' in result

    def test_font_family_allowed(self):
        result = _sanitize_style('font-family: Arial, sans-serif;')
        assert 'font-family: Arial, sans-serif' in result

    def test_line_height_allowed(self):
        result = _sanitize_style('line-height: 1.5;')
        assert 'line-height: 1.5' in result

    def test_max_width_allowed(self):
        result = _sanitize_style('max-width: 600px;')
        assert 'max-width: 600px' in result

    def test_margin_shorthand_variants_allowed(self):
        result = _sanitize_style('margin-top: 10px; margin-bottom: 20px;')
        assert 'margin-top: 10px' in result
        assert 'margin-bottom: 20px' in result

    def test_padding_shorthand_variants_allowed(self):
        result = _sanitize_style('padding-left: 5px; padding-right: 5px;')
        assert 'padding-left: 5px' in result
        assert 'padding-right: 5px' in result

    def test_border_radius_allowed(self):
        result = _sanitize_style('border-radius: 4px;')
        assert 'border-radius: 4px' in result

    def test_border_collapse_allowed(self):
        result = _sanitize_style('border-collapse: collapse;')
        assert 'border-collapse: collapse' in result

    def test_list_style_type_allowed(self):
        result = _sanitize_style('list-style-type: disc;')
        assert 'list-style-type: disc' in result


class TestFigureAndImageElements:
    """Tests for figure, figcaption, and img elements (Issue #129)."""

    def test_img_tag_preserved(self):
        result = sanitize_html('<img src="example.png" alt="Example">')
        assert '<img' in str(result)
        assert 'src="example.png"' in str(result)
        assert 'alt="Example"' in str(result)

    def test_figure_and_figcaption_preserved(self):
        html_input = '<figure><img src="ex.png" alt="Ex"><figcaption>Caption</figcaption></figure>'
        result = sanitize_html(html_input)
        result_str = str(result)
        assert '<figure>' in result_str
        assert '<figcaption>' in result_str
        assert '</figcaption>' in result_str
        assert '</figure>' in result_str

    def test_figure_with_class_and_style(self):
        result = sanitize_html('<figure class="example-fig" style="margin: 10px;">')
        result_str = str(result)
        assert 'class="example-fig"' in result_str
        assert 'margin: 10px' in result_str

    def test_img_blocks_javascript_src(self):
        result = sanitize_html('<img src="javascript:alert(1)" alt="xss">')
        result_str = str(result)
        assert 'javascript:' not in result_str

    def test_img_blocks_data_src(self):
        result = sanitize_html('<img src="data:text/html,<script>alert(1)</script>" alt="xss">')
        result_str = str(result)
        assert 'data:' not in result_str

    def test_img_allows_relative_path(self):
        result = sanitize_html('<img src="data_files/screenshot.png" alt="Screenshot">')
        result_str = str(result)
        assert 'src="data_files/screenshot.png"' in result_str

    def test_img_width_height_allowed(self):
        result = sanitize_html('<img src="ex.png" width="400" height="300">')
        result_str = str(result)
        assert 'width="400"' in result_str
        assert 'height="300"' in result_str

    def test_img_onclick_blocked(self):
        """Event handlers should not be in the allowed attributes."""
        result = sanitize_html('<img src="ex.png" onclick="alert(1)">')
        result_str = str(result)
        assert 'onclick' not in result_str

    def test_img_in_allowlist(self):
        assert 'img' in ALLOWED_ELEMENTS

    def test_figure_in_allowlist(self):
        assert 'figure' in ALLOWED_ELEMENTS

    def test_figcaption_in_allowlist(self):
        assert 'figcaption' in ALLOWED_ELEMENTS


class TestDefinitionLists:
    """Tests for dl/dt/dd elements."""

    def test_definition_list_preserved(self):
        html_input = '<dl><dt>Term</dt><dd>Definition</dd></dl>'
        result = str(sanitize_html(html_input))
        assert '<dl>' in result
        assert '<dt>Term</dt>' in result
        assert '<dd>Definition</dd>' in result
        assert '</dl>' in result

    def test_dl_with_class(self):
        result = str(sanitize_html('<dl class="glossary">'))
        assert 'class="glossary"' in result

    def test_dd_with_style(self):
        result = str(sanitize_html('<dd style="margin-left: 20px;">'))
        assert 'margin-left: 20px' in result


class TestCollapsibleSections:
    """Tests for details/summary elements."""

    def test_details_summary_preserved(self):
        html_input = '<details><summary>Click to expand</summary><p>Hidden content</p></details>'
        result = str(sanitize_html(html_input))
        assert '<details>' in result
        assert '<summary>Click to expand</summary>' in result
        assert '</details>' in result

    def test_details_open_attribute(self):
        result = str(sanitize_html('<details open>'))
        # 'open' is a boolean attribute; our parser requires =value format,
        # so it may or may not be preserved depending on parser behavior
        assert '<details' in result

    def test_details_with_class(self):
        result = str(sanitize_html('<details class="faq-item" style="margin: 10px;">'))
        assert 'class="faq-item"' in result
        assert 'margin: 10px' in result

    def test_summary_onclick_blocked(self):
        result = str(sanitize_html('<summary onclick="alert(1)">Title</summary>'))
        assert 'onclick' not in result
        assert '<summary>' in result


class TestAbbreviation:
    """Tests for abbr element."""

    def test_abbr_with_title(self):
        result = str(sanitize_html('<abbr title="Natural Language Processing">NLP</abbr>'))
        assert '<abbr title="Natural Language Processing">NLP</abbr>' in result

    def test_abbr_in_allowlist(self):
        assert 'abbr' in ALLOWED_ELEMENTS


class TestTextEditingMarks:
    """Tests for s, del, ins elements."""

    def test_strikethrough_preserved(self):
        result = str(sanitize_html('<s>old text</s>'))
        assert '<s>old text</s>' in result

    def test_del_preserved(self):
        result = str(sanitize_html('<del>removed</del>'))
        assert '<del>removed</del>' in result

    def test_ins_preserved(self):
        result = str(sanitize_html('<ins>added</ins>'))
        assert '<ins>added</ins>' in result

    def test_del_with_datetime(self):
        result = str(sanitize_html('<del datetime="2026-01-01">old</del>'))
        assert 'datetime="2026-01-01"' in result

    def test_ins_with_cite(self):
        result = str(sanitize_html('<ins cite="https://example.com/change">new</ins>'))
        assert 'cite="https://example.com/change"' in result


class TestTableCaption:
    """Tests for caption element."""

    def test_caption_preserved(self):
        html_input = '<table><caption>Table 1: Results</caption><tr><td>data</td></tr></table>'
        result = str(sanitize_html(html_input))
        assert '<caption>Table 1: Results</caption>' in result

    def test_caption_with_style(self):
        result = str(sanitize_html('<caption style="text-align: center;">Title</caption>'))
        assert 'text-align: center' in result


class TestTechnicalInlineElements:
    """Tests for kbd, samp, var elements."""

    def test_kbd_preserved(self):
        result = str(sanitize_html('Press <kbd>Ctrl</kbd>+<kbd>S</kbd>'))
        assert '<kbd>Ctrl</kbd>' in result
        assert '<kbd>S</kbd>' in result

    def test_samp_preserved(self):
        result = str(sanitize_html('Output: <samp>Hello World</samp>'))
        assert '<samp>Hello World</samp>' in result

    def test_var_preserved(self):
        result = str(sanitize_html('Set <var>x</var> = 5'))
        assert '<var>x</var>' in result

    def test_cite_preserved(self):
        result = str(sanitize_html('From <cite>The Art of Annotation</cite>'))
        assert '<cite>The Art of Annotation</cite>' in result


class TestMiscElements:
    """Tests for wbr and ruby elements."""

    def test_wbr_preserved(self):
        result = str(sanitize_html('supercalifragilistic<wbr>expialidocious'))
        assert '<wbr>' in result

    def test_ruby_annotation_preserved(self):
        html_input = '<ruby>漢<rp>(</rp><rt>kan</rt><rp>)</rp></ruby>'
        result = str(sanitize_html(html_input))
        assert '<ruby>' in result
        assert '<rt>kan</rt>' in result
        assert '<rp>(</rp>' in result


class TestExpandedAllowlistCompleteness:
    """Verify all new elements are in ALLOWED_ELEMENTS."""

    @pytest.mark.parametrize("tag", [
        'dl', 'dt', 'dd',
        'details', 'summary',
        'abbr', 'cite', 'kbd', 'samp', 'var',
        's', 'del', 'ins',
        'caption',
        'wbr',
        'ruby', 'rt', 'rp',
    ])
    def test_tag_in_allowlist(self, tag):
        assert tag in ALLOWED_ELEMENTS, f"'{tag}' should be in ALLOWED_ELEMENTS"
