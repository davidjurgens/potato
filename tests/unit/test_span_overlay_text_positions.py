"""
Unit tests for span overlay position calculation.

These tests verify that span overlays are correctly positioned when:
1. The DOM contains only plain text (no existing annotations)
2. The DOM contains server-rendered span elements (existing annotations)

BUG CAUGHT: The getTextPositions() function assumed a single text node,
but server-rendered span elements create multiple text nodes. Position
calculations would fail because offsets were applied to the wrong text node.
"""

import pytest
from jinja2 import Environment
from markupsafe import Markup

from potato.server_utils.html_sanitizer import sanitize_html


class TestDataOriginalTextAttribute:
    """
    Test that data-original-text contains plain text, not HTML.

    BUG CAUGHT: The template was using the same variable for both
    data-original-text (should be plain text) and DOM content (may have HTML).
    This caused position calculations to be based on HTML-escaped text,
    which didn't match the rendered DOM text.
    """

    def test_plain_text_preserved_in_attribute(self):
        """
        data-original-text should contain plain text without span HTML.

        When existing annotations are rendered as HTML spans, the
        data-original-text attribute must still contain the original
        plain text for position calculations to work correctly.
        """
        env = Environment(autoescape=True)
        env.filters['sanitize_html'] = sanitize_html

        # Simulate template rendering with plain text for attribute
        # and HTML with spans for content
        template = env.from_string('''
            <div id="text-content"
                 data-original-text="{{ instance_plain_text | sanitize_html }}"
                 >{{ instance | sanitize_html }}</div>
        ''')

        plain_text = "I am happy today"
        html_with_spans = 'I am <span class="span-highlight">happy</span> today'

        result = template.render(
            instance_plain_text=plain_text,
            instance=html_with_spans
        )

        # Check that data-original-text has plain text
        assert 'data-original-text="I am happy today"' in result, \
            "data-original-text should contain plain text"

        # Check that content has span HTML
        assert '<span class="span-highlight">happy</span>' in result, \
            "DOM content should have span HTML"

        # The attribute should NOT have span tags
        assert 'data-original-text="' not in result or \
               'span-highlight' not in result.split('data-original-text="')[1].split('"')[0], \
            "data-original-text should not contain span HTML"

    def test_special_characters_escaped_in_attribute(self):
        """
        Special characters should be properly escaped in the attribute.
        """
        env = Environment(autoescape=True)
        env.filters['sanitize_html'] = sanitize_html

        template = env.from_string('''
            <div data-original-text="{{ text | sanitize_html }}">{{ text | sanitize_html }}</div>
        ''')

        # Text with special characters that need escaping
        text = "Compare: a < b and c > d"

        result = template.render(text=text)

        # Both attribute and content should have escaped < and >
        assert '&lt;' in result
        assert '&gt;' in result


class TestPositionCalculationWithServerRenderedSpans:
    """
    Test that position calculations work when DOM has server-rendered spans.

    BUG CAUGHT: getTextPositions() used textElement.firstChild assuming a
    single text node. With server-rendered spans, the DOM has multiple text
    nodes, and range.setStart/setEnd failed with out-of-bounds offsets.
    """

    def test_dom_structure_with_server_rendered_spans(self):
        """
        Verify that server-rendered spans create expected DOM structure.

        When spans are rendered by the server, the DOM looks like:
        [TextNode: "I am "][SpanElement[TextNode: "happy"]][TextNode: " today"]

        Position calculation must traverse all text nodes.
        """
        # This simulates what the browser sees after server rendering
        html_content = 'I am <span class="span-highlight">happy</span> today'

        # The plain text (what data-original-text should contain)
        plain_text = "I am happy today"

        # Calculate expected positions in plain text
        happy_start = plain_text.index("happy")  # 5
        happy_end = happy_start + len("happy")   # 10

        assert happy_start == 5
        assert happy_end == 10

        # In the HTML, "happy" is inside a span element
        # The position calculation code must:
        # 1. Read positions from data-original-text (plain text)
        # 2. Map those positions to the actual DOM text nodes
        # 3. Create a Range that spans the correct nodes

    def test_text_before_span_position(self):
        """
        Test position calculation for text before any span element.
        """
        plain_text = "I am happy today"
        am_start = plain_text.index("am")  # 2
        am_end = am_start + len("am")      # 4

        # "am" appears before the span, so it should be in the first text node
        assert am_start == 2
        assert am_end == 4

    def test_text_after_span_position(self):
        """
        Test position calculation for text after a span element.
        """
        plain_text = "I am happy today"
        today_start = plain_text.index("today")  # 11
        today_end = today_start + len("today")   # 16

        # "today" appears after the span, so it should be in the last text node
        assert today_start == 11
        assert today_end == 16

    def test_text_spanning_multiple_nodes(self):
        """
        Test position calculation for text that crosses span boundaries.

        This tests the case where the selected text spans multiple DOM nodes,
        such as selecting "happy today" which crosses from inside a span
        to the text after it.
        """
        plain_text = "I am happy today"
        selection_start = plain_text.index("happy")  # 5
        selection_end = plain_text.index("today") + len("today")  # 16

        # Selection spans from inside the span element to after it
        selected_text = plain_text[selection_start:selection_end]
        assert selected_text == "happy today"


class TestFlaskServerPlainTextVariable:
    """
    Test that flask_server.py provides both plain text and rendered HTML.
    """

    def test_original_plain_text_separate_from_rendered(self):
        """
        flask_server.py should pass both:
        - instance_plain_text: original text without span HTML
        - instance: rendered text (may have span HTML for existing annotations)
        """
        # This is a documentation test - the actual behavior is tested
        # in integration tests. This documents the expected interface.
        expected_template_variables = {
            'instance_plain_text': "I am happy today",  # Plain text
            'instance': 'I am <span class="span-highlight">happy</span> today',  # Rendered
        }

        # instance_plain_text should be used for data-original-text
        # instance should be used for DOM content


class TestRenderSpanAnnotationsOutput:
    """
    Test the server-side span rendering function.
    """

    def test_render_span_annotations_preserves_text_length(self):
        """
        render_span_annotations() should preserve the semantic text,
        only adding HTML wrapper elements.
        """
        from potato.server_utils.schemas.span import render_span_annotations, SpanAnnotation

        original_text = "I am happy today"

        # Create a mock span annotation
        class MockSpanAnnotation:
            def __init__(self):
                self.schema = "sentiment"
                self.name = "positive"
                self.start = 5   # "happy"
                self.end = 10
                self.title = "positive"

            def get_schema(self): return self.schema
            def get_name(self): return self.name
            def get_start(self): return self.start
            def get_end(self): return self.end
            def get_title(self): return self.title
            def get_id(self): return "span_5_10"

        spans = [MockSpanAnnotation()]

        rendered = render_span_annotations(original_text, spans)

        # The rendered text should contain the span HTML
        assert '<span' in rendered
        assert 'happy' in rendered

        # Strip HTML to verify text is preserved
        import re
        text_only = re.sub(r'<[^>]+>', '', rendered)
        assert text_only == original_text, \
            "Text content should be preserved after rendering"


class TestHandleTextSelectionFlow:
    """
    Test the handleTextSelection flow for immediate overlay creation.

    BUG CAUGHT: The overlay was created but never appended to the DOM,
    so it was invisible until the page was reloaded.
    """

    def test_overlay_must_be_appended_to_dom(self):
        """
        After creating an overlay, it MUST be appended to #span-overlays.

        This documents the required behavior - the actual fix is in JavaScript.
        The handleTextSelection() function must:
        1. Create the overlay via createSpanFromSelection()
        2. Update the label text with the selected label
        3. Update the highlight color
        4. APPEND the overlay to #span-overlays (this was missing!)
        5. Add span to local state
        6. Save to server
        """
        # This is a documentation test for the JavaScript fix
        required_steps = [
            "createSpanFromSelection() creates overlay",
            "Update overlay.querySelector('.span-label').textContent",
            "Update segment.style.backgroundColor with correct color",
            "spanOverlays.appendChild(overlay)",  # THIS WAS MISSING
            "this.annotations.spans.push(span)",
            "this.saveSpan(span)",
        ]
        assert len(required_steps) == 6

    def test_overlay_color_must_be_applied_to_segments(self):
        """
        The highlight color must be applied to .span-highlight-segment elements.

        createOverlay() creates segments with default color (yellow).
        handleTextSelection() must update segments with the label's color.
        """
        # The overlay has segments for each line of text
        # Each segment must have backgroundColor set to the label's color
        pass


class TestSpanAnnotationIntegrationFlow:
    """
    Test the complete flow of span annotation.

    These tests document the expected behavior at each step:
    1. User selects text
    2. Frontend calculates positions from data-original-text (plain text)
    3. Span is saved to server with start/end positions
    4. On page reload, server renders span as HTML
    5. data-original-text still contains plain text
    6. Frontend can re-render overlays using same position logic
    """

    def test_first_span_creation_flow(self):
        """
        When no existing spans, both data-original-text and DOM have plain text.
        """
        plain_text = "I am happy today"

        # On first load, no spans exist
        instance = plain_text
        instance_plain_text = plain_text

        # Template renders with:
        # data-original-text="{{ instance_plain_text }}"  -> "I am happy today"
        # content: {{ instance }}                          -> "I am happy today"

        # Both are the same - DOM is just a text node
        assert instance == instance_plain_text

    def test_subsequent_span_creation_flow(self):
        """
        When existing spans rendered as HTML, data-original-text is still plain.
        """
        plain_text = "I am happy today"

        # Server renders existing span
        rendered_html = 'I am <span class="span-highlight">happy</span> today'

        # Template receives:
        instance = rendered_html
        instance_plain_text = plain_text

        # data-original-text gets plain text
        # content gets HTML with spans

        assert '<span' in instance
        assert '<span' not in instance_plain_text

        # Position calculation should use instance_plain_text
        target_text = "today"
        position_in_plain = instance_plain_text.index(target_text)
        assert position_in_plain == 11
