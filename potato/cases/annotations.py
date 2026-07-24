"""
Case-level annotations storage.

SQLite-backed CRUD over `case_annotations` in `<task_dir>/project.sqlite`.
One row per (case, annotator, schema); the value is a small JSON blob
(``{"value": x}`` or ``{"values": [...]}``) so every session-level schema
type shares one shape. Used by session-level scoring (a *session* is a
case in the ``<project>::sessions`` namespace) but deliberately generic —
QDA cases could adopt case-level annotation with zero schema changes.

No business rules here (the sessions service owns schema validation,
aggregation, and export).
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration

_CASE_ANNOTATIONS_MIGRATION = Migration(
    name="0002_case_annotations",
    sql="""
    CREATE TABLE IF NOT EXISTS case_annotations (
        case_id     TEXT NOT NULL,
        annotator   TEXT NOT NULL,
        schema      TEXT NOT NULL,
        value       TEXT,
        updated_at  REAL NOT NULL,
        PRIMARY KEY (case_id, annotator, schema)
    );
    CREATE INDEX IF NOT EXISTS idx_case_annos_case
        ON case_annotations (case_id);
    """,
)

register_migration(_CASE_ANNOTATIONS_MIGRATION)


def _db(task_dir: str):
    register_migration(_CASE_ANNOTATIONS_MIGRATION)
    return get_db(task_dir)


def set_annotation(
    task_dir: str, *, case_id: str, annotator: str, schema: str,
    value: Optional[Dict[str, Any]],
) -> None:
    """Upsert one (case, annotator, schema) annotation. ``value=None``
    (or an empty dict) deletes the row — a cleared widget leaves no
    stale score behind."""
    conn = _db(task_dir)
    if not value:
        conn.execute(
            """DELETE FROM case_annotations
               WHERE case_id = ? AND annotator = ? AND schema = ?""",
            (case_id, annotator, schema),
        )
    else:
        conn.execute(
            """INSERT OR REPLACE INTO case_annotations
               (case_id, annotator, schema, value, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (case_id, annotator, schema, json.dumps(value), time.time()),
        )
    conn.commit()


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["value"] = json.loads(d["value"]) if d["value"] else None
    except (ValueError, TypeError):
        d["value"] = None
    return d


def annotations_for_case(
    task_dir: str, case_id: str, annotator: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if annotator is None:
        rows = _db(task_dir).execute(
            "SELECT * FROM case_annotations WHERE case_id = ?",
            (case_id,),
        ).fetchall()
    else:
        rows = _db(task_dir).execute(
            """SELECT * FROM case_annotations
               WHERE case_id = ? AND annotator = ?""",
            (case_id, annotator),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def annotations_for_project(
    task_dir: str, project: str
) -> List[Dict[str, Any]]:
    """All case annotations for a project (joined with the case name),
    ordered stably for export."""
    rows = _db(task_dir).execute(
        """SELECT a.*, c.name AS case_name
           FROM case_annotations a
           JOIN cases c ON c.id = a.case_id
           WHERE c.project = ?
           ORDER BY c.name, a.annotator, a.schema""",
        (project,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]
