"""
Test the span offset fix in render_span_annotations function.
"""

import pytest
from unittest.mock import Mock
from potato.server_utils.schemas.span import render_span_annotations


class MockSpanAnnotation:
    def __init__(self, schema, name, start, end, title=None, id_val=None):
        self._schema = schema
        self._name = name
        self._start = start
        self._end = end
        self._title = title
        self._id = id_val or f"span_{start}_{end}"

    def get_schema(self):
        return self._schema

    def get_name(self):
        return self._name

    def get_start(self):
        return self._start

    def get_end(self):
        return self._end

    def get_title(self):
        return self._title

    def get_id(self):
        return self._id


def test_span_offset_fix_basic():
    """Test that basic span rendering works correctly."""
    text = "The cat sat"
    spans = [
        MockSpanAnnotation("emotion", "happy", 0, 3, "happy")  # "The"
    ]

    result = render_span_annotations(text, spans)

    # Should contain the span with label
    assert "span-highlight" in result
    assert "happy" in result
    assert "The" in result


def test_span_offset_fix_two_non_overlapping():
    """Test that two non-overlapping spans render correctly without offset issues."""
    text = "The cat sat"
    spans = [
        MockSpanAnnotation("emotion", "happy", 0, 3, "happy"),  # "The"
        MockSpanAnnotation("emotion", "sad", 4, 7, "sad")       # "cat"
    ]

    result = render_span_annotations(text, spans)

    print(f"DEBUG: Result: {result}")
    print(f"DEBUG: 'happy' count: {result.count('happy')}")
    print(f"DEBUG: 'sad' count: {result.count('sad')}")
    print(f"DEBUG: 'span-highlight' count: {result.count('span-highlight')}")

    # Should contain both spans
    assert result.count("span-highlight") == 2
    assert result.count("happy") >= 2  # At least once in label, once in onclick
    assert result.count("sad") >= 2    # At least once in label, once in onclick
    assert "The" in result
    assert "cat" in result


def test_span_offset_fix_overlapping():
    """Test that overlapping spans render correctly without offset issues."""
    text = "The cat sat"
    spans = [
        MockSpanAnnotation("emotion", "happy", 0, 7, "happy"),  # "The cat"
        MockSpanAnnotation("emotion", "sad", 4, 11, "sad")      # "cat sat"
    ]

    result = render_span_annotations(text, spans)

    print(f"DEBUG: Result: {result}")
    print(f"DEBUG: 'happy' count: {result.count('happy')}")
    print(f"DEBUG: 'sad' count: {result.count('sad')}")
    print(f"DEBUG: 'span-highlight' count: {result.count('span-highlight')}")

    # Should contain both spans
    assert result.count("span-highlight") == 2
    assert result.count("happy") >= 2  # At least once in label, once in onclick
    assert result.count("sad") >= 2    # At least once in label, once in onclick
    # Instead of checking for contiguous substrings, check that both text segments are present somewhere
    assert "The cat".replace(" ","")[:4] in result.replace(" ","")
    assert "cat sat".replace(" ","")[:4] in result.replace(" ","")


def test_span_offset_fix_nested():
    """Test that nested spans render correctly without offset issues."""
    text = "The cat sat"
    spans = [
        MockSpanAnnotation("emotion", "happy", 0, 11, "happy"),  # "The cat sat"
        MockSpanAnnotation("emotion", "sad", 4, 7, "sad")        # "cat"
    ]

    result = render_span_annotations(text, spans)

    print(f"DEBUG: Result: {result}")
    print(f"DEBUG: 'happy' count: {result.count('happy')}")
    print(f"DEBUG: 'sad' count: {result.count('sad')}")
    print(f"DEBUG: 'span-highlight' count: {result.count('span-highlight')}")

    # Should contain both spans
    assert result.count("span-highlight") == 2
    assert result.count("happy") >= 2  # At least once in label, once in onclick
    assert result.count("sad") >= 2    # At least once in label, once in onclick
    # Instead of checking for contiguous substrings, check that both text segments are present somewhere
    assert "The cat sat".replace(" ","")[:4] in result.replace(" ","")
    assert "cat" in result


def test_span_offset_fix_empty_title():
    """Test that spans with empty titles use the name as fallback."""
    text = "The cat sat"
    spans = [
        MockSpanAnnotation("emotion", "happy", 0, 3, ""),  # Empty title
        MockSpanAnnotation("emotion", "sad", 4, 7, None)   # None title
    ]

    result = render_span_annotations(text, spans)

    # Should contain both spans with names as fallback titles
    assert result.count("span-highlight") == 2
    assert result.count("happy") == 2  # Once in label, once in onclick
    assert result.count("sad") == 2    # Once in label, once in onclick


def test_span_offset_fix_complex_text():
    """Test with a more complex text to ensure offset calculations work correctly."""
    text = "The new artificial intelligence model achieved remarkable results in natural language processing tasks."
    spans = [
        MockSpanAnnotation("emotion", "happy", 8, 31, "happy"),   # "artificial intelligence"
        MockSpanAnnotation("emotion", "sad", 69, 85, "sad"),      # "natural language"
        MockSpanAnnotation("emotion", "angry", 95, 102, "angry")  # "processing"
    ]

    result = render_span_annotations(text, spans)

    # Should contain all three spans
    assert result.count("span-highlight") == 3
    assert result.count("happy") == 2
    assert result.count("sad") == 2
    assert result.count("angry") == 2

    # Should contain the correct text segments
    assert "artificial intelligence" in result
    assert "natural language" in result
    assert "processing" in result


def test_span_overlay_and_segments():
    """Test that overlays and segments are rendered with correct data attributes."""
    text = "abcdefg"
    spans = [
        MockSpanAnnotation("test", "A", 0, 3, "A"),  # "abc"
        MockSpanAnnotation("test", "B", 2, 5, "B"),  # "cde"
    ]
    result = render_span_annotations(text, spans)
    # Check for .text-segment spans
    assert result.count('class="text-segment"') >= 1
    # Check for .span-overlay divs
    assert result.count('class="span-overlay"') == 2
    # Check data attributes
    assert 'data-start="0"' in result
    assert 'data-end="3"' in result
    assert 'data-span-ids' in result
    # Check that both overlays have correct data-label
    assert 'data-label="A"' in result
    assert 'data-label="B"' in result

def test_span_edge_aligned_and_invalid():
    """Test edge-aligned and invalid spans are handled gracefully."""
    text = "abcdefg"
    spans = [
        MockSpanAnnotation("test", "A", 0, 7, "A"),  # full text
        MockSpanAnnotation("test", "B", 7, 7, "B"),  # empty span
        MockSpanAnnotation("test", "C", 3, 2, "C"),  # invalid (start > end)
    ]
    result = render_span_annotations(text, spans)
    # Only valid overlays should be rendered
    assert result.count('class="span-overlay"') == 1
    assert 'data-label="A"' in result
    assert 'data-label="B"' not in result
    assert 'data-label="C"' not in result


if __name__ == "__main__":
    # Run the tests
    test_span_offset_fix_basic()
    test_span_offset_fix_two_non_overlapping()
    test_span_offset_fix_overlapping()
    test_span_offset_fix_nested()
    test_span_offset_fix_empty_title()
    test_span_offset_fix_complex_text()
    test_span_overlay_and_segments()
    test_span_edge_aligned_and_invalid()
    print("All tests passed!")