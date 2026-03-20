"""
Webhook Event Types and Payload Builders

Defines the canonical event types and helper functions to build
well-structured payloads for each event.
"""

import datetime

# Event type constants
ANNOTATION_CREATED = "annotation.created"
ANNOTATION_UPDATED = "annotation.updated"
ITEM_FULLY_ANNOTATED = "item.fully_annotated"
TASK_COMPLETED = "task.completed"
USER_PHASE_COMPLETED = "user.phase_completed"
QUALITY_ATTENTION_CHECK_FAILED = "quality.attention_check_failed"

ALL_EVENTS = [
    ANNOTATION_CREATED,
    ANNOTATION_UPDATED,
    ITEM_FULLY_ANNOTATED,
    TASK_COMPLETED,
    USER_PHASE_COMPLETED,
    QUALITY_ATTENTION_CHECK_FAILED,
]


def _now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"


def build_annotation_payload(event_type, user_id, instance_id, annotations,
                              schema_name=None):
    """Build payload for annotation.created / annotation.updated."""
    return {
        "event": event_type,
        "timestamp": _now_iso(),
        "data": {
            "user_id": user_id,
            "instance_id": instance_id,
            "annotations": annotations,
            "schema_name": schema_name,
        },
    }


def build_item_fully_annotated_payload(instance_id, annotator_count,
                                        required_count):
    """Build payload for item.fully_annotated."""
    return {
        "event": ITEM_FULLY_ANNOTATED,
        "timestamp": _now_iso(),
        "data": {
            "instance_id": instance_id,
            "annotator_count": annotator_count,
            "required_count": required_count,
        },
    }


def build_task_completed_payload(user_id, total_annotations):
    """Build payload for task.completed."""
    return {
        "event": TASK_COMPLETED,
        "timestamp": _now_iso(),
        "data": {
            "user_id": user_id,
            "total_annotations": total_annotations,
        },
    }


def build_phase_completed_payload(user_id, phase_name, next_phase=None):
    """Build payload for user.phase_completed."""
    return {
        "event": USER_PHASE_COMPLETED,
        "timestamp": _now_iso(),
        "data": {
            "user_id": user_id,
            "completed_phase": phase_name,
            "next_phase": next_phase,
        },
    }


def build_attention_check_failed_payload(user_id, instance_id, message=None,
                                          blocked=False):
    """Build payload for quality.attention_check_failed."""
    return {
        "event": QUALITY_ATTENTION_CHECK_FAILED,
        "timestamp": _now_iso(),
        "data": {
            "user_id": user_id,
            "instance_id": instance_id,
            "message": message,
            "blocked": blocked,
        },
    }
