"""
Cases service.

get-or-create semantics, QDA auto-detection from item metadata, and the
attribute accessors the crosstab uses. Single write path so detection
and manual case creation share one audit trail.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from potato.cases import store

logger = logging.getLogger(__name__)

# Item-data keys QDA scans, in priority order, when no explicit
# `cases.key` is configured.
DEFAULT_CASE_KEYS = ("case_id", "participant_id", "respondent_id")


def get_or_create_case(
    task_dir: str, *, project: str, name: str,
    created_by: str = "cases",
) -> Dict[str, Any]:
    existing = store.find_case(task_dir, project, name)
    if existing is not None:
        return existing
    return store.insert_case(
        task_dir, project=project, name=name, created_by=created_by)


def list_cases(task_dir: str, project: str) -> List[Dict[str, Any]]:
    return store.list_cases(task_dir, project)


def set_attribute(
    task_dir: str, case_id: str, key: str, value: Optional[str]
) -> None:
    store.set_attribute(task_dir, case_id, key, value)


def attributes(task_dir: str, case_id: str) -> Dict[str, Any]:
    return store.attributes(task_dir, case_id)


def assign_instance(
    task_dir: str, *, project: str, instance_id: str, case_id: str
) -> None:
    store.assign_instance(
        task_dir, project=project, instance_id=instance_id,
        case_id=case_id)


def case_for_instance(
    task_dir: str, project: str, instance_id: str
) -> Optional[Dict[str, Any]]:
    return store.case_for_instance(task_dir, project, instance_id)


def attribute_for_instance(
    task_dir: str, project: str, instance_id: str, key: str
) -> Optional[str]:
    """Resolve a case-level attribute for the instance's case. Used by
    the crosstab so codes can be tabulated by participant-level
    metadata that does not live on each instance."""
    case = store.case_for_instance(task_dir, project, instance_id)
    if case is None:
        return None
    return store.attributes(task_dir, case["id"]).get(key)


def _detect_key(item: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
    for k in keys:
        v = item.get(k)
        if v is not None and str(v).strip() != "":
            return str(v)
    return None


def auto_detect(
    task_dir: str,
    *,
    project: str,
    items: Sequence[Dict[str, Any]],
    case_key: Optional[str] = None,
    attribute_keys: Optional[Sequence[str]] = None,
) -> Dict[str, int]:
    """Group items into cases by `case_key` (or the first present of
    DEFAULT_CASE_KEYS) and lift `attribute_keys` onto the case. Returns
    {"cases": n, "assigned": m}. Idempotent (get-or-create + upsert)."""
    keys = (case_key,) if case_key else DEFAULT_CASE_KEYS
    attr_keys = list(attribute_keys or [])
    cases_seen: Dict[str, str] = {}
    assigned = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        name = _detect_key(item, keys)
        if name is None:
            continue
        instance_id = str(
            item.get("id") or item.get("instance_id") or "")
        if not instance_id:
            continue

        cid = cases_seen.get(name)
        if cid is None:
            case = get_or_create_case(
                task_dir, project=project, name=name,
                created_by="cases-autodetect")
            cid = case["id"]
            cases_seen[name] = cid

        store.assign_instance(
            task_dir, project=project, instance_id=instance_id,
            case_id=cid)
        assigned += 1

        for ak in attr_keys:
            if ak in item and item[ak] is not None:
                store.set_attribute(task_dir, cid, ak, str(item[ak]))

    if cases_seen:
        logger.info(
            "Cases auto-detect: %d case(s), %d instance(s) assigned "
            "for project %r", len(cases_seen), assigned, project)
    return {"cases": len(cases_seen), "assigned": assigned}


def cases_enabled(config: Dict[str, Any]) -> bool:
    """Cases run when explicitly enabled, or implicitly under QDA mode
    (unless `cases.enabled: false` opts out)."""
    cases_cfg = config.get("cases") or {}
    if cases_cfg.get("enabled") is True:
        return True
    if cases_cfg.get("enabled") is False:
        return False
    return bool((config.get("qda_mode") or {}).get("enabled"))


def init_cases_from_config(config: Dict[str, Any]) -> Dict[str, int]:
    """Server-start entry point: auto-detect cases from loaded items.
    No-op (returns zeros) when cases are disabled or auto_detect is off.
    """
    if not cases_enabled(config):
        return {"cases": 0, "assigned": 0}
    cases_cfg = config.get("cases") or {}
    if cases_cfg.get("auto_detect") is False:
        return {"cases": 0, "assigned": 0}

    task_dir = config.get("task_dir", ".")
    project = config.get("annotation_task_name") or "default"
    case_key = cases_cfg.get("key")
    attribute_keys = cases_cfg.get("attributes") or []

    from potato.item_state_management import get_item_state_manager
    ism = get_item_state_manager()
    items: List[Dict[str, Any]] = []
    for iid in ism.get_instance_ids():
        data = ism.get_item(iid).get_data()
        if isinstance(data, dict):
            row = dict(data)
            row.setdefault("id", str(iid))
            items.append(row)

    return auto_detect(
        task_dir, project=project, items=items,
        case_key=case_key, attribute_keys=attribute_keys)
