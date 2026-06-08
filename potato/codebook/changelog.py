"""
Codebook change-provenance overlay (Phase 2 C).

A **separate** audit/overlay layer for retroactive codebook edits
(merge / split / rename / recolor / move / delete) and the LLM
propose -> human-confirm flow. It is deliberately NOT part of the
`codes` records: `Codebook.labels()` / `as_tree()` feed the ICL prompt
verbatim, so authorship / change history must never join into them
(open-question #2 resolution).

Two tables (own migration, universal project.sqlite):
- ``codebook_change`` — append-only event log: every retroactive op,
  who/what/old->new/when, with ``actor_kind`` (human|model). Generalises
  the additive-only ``revision.codes_added_since`` so the review
  worklist / banner can say "X merged into Y", not just "N codes added".
- ``codebook_proposal`` — pending model-proposed edits awaiting human
  confirmation (status pending|confirmed|rejected).

Plus the temporal columns that make retroactive edits **append-only**:
- ``annotation_codes.invalidated_at`` / ``invalidated_by_change`` —
  a superseded link is marked, never DELETEd (NULL = live). NOTE:
  ``started_at``/``ended_at`` already mean *elapsed time on a span /
  agentic trace* — they are NOT validity and must not be reused.
- ``codes.archived_at`` — a merged-away source code is archived (leaves
  the palette + ICL prompt) but its row and history survive.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration

_CHANGE_MIGRATION = Migration(
    name="0003_codebook_change_provenance",
    sql="""
    ALTER TABLE annotation_codes ADD COLUMN invalidated_at REAL;
    ALTER TABLE annotation_codes ADD COLUMN invalidated_by_change TEXT;
    ALTER TABLE codes ADD COLUMN archived_at REAL;

    CREATE TABLE IF NOT EXISTS codebook_change (
        id              TEXT PRIMARY KEY,
        project         TEXT NOT NULL,
        code_id         TEXT,
        related_code_id TEXT,
        op              TEXT NOT NULL,
        old_value       TEXT,
        new_value       TEXT,
        actor           TEXT NOT NULL,
        actor_kind      TEXT NOT NULL DEFAULT 'human',
        created_at      REAL NOT NULL,
        revision        INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_cbchange_proj
        ON codebook_change (project, created_at);

    CREATE TABLE IF NOT EXISTS codebook_proposal (
        id          TEXT PRIMARY KEY,
        project     TEXT NOT NULL,
        op          TEXT NOT NULL,
        payload     TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'pending',
        actor       TEXT NOT NULL,
        actor_kind  TEXT NOT NULL DEFAULT 'model',
        created_at  REAL NOT NULL,
        decided_by  TEXT,
        decided_at  REAL,
        change_id   TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_cbproposal_proj
        ON codebook_proposal (project, status, created_at);
    """,
)

# Defensive ordering: 0003 ALTERs `annotation_codes` and `codes`, so the
# 0001 CREATE and both 0002 ALTERs must register first regardless of
# import path (mirrors revision.py — import the Migration objects
# directly, not via package side effects, to avoid circular imports).
from potato.codebook.store import _CODEBOOK_MIGRATION as _CB_MIG
from potato.codebook.revision import (
    _REVISION_MIGRATION as _REV_MIG,
    _CODES_REV_MIGRATION as _CODES_REV_MIG,
)

register_migration(_CB_MIG)
register_migration(_REV_MIG)
register_migration(_CODES_REV_MIG)
register_migration(_CHANGE_MIGRATION)


def _db(task_dir: str):
    register_migration(_CHANGE_MIGRATION)
    return get_db(task_dir)


# ---- change log ----------------------------------------------------------

def log_change(
    task_dir: str, *, project: str, op: str, actor: str,
    actor_kind: str = "human", code_id: Optional[str] = None,
    related_code_id: Optional[str] = None,
    old_value: Optional[str] = None, new_value: Optional[str] = None,
    revision: int = 0,
) -> str:
    """Append one immutable change-log row; return its id."""
    cid = uuid.uuid4().hex
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO codebook_change
               (id, project, code_id, related_code_id, op, old_value,
                new_value, actor, actor_kind, created_at, revision)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cid, project, code_id, related_code_id, op, old_value,
         new_value, actor, actor_kind, time.time(), revision),
    )
    conn.commit()
    return cid


def changes_since(
    task_dir: str, project: str, revision: int
) -> List[Dict[str, Any]]:
    """Change-log rows recorded after `revision` — the non-additive
    counterpart to revision.codes_added_since, for the worklist/banner
    and the before->after delta view."""
    rows = _db(task_dir).execute(
        """SELECT id, code_id, related_code_id, op, old_value, new_value,
                  actor, actor_kind, created_at, revision
           FROM codebook_change
           WHERE project = ? AND revision > ?
           ORDER BY created_at ASC""",
        (project, revision),
    ).fetchall()
    return [dict(r) for r in rows]


def code_history(
    task_dir: str, project: str, code_id: str
) -> List[Dict[str, Any]]:
    """Full change history for a single code (newest last) — every edit
    that touched it, including the structured-field edits. Powers the
    per-code "version history" view."""
    rows = _db(task_dir).execute(
        """SELECT id, code_id, related_code_id, op, old_value, new_value,
                  actor, actor_kind, created_at, revision
           FROM codebook_change
           WHERE project = ? AND (code_id = ? OR related_code_id = ?)
           ORDER BY created_at ASC""",
        (project, code_id, code_id),
    ).fetchall()
    return [dict(r) for r in rows]


def all_changes(
    task_dir: str, project: str
) -> List[Dict[str, Any]]:
    rows = _db(task_dir).execute(
        """SELECT id, code_id, related_code_id, op, old_value, new_value,
                  actor, actor_kind, created_at, revision
           FROM codebook_change
           WHERE project = ?
           ORDER BY created_at ASC""",
        (project,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- proposals (model -> human-confirm) ---------------------------------

def record_proposal(
    task_dir: str, *, project: str, op: str, payload: Dict[str, Any],
    actor: str, actor_kind: str = "model",
) -> Dict[str, Any]:
    pid = uuid.uuid4().hex
    now = time.time()
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO codebook_proposal
               (id, project, op, payload, status, actor, actor_kind,
                created_at)
           VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (pid, project, op, json.dumps(payload), actor, actor_kind, now),
    )
    conn.commit()
    return get_proposal(task_dir, pid)


def get_proposal(task_dir: str, proposal_id: str) -> Optional[Dict]:
    row = _db(task_dir).execute(
        "SELECT * FROM codebook_proposal WHERE id = ?", (proposal_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["payload"] = json.loads(d["payload"])
    except Exception:
        pass
    return d


def list_proposals(
    task_dir: str, project: str, status: str = "pending"
) -> List[Dict[str, Any]]:
    rows = _db(task_dir).execute(
        """SELECT * FROM codebook_proposal
           WHERE project = ? AND status = ?
           ORDER BY created_at ASC""",
        (project, status),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"])
        except Exception:
            pass
        out.append(d)
    return out


def set_proposal_status(
    task_dir: str, proposal_id: str, *, status: str,
    decided_by: str, change_id: Optional[str] = None,
) -> bool:
    conn = _db(task_dir)
    cur = conn.execute(
        """UPDATE codebook_proposal
           SET status = ?, decided_by = ?, decided_at = ?, change_id = ?
           WHERE id = ? AND status = 'pending'""",
        (status, decided_by, time.time(), change_id, proposal_id),
    )
    conn.commit()
    return cur.rowcount > 0


def propose_change(
    task_dir: str, *, project: str, op: str, payload: Dict[str, Any],
    actor: str, actor_kind: str = "model",
) -> Dict[str, Any]:
    """Thin entry point for in-process (e.g. solo-mode LLM) producers
    that aren't going through the HTTP API. The contract is identical to
    POST /api/codebook/proposals."""
    return record_proposal(
        task_dir, project=project, op=op, payload=payload,
        actor=actor, actor_kind=actor_kind)
