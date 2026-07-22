"""
Human rationale notes captured during solo-mode validation and
disagreement resolution.

Annotators can attach a free-text note explaining *why* they picked a
label — during validation (`record_validation`) or when resolving a
human/LLM disagreement (`resolve_disagreement`). Both call sites used to
accept a `notes` argument and drop it on the floor. This module gives that
text somewhere durable to land, so it can later be mined for codebook
feedback (see `notes_feedback.py`).

SQLite-backed, same universal-persistence pattern as
`potato/codebook/changelog.py`: one small append-only table in the
project's shared `project.sqlite`.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration

_MIGRATION = Migration(
    name="0001_annotation_notes",
    sql="""
    CREATE TABLE IF NOT EXISTS annotation_notes (
        id          TEXT PRIMARY KEY,
        project     TEXT NOT NULL,
        instance_id TEXT NOT NULL,
        schema_name TEXT NOT NULL,
        note        TEXT NOT NULL,
        source      TEXT NOT NULL,
        actor       TEXT NOT NULL,
        created_at  REAL NOT NULL,
        label       TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_annotation_notes_proj
        ON annotation_notes (project, created_at);
    """,
)

register_migration(_MIGRATION)


def _db(task_dir: str):
    register_migration(_MIGRATION)
    return get_db(task_dir)


def save_note(
    task_dir: str,
    *,
    project: str,
    instance_id: str,
    schema_name: str,
    note: str,
    source: str,
    actor: str = "human",
    label: Optional[str] = None,
) -> Optional[str]:
    """Persist one rationale note. No-op (returns None) for blank notes so
    callers can invoke this unconditionally without an `if notes:` guard.
    ``label`` is the resolved/human label the note explains, when known —
    lets notes_feedback.py target the right code without re-deriving it."""
    note = (note or "").strip()
    if not note:
        return None
    nid = uuid.uuid4().hex
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO annotation_notes
               (id, project, instance_id, schema_name, note, source, actor,
                created_at, label)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (nid, project, instance_id, schema_name, note, source, actor,
         time.time(), label),
    )
    conn.commit()
    return nid


def notes_for_instance(
    task_dir: str, project: str, instance_id: str
) -> List[Dict[str, Any]]:
    rows = _db(task_dir).execute(
        """SELECT id, instance_id, schema_name, note, source, actor,
                  created_at, label
           FROM annotation_notes
           WHERE project = ? AND instance_id = ?
           ORDER BY created_at ASC""",
        (project, instance_id),
    ).fetchall()
    return [dict(r) for r in rows]


def recent_notes(
    task_dir: str, project: str, *, since: float = 0.0, limit: int = 200
) -> List[Dict[str, Any]]:
    """Notes recorded after `since` (unix time), newest last — feed for
    `notes_feedback.py`'s propose-from-notes pass."""
    rows = _db(task_dir).execute(
        """SELECT id, instance_id, schema_name, note, source, actor,
                  created_at, label
           FROM annotation_notes
           WHERE project = ? AND created_at > ?
           ORDER BY created_at ASC
           LIMIT ?""",
        (project, since, limit),
    ).fetchall()
    return [dict(r) for r in rows]
