"""
Unit tests for discontinuous span annotation support.

Discontinuous spans allow annotating entities that span non-contiguous text,
e.g., "New" and "York" in "New and exciting York" can be annotated as
a single LOCATION entity.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestSpanAnnotationDiscontinuous:
    """Tests for SpanAnnotation class discontinuous span support."""

    def test_span_annotation_accepts_additional_parts(self):
        """Test that SpanAnnotation accepts additional_parts parameter."""
        from potato.item_state_management import SpanAnnotation

        additional_parts = [
            {"start": 18, "end": 22, "text": "York"}
        ]

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3,
            additional_parts=additional_parts
        )

        assert span.additional_parts == additional_parts
        assert len(span.additional_parts) == 1

    def test_span_annotation_default_additional_parts(self):
        """Test that SpanAnnotation has empty additional_parts by default."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3
        )

        assert span.additional_parts == []
        assert not span.is_discontinuous()

    def test_span_annotation_is_discontinuous(self):
        """Test is_discontinuous() returns True when there are additional parts."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3,
            additional_parts=[{"start": 18, "end": 22, "text": "York"}]
        )

        assert span.is_discontinuous() is True

    def test_span_annotation_add_part(self):
        """Test adding parts to a discontinuous span."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3
        )

        # Initially not discontinuous
        assert not span.is_discontinuous()

        # Add a part
        span.add_part(18, 22, "York")

        assert span.is_discontinuous()
        assert len(span.additional_parts) == 1
        assert span.additional_parts[0]["start"] == 18
        assert span.additional_parts[0]["end"] == 22
        assert span.additional_parts[0]["text"] == "York"

    def test_span_annotation_add_multiple_parts_sorted(self):
        """Test that additional parts are kept sorted by start position."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3
        )

        # Add parts out of order
        span.add_part(30, 35, "City")
        span.add_part(18, 22, "York")

        assert len(span.additional_parts) == 2
        # Should be sorted by start position
        assert span.additional_parts[0]["start"] == 18
        assert span.additional_parts[1]["start"] == 30

    def test_span_annotation_remove_part(self):
        """Test removing parts from a discontinuous span."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3,
            additional_parts=[
                {"start": 18, "end": 22, "text": "York"},
                {"start": 30, "end": 35, "text": "City"}
            ]
        )

        assert len(span.additional_parts) == 2

        span.remove_part(18, 22)

        assert len(span.additional_parts) == 1
        assert span.additional_parts[0]["start"] == 30

    def test_span_annotation_get_all_parts(self):
        """Test get_all_parts() returns primary and additional parts sorted."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3,
            additional_parts=[
                {"start": 30, "end": 35, "text": "City"},
                {"start": 18, "end": 22, "text": "York"}
            ]
        )

        all_parts = span.get_all_parts()

        assert len(all_parts) == 3
        # Should be sorted by start position
        assert all_parts[0]["start"] == 0  # Primary span
        assert all_parts[1]["start"] == 18
        assert all_parts[2]["start"] == 30

    def test_span_annotation_to_dict_includes_additional_parts(self):
        """Test to_dict() includes additional_parts when present."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3,
            additional_parts=[{"start": 18, "end": 22, "text": "York"}]
        )

        result = span.to_dict()

        assert "additional_parts" in result
        assert result["additional_parts"] == [{"start": 18, "end": 22, "text": "York"}]

    def test_span_annotation_to_dict_excludes_empty_additional_parts(self):
        """Test to_dict() excludes additional_parts when empty."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3
        )

        result = span.to_dict()

        assert "additional_parts" not in result

    def test_span_annotation_equality_with_additional_parts(self):
        """Test equality comparison includes additional_parts."""
        from potato.item_state_management import SpanAnnotation

        span1 = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3,
            additional_parts=[{"start": 18, "end": 22}]
        )

        span2 = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3,
            additional_parts=[{"start": 18, "end": 22}]
        )

        span3 = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3,
            additional_parts=[{"start": 25, "end": 30}]  # Different parts
        )

        assert span1 == span2
        assert span1 != span3

    def test_span_annotation_hash_with_additional_parts(self):
        """Test hash includes additional_parts."""
        from potato.item_state_management import SpanAnnotation

        span1 = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3,
            additional_parts=[{"start": 18, "end": 22}]
        )

        span2 = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3,
            additional_parts=[{"start": 18, "end": 22}]
        )

        # Same spans should have same hash
        assert hash(span1) == hash(span2)


class TestSpanLayoutDiscontinuous:
    """Tests for span layout generation with discontinuous support."""

    @pytest.fixture(autouse=True)
    def setup_mocks(self):
        """Setup mocks for config module."""
        with patch('potato.server_utils.schemas.span.config', {}):
            yield

    def test_schema_config_accepts_allow_discontinuous(self):
        """Test that span schema accepts allow_discontinuous configuration."""
        from potato.server_utils.schemas.span import _generate_span_layout_internal
        from potato.server_utils.schemas.span import reset_span_counter

        reset_span_counter()

        annotation_scheme = {
            "name": "entities",
            "description": "Entity types",
            "labels": ["PERSON", "LOCATION"],
            "annotation_id": "test_annotation",
            "allow_discontinuous": True
        }

        html, keybindings = _generate_span_layout_internal(annotation_scheme)

        # Check that discontinuous attribute is added
        assert 'data-allow-discontinuous="true"' in html

    def test_schema_config_allow_discontinuous_default_false(self):
        """Test that allow_discontinuous defaults to False."""
        from potato.server_utils.schemas.span import _generate_span_layout_internal
        from potato.server_utils.schemas.span import reset_span_counter

        reset_span_counter()

        annotation_scheme = {
            "name": "entities",
            "description": "Entity types",
            "labels": ["PERSON", "LOCATION"],
            "annotation_id": "test_annotation"
        }

        html, keybindings = _generate_span_layout_internal(annotation_scheme)

        # Check that discontinuous attribute is NOT added
        assert 'data-allow-discontinuous' not in html

    def test_schema_config_shows_discontinuous_hint(self):
        """Test that discontinuous hint is shown when enabled."""
        from potato.server_utils.schemas.span import _generate_span_layout_internal
        from potato.server_utils.schemas.span import reset_span_counter

        reset_span_counter()

        annotation_scheme = {
            "name": "entities",
            "description": "Entity types",
            "labels": ["PERSON", "LOCATION"],
            "annotation_id": "test_annotation",
            "allow_discontinuous": True
        }

        html, keybindings = _generate_span_layout_internal(annotation_scheme)

        # Check that hint text is included
        assert 'discontinuous-hint' in html
        assert 'Ctrl/Cmd' in html


class TestRenderSpanAnnotationsDiscontinuous:
    """Tests for rendering discontinuous spans."""

    @pytest.fixture(autouse=True)
    def setup_mocks(self):
        """Setup mocks for config module."""
        with patch('potato.server_utils.schemas.span.config', {}):
            yield

    def test_render_discontinuous_span(self):
        """Test rendering a span with additional parts."""
        from potato.server_utils.schemas.span import render_span_annotations

        text = "New and exciting York City"
        span_annotations = [
            {
                'id': 'span_1',
                'schema': 'entities',
                'name': 'LOCATION',
                'title': 'LOCATION',
                'start': 0,
                'end': 3,
                'additional_parts': [
                    {'start': 17, 'end': 21}  # "York"
                ]
            }
        ]

        result = render_span_annotations(text, span_annotations)

        # Primary span should be rendered
        assert 'data-annotation-id="span_1"' in result
        # Additional part should also be rendered
        assert result.count('span_1') >= 2  # ID appears in both parts

    def test_render_discontinuous_span_with_discontinuous_class(self):
        """Test that discontinuous spans get the discontinuous-part class."""
        from potato.server_utils.schemas.span import render_span_annotations

        text = "New and exciting York City"
        span_annotations = [
            {
                'id': 'span_1',
                'schema': 'entities',
                'name': 'LOCATION',
                'title': 'LOCATION',
                'start': 0,
                'end': 3,
                'additional_parts': [
                    {'start': 17, 'end': 21}
                ]
            }
        ]

        result = render_span_annotations(text, span_annotations)

        # Discontinuous spans should have the discontinuous-part class
        assert 'discontinuous-part' in result

    def test_render_single_span_still_works(self):
        """Test that single (non-discontinuous) spans still render correctly."""
        from potato.server_utils.schemas.span import render_span_annotations

        text = "Hello World"
        span_annotations = [
            {
                'id': 'span_1',
                'schema': 'entities',
                'name': 'GREETING',
                'title': 'GREETING',
                'start': 0,
                'end': 5
            }
        ]

        result = render_span_annotations(text, span_annotations)

        # Single span should be rendered
        assert '<span class="span-highlight"' in result
        assert 'data-annotation-id="span_1"' in result
        # Should NOT have discontinuous-part class
        assert 'discontinuous-part' not in result


class TestSpanAnnotationObjectDiscontinuous:
    """Tests for SpanAnnotation object with discontinuous parts."""

    def test_span_annotation_object_with_additional_parts(self):
        """Test SpanAnnotation object handles additional_parts correctly."""
        from potato.item_state_management import SpanAnnotation
        from potato.server_utils.schemas.span import render_span_annotations

        with patch('potato.server_utils.schemas.span.config', {}):
            text = "New and exciting York City"

            span = SpanAnnotation(
                schema="entities",
                name="LOCATION",
                title="LOCATION",
                start=0,
                end=3,
                id="span_1",
                additional_parts=[{"start": 17, "end": 21}]
            )

            result = render_span_annotations(text, [span])

            # Both parts should be rendered
            assert 'data-annotation-id="span_1"' in result
            assert 'discontinuous-part' in result


class TestSpanAnnotationStr:
    """Tests for SpanAnnotation string representation."""

    def test_str_includes_additional_parts_count(self):
        """Test __str__ includes additional_parts count when present."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3,
            additional_parts=[
                {"start": 18, "end": 22},
                {"start": 30, "end": 35}
            ]
        )

        result = str(span)

        assert "additional_parts:2" in result

    def test_str_no_additional_parts_info_when_empty(self):
        """Test __str__ does not include additional_parts info when empty."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="entities",
            name="LOCATION",
            title="LOCATION",
            start=0,
            end=3
        )

        result = str(span)

        assert "additional_parts" not in result
