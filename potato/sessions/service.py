"""
Sessions service.

Session detection (reusing the cases auto-detect machinery under a
namespaced project so QDA cases and sessions coexist), session-level
scheme discovery, cross-annotator aggregates, and the
``session_annotations.jsonl`` export writer.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Item-data keys scanned, in priority order, when no explicit
#: ``sessions.key`` is configured. Matches what the langfuse poller and
#: trace converters emit.
DEFAULT_SESSION_KEYS = ("session_id", "thread_id", "conversation_id")

#: Schema types scoreable at session level. Mirrors the turn-level set:
#: compact value-carrying widgets; complex interactive schemas (span,
#: image_annotation, ...) stay per-instance.
SESSION_LEVEL_SUPPORTED_TYPES = {
    "radio",
    "multiselect",
    "likert",
    "slider",
    "select",
    "text",
    "number",
}


def sessions_enabled(config: Dict[str, Any]) -> bool:
    return bool((config.get("sessions") or {}).get("enabled"))


def sessions_project(config: Dict[str, Any]) -> str:
    """Cases-store namespace for sessions — separate from QDA cases so
    one instance can belong to both a participant case and a session."""
    project = config.get("annotation_task_name") or "default"
    return f"{project}::sessions"


def is_session_level_scheme(scheme: Dict[str, Any]) -> bool:
    return bool(scheme.get("session_level"))


def get_session_level_schemes(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """All session-level annotation schemes (top-level or phase-based)."""
    schemes: List[Dict[str, Any]] = []
    if "annotation_schemes" in config:
        schemes = list(config.get("annotation_schemes") or [])
    elif "phases" in config:
        phases = config["phases"]
        iterable = phases if isinstance(phases, list) else [
            p for name, p in phases.items()
            if name != "order" and isinstance(p, dict)
        ]
        for phase in iterable:
            schemes.extend(phase.get("annotation_schemes", []) or [])
    return [s for s in schemes
            if isinstance(s, dict) and is_session_level_scheme(s)]


def init_sessions_from_config(config: Dict[str, Any]) -> Dict[str, int]:
    """Server-start entry point: group loaded items into sessions by
    their session key. No-op (returns zeros) when sessions are disabled.
    Idempotent — safe to re-run on ingestion."""
    if not sessions_enabled(config):
        return {"cases": 0, "assigned": 0}

    sessions_cfg = config.get("sessions") or {}
    task_dir = config.get("task_dir", ".")
    explicit_key = sessions_cfg.get("key")
    attribute_keys = sessions_cfg.get("attributes") or []

    keys = (explicit_key,) if explicit_key else DEFAULT_SESSION_KEYS

    from potato.item_state_management import get_item_state_manager
    ism = get_item_state_manager()
    items: List[Dict[str, Any]] = []
    for iid in ism.get_instance_ids():
        data = ism.get_item(iid).get_data()
        if not isinstance(data, dict):
            continue
        row = dict(data)
        # Session ids live either top-level or under metadata (langfuse
        # poller, trace converters). Lift the first match into a synthetic
        # field so auto_detect groups on one key even when items mix
        # session_id / thread_id.
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        for k in keys:
            v = row.get(k, meta.get(k))
            if v is not None and str(v).strip() != "":
                row["__session__"] = str(v)
                break
        row.setdefault("id", str(iid))
        items.append(row)

    from potato.cases import auto_detect
    result = auto_detect(
        task_dir,
        project=sessions_project(config),
        items=items,
        case_key="__session__",
        attribute_keys=attribute_keys,
    )
    if result["cases"]:
        logger.info("Sessions: %d session(s), %d trace(s) grouped",
                    result["cases"], result["assigned"])
    return result


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

def session_aggregates(
    annotations: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Aggregate one session's annotations across annotators.

    Args:
        annotations: rows from ``annotations_for_case`` (value already
            JSON-decoded to ``{"value": x}`` / ``{"values": [...]}``)

    Returns::

        {schema: {"n_annotators": int, "mean": float | None,
                  "value_counts": {label: int}}}
    """
    out: Dict[str, Dict[str, Any]] = {}
    for row in annotations:
        schema = row["schema"]
        value = row.get("value") or {}
        stats = out.setdefault(schema, {
            "n_annotators": 0, "_numeric": [], "value_counts": {},
        })
        stats["n_annotators"] += 1
        values = value.get("values")
        if values is None and "value" in value:
            values = [value["value"]]
        for v in values or []:
            num = _as_number(v)
            if num is not None:
                stats["_numeric"].append(num)
            else:
                key = str(v)
                stats["value_counts"][key] = stats["value_counts"].get(key, 0) + 1
    for stats in out.values():
        numeric = stats.pop("_numeric")
        stats["mean"] = (sum(numeric) / len(numeric)) if numeric else None
    return out


def _as_number(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def write_session_export(config: Dict[str, Any]) -> Optional[str]:
    """Rewrite ``<output_annotation_dir>/session_annotations.jsonl`` from
    the current case_annotations state. Called after every save (the
    table is small); best-effort — failures log but never break a save.

    Returns the written path, or None when nothing was written.
    """
    try:
        task_dir = config.get("task_dir", ".")
        out_dir = config.get("output_annotation_dir", "annotation_output")
        if not os.path.isabs(out_dir):
            out_dir = os.path.join(task_dir, out_dir)

        from potato.cases import store as case_store
        from potato.cases import annotations as case_annos
        project = sessions_project(config)

        lines = []
        for row in case_annos.annotations_for_project(task_dir, project):
            lines.append(json.dumps({
                "session": row.get("case_name"),
                "case_id": row["case_id"],
                "annotator": row["annotator"],
                "schema": row["schema"],
                "value": row.get("value"),
                "updated_at": row.get("updated_at"),
                "instance_ids": case_store.instances_for_case(
                    task_dir, row["case_id"]),
            }))
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "session_annotations.jsonl")
        with open(path, "w") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        return path
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("session export skipped: %s", e)
        return None
