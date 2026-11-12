"""
Codebook content versioning — full snapshots + diff + restore support.

Every content save records one immutable `codebook_snapshot` row holding
the *post-state* of the affected scope (a code or a doc-level section):
its serialized markdown plus the structured blocks JSON. A scope's
timeline is the snapshot rows ordered by `created_at`; a diff is computed
between any two `snapshot_md` strings; a restore re-saves an older
snapshot's `blocks_json` through the normal mutation path (so restore is
itself audited and snapshotted — never a destructive rewind).

The table is created by `blocks._BLOCKS_MIGRATION` (0004). This module is
the typed CRUD + diff over it.
"""

from __future__ import annotations

import difflib
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from potato.persistence import get_db, register_migration
from potato.codebook.blocks import _BLOCKS_MIGRATION
from potato.codebook.markdown import blocks_to_markdown


def _db(task_dir: str):
    register_migration(_BLOCKS_MIGRATION)
    return get_db(task_dir)


def record_snapshot(
    task_dir: str, *,
    project: str,
    scope_kind: str,           # 'code' | 'section'
    scope_id: str,             # code_id or section name
    blocks: List[Dict[str, Any]],
    semantic: bool,
    revision: int,
    sem_revision: int,
    change_id: Optional[str] = None,
    actor: str,
    actor_kind: str = "human",
) -> str:
    """Persist the post-state of a scope after a content save. Returns id."""
    sid = uuid.uuid4().hex
    # Only the persisted block fields go into the snapshot (the parse-time
    # `classified` flag is a UI signal, not state).
    clean = [
        {
            "block_type": b.get("block_type") or "custom",
            "custom_label": b.get("custom_label"),
            "body_md": b.get("body_md") or "",
        }
        for b in blocks
    ]
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO codebook_snapshot
               (id, project, scope_kind, scope_id, snapshot_md, blocks_json,
                semantic, revision, sem_revision, change_id, actor,
                actor_kind, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sid, project, scope_kind, scope_id,
         blocks_to_markdown(clean), json.dumps(clean),
         1 if semantic else 0, revision, sem_revision, change_id,
         actor, actor_kind, time.time()),
    )
    conn.commit()
    return sid


def list_snapshots(
    task_dir: str, project: str, scope_kind: str, scope_id: str
) -> List[Dict[str, Any]]:
    """Newest-first timeline for a scope (metadata; not the full blocks)."""
    rows = _db(task_dir).execute(
        """SELECT id, scope_kind, scope_id, semantic, revision, sem_revision,
                  change_id, actor, actor_kind, created_at
           FROM codebook_snapshot
           WHERE project = ? AND scope_kind = ? AND scope_id = ?
           ORDER BY created_at DESC""",
        (project, scope_kind, scope_id),
    ).fetchall()
    return [dict(r) for r in rows]


def get_snapshot(task_dir: str, snapshot_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM codebook_snapshot WHERE id = ?", (snapshot_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["blocks"] = json.loads(d["blocks_json"])
    except Exception:
        d["blocks"] = []
    return d


def diff_markdown(old_md: str, new_md: str) -> List[str]:
    """Unified-diff hunks between two markdown strings (stdlib difflib)."""
    return list(difflib.unified_diff(
        (old_md or "").splitlines(),
        (new_md or "").splitlines(),
        fromfile="before", tofile="after", lineterm="",
    ))
