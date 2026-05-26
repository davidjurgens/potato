"""
Codebook storage (universal).

SQLite-backed CRUD over `codes` and `annotation_codes` in
`<task_dir>/project.sqlite` via the universal persistence layer. No
business rules live here (no cycle checks, no permissions, no cache
invalidation) — that is the service layer's job. This module only
persists rows.

A *code* is a (possibly nested) label in a project's codebook. An
*annotation_code* links a stored annotation to a code, optionally with a
time span (`started_at`/`ended_at`) for temporal / agentic-trace coding.
Universal: usable in standard annotation, solo mode, and QDA mode.

Design notes:
- `parent_id` is TEXT NOT NULL DEFAULT '' where '' means "root". Using a
  sentinel instead of NULL lets `UNIQUE(project, parent_id, name)`
  actually prevent duplicate sibling names at the root too (SQLite
  treats NULLs as distinct in UNIQUE constraints).
- No SQL foreign keys (consistent with the memos store): the service
  layer enforces parent existence, cycle-freedom, and recursive delete.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration

ROOT = ""  # sentinel parent_id for top-level codes

_CODEBOOK_MIGRATION = Migration(
    name="0001_codebook",
    sql="""
    CREATE TABLE IF NOT EXISTS codes (
        id          TEXT PRIMARY KEY,
        project     TEXT NOT NULL,
        name        TEXT NOT NULL,
        color       TEXT,
        parent_id   TEXT NOT NULL DEFAULT '',
        sort_order  INTEGER NOT NULL DEFAULT 0,
        created_by  TEXT NOT NULL,
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL,
        UNIQUE (project, parent_id, name)
    );
    CREATE INDEX IF NOT EXISTS idx_codes_project ON codes (project);
    CREATE INDEX IF NOT EXISTS idx_codes_parent
        ON codes (project, parent_id);

    CREATE TABLE IF NOT EXISTS annotation_codes (
        annotation_id TEXT NOT NULL,
        code_id       TEXT NOT NULL,
        project       TEXT NOT NULL,
        created_by    TEXT NOT NULL,
        started_at    REAL,
        ended_at      REAL,
        PRIMARY KEY (annotation_id, code_id)
    );
    CREATE INDEX IF NOT EXISTS idx_anncodes_code
        ON annotation_codes (project, code_id);
    CREATE INDEX IF NOT EXISTS idx_anncodes_ann
        ON annotation_codes (annotation_id);
    """,
)

register_migration(_CODEBOOK_MIGRATION)


def _db(task_dir: str):
    """Connection guaranteeing the codebook migration is registered.

    register_migration is idempotent, so this is a no-op normally; it
    makes the store robust if a test helper (clear_migrations) wiped the
    process-global registry before this task_dir's first get_db().
    """
    register_migration(_CODEBOOK_MIGRATION)
    return get_db(task_dir)


def _ensure_temporal_schema() -> None:
    """Guarantee the Phase 2 (C) append-only columns/tables exist before
    any link read/write that depends on `invalidated_at`. Lazy import
    avoids a module-load cycle (changelog imports this module). The
    0003 migration is additive (nullable cols + new tables), so this is
    safe even for callers that only registered 0001."""
    from potato.codebook.changelog import _CHANGE_MIGRATION
    from potato.codebook.revision import (
        _REVISION_MIGRATION, _CODES_REV_MIGRATION)
    register_migration(_REVISION_MIGRATION)
    register_migration(_CODES_REV_MIGRATION)
    register_migration(_CHANGE_MIGRATION)


# ---- codes ---------------------------------------------------------------

def insert_code(
    task_dir: str,
    *,
    project: str,
    name: str,
    created_by: str,
    color: Optional[str] = None,
    parent_id: str = ROOT,
    sort_order: int = 0,
    code_id: Optional[str] = None,
    created_revision: int = 0,
) -> Dict[str, Any]:
    """Insert one code row and return it. `code_id` lets the init CLI
    supply a deterministic id; otherwise a random uuid4 is used.
    `created_revision` records the codebook revision the code first
    appeared in (for provenance / the review worklist)."""
    cid = code_id or uuid.uuid4().hex
    now = time.time()
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO codes
           (id, project, name, color, parent_id, sort_order,
            created_by, created_at, updated_at, created_revision)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cid, project, name, color, parent_id, sort_order,
         created_by, now, now, created_revision),
    )
    conn.commit()
    return get_code(task_dir, cid)


def get_code(task_dir: str, code_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM codes WHERE id = ?", (code_id,)
    ).fetchone()
    return dict(row) if row else None


def find_code(
    task_dir: str, project: str, parent_id: str, name: str
) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        """SELECT * FROM codes
           WHERE project = ? AND parent_id = ? AND name = ?""",
        (project, parent_id, name),
    ).fetchone()
    return dict(row) if row else None


def list_codes(task_dir: str, project: str) -> List[Dict[str, Any]]:
    rows = _db(task_dir).execute(
        """SELECT * FROM codes WHERE project = ?
           ORDER BY parent_id ASC, sort_order ASC, name ASC""",
        (project,),
    ).fetchall()
    return [dict(r) for r in rows]


def children_of(
    task_dir: str, project: str, parent_id: str
) -> List[Dict[str, Any]]:
    rows = _db(task_dir).execute(
        """SELECT * FROM codes WHERE project = ? AND parent_id = ?
           ORDER BY sort_order ASC, name ASC""",
        (project, parent_id),
    ).fetchall()
    return [dict(r) for r in rows]


def update_code(
    task_dir: str,
    code_id: str,
    *,
    name: Optional[str] = None,
    color: Optional[str] = None,
    parent_id: Optional[str] = None,
    sort_order: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    sets, params = [], []
    if name is not None:
        sets.append("name = ?"); params.append(name)
    if color is not None:
        sets.append("color = ?"); params.append(color)
    if parent_id is not None:
        sets.append("parent_id = ?"); params.append(parent_id)
    if sort_order is not None:
        sets.append("sort_order = ?"); params.append(sort_order)
    if not sets:
        return get_code(task_dir, code_id)
    sets.append("updated_at = ?"); params.append(time.time())
    params.append(code_id)
    conn = _db(task_dir)
    conn.execute(f"UPDATE codes SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    return get_code(task_dir, code_id)


def delete_codes(task_dir: str, code_ids: List[str]) -> int:
    """Delete the given codes and their annotation_codes links. The
    service computes the full subtree; this just executes the delete."""
    if not code_ids:
        return 0
    qs = ",".join("?" * len(code_ids))
    conn = _db(task_dir)
    conn.execute(
        f"DELETE FROM annotation_codes WHERE code_id IN ({qs})", code_ids)
    cur = conn.execute(
        f"DELETE FROM codes WHERE id IN ({qs})", code_ids)
    conn.commit()
    return cur.rowcount


# ---- annotation_codes ----------------------------------------------------

def link_annotation(
    task_dir: str,
    *,
    project: str,
    annotation_id: str,
    code_id: str,
    created_by: str,
    started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
) -> None:
    conn = _db(task_dir)
    conn.execute(
        """INSERT OR REPLACE INTO annotation_codes
           (annotation_id, code_id, project, created_by,
            started_at, ended_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (annotation_id, code_id, project, created_by,
         started_at, ended_at),
    )
    conn.commit()


def unlink_annotation(
    task_dir: str, annotation_id: str, code_id: str
) -> bool:
    conn = _db(task_dir)
    cur = conn.execute(
        """DELETE FROM annotation_codes
           WHERE annotation_id = ? AND code_id = ?""",
        (annotation_id, code_id),
    )
    conn.commit()
    return cur.rowcount > 0


def codes_for_annotation(
    task_dir: str, annotation_id: str
) -> List[Dict[str, Any]]:
    # THE single load-bearing temporal reader: only LIVE links, and
    # never an archived (e.g. merged-away) code.
    _ensure_temporal_schema()
    rows = _db(task_dir).execute(
        """SELECT ac.code_id, ac.started_at, ac.ended_at,
                  ac.created_by, c.name, c.color, c.parent_id
           FROM annotation_codes ac
           JOIN codes c ON c.id = ac.code_id
           WHERE ac.annotation_id = ?
             AND ac.invalidated_at IS NULL
             AND c.archived_at IS NULL
           ORDER BY c.name ASC""",
        (annotation_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- Phase 2 (C): append-only retroactive primitives --------------------

def affected_annotation_ids(
    task_dir: str, project: str, code_id: str,
    created_by: Optional[str] = None,
) -> List[str]:
    """annotation_ids with a LIVE link to `code_id` (optionally only
    those created by `created_by` — the split-by-annotator selector)."""
    _ensure_temporal_schema()
    q = ("SELECT DISTINCT annotation_id FROM annotation_codes "
         "WHERE project = ? AND code_id = ? AND invalidated_at IS NULL")
    p: List[Any] = [project, code_id]
    if created_by is not None:
        q += " AND created_by = ?"
        p.append(created_by)
    rows = _db(task_dir).execute(q, p).fetchall()
    return [r["annotation_id"] for r in rows]


def get_link(
    task_dir: str, annotation_id: str, code_id: str
) -> Optional[Dict[str, Any]]:
    _ensure_temporal_schema()
    row = _db(task_dir).execute(
        """SELECT * FROM annotation_codes
           WHERE annotation_id = ? AND code_id = ?""",
        (annotation_id, code_id),
    ).fetchone()
    return dict(row) if row else None


def invalidate_links(
    task_dir: str, *, project: str, code_id: str, change_id: str,
    created_by: Optional[str] = None,
) -> int:
    """Mark live links to `code_id` superseded (append-only — never
    DELETE). Optional `created_by` scopes to one annotator (split)."""
    _ensure_temporal_schema()
    q = ("UPDATE annotation_codes SET invalidated_at = ?, "
         "invalidated_by_change = ? "
         "WHERE project = ? AND code_id = ? AND invalidated_at IS NULL")
    p: List[Any] = [time.time(), change_id, project, code_id]
    if created_by is not None:
        q += " AND created_by = ?"
        p.append(created_by)
    conn = _db(task_dir)
    cur = conn.execute(q, p)
    conn.commit()
    return cur.rowcount


def set_link_live(
    task_dir: str, *, project: str, annotation_id: str, code_id: str,
    created_by: str, started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
) -> None:
    """Make (annotation_id, code_id) a LIVE link. Idempotent against the
    PK(annotation_id, code_id): if the row exists (live or invalidated)
    it is reactivated rather than duplicated/clobbered — this is how a
    merge stays correct when the annotation is already on the target."""
    _ensure_temporal_schema()
    conn = _db(task_dir)
    cur = conn.execute(
        """UPDATE annotation_codes
           SET invalidated_at = NULL, invalidated_by_change = NULL
           WHERE annotation_id = ? AND code_id = ?""",
        (annotation_id, code_id),
    )
    if cur.rowcount == 0:
        conn.execute(
            """INSERT INTO annotation_codes
               (annotation_id, code_id, project, created_by,
                started_at, ended_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (annotation_id, code_id, project, created_by,
             started_at, ended_at),
        )
    conn.commit()


def archive_code(task_dir: str, code_id: str) -> bool:
    """Soft-archive a code (merged away): leaves the live palette + ICL
    prompt but the row and its history survive (append-only)."""
    _ensure_temporal_schema()
    conn = _db(task_dir)
    cur = conn.execute(
        "UPDATE codes SET archived_at = ?, updated_at = ? WHERE id = ?",
        (time.time(), time.time(), code_id),
    )
    conn.commit()
    return cur.rowcount > 0
