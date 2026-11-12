"""
Shared progress-statistics computation.

Single source of truth for project-level and per-annotator progress numbers,
used by BOTH the admin dashboard overview and the (opt-in, read-only)
annotator-facing progress dashboard. Keeping one implementation avoids a second
copy of the math that could silently drift from the admin numbers.

Imports of the state managers are done lazily inside the functions to avoid
import-time circular dependencies with potato.flask_server.
"""

from typing import Any, Dict, Optional


def compute_project_progress() -> Dict[str, Any]:
    """
    Compute project-wide aggregate progress.

    Returns a dict with:
        total_items: number of items in the project
        items_with_annotations: items that have >=1 annotator
        completion_percentage: items_with_annotations / total_items * 100 (1 dp)
        total_annotations: total annotation count across all users
        active_annotators: count of users currently in the ANNOTATION phase
                           (a COUNT only — never names, for annotator-facing use)
    """
    from potato.flask_server import get_users, get_total_annotations
    from potato.item_state_management import get_item_state_manager
    from potato.user_state_management import get_user_state_manager

    usm = get_user_state_manager()
    ism = get_item_state_manager()

    users = get_users()
    total_annotations = get_total_annotations()

    active_annotators = 0
    for username in users:
        user_state = usm.get_user_state(username)
        if user_state and _phase_name(user_state) == "annotation":
            active_annotators += 1

    items = ism.items()
    total_items = len(items)
    items_with_annotations = 0
    total_assignments = 0
    for item in items:
        annotators = ism.get_annotators_for_item(item.get_id())
        if annotators:
            items_with_annotations += 1
            total_assignments += len(annotators)

    completion_percentage = (
        items_with_annotations / total_items * 100 if total_items > 0 else 0
    )

    return {
        "total_items": total_items,
        "items_with_annotations": items_with_annotations,
        "completion_percentage": round(completion_percentage, 1),
        "total_annotations": total_annotations,
        "active_annotators": active_annotators,
        "total_assignments": total_assignments,
    }


def compute_personal_progress(username: str) -> Dict[str, Any]:
    """
    Compute the requesting annotator's OWN progress only.

    Never reads or returns any other user's data.

    Returns a dict with:
        annotated: instances this user has annotated
        assigned: instances assigned to this user
        completion_percentage: annotated / assigned * 100 (1 dp)
    """
    from potato.user_state_management import get_user_state_manager

    usm = get_user_state_manager()
    user_state = usm.get_user_state(username)
    if not user_state:
        return {"annotated": 0, "assigned": 0, "completion_percentage": 0.0}

    assigned = user_state.get_assigned_instance_count()
    annotated = (
        user_state.get_annotation_count()
        if hasattr(user_state, "get_annotation_count")
        else len(user_state.get_annotated_instance_ids())
    )
    completion_percentage = (annotated / assigned * 100) if assigned > 0 else 0.0

    return {
        "annotated": annotated,
        "assigned": assigned,
        "completion_percentage": round(completion_percentage, 1),
    }


def _phase_name(user_state) -> Optional[str]:
    """Return the user's phase as a lowercase string, robust to enum format.

    See project memory project_solo_mode_phase_enum: phase .value may be an int
    (auto()) while .name is the canonical underscored string. Use .name.lower().
    """
    try:
        phase = user_state.get_phase()
    except Exception:
        return None
    name = getattr(phase, "name", None)
    if name is not None:
        return name.lower()
    return str(phase).lower()
