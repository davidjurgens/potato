"""Tests for webhook event payload builders."""

import pytest

from potato.webhooks.events import (
    ALL_EVENTS,
    ANNOTATION_CREATED,
    ANNOTATION_UPDATED,
    ITEM_FULLY_ANNOTATED,
    TASK_COMPLETED,
    USER_PHASE_COMPLETED,
    QUALITY_ATTENTION_CHECK_FAILED,
    build_annotation_payload,
    build_item_fully_annotated_payload,
    build_task_completed_payload,
    build_phase_completed_payload,
    build_attention_check_failed_payload,
)


class TestEventConstants:
    def test_all_events_list_complete(self):
        expected = {
            ANNOTATION_CREATED,
            ANNOTATION_UPDATED,
            ITEM_FULLY_ANNOTATED,
            TASK_COMPLETED,
            USER_PHASE_COMPLETED,
            QUALITY_ATTENTION_CHECK_FAILED,
        }
        assert set(ALL_EVENTS) == expected

    def test_event_names_are_dotted(self):
        for event in ALL_EVENTS:
            assert "." in event, f"Event {event} should use dotted notation"


class TestAnnotationPayload:
    def test_structure(self):
        p = build_annotation_payload(
            ANNOTATION_CREATED, "user1", "item_42", {"label": "pos"}
        )
        assert p["event"] == ANNOTATION_CREATED
        assert "timestamp" in p
        assert p["data"]["user_id"] == "user1"
        assert p["data"]["instance_id"] == "item_42"
        assert p["data"]["annotations"] == {"label": "pos"}

    def test_schema_name_optional(self):
        p = build_annotation_payload(
            ANNOTATION_UPDATED, "u", "i", {}, schema_name="sentiment"
        )
        assert p["data"]["schema_name"] == "sentiment"


class TestItemFullyAnnotatedPayload:
    def test_structure(self):
        p = build_item_fully_annotated_payload("item_1", 3, 3)
        assert p["event"] == ITEM_FULLY_ANNOTATED
        assert p["data"]["instance_id"] == "item_1"
        assert p["data"]["annotator_count"] == 3
        assert p["data"]["required_count"] == 3


class TestTaskCompletedPayload:
    def test_structure(self):
        p = build_task_completed_payload("user_x", 50)
        assert p["event"] == TASK_COMPLETED
        assert p["data"]["user_id"] == "user_x"
        assert p["data"]["total_annotations"] == 50


class TestPhaseCompletedPayload:
    def test_structure(self):
        p = build_phase_completed_payload("user_y", "training", "annotation")
        assert p["event"] == USER_PHASE_COMPLETED
        assert p["data"]["user_id"] == "user_y"
        assert p["data"]["completed_phase"] == "training"
        assert p["data"]["next_phase"] == "annotation"

    def test_next_phase_optional(self):
        p = build_phase_completed_payload("u", "done")
        assert p["data"]["next_phase"] is None


class TestAttentionCheckFailedPayload:
    def test_structure(self):
        p = build_attention_check_failed_payload(
            "user_z", "attn_1", "Wrong answer", blocked=True
        )
        assert p["event"] == QUALITY_ATTENTION_CHECK_FAILED
        assert p["data"]["user_id"] == "user_z"
        assert p["data"]["instance_id"] == "attn_1"
        assert p["data"]["message"] == "Wrong answer"
        assert p["data"]["blocked"] is True

    def test_defaults(self):
        p = build_attention_check_failed_payload("u", "i")
        assert p["data"]["message"] is None
        assert p["data"]["blocked"] is False
