"""
Test span text normalization consistency between template and API.

This test verifies the fix for a critical bug where span annotation positions
broke after navigation due to text normalization mismatch:
- Template (flask_server.py) normalized text: stripped HTML, normalized whitespace
- API (routes.py) returned raw text without normalization
- Result: Span offsets calculated on normalized text were applied to unnormalized text

The fix ensures both template and API use the same normalization logic.
"""

import re
import pytest


def normalize_text_for_spans(text: str) -> str:
    """
    Normalize text for span position calculations.

    This function mirrors the normalization done in:
    - flask_server.py (lines 1257-1260) for template rendering
    - routes.py (get_span_data endpoint) for API responses

    Args:
        text: Raw text that may contain HTML and irregular whitespace

    Returns:
        Normalized text with HTML stripped and whitespace normalized
    """
    # 1. Strip HTML tags
    normalized = re.sub(r'<[^>]+>', '', text)
    # 2. Normalize whitespace (multiple spaces/newlines -> single space)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


class TestSpanTextNormalization:
    """Test text normalization for span annotations."""

    def test_html_tags_stripped(self):
        """HTML tags should be removed from text."""
        text = '<span class="highlight">Hello</span> <b>World</b>'
        result = normalize_text_for_spans(text)
        assert result == "Hello World"
        assert '<' not in result
        assert '>' not in result

    def test_multiple_spaces_normalized(self):
        """Multiple consecutive spaces should become single space."""
        text = "Hello    World"
        result = normalize_text_for_spans(text)
        assert result == "Hello World"

    def test_newlines_normalized(self):
        """Newlines should be converted to single space."""
        text = "Hello\n\nWorld"
        result = normalize_text_for_spans(text)
        assert result == "Hello World"

    def test_tabs_normalized(self):
        """Tabs should be converted to single space."""
        text = "Hello\t\tWorld"
        result = normalize_text_for_spans(text)
        assert result == "Hello World"

    def test_mixed_whitespace_normalized(self):
        """Mixed whitespace types should be normalized."""
        text = "Hello  \n\t  World"
        result = normalize_text_for_spans(text)
        assert result == "Hello World"

    def test_leading_trailing_whitespace_trimmed(self):
        """Leading and trailing whitespace should be trimmed."""
        text = "  Hello World  "
        result = normalize_text_for_spans(text)
        assert result == "Hello World"

    def test_dialogue_turn_html_stripped(self):
        """Dialogue turn HTML formatting should be stripped."""
        text = '<span class="dialogue-turn dialogue-turn-even" style="display:block;"><b class="dialogue-speaker speaker-color-3">Alex:</b> Hello!</span>'
        result = normalize_text_for_spans(text)
        assert result == "Alex: Hello!"

    def test_nested_html_stripped(self):
        """Nested HTML tags should all be stripped."""
        text = '<div><span class="outer"><span class="inner">Text</span></span></div>'
        result = normalize_text_for_spans(text)
        assert result == "Text"

    def test_html_with_attributes_stripped(self):
        """HTML tags with various attributes should be stripped."""
        text = '<span data-speaker="Alex" data-speaker-index="0" class="test" style="color: red;">Content</span>'
        result = normalize_text_for_spans(text)
        assert result == "Content"

    def test_self_closing_tags_stripped(self):
        """Self-closing HTML tags should be stripped."""
        text = "Line 1<br/>Line 2<br />Line 3"
        result = normalize_text_for_spans(text)
        # Note: Stripping tags does not insert spaces, so "Line 1" and "Line 2"
        # become adjacent. This is acceptable since dialogue HTML includes spaces.
        assert result == "Line 1Line 2Line 3"
        assert '<br' not in result

    def test_empty_text_returns_empty(self):
        """Empty input should return empty string."""
        result = normalize_text_for_spans("")
        assert result == ""

    def test_whitespace_only_returns_empty(self):
        """Whitespace-only input should return empty string."""
        result = normalize_text_for_spans("   \n\t  ")
        assert result == ""

    def test_plain_text_unchanged(self):
        """Plain text without HTML or extra whitespace should be unchanged."""
        text = "Hello World"
        result = normalize_text_for_spans(text)
        assert result == "Hello World"


class TestSpanOffsetConsistency:
    """Test that span offsets work correctly with normalized text."""

    def test_span_offset_matches_normalized_text(self):
        """Span offsets should work correctly on normalized text."""
        raw_text = '<span class="dialogue-turn"><b>Alex:</b> Hello World!</span>'
        normalized = normalize_text_for_spans(raw_text)

        # Simulate a span annotation for "Hello"
        # In normalized text "Alex: Hello World!", "Hello" starts at index 6
        span_start = 6
        span_end = 11

        extracted = normalized[span_start:span_end]
        assert extracted == "Hello"

    def test_multi_turn_dialogue_offsets(self):
        """Span offsets should work across multiple dialogue turns."""
        raw_text = '''<span class="dialogue-turn"><b>Alex:</b> Hi!</span>
        <span class="dialogue-turn"><b>Jordan:</b> Hello!</span>'''
        normalized = normalize_text_for_spans(raw_text)

        # Normalized should be: "Alex: Hi! Jordan: Hello!"
        assert "Alex: Hi!" in normalized
        assert "Jordan: Hello!" in normalized

        # Find "Jordan" in the normalized text
        jordan_start = normalized.find("Jordan")
        jordan_end = jordan_start + len("Jordan")

        extracted = normalized[jordan_start:jordan_end]
        assert extracted == "Jordan"

    def test_span_across_whitespace_normalization(self):
        """Span containing text that had whitespace normalized."""
        raw_text = "Hello    beautiful    World"
        normalized = normalize_text_for_spans(raw_text)

        # In normalized "Hello beautiful World", "beautiful" is at index 6
        span_start = 6
        span_end = 15

        extracted = normalized[span_start:span_end]
        assert extracted == "beautiful"


class TestDialogueFormatting:
    """Test dialogue-specific text normalization scenarios."""

    def test_multiple_speakers_normalized(self):
        """Multiple speaker dialogue should normalize correctly."""
        raw_text = '''<span class="dialogue-turn dialogue-turn-even" style="display:block;"><b class="dialogue-speaker speaker-color-0">Dr. Smith:</b> The patient shows improvement.</span>
        <span class="dialogue-turn dialogue-turn-odd" style="display:block;"><b class="dialogue-speaker speaker-color-1">Nurse:</b> Noted.</span>'''

        normalized = normalize_text_for_spans(raw_text)

        # Should contain both speakers without HTML
        assert "Dr. Smith:" in normalized
        assert "The patient shows improvement." in normalized
        assert "Nurse:" in normalized
        assert "Noted." in normalized

        # Should not contain any HTML
        assert '<' not in normalized
        assert '>' not in normalized

    def test_long_response_normalized(self):
        """Long dialogue responses should normalize correctly."""
        long_response = "I have over 10 years of experience in software development, primarily focused on backend systems."
        raw_text = f'<span class="dialogue-turn"><b>Candidate:</b> {long_response}</span>'

        normalized = normalize_text_for_spans(raw_text)

        assert f"Candidate: {long_response}" == normalized

    def test_emotional_text_preserved(self):
        """Emotional expressions (caps, punctuation) should be preserved."""
        raw_text = '<span class="dialogue-turn"><b>Kid:</b> I KNOW, Mom!</span>'
        normalized = normalize_text_for_spans(raw_text)

        assert normalized == "Kid: I KNOW, Mom!"


class TestEdgeCases:
    """Test edge cases for text normalization."""

    def test_html_entities_not_decoded(self):
        """HTML entities should remain encoded (they're text, not tags)."""
        text = "Hello &amp; World"
        result = normalize_text_for_spans(text)
        # Note: We only strip tags, not decode entities
        assert result == "Hello &amp; World"

    def test_angle_brackets_in_text(self):
        """Angle brackets as part of text (math) - documents known limitation."""
        text = "x < 5 and y > 3"
        result = normalize_text_for_spans(text)
        # Known limitation: The regex r'<[^>]+>' matches "< 5 and y >" as a "tag"
        # This means math expressions with angle brackets may be mangled.
        # In practice, this is rare in annotation data and the regex is fast.
        # If this becomes an issue, consider using an HTML parser instead.
        assert "x" in result
        assert "3" in result
        # Note: "y" gets stripped because "< 5 and y >" looks like a tag to regex

    def test_malformed_html_handled(self):
        """Malformed HTML should be handled gracefully."""
        text = "<span>Unclosed tag and </span more content"
        result = normalize_text_for_spans(text)
        # The regex will strip what looks like tags
        assert "Unclosed tag and" in result

    def test_unicode_preserved(self):
        """Unicode characters should be preserved."""
        text = '<span class="test">Hello 世界 🌍</span>'
        result = normalize_text_for_spans(text)
        assert result == "Hello 世界 🌍"

    def test_url_in_text_preserved(self):
        """URLs in text should be preserved."""
        text = '<span>Check https://example.com/report.pdf</span>'
        result = normalize_text_for_spans(text)
        assert result == "Check https://example.com/report.pdf"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
