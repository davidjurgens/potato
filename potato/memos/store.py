"""
Memo storage (universal).

SQLite-backed CRUD over the `memos` table in `<task_dir>/project.sqlite`
via the universal persistence layer. No visibility/permission logic lives
here — that is the service layer's job. This module only persists rows.

A memo is a free-text note an annotator attaches to an instance, or to a
text selection within an instance (offset-anchored). Universal: usable in
standard annotation, solo mode, and QDA mode.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration

_MEMOS_MIGRATION = Migration(
    name="0001_memos",
    sql="""
    CREATE TABLE IF NOT EXISTS memos (
        id          TEXT PRIMARY KEY,
        project     TEXT NOT NULL,
        instance_id TEXT NOT NULL,
        anchor      TEXT,                -- NULL = instance-level; else JSON {start,end,field}
        body        TEXT NOT NULL,
        created_by  TEXT NOT NULL,
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL,
        visibility  TEXT NOT NULL DEFAULT 'private'
                    CHECK (visibility IN ('private', 'shared'))
    );
    CREATE INDEX IF NOT EXISTS idx_memos_instance
        ON memos (project, instance_id);
    CREATE INDEX IF NOT EXISTS idx_memos_author
        ON memos (project, created_by);
    """,
)

# Registered at import so the table exists on the first get_db() call.
register_migration(_MEMOS_MIGRATION)


def _db(task_dir: str):
    """Connection for the memos store, guaranteeing the migration is
    registered first. register_migration is idempotent, so this is a
    no-op in normal operation; it makes the store robust if a test
    helper (clear_migrations) wiped the process-global registry before
    the first get_db() for this task_dir opens the connection."""
    register_migration(_MEMOS_MIGRATION)
    return get_db(task_dir)


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    d["anchor"] = json.loads(d["anchor"]) if d["anchor"] else None
    return d


def create(
    task_dir: str,
    *,
    project: str,
    instance_id: str,
    body: str,
    created_by: str,
    anchor: Optional[Dict[str, Any]] = None,
    visibility: str = "private",
) -> Dict[str, Any]:
    """Insert a memo row and return it as a dict."""
    memo_id = uuid.uuid4().hex
    now = time.time()
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO memos
           (id, project, instance_id, anchor, body, created_by,
            created_at, updated_at, visibility)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            memo_id, project, instance_id,
            json.dumps(anchor) if anchor else None,
            body, created_by, now, now, visibility,
        ),
    )
    conn.commit()
    return get(task_dir, memo_id)


def get(task_dir: str, memo_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM memos WHERE id = ?", (memo_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_for_instance(
    task_dir: str, project: str, instance_id: str
) -> List[Dict[str, Any]]:
    """All memos on an instance (no visibility filtering — service does that)."""
    rows = _db(task_dir).execute(
        """SELECT * FROM memos
           WHERE project = ? AND instance_id = ?
           ORDER BY created_at ASC""",
        (project, instance_id),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update(
    task_dir: str,
    memo_id: str,
    *,
    body: Optional[str] = None,
    visibility: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Patch body and/or visibility; bumps updated_at. No-op fields ignored."""
    sets, params = [], []
    if body is not None:
        sets.append("body = ?")
        params.append(body)
    if visibility is not None:
        sets.append("visibility = ?")
        params.append(visibility)
    if not sets:
        return get(task_dir, memo_id)
    sets.append("updated_at = ?")
    params.append(time.time())
    params.append(memo_id)
    conn = _db(task_dir)
    conn.execute(f"UPDATE memos SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    return get(task_dir, memo_id)


def delete(task_dir: str, memo_id: str) -> bool:
    conn = _db(task_dir)
    cur = conn.execute("DELETE FROM memos WHERE id = ?", (memo_id,))
    conn.commit()
    return cur.rowcount > 0
