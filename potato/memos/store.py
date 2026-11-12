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

# Threads and issues. A side table rather than ALTER TABLE: SQLite has no
# "ADD COLUMN IF NOT EXISTS", so an ALTER that failed halfway could never be
# re-run, while CREATE ... IF NOT EXISTS is idempotent like every other
# migration here. A memo with no row in it is a plain top-level note.
#
#   parent_id   the thread's first memo, for a reply (NULL for a thread root)
#   status      NULL for a plain note; 'open' or 'resolved' for an issue
#   assignee    who is expected to resolve an issue
_THREADS_MIGRATION = Migration(
    name="0002_memo_threads",
    sql="""
    CREATE TABLE IF NOT EXISTS memo_threads (
        memo_id     TEXT PRIMARY KEY REFERENCES memos(id) ON DELETE CASCADE,
        parent_id   TEXT,
        status      TEXT CHECK (status IS NULL OR status IN ('open', 'resolved')),
        assignee    TEXT,
        resolved_by TEXT,
        resolved_at REAL
    );
    CREATE INDEX IF NOT EXISTS idx_memo_threads_parent ON memo_threads (parent_id);
    CREATE INDEX IF NOT EXISTS idx_memo_threads_status ON memo_threads (status);
    """,
)

# Who beyond the visibility rule may read a memo. Another side table, for the
# reason above and one more: rebuilding `memos` to widen its CHECK constraint
# would mean DROP TABLE, and with foreign keys on that cascades into
# memo_threads.
#
#   scope    'personal': the author alone, adjudicators included in "others"
#            (the row's visibility is stored as 'private' underneath);
#            'team': the members of team_id, for a live session's threads
#   team_id  the collaborative team a 'team' memo belongs to
_SCOPE_MIGRATION = Migration(
    name="0003_memo_scope",
    sql="""
    CREATE TABLE IF NOT EXISTS memo_scope (
        memo_id  TEXT PRIMARY KEY REFERENCES memos(id) ON DELETE CASCADE,
        scope    TEXT NOT NULL CHECK (scope IN ('personal', 'team')),
        team_id  TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_memo_scope_team ON memo_scope (team_id);
    """,
)

# Registered at import so the tables exist on the first get_db() call.
register_migration(_MEMOS_MIGRATION)
register_migration(_THREADS_MIGRATION)
register_migration(_SCOPE_MIGRATION)

_SELECT = """SELECT m.*, t.parent_id, t.status, t.assignee, t.resolved_by, t.resolved_at,
                    s.scope, s.team_id
             FROM memos m LEFT JOIN memo_threads t ON t.memo_id = m.id
                          LEFT JOIN memo_scope s ON s.memo_id = m.id"""

# The visibility the rest of the code sees for a personal memo. Stored as
# 'private' plus a scope row, so the column's CHECK constraint still holds.
PERSONAL = "personal"


def _db(task_dir: str):
    """Connection for the memos store, guaranteeing the migration is
    registered first. register_migration is idempotent, so this is a
    no-op in normal operation; it makes the store robust if a test
    helper (clear_migrations) wiped the process-global registry before
    the first get_db() for this task_dir opens the connection."""
    register_migration(_MEMOS_MIGRATION)
    register_migration(_THREADS_MIGRATION)
    register_migration(_SCOPE_MIGRATION)
    return get_db(task_dir)


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    d["anchor"] = json.loads(d["anchor"]) if d["anchor"] else None
    if d.get("scope") == PERSONAL:
        d["visibility"] = PERSONAL
    return d


def _write_scope(conn, memo_id: str, visibility: str,
                 team_id: Optional[str]) -> str:
    """Record the memo's scope and return the visibility to store on the row."""
    conn.execute("DELETE FROM memo_scope WHERE memo_id = ?", (memo_id,))
    if visibility == PERSONAL:
        conn.execute("INSERT INTO memo_scope (memo_id, scope, team_id) VALUES (?, ?, NULL)",
                     (memo_id, PERSONAL))
        return "private"
    if team_id:
        conn.execute("INSERT INTO memo_scope (memo_id, scope, team_id) VALUES (?, 'team', ?)",
                     (memo_id, team_id))
    return visibility


def create(
    task_dir: str,
    *,
    project: str,
    instance_id: str,
    body: str,
    created_by: str,
    anchor: Optional[Dict[str, Any]] = None,
    visibility: str = "private",
    parent_id: Optional[str] = None,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    team_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a memo row (and its thread and scope rows, if any) and return it.

    ``visibility='personal'`` stores a private row plus a personal scope row.
    """
    memo_id = uuid.uuid4().hex
    now = time.time()
    conn = _db(task_dir)
    stored_visibility = "private" if visibility == PERSONAL else visibility
    conn.execute(
        """INSERT INTO memos
           (id, project, instance_id, anchor, body, created_by,
            created_at, updated_at, visibility)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            memo_id, project, instance_id,
            json.dumps(anchor) if anchor else None,
            body, created_by, now, now, stored_visibility,
        ),
    )
    _write_scope(conn, memo_id, visibility, team_id)
    if parent_id or status or assignee:
        conn.execute(
            "INSERT INTO memo_threads (memo_id, parent_id, status, assignee) VALUES (?, ?, ?, ?)",
            (memo_id, parent_id, status, assignee),
        )
    conn.commit()
    return get(task_dir, memo_id)


def get(task_dir: str, memo_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        f"{_SELECT} WHERE m.id = ?", (memo_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_for_instance(
    task_dir: str, project: str, instance_id: str
) -> List[Dict[str, Any]]:
    """All memos on an instance (no visibility filtering — service does that)."""
    rows = _db(task_dir).execute(
        f"""{_SELECT}
           WHERE m.project = ? AND m.instance_id = ?
           ORDER BY m.created_at ASC""",
        (project, instance_id),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_issues(task_dir: str, project: str, status: Optional[str] = None,
                assignee: Optional[str] = None) -> List[Dict[str, Any]]:
    """Thread roots that are issues, across the project, newest first."""
    where, params = ["m.project = ?", "t.status IS NOT NULL", "t.parent_id IS NULL"], [project]
    if status:
        where.append("t.status = ?")
        params.append(status)
    if assignee:
        where.append("t.assignee = ?")
        params.append(assignee)
    rows = _db(task_dir).execute(
        f"{_SELECT} WHERE {' AND '.join(where)} ORDER BY m.created_at DESC", params,
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def set_thread(task_dir: str, memo_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """Set status / assignee / resolved_by / resolved_at on a thread root."""
    allowed = {"status", "assignee", "resolved_by", "resolved_at"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    conn = _db(task_dir)
    conn.execute("INSERT OR IGNORE INTO memo_threads (memo_id) VALUES (?)", (memo_id,))
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE memo_threads SET {sets} WHERE memo_id = ?",
                     list(fields.values()) + [memo_id])
    conn.execute("UPDATE memos SET updated_at = ? WHERE id = ?", (time.time(), memo_id))
    conn.commit()
    return get(task_dir, memo_id)


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
    conn = _db(task_dir)
    if visibility is not None:
        current = get(task_dir, memo_id) or {}
        sets.append("visibility = ?")
        params.append(_write_scope(conn, memo_id, visibility, current.get("team_id")))
    if not sets:
        return get(task_dir, memo_id)
    sets.append("updated_at = ?")
    params.append(time.time())
    params.append(memo_id)
    conn.execute(f"UPDATE memos SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    return get(task_dir, memo_id)


def delete(task_dir: str, memo_id: str) -> bool:
    """Delete a memo; deleting a thread's first memo deletes its replies."""
    conn = _db(task_dir)
    replies = [r[0] for r in conn.execute(
        "SELECT memo_id FROM memo_threads WHERE parent_id = ?", (memo_id,)).fetchall()]
    for reply in replies:
        conn.execute("DELETE FROM memo_threads WHERE memo_id = ?", (reply,))
        conn.execute("DELETE FROM memo_scope WHERE memo_id = ?", (reply,))
        conn.execute("DELETE FROM memos WHERE id = ?", (reply,))
    conn.execute("DELETE FROM memo_threads WHERE memo_id = ?", (memo_id,))
    conn.execute("DELETE FROM memo_scope WHERE memo_id = ?", (memo_id,))
    cur = conn.execute("DELETE FROM memos WHERE id = ?", (memo_id,))
    conn.commit()
    return cur.rowcount > 0
