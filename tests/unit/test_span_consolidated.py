#!/usr/bin/env python3
"""
Consolidated unit tests for span annotation functionality.

This module consolidates unit tests from multiple files:
- test_span_annotations.py: SpanAnnotation data model
- test_span_schema_loading.py: Schema generation and HTML output
- test_span_integration.py: Backend API data types (no client)
- test_span_offset_fix.py: render_span_annotations function
- test_span_overlap_position.py: Overlap detection
- test_span_overlap_fix_unit.py: Validation logic
- test_span_persistence.py: Data transformation logic

Tests that require Flask client fixture are in tests/server/test_span_e2e.py.
Tests for browser behavior are in tests/selenium/test_span_browser.py.
"""

import json
import os
import unittest
import pytest

from tests.helpers.span_test_helpers import (
    MockSpanAnnotation,
    SpanTestData,
    assert_span_valid,
    assert_spans_equal,
    assert_no_html_in_span,
    spans_overlap,
    calculate_overlap_depth,
)


class TestSpanAnnotationModel(unittest.TestCase):
    """Tests for SpanAnnotation data model - creation, equality, serialization."""

    def test_span_annotation_creation(self):
        """Test basic SpanAnnotation creation with all fields."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation("test_schema", "positive", "Positive sentiment", 0, 5)
        self.assertEqual(span.get_schema(), "test_schema")
        self.assertEqual(span.get_name(), "positive")
        self.assertEqual(span.get_title(), "Positive sentiment")
        self.assertEqual(span.get_start(), 0)
        self.assertEqual(span.get_end(), 5)
        self.assertIsNotNone(span.get_id())
        self.assertTrue(span.get_id().startswith("span_"))

    def test_span_annotation_with_custom_id(self):
        """Test SpanAnnotation with custom ID."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation("test_schema", "negative", "Negative sentiment", 10, 15, "custom_id_123")
        self.assertEqual(span.get_id(), "custom_id_123")

    def test_span_annotation_equality(self):
        """Test SpanAnnotation equality based on schema, name, start, end."""
        from potato.item_state_management import SpanAnnotation

        span1 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id1")
        span2 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id2")
        span3 = SpanAnnotation("schema1", "label1", "title1", 0, 5, "id1")

        # Same schema, name, start, end should be equal regardless of id
        self.assertEqual(span1, span2)
        self.assertEqual(span1, span3)

        # Different schema should not be equal
        span4 = SpanAnnotation("schema2", "label1", "title1", 0, 5, "id1")
        self.assertNotEqual(span1, span4)

    def test_span_annotation_string_representation(self):
        """Test SpanAnnotation string representation contains key fields."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation("test_schema", "positive", "Positive sentiment", 0, 5, "test_id")
        str_repr = str(span)

        self.assertIn("test_id", str_repr)
        self.assertIn("test_schema", str_repr)
        self.assertIn("positive", str_repr)
        self.assertIn("0", str_repr)
        self.assertIn("5", str_repr)


class TestMockSpanAnnotation(unittest.TestCase):
    """Tests for MockSpanAnnotation helper class."""

    def test_mock_span_creation(self):
        """Test MockSpanAnnotation matches real SpanAnnotation interface."""
        mock = MockSpanAnnotation("emotion", "happy", 5, 10)

        self.assertEqual(mock.get_schema(), "emotion")
        self.assertEqual(mock.get_name(), "happy")
        self.assertEqual(mock.get_title(), "Happy")  # Auto-generated
        self.assertEqual(mock.get_start(), 5)
        self.assertEqual(mock.get_end(), 10)
        self.assertIn("span_5_10", mock.get_id())

    def test_mock_span_with_custom_title(self):
        """Test MockSpanAnnotation with custom title."""
        mock = MockSpanAnnotation("emotion", "happy", 5, 10, title="Custom Happy")
        self.assertEqual(mock.get_title(), "Custom Happy")

    def test_mock_span_to_dict(self):
        """Test MockSpanAnnotation serialization to dict."""
        mock = MockSpanAnnotation("emotion", "happy", 5, 10, span_id="custom_id")
        d = mock.to_dict()

        self.assertEqual(d['id'], "custom_id")
        self.assertEqual(d['schema'], "emotion")
        self.assertEqual(d['name'], "happy")
        self.assertEqual(d['label'], "happy")
        self.assertEqual(d['start'], 5)
        self.assertEqual(d['end'], 10)


class TestSpanSchemaGeneration(unittest.TestCase):
    """Tests for span schema HTML generation."""

    def test_span_schema_generation_basic(self):
        """Test that span schemas generate proper HTML layout."""
        from potato.server_utils.schemas.span import generate_span_layout

        schema = SpanTestData.EMOTION_SCHEMA.copy()
        schema['annotation_id'] = 0

        html_layout, keybindings = generate_span_layout(schema)

        # Verify schema name is embedded
        self.assertIn('schema="emotion"', html_layout)
        self.assertIn('name="span_label:::emotion"', html_layout)

        # Verify all labels are present
        self.assertIn('happy', html_layout)
        self.assertIn('sad', html_layout)
        self.assertIn('angry', html_layout)

    def test_span_schema_with_colors(self):
        """Test span schema generation with custom colors."""
        from potato.server_utils.schemas.span import generate_span_layout

        schema = SpanTestData.EMOTION_SCHEMA_WITH_COLORS.copy()
        schema['annotation_id'] = 0

        html_layout, keybindings = generate_span_layout(schema)

        # Verify colors are in the layout
        self.assertIn('happy', html_layout)
        self.assertIn('sad', html_layout)


class TestSpanRendering(unittest.TestCase):
    """Tests for render_span_annotations function."""

    def test_render_basic_span(self):
        """Test basic span rendering with single span."""
        from potato.server_utils.schemas.span import render_span_annotations

        text = "The cat sat"
        spans = [MockSpanAnnotation("emotion", "happy", 0, 3, title="happy")]

        result = render_span_annotations(text, spans)

        self.assertIn("span-highlight", result)
        self.assertIn("happy", result)
        self.assertIn("The", result)

    def test_render_two_non_overlapping_spans(self):
        """Test rendering two non-overlapping spans without offset issues."""
        from potato.server_utils.schemas.span import render_span_annotations

        text = "The cat sat"
        spans = [
            MockSpanAnnotation("emotion", "happy", 0, 3, title="happy"),  # "The"
            MockSpanAnnotation("emotion", "sad", 4, 7, title="sad")       # "cat"
        ]

        result = render_span_annotations(text, spans)

        self.assertEqual(result.count("span-highlight"), 2)
        # "happy" appears in both data-label and data-annotation-id
        self.assertIn('data-label="happy"', result)
        self.assertIn('data-label="sad"', result)
        self.assertIn("The", result)
        self.assertIn("cat", result)

    def test_render_overlapping_spans(self):
        """Test rendering overlapping spans correctly."""
        from potato.server_utils.schemas.span import render_span_annotations

        text = "The cat sat"
        spans = [
            MockSpanAnnotation("emotion", "happy", 0, 7, title="happy"),  # "The cat"
            MockSpanAnnotation("emotion", "sad", 4, 11, title="sad")      # "cat sat"
        ]

        result = render_span_annotations(text, spans)

        self.assertEqual(result.count("span-highlight"), 2)
        self.assertIn('data-label="happy"', result)
        self.assertIn('data-label="sad"', result)

    def test_render_nested_spans(self):
        """Test rendering nested spans correctly."""
        from potato.server_utils.schemas.span import render_span_annotations

        text = "The cat sat"
        spans = [
            MockSpanAnnotation("emotion", "happy", 0, 11, title="happy"),  # "The cat sat"
            MockSpanAnnotation("emotion", "sad", 4, 7, title="sad")        # "cat"
        ]

        result = render_span_annotations(text, spans)

        self.assertEqual(result.count("span-highlight"), 2)
        self.assertIn('data-label="happy"', result)
        self.assertIn('data-label="sad"', result)

    def test_render_span_empty_title_fallback(self):
        """Test that spans with empty titles use name as fallback."""
        from potato.server_utils.schemas.span import render_span_annotations

        text = "The cat sat"
        spans = [
            MockSpanAnnotation("emotion", "happy", 0, 3, title=""),  # Empty title
            MockSpanAnnotation("emotion", "sad", 4, 7, title=None)   # None title
        ]

        result = render_span_annotations(text, spans)

        self.assertEqual(result.count("span-highlight"), 2)
        self.assertIn("happy", result)
        self.assertIn("sad", result)

    def test_render_complex_text(self):
        """Test rendering with complex text to verify offset calculations."""
        from potato.server_utils.schemas.span import render_span_annotations

        text = "The new artificial intelligence model achieved remarkable results in natural language processing tasks."
        spans = [
            MockSpanAnnotation("emotion", "happy", 8, 31, title="happy"),   # "artificial intelligence"
            MockSpanAnnotation("emotion", "sad", 69, 85, title="sad"),      # "natural language"
            MockSpanAnnotation("emotion", "angry", 86, 96, title="angry")   # "processing"
        ]

        result = render_span_annotations(text, spans)

        self.assertEqual(result.count("span-highlight"), 3)
        self.assertIn("artificial intelligence", result)
        self.assertIn("natural language", result)
        self.assertIn("processing", result)

    def test_render_span_data_attributes(self):
        """Test that rendered spans have correct data attributes."""
        from potato.server_utils.schemas.span import render_span_annotations

        text = "abcdefg"
        spans = [
            MockSpanAnnotation("test", "A", 0, 3, title="A"),
            MockSpanAnnotation("test", "B", 2, 5, title="B"),
        ]

        result = render_span_annotations(text, spans)

        self.assertEqual(result.count('class="span-highlight"'), 2)
        # Annotation IDs include the label name
        self.assertIn('data-annotation-id="span_0_3_A"', result)
        self.assertIn('data-annotation-id="span_2_5_B"', result)
        self.assertIn('data-label="A"', result)
        self.assertIn('data-label="B"', result)


class TestSpanOverlapDetection(unittest.TestCase):
    """Tests for span overlap detection logic."""

    def test_overlapping_spans_detected(self):
        """Test that overlapping spans are correctly detected."""
        # "artificial intelligence" vs "intelligence model"
        self.assertTrue(spans_overlap(8, 32, 20, 35))
        self.assertTrue(spans_overlap(20, 35, 8, 32))  # Reverse order

    def test_non_overlapping_spans_not_detected(self):
        """Test that non-overlapping spans are not detected as overlapping."""
        self.assertFalse(spans_overlap(8, 32, 40, 60))
        self.assertFalse(spans_overlap(40, 60, 8, 32))

    def test_adjacent_spans_not_overlapping(self):
        """Test that adjacent spans (touching at edge) are not overlapping."""
        self.assertFalse(spans_overlap(8, 32, 32, 40))
        self.assertFalse(spans_overlap(32, 40, 8, 32))

    def test_nested_spans_overlap(self):
        """Test that nested (contained) spans are detected as overlapping."""
        self.assertTrue(spans_overlap(8, 35, 20, 32))  # 20-32 is inside 8-35
        self.assertTrue(spans_overlap(20, 32, 8, 35))

    def test_identical_spans_overlap(self):
        """Test that identical spans are detected as overlapping."""
        self.assertTrue(spans_overlap(8, 32, 8, 32))


class TestOverlapDepthCalculation(unittest.TestCase):
    """Tests for calculating maximum overlap depth."""

    def test_no_spans(self):
        """Test overlap depth with no spans."""
        self.assertEqual(calculate_overlap_depth([]), 0)

    def test_single_span(self):
        """Test overlap depth with single span."""
        spans = [{'start': 0, 'end': 10}]
        self.assertEqual(calculate_overlap_depth(spans), 1)

    def test_non_overlapping_spans(self):
        """Test overlap depth with non-overlapping spans."""
        spans = [
            {'start': 0, 'end': 10},
            {'start': 20, 'end': 30},
        ]
        self.assertEqual(calculate_overlap_depth(spans), 1)

    def test_two_overlapping_spans(self):
        """Test overlap depth with two overlapping spans."""
        spans = [
            {'start': 0, 'end': 20},
            {'start': 10, 'end': 30},
        ]
        self.assertEqual(calculate_overlap_depth(spans), 2)

    def test_three_overlapping_spans(self):
        """Test overlap depth with three overlapping spans at one point."""
        spans = [
            {'start': 0, 'end': 30},
            {'start': 10, 'end': 25},
            {'start': 15, 'end': 20},
        ]
        self.assertEqual(calculate_overlap_depth(spans), 3)


class TestSpanDataTransformation(unittest.TestCase):
    """Tests for span data transformation between formats."""

    def test_combine_existing_with_new_span(self):
        """Test combining existing spans with a new span."""
        existing_spans = [
            {
                'id': '1',
                'label': 'happy',
                'start': 8,
                'end': 32,
                'text': 'artificial intelligence'
            }
        ]

        new_span = {
            'name': 'sad',
            'start': 20,
            'end': 35,
            'title': 'sad',
            'value': 'intelligence model'
        }

        def combine_spans(existing, new):
            existing_formatted = [{
                'name': span['label'],
                'start': span['start'],
                'end': span['end'],
                'title': span['label'],
                'value': span.get('text') or span.get('value')
            } for span in existing]
            return existing_formatted + [new]

        result = combine_spans(existing_spans, new_span)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], 'happy')
        self.assertEqual(result[0]['start'], 8)
        self.assertEqual(result[1]['name'], 'sad')
        self.assertEqual(result[1]['start'], 20)

    def test_filter_deleted_span(self):
        """Test filtering out a deleted span."""
        existing_spans = [
            {'id': '1', 'label': 'happy', 'start': 8, 'end': 32},
            {'id': '2', 'label': 'sad', 'start': 20, 'end': 35},
        ]

        def filter_out_deleted(spans, span_id):
            return [span for span in spans if span['id'] != span_id]

        remaining = filter_out_deleted(existing_spans, '1')

        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]['id'], '2')
        self.assertEqual(remaining[0]['label'], 'sad')

    def test_span_data_consistency(self):
        """Test span data format transformation consistency."""
        original = {
            'id': '1',
            'label': 'happy',
            'start': 8,
            'end': 32,
            'text': 'artificial intelligence'
        }

        api_format = {
            'name': original['label'],
            'start': original['start'],
            'end': original['end'],
            'title': original['label'],
            'value': original['text']
        }

        self.assertEqual(api_format['name'], 'happy')
        self.assertEqual(api_format['start'], 8)
        self.assertEqual(api_format['end'], 32)
        self.assertEqual(api_format['value'], 'artificial intelligence')


class TestSpanDataValidation(unittest.TestCase):
    """Tests for span data validation."""

    def test_no_html_in_span_data(self):
        """Test that span API data contains no HTML markup."""
        span_data = {
            'id': 'span_1',
            'schema': 'sentiment',
            'name': 'positive',
            'title': 'Positive sentiment',
            'start': 0,
            'end': 4
        }

        # Should not raise
        assert_no_html_in_span(span_data)

    def test_span_valid_structure(self):
        """Test span validation with valid structure."""
        span = {
            'id': 'span_1',
            'label': 'positive',
            'start': 0,
            'end': 4
        }

        # Should not raise
        assert_span_valid(span)

    def test_span_valid_with_schema(self):
        """Test span validation with expected schema."""
        span = {
            'id': 'span_1',
            'label': 'positive',
            'schema': 'sentiment',
            'start': 0,
            'end': 4
        }

        # Should not raise
        assert_span_valid(span, expected_schema='sentiment')

    def test_span_data_type_integrity(self):
        """Test that span data types are correct."""
        span_data = {
            'id': 'span_2',
            'schema': 'entity',
            'name': 'person',
            'title': 'Person entity',
            'start': 5,
            'end': 10
        }

        self.assertIsInstance(span_data['start'], int)
        self.assertIsInstance(span_data['end'], int)
        self.assertIsInstance(span_data['name'], str)
        self.assertIsInstance(span_data['schema'], str)
        self.assertIsInstance(span_data['title'], str)
        self.assertIsInstance(span_data['id'], str)

    def test_selection_validation_logic(self):
        """Test validation logic for text selections."""
        def validate_selection(start, end):
            return start < end

        # Valid selections
        self.assertTrue(validate_selection(8, 32))
        self.assertTrue(validate_selection(0, 1))

        # Invalid selections
        self.assertFalse(validate_selection(32, 8))  # start > end
        self.assertFalse(validate_selection(20, 20))  # start == end
        self.assertFalse(validate_selection(0, 0))    # start == end


class TestSpanPositionCalculation(unittest.TestCase):
    """Tests for span position calculation."""

    def test_text_positions_match_expected(self):
        """Test that text.find() returns expected positions."""
        text = "The new artificial intelligence model achieved remarkable results in natural language processing tasks."

        self.assertEqual(text.find("artificial intelligence"), 8)
        self.assertEqual(text.find("intelligence model"), 19)

    def test_span_position_validity(self):
        """Test that span positions are valid (start < end, non-negative)."""
        span1_start, span1_end = 8, 32
        span2_start, span2_end = 20, 35

        self.assertGreater(span1_end, span1_start)
        self.assertGreater(span2_end, span2_start)
        self.assertGreaterEqual(span1_start, 0)
        self.assertGreaterEqual(span2_start, 0)


class TestSpanColorSystem(unittest.TestCase):
    """Tests for span color system."""

    def test_get_span_color_returns_consistent(self):
        """Test that get_span_color returns consistent colors."""
        from potato.server_utils.schemas.span import get_span_color

        color1 = get_span_color('sentiment', 'positive')
        color2 = get_span_color('sentiment', 'positive')

        self.assertEqual(color1, color2)

    def test_get_span_color_unknown(self):
        """Test get_span_color with unknown schema returns None."""
        from potato.server_utils.schemas.span import get_span_color

        color = get_span_color('unknown_schema', 'unknown_label')
        self.assertIsNone(color)


class TestSpansEqual(unittest.TestCase):
    """Tests for span equality comparison helper."""

    def test_spans_equal_same_positions(self):
        """Test that spans with same positions are considered equal."""
        span1 = {'start': 0, 'end': 10, 'label': 'happy'}
        span2 = {'start': 0, 'end': 10, 'name': 'happy'}  # Uses 'name' instead

        # Should not raise
        assert_spans_equal(span1, span2)

    def test_spans_equal_with_id_check(self):
        """Test span equality with ID comparison."""
        span1 = {'id': 'span_1', 'start': 0, 'end': 10, 'label': 'happy'}
        span2 = {'id': 'span_1', 'start': 0, 'end': 10, 'label': 'happy'}

        # Should not raise
        assert_spans_equal(span1, span2, ignore_id=False)


if __name__ == '__main__':
    unittest.main()
