"""
Unit tests for multi-span target_field storage.

Verifies that SpanAnnotation objects with different target_fields
hash/compare differently and that the field-keyed format round-trips.
"""

import pytest
from potato.item_state_management import SpanAnnotation
from potato.server_utils.schemas.span import render_span_annotations, get_spans_for_field


class TestSpanAnnotationTargetField:
    """Tests for target_field support in SpanAnnotation."""

    def test_target_field_stored(self):
        span = SpanAnnotation("schema", "label", "title", 0, 5, target_field="premise")
        assert span.get_target_field() == "premise"

    def test_target_field_none_by_default(self):
        span = SpanAnnotation("schema", "label", "title", 0, 5)
        assert span.get_target_field() is None

    def test_different_target_fields_not_equal(self):
        span_a = SpanAnnotation("s", "label", "title", 0, 5, target_field="premise")
        span_b = SpanAnnotation("s", "label", "title", 0, 5, target_field="hypothesis")
        assert span_a != span_b

    def test_different_target_fields_different_hash(self):
        span_a = SpanAnnotation("s", "label", "title", 0, 5, target_field="premise")
        span_b = SpanAnnotation("s", "label", "title", 0, 5, target_field="hypothesis")
        assert hash(span_a) != hash(span_b)

    def test_same_target_field_equal(self):
        span_a = SpanAnnotation("s", "label", "title", 0, 5, target_field="premise")
        span_b = SpanAnnotation("s", "label", "title", 0, 5, target_field="premise")
        assert span_a == span_b
        assert hash(span_a) == hash(span_b)

    def test_none_and_missing_target_field_equal(self):
        span_a = SpanAnnotation("s", "label", "title", 0, 5, target_field=None)
        span_b = SpanAnnotation("s", "label", "title", 0, 5)
        assert span_a == span_b

    def test_target_field_in_str(self):
        span = SpanAnnotation("s", "label", "title", 0, 5, target_field="premise")
        assert "premise" in str(span)

    def test_no_target_field_in_str_when_none(self):
        span = SpanAnnotation("s", "label", "title", 0, 5)
        assert "target_field" not in str(span)

    def test_dict_key_with_target_field(self):
        """SpanAnnotation objects with different target_fields should be distinct dict keys."""
        span_a = SpanAnnotation("s", "label", "title", 0, 5, target_field="premise")
        span_b = SpanAnnotation("s", "label", "title", 0, 5, target_field="hypothesis")
        d = {span_a: "val_a", span_b: "val_b"}
        assert len(d) == 2
        assert d[span_a] == "val_a"
        assert d[span_b] == "val_b"


class TestFieldKeyedFormat:
    """Tests for field-keyed span format used in multi-span mode."""

    def test_render_field_keyed_spans_filters_by_field(self):
        text = "Hello world test"
        field_spans = {
            "premise": [
                {"schema": "s", "name": "MATCH", "title": "MATCH", "start": 0, "end": 5, "target_field": "premise"}
            ],
            "hypothesis": [
                {"schema": "s", "name": "NEW", "title": "NEW", "start": 6, "end": 11, "target_field": "hypothesis"}
            ]
        }
        result = render_span_annotations(text, field_spans, target_field="premise")
        assert "span-highlight" in result
        assert "Hello" in result
        # Should not include hypothesis spans when filtering by premise
        assert result.count("span-highlight") == 1

    def test_render_field_keyed_spans_flattens_without_filter(self):
        text = "Hello world test"
        field_spans = {
            "premise": [
                {"schema": "s", "name": "A", "title": "A", "start": 0, "end": 5}
            ],
            "hypothesis": [
                {"schema": "s", "name": "B", "title": "B", "start": 6, "end": 11}
            ]
        }
        result = render_span_annotations(text, field_spans, target_field=None)
        assert result.count("span-highlight") == 2

    def test_get_spans_for_field_from_field_keyed(self):
        field_spans = {
            "premise": [{"name": "A"}],
            "hypothesis": [{"name": "B"}]
        }
        result = get_spans_for_field(field_spans, "premise")
        assert len(result) == 1
        assert result[0]["name"] == "A"

    def test_get_spans_for_field_missing_key(self):
        field_spans = {
            "premise": [{"name": "A"}]
        }
        result = get_spans_for_field(field_spans, "hypothesis")
        assert len(result) == 0

    def test_get_spans_for_field_from_list(self):
        spans = [
            SpanAnnotation("s", "A", "A", 0, 5, target_field="premise"),
            SpanAnnotation("s", "B", "B", 6, 11, target_field="hypothesis"),
            SpanAnnotation("s", "C", "C", 0, 3, target_field="premise"),
        ]
        result = get_spans_for_field(spans, "premise")
        assert len(result) == 2

    def test_render_span_annotations_with_span_objects_filter(self):
        text = "Hello world test"
        spans = [
            SpanAnnotation("s", "A", "A", 0, 5, target_field="premise"),
            SpanAnnotation("s", "B", "B", 6, 11, target_field="hypothesis"),
        ]
        result = render_span_annotations(text, spans, target_field="premise")
        assert result.count("span-highlight") == 1
        assert "Hello" in result

    def test_render_empty_spans(self):
        text = "Hello world"
        assert render_span_annotations(text, None) == text
        assert render_span_annotations(text, []) == text
        assert render_span_annotations(text, {}) == text
