"""
Single-select collapse for exports and repair.

Potato versions before the GH #167 fix could persist several labels for one
``radio``/``likert``/``confidence`` schema — one per option the annotator ever clicked.
This module resolves such a group back to the single answer the annotator settled on,
and is shared by the tabular exporters and ``potato repair-annotations`` so both use
identical logic.

Resolution order, best evidence first:

1. **Behavioral trail.** ``user_state.json`` carries
   ``instance_id_to_behavioral_data[*].annotation_changes``, each with a wall-clock
   ``timestamp``. The latest ``select`` for the schema names the winning label
   outright. Interaction tracking is unconditional, so this is available for most
   real studies.
2. **Persisted order.** Failing that, the last entry in the stored list.

The fallback is a heuristic and is reported as such. ``instance_id_to_label_to_value``
is a dict keyed by ``Label``, so its serialized order is *first-write* order, not
recency: a ``5 → 4 → 5`` revision persists as ``[5, 4]`` and the fallback would answer
``4``. Callers surface a warning whenever they have to rely on it.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Kept in sync with potato.server_utils.schema_exclusivity.NON_EXCLUSIVE_LABEL_NAMES.
#: Duplicated rather than imported so the export path stays usable without a loaded
#: server config.
EXEMPT_LABEL_NAMES = frozenset({"free_response"})

#: Annotation types whose options each get their own Label entry.
SINGLE_SELECT_TYPES = frozenset({"radio", "likert", "confidence"})


def single_select_schema_names(schemas: List[dict]) -> set:
    """Names of the single-select schemas in a config scheme list."""
    names = set()
    for scheme in schemas or []:
        if not isinstance(scheme, dict):
            continue
        if scheme.get("turn_level") or scheme.get("session_level"):
            continue
        if scheme.get("annotation_type") in SINGLE_SELECT_TYPES:
            name = scheme.get("name")
            if name:
                names.add(name)
    return names


def resolve_final_label(schema_name: str,
                        label_names: List[str],
                        changes: Optional[List[Dict[str, Any]]] = None
                        ) -> Tuple[Optional[str], str]:
    """Pick the label the annotator settled on.

    Args:
        schema_name: The schema being resolved.
        label_names: The stored label names, in persisted order.
        changes: ``annotation_changes`` dicts for the same instance/page, if available.

    Returns:
        ``(winning_label_name, method)`` where method is ``"single"`` (nothing to
        resolve), ``"behavioral"`` (decided from timestamps) or ``"order"``
        (heuristic fallback). Returns ``(None, "empty")`` for an empty group.
    """
    candidates = [n for n in label_names if n not in EXEMPT_LABEL_NAMES]
    if not candidates:
        return None, "empty"
    if len(candidates) == 1:
        return candidates[0], "single"

    if changes:
        selections = [
            c for c in changes
            if isinstance(c, dict)
            and c.get("schema_name") == schema_name
            and c.get("action") in ("select", "update")
            and c.get("label_name") in candidates
        ]
        if selections:
            latest = max(selections, key=lambda c: c.get("timestamp") or 0)
            return latest.get("label_name"), "behavioral"

    # Heuristic: last persisted entry. See module docstring for why this can be wrong.
    return candidates[-1], "order"


def collapse_labels(schema_name: str,
                    labels: Dict[str, Any],
                    changes: Optional[List[Dict[str, Any]]] = None
                    ) -> Tuple[Dict[str, Any], Optional[str], str]:
    """Reduce one schema's labels to the winning option plus any exempt labels.

    Returns:
        ``(collapsed_labels, winning_label_name, method)``. ``method`` is
        ``"none"`` when there was nothing to collapse.
    """
    label_names = list(labels.keys())
    non_exempt = [n for n in label_names if n not in EXEMPT_LABEL_NAMES]
    if len(non_exempt) <= 1:
        return dict(labels), (non_exempt[0] if non_exempt else None), "none"

    winner, method = resolve_final_label(schema_name, label_names, changes)
    collapsed = {n: v for n, v in labels.items() if n in EXEMPT_LABEL_NAMES}
    if winner is not None:
        collapsed[winner] = labels[winner]
    return collapsed, winner, method


def behavioral_changes(user_state: dict, instance_id: str) -> List[Dict[str, Any]]:
    """``annotation_changes`` recorded against one instance id, or an empty list."""
    bucket = (user_state.get("instance_id_to_behavioral_data") or {}).get(instance_id)
    if not isinstance(bucket, dict):
        return []
    changes = bucket.get("annotation_changes")
    return changes if isinstance(changes, list) else []


def phase_changes(user_state: dict, phase: str, page: str) -> List[Dict[str, Any]]:
    """``annotation_changes`` for one phase page.

    Every non-annotation page shares the ``__phase_page__`` bucket, so records are
    filtered by the ``phase``/``page`` fields stamped since the #167 fix. Records
    written by older versions carry neither field and cannot be attributed to a page;
    they are included unconditionally, so the caller must treat the result as
    best-effort evidence rather than proof.
    """
    out = []
    for bucket in (user_state.get("instance_id_to_behavioral_data") or {}).values():
        if not isinstance(bucket, dict):
            continue
        for change in bucket.get("annotation_changes") or []:
            if not isinstance(change, dict):
                continue
            c_phase, c_page = change.get("phase"), change.get("page")
            if c_phase is None and c_page is None:
                out.append(change)  # pre-#167 record, no phase tagging
            elif str(c_phase) == str(phase) and (c_page is None or str(c_page) == str(page)):
                out.append(change)
    return out
