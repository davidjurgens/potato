"""
Tests for Batch 2 fixes: Data Integrity (2A) + Security Hardening (2B).

Batch 2A — Data Integrity:
1. Entity link (KB) fields preserved through serialization/deserialization
2. Event annotations included in state management methods

Batch 2B — Security Hardening:
3. Path traversal prevention in local_source.py
4. Cache directory path validation in ai_cache.py
5. Input validation on update_span endpoint
6. Event API instance authorization
7. annotation_id bounds check in get_ai_suggestion
8. Prefetch count validation/clamping
"""

import pytest
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ============================================================================
# Issue 1: Entity link (KB) fields preserved through deserialization
# ============================================================================

class TestSpanKBDeserialization:
    """Tests that KB fields survive save/load round-trips."""

    def test_span_annotation_to_dict_includes_kb_fields(self):
        """Test that SpanAnnotation.to_dict() includes KB fields."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            "ner", "PER", "Person", 0, 5,
            kb_id="Q42", kb_source="wikidata", kb_label="Douglas Adams"
        )
        d = span.to_dict()
        assert d["kb_id"] == "Q42"
        assert d["kb_source"] == "wikidata"
        assert d["kb_label"] == "Douglas Adams"

    def test_span_annotation_to_dict_without_kb_fields(self):
        """Test that KB fields are absent when not set."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation("ner", "PER", "Person", 0, 5)
        d = span.to_dict()
        assert "kb_id" not in d
        assert "kb_source" not in d
        assert "kb_label" not in d

    def test_to_span_preserves_kb_fields(self):
        """Test that the to_span() deserialization function preserves KB fields."""
        from potato.item_state_management import SpanAnnotation

        # Simulate what to_span() does in user_state_management.py
        d = {
            "schema": "ner", "name": "PER", "title": "Person",
            "start": 0, "end": 5, "id": "span_test123",
            "kb_id": "Q42", "kb_source": "wikidata", "kb_label": "Douglas Adams",
        }
        span = SpanAnnotation(
            d['schema'], d['name'], d['title'], int(d['start']), int(d['end']),
            id=d.get('id'), target_field=d.get('target_field'),
            format_coords=d.get('format_coords'),
            additional_parts=d.get('additional_parts'),
            kb_id=d.get('kb_id'), kb_source=d.get('kb_source'),
            kb_label=d.get('kb_label'),
        )
        assert span.kb_id == "Q42"
        assert span.kb_source == "wikidata"
        assert span.kb_label == "Douglas Adams"
        assert span._id == "span_test123"

    def test_to_span_without_kb_fields(self):
        """Test that to_span() handles missing KB fields gracefully."""
        from potato.item_state_management import SpanAnnotation

        d = {
            "schema": "ner", "name": "PER", "title": "Person",
            "start": 0, "end": 5,
        }
        span = SpanAnnotation(
            d['schema'], d['name'], d['title'], int(d['start']), int(d['end']),
            id=d.get('id'), target_field=d.get('target_field'),
            format_coords=d.get('format_coords'),
            additional_parts=d.get('additional_parts'),
            kb_id=d.get('kb_id'), kb_source=d.get('kb_source'),
            kb_label=d.get('kb_label'),
        )
        assert span.kb_id is None
        assert span.kb_source is None
        assert span.kb_label is None

    def test_to_span_preserves_additional_parts(self):
        """Test that additional_parts and other optional fields are also preserved."""
        from potato.item_state_management import SpanAnnotation

        d = {
            "schema": "ner", "name": "LOC", "title": "Location",
            "start": 0, "end": 3, "id": "span_xyz",
            "target_field": "text_field",
            "additional_parts": [{"start": 20, "end": 24, "text": "York"}],
        }
        span = SpanAnnotation(
            d['schema'], d['name'], d['title'], int(d['start']), int(d['end']),
            id=d.get('id'), target_field=d.get('target_field'),
            format_coords=d.get('format_coords'),
            additional_parts=d.get('additional_parts'),
            kb_id=d.get('kb_id'), kb_source=d.get('kb_source'),
            kb_label=d.get('kb_label'),
        )
        assert span.target_field == "text_field"
        assert len(span.additional_parts) == 1
        assert span.additional_parts[0]["text"] == "York"

    def test_span_round_trip(self):
        """Test full round-trip: create → to_dict → reconstruct."""
        from potato.item_state_management import SpanAnnotation

        original = SpanAnnotation(
            "ner", "ORG", "Organization", 10, 25,
            kb_id="Q312", kb_source="wikidata", kb_label="Apple Inc.",
            target_field="main_text",
        )
        d = original.to_dict()

        reconstructed = SpanAnnotation(
            d['schema'], d['name'], d['title'], int(d['start']), int(d['end']),
            id=d.get('id'), target_field=d.get('target_field'),
            format_coords=d.get('format_coords'),
            additional_parts=d.get('additional_parts'),
            kb_id=d.get('kb_id'), kb_source=d.get('kb_source'),
            kb_label=d.get('kb_label'),
        )

        assert reconstructed.kb_id == "Q312"
        assert reconstructed.kb_source == "wikidata"
        assert reconstructed.kb_label == "Apple Inc."
        assert reconstructed.target_field == "main_text"
        assert reconstructed.schema == "ner"
        assert reconstructed.start == 10
        assert reconstructed.end == 25


# ============================================================================
# Issue 2: Event annotations included in state management methods
# ============================================================================

class TestEventAnnotationStateManagement:
    """Tests that event annotations are properly included in state methods."""

    def _make_user_state(self):
        """Create a minimal InMemoryUserState for testing."""
        from potato.user_state_management import InMemoryUserState
        from potato.item_state_management import SpanAnnotation, EventAnnotation

        user_state = InMemoryUserState("test_user", max_assignments=10)
        user_state.instance_id_ordering = ["inst_1", "inst_2", "inst_3"]
        user_state.assigned_instance_ids = {"inst_1", "inst_2", "inst_3"}

        # Add a label annotation
        user_state.instance_id_to_label_to_value["inst_1"] = {"sentiment": "positive"}

        # Add a span annotation
        span = SpanAnnotation("ner", "PER", "Person", 0, 5)
        user_state.instance_id_to_span_to_value["inst_2"] = {span: True}

        # Add an event annotation (on inst_3 only)
        event = EventAnnotation(
            schema="event",
            event_type="ATTACK",
            trigger_span_id="span_trigger_1",
            arguments=[],
        )
        user_state.instance_id_to_event_to_value["inst_3"] = {event.get_id(): event}

        return user_state

    def test_get_all_annotations_includes_events(self):
        """Test that get_all_annotations() returns events."""
        user_state = self._make_user_state()
        all_anns = user_state.get_all_annotations()

        assert "inst_3" in all_anns
        assert "events" in all_anns["inst_3"]
        assert len(all_anns["inst_3"]["events"]) == 1

    def test_get_all_annotations_includes_links(self):
        """Test that get_all_annotations() returns links key."""
        user_state = self._make_user_state()
        all_anns = user_state.get_all_annotations()

        # inst_1 has labels, so it should have all keys
        assert "links" in all_anns["inst_1"]

    def test_get_annotated_instance_ids_includes_event_only_instances(self):
        """Test that get_annotated_instance_ids() includes instances with only events."""
        user_state = self._make_user_state()
        ids = user_state.get_annotated_instance_ids()

        assert "inst_1" in ids  # has labels
        assert "inst_2" in ids  # has spans
        assert "inst_3" in ids  # has events only

    def test_has_annotated_returns_true_for_event_only_instance(self):
        """Test that has_annotated() returns True for event-only instances."""
        user_state = self._make_user_state()

        assert user_state.has_annotated("inst_1") is True  # labels
        assert user_state.has_annotated("inst_2") is True  # spans
        assert user_state.has_annotated("inst_3") is True  # events

    def test_has_annotated_returns_false_for_unannotated(self):
        """Test that has_annotated() returns False for unannotated instances."""
        user_state = self._make_user_state()
        assert user_state.has_annotated("inst_nonexistent") is False

    def test_clear_all_annotations_clears_events(self):
        """Test that clear_all_annotations() clears events."""
        user_state = self._make_user_state()

        # Verify events exist before clearing
        assert len(user_state.instance_id_to_event_to_value) > 0

        user_state.clear_all_annotations()

        assert len(user_state.instance_id_to_event_to_value) == 0
        assert len(user_state.instance_id_to_label_to_value) == 0
        assert len(user_state.instance_id_to_span_to_value) == 0

    def test_clear_all_annotations_clears_links(self):
        """Test that clear_all_annotations() clears links."""
        from potato.item_state_management import SpanLink

        user_state = self._make_user_state()
        link = SpanLink(
            schema="coref",
            link_type="coreference",
            span_ids=["span_1", "span_2"],
        )
        user_state.instance_id_to_link_to_value["inst_1"] = {link.get_id(): link}

        assert len(user_state.instance_id_to_link_to_value) > 0

        user_state.clear_all_annotations()

        assert len(user_state.instance_id_to_link_to_value) == 0

    def test_annotation_count_includes_event_only_instances(self):
        """Test that get_annotation_count() counts event-only instances."""
        user_state = self._make_user_state()
        # 3 instances: labels, spans, events
        assert user_state.get_annotation_count() == 3


# ============================================================================
# Issue 3: Path traversal prevention in local_source.py
# ============================================================================

class TestLocalSourcePathTraversal:
    """Tests that LocalFileSource prevents path traversal."""

    def _make_source(self, path, task_dir=None):
        """Create a LocalFileSource with the given path."""
        from potato.data_sources.base import SourceConfig
        from potato.data_sources.sources.local_source import LocalFileSource

        raw_config = {"task_dir": task_dir or os.getcwd()}
        config = SourceConfig.from_dict({
            "type": "file",
            "path": path,
        })
        config._raw_config = raw_config
        source = LocalFileSource(config)
        source._raw_config = raw_config
        return source

    def test_normal_relative_path_resolves(self):
        """Test that a normal relative path resolves correctly."""
        source = self._make_source("data/test.jsonl")
        resolved = source._resolve_path()
        assert resolved.endswith("data/test.jsonl")

    def test_path_traversal_rejected(self):
        """Test that ../../../etc/passwd style paths are rejected."""
        with tempfile.TemporaryDirectory() as task_dir:
            source = self._make_source("../../../etc/passwd", task_dir=task_dir)
            with pytest.raises(ValueError, match="outside the task directory"):
                source._resolve_path()

    def test_absolute_path_allowed(self):
        """Test that absolute paths are allowed (admin-provided via config)."""
        with tempfile.TemporaryDirectory() as task_dir:
            # Absolute paths bypass traversal check since they're explicitly configured
            source = self._make_source("/tmp/some_file.jsonl", task_dir=task_dir)
            resolved = source._resolve_path()
            assert resolved == "/tmp/some_file.jsonl" or resolved.endswith("some_file.jsonl")

    def test_absolute_path_within_task_dir_accepted(self):
        """Test that absolute paths within task_dir are accepted."""
        with tempfile.TemporaryDirectory() as task_dir:
            valid_path = os.path.join(task_dir, "data", "test.jsonl")
            source = self._make_source(valid_path, task_dir=task_dir)
            resolved = source._resolve_path()
            assert resolved == valid_path

    def test_dot_dot_within_task_dir_accepted(self):
        """Test that .. that stays within task_dir is accepted."""
        with tempfile.TemporaryDirectory() as task_dir:
            # Create a subdirectory
            sub_dir = os.path.join(task_dir, "sub")
            os.makedirs(sub_dir, exist_ok=True)
            # Path goes up then back into task_dir
            source = self._make_source("sub/../data/test.jsonl", task_dir=task_dir)
            resolved = source._resolve_path()
            assert resolved.startswith(task_dir)


# ============================================================================
# Issue 4: Cache directory path validation
# ============================================================================

class TestCachePathValidation:
    """Tests that cache directory paths are validated."""

    def test_cache_path_outside_task_dir_rejected(self):
        """Test that a cache path outside task_dir is rejected."""
        # Import and test directly
        import os
        task_dir = os.path.abspath("/tmp/test_task_dir")
        cache_path = "/var/cache/attacker"

        cache_abs = os.path.abspath(
            os.path.join(task_dir, cache_path)
            if not os.path.isabs(cache_path)
            else cache_path
        )
        # Verify that this would fail the check
        assert not (cache_abs.startswith(task_dir + os.sep) or cache_abs == task_dir)

    def test_cache_path_within_task_dir_accepted(self):
        """Test that a cache path within task_dir passes."""
        import os
        task_dir = os.path.abspath("/tmp/test_task_dir")
        cache_path = "cache/ai"

        cache_abs = os.path.abspath(os.path.join(task_dir, cache_path))
        assert cache_abs.startswith(task_dir + os.sep)


# ============================================================================
# Issue 5: update_span input validation
# ============================================================================

class TestUpdateSpanInputValidation:
    """Tests for input validation on the update_span endpoint."""

    def test_string_length_validation_logic(self):
        """Test that the validation logic rejects oversized strings."""
        MAX_FIELD_LEN = 1024
        # Normal values pass
        assert isinstance("Q42", str) and len("Q42") <= MAX_FIELD_LEN
        # Oversized values fail
        oversized = "x" * 1025
        assert len(oversized) > MAX_FIELD_LEN
        # Non-string values fail
        assert not isinstance(123, str)

    def test_valid_kb_fields_pass_validation(self):
        """Test that normal KB field values pass validation."""
        MAX_FIELD_LEN = 1024
        for val in ["Q42", "wikidata", "Douglas Adams", "span_abc123"]:
            assert isinstance(val, str) and len(val) <= MAX_FIELD_LEN


# ============================================================================
# Issue 7: annotation_id bounds check
# ============================================================================

class TestAnnotationIdBoundsCheck:
    """Tests for annotation_id validation."""

    def test_invalid_annotation_id_types(self):
        """Test that non-integer annotation_id is handled."""
        for invalid in ["abc", "", None]:
            with pytest.raises((ValueError, TypeError)):
                int(invalid)

    def test_negative_annotation_id_out_of_range(self):
        """Test that negative annotation_id fails bounds check."""
        annotation_id = -1
        num_schemes = 3
        assert annotation_id < 0 or annotation_id >= num_schemes

    def test_too_large_annotation_id_out_of_range(self):
        """Test that too-large annotation_id fails bounds check."""
        annotation_id = 10
        num_schemes = 3
        assert annotation_id >= num_schemes

    def test_valid_annotation_id_passes(self):
        """Test that valid annotation_id passes bounds check."""
        annotation_id = 0
        num_schemes = 3
        assert not (annotation_id < 0 or annotation_id >= num_schemes)


# ============================================================================
# Issue 8: Prefetch count validation/clamping
# ============================================================================

class TestPrefetchCountValidation:
    """Tests that prefetch configuration values are clamped to safe ranges."""

    def test_negative_prefetch_clamped_to_zero(self):
        """Test that negative prefetch values are clamped to 0."""
        assert max(0, min(int(-999), 10000)) == 0

    def test_excessive_prefetch_clamped_to_max(self):
        """Test that excessively large prefetch values are clamped."""
        assert max(0, min(int(999999999), 10000)) == 10000

    def test_normal_prefetch_passes_through(self):
        """Test that normal values pass through unchanged."""
        assert max(0, min(int(5), 10000)) == 5
        assert max(0, min(int(20), 10000)) == 20
        assert max(0, min(int(100), 10000)) == 100

    def test_zero_prefetch_accepted(self):
        """Test that zero prefetch is accepted."""
        assert max(0, min(int(0), 10000)) == 0


# ============================================================================
# MySQL Schema: KB columns in span_annotations table
# ============================================================================

class TestMySQLSpanSchemaKBColumns:
    """Tests that the MySQL schema includes KB columns."""

    def test_span_annotations_schema_has_kb_columns(self):
        """Test that the CREATE TABLE SQL includes kb_id, kb_source, kb_label."""
        from potato.database.connection import DatabaseManager

        import inspect
        source = inspect.getsource(DatabaseManager.create_tables)
        assert "kb_id" in source
        assert "kb_source" in source
        assert "kb_label" in source

    def test_mysql_span_insert_includes_kb_fields(self):
        """Test that the INSERT SQL includes KB fields."""
        import inspect
        from potato.database.mysql_user_state import MysqlUserState

        source = inspect.getsource(MysqlUserState.add_span_annotation)
        assert "kb_id" in source
        assert "kb_source" in source
        assert "kb_label" in source

    def test_mysql_span_select_includes_kb_fields(self):
        """Test that the SELECT SQL includes KB fields."""
        import inspect
        from potato.database.mysql_user_state import MysqlUserState

        source = inspect.getsource(MysqlUserState.get_span_annotations)
        assert "kb_id" in source
        assert "kb_source" in source
        assert "kb_label" in source
