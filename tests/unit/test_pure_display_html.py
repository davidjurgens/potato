"""
Tests for issue #117: Allow optional HTML rendering in pure_display surveyflow content.

When allow_html is False (default), all HTML is escaped.
When allow_html is True, safe HTML is preserved through the sanitizer.
"""

import pytest


class TestPureDisplayDefaultEscaping:
    """Test that HTML is escaped by default (allow_html=False)."""

    def test_description_html_escaped_by_default(self):
        """HTML in description should be escaped when allow_html is not set."""
        from potato.server_utils.schemas.pure_display import generate_pure_display_layout

        scheme = {
            "name": "test_display",
            "annotation_type": "pure_display",
            "description": "<b>Bold text</b>",
            "labels": ["some content"],
        }
        html, keybindings = generate_pure_display_layout(scheme)

        assert "&lt;b&gt;" in html
        assert "<b>Bold text</b>" not in html
        assert keybindings == []

    def test_labels_html_escaped_by_default(self):
        """HTML in labels should be escaped when allow_html is not set."""
        from potato.server_utils.schemas.pure_display import generate_pure_display_layout

        scheme = {
            "name": "test_display",
            "annotation_type": "pure_display",
            "description": "Header",
            "labels": ["<em>emphasized</em>", "<script>alert('xss')</script>"],
        }
        html, _ = generate_pure_display_layout(scheme)

        assert "&lt;em&gt;" in html
        assert "&lt;script&gt;" in html
        assert "<em>emphasized</em>" not in html
        assert "<script>" not in html

    def test_allow_html_false_explicit(self):
        """Explicitly setting allow_html=False should escape HTML."""
        from potato.server_utils.schemas.pure_display import generate_pure_display_layout

        scheme = {
            "name": "test_display",
            "annotation_type": "pure_display",
            "description": "<b>Bold</b>",
            "labels": ["content"],
            "allow_html": False,
        }
        html, _ = generate_pure_display_layout(scheme)

        assert "&lt;b&gt;" in html


class TestPureDisplayAllowHtml:
    """Test that safe HTML is preserved when allow_html=True."""

    def test_bold_preserved_when_allowed(self):
        """<b> tags should be preserved when allow_html is True."""
        from potato.server_utils.schemas.pure_display import generate_pure_display_layout

        scheme = {
            "name": "test_display",
            "annotation_type": "pure_display",
            "description": "Please read the <b>following</b> carefully.",
            "allow_html": True,
        }
        html, _ = generate_pure_display_layout(scheme)

        assert "<b>following</b>" in html
        assert "&lt;b&gt;" not in html

    def test_em_and_strong_preserved(self):
        """<em> and <strong> should be preserved when allow_html is True."""
        from potato.server_utils.schemas.pure_display import generate_pure_display_layout

        scheme = {
            "name": "test_display",
            "annotation_type": "pure_display",
            "description": "<em>Note:</em> <strong>Important</strong>",
            "allow_html": True,
        }
        html, _ = generate_pure_display_layout(scheme)

        assert "<em>Note:</em>" in html
        assert "<strong>Important</strong>" in html

    def test_br_preserved_in_labels(self):
        """<br> tags in labels should be preserved when allow_html is True."""
        from potato.server_utils.schemas.pure_display import generate_pure_display_layout

        scheme = {
            "name": "test_display",
            "annotation_type": "pure_display",
            "description": "Instructions",
            "labels": ["Line 1<br>Line 2"],
            "allow_html": True,
        }
        html, _ = generate_pure_display_layout(scheme)

        # br should be preserved (sanitizer allows it)
        assert "<br>" in html or "<br/>" in html

    def test_script_blocked_even_when_html_allowed(self):
        """<script> tags should be neutralized even when allow_html is True."""
        from potato.server_utils.schemas.pure_display import generate_pure_display_layout

        scheme = {
            "name": "test_display",
            "annotation_type": "pure_display",
            "description": "Hello <script>alert('xss')</script> world",
            "labels": ["content"],
            "allow_html": True,
        }
        html, _ = generate_pure_display_layout(scheme)

        # Script tag should be escaped (not executable)
        assert "<script>" not in html

    def test_event_handlers_blocked_when_html_allowed(self):
        """Event handler attributes should be stripped even when allow_html is True."""
        from potato.server_utils.schemas.pure_display import generate_pure_display_layout

        scheme = {
            "name": "test_display",
            "annotation_type": "pure_display",
            "description": '<b onclick="alert(1)">Click me</b>',
            "labels": ["content"],
            "allow_html": True,
        }
        html, _ = generate_pure_display_layout(scheme)

        assert "onclick" not in html
        # The <b> tag itself should still be present (content preserved)
        assert "<b>" in html or "<b " in html

    def test_labels_with_html_when_allowed(self):
        """Labels should support HTML when allow_html is True."""
        from potato.server_utils.schemas.pure_display import generate_pure_display_layout

        scheme = {
            "name": "test_display",
            "annotation_type": "pure_display",
            "description": "Section",
            "labels": [
                "<b>Step 1:</b> Read the text",
                "<b>Step 2:</b> Make a selection",
            ],
            "allow_html": True,
        }
        html, _ = generate_pure_display_layout(scheme)

        assert "<b>Step 1:</b>" in html
        assert "<b>Step 2:</b>" in html

    def test_name_always_escaped(self):
        """Schema name should always be escaped (used in HTML attributes)."""
        from potato.server_utils.schemas.pure_display import generate_pure_display_layout

        scheme = {
            "name": 'test"><script>',
            "annotation_type": "pure_display",
            "description": "Safe description",
            "labels": ["content"],
            "allow_html": True,
        }
        html, _ = generate_pure_display_layout(scheme)

        # Name should be escaped even with allow_html
        assert '<script>' not in html.split('class="annotation-form')[0]


class TestFormatDisplayContent:
    """Test the format_display_content helper function."""

    def test_empty_labels(self):
        from potato.server_utils.schemas.pure_display import format_display_content
        assert format_display_content([]) == ""

    def test_labels_joined_with_br(self):
        from potato.server_utils.schemas.pure_display import format_display_content
        result = format_display_content(["A", "B", "C"])
        assert "A<br>B<br>C" == result

    def test_labels_escaped_by_default(self):
        from potato.server_utils.schemas.pure_display import format_display_content
        result = format_display_content(["<b>bold</b>"])
        assert "&lt;b&gt;" in result

    def test_labels_html_when_allowed(self):
        from potato.server_utils.schemas.pure_display import format_display_content
        result = format_display_content(["<b>bold</b>"], allow_html=True)
        assert "<b>bold</b>" in result


class TestIssue120StructuralHtml:
    """Test that structural HTML works in pure_display with allow_html (Issue #120)."""

    def test_allow_html_preserves_paragraphs_and_lists(self):
        """Paragraphs and lists should be preserved with allow_html."""
        from potato.server_utils.schemas.pure_display import format_display_content
        html = "<p>Read carefully.</p><ul><li>Step 1</li><li>Step 2</li></ul>"
        result = format_display_content([html], allow_html=True)
        assert "<p>Read carefully.</p>" in result
        assert "<ul>" in result
        assert "<li>Step 1</li>" in result

    def test_allow_html_preserves_headings(self):
        """Headings should be preserved with allow_html."""
        from potato.server_utils.schemas.pure_display import format_display_content
        result = format_display_content(["<h3>Instructions</h3>"], allow_html=True)
        assert "<h3>Instructions</h3>" in result

    def test_allow_html_preserves_tables(self):
        """Tables should be preserved with allow_html."""
        from potato.server_utils.schemas.pure_display import format_display_content
        html = "<table><tr><th>Key</th><td>Value</td></tr></table>"
        result = format_display_content([html], allow_html=True)
        assert "<table>" in result
        assert "<th>Key</th>" in result
        assert "<td>Value</td>" in result

    def test_issue_120_full_example(self):
        """The exact example from Issue #120 should render correctly."""
        from potato.server_utils.schemas.pure_display import format_display_content
        html = '<h3>Instructions</h3><p>Please read carefully.</p><ul><li>Step 1</li><li>Step 2</li></ul>'
        result = format_display_content([html], allow_html=True)
        assert "<h3>Instructions</h3>" in result
        assert "<p>Please read carefully.</p>" in result
        assert "<li>Step 1</li>" in result
        assert "<li>Step 2</li>" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
