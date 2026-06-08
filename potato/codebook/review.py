"""
Codebook-change output review (significant-difference gating).

When a codebook edit changes what the model is told (a definition,
clarification, negative clarification, an example, or a rename), the
model's label for already-processed instances can change. Most such
changes are noise; some flip the label. This module records the latter
as **review flags** so a human is asked to look only at the instances a
codebook edit actually moved — and ties each flag back to the specific
codebook change (`change_id`) and instance that produced it.

Decoupling: this module knows nothing about LLM endpoints or the solo
thread. Callers re-label affected instances however they like and hand
the before/after here via :func:`evaluate_relabels`; the significance
policy and the persistence live in one place.

Table (own migration, universal project.sqlite):
- ``codebook_review_flag`` — one row per (instance, schema) the change
  moved, with old/new label + confidence, severity, the originating
  ``change_id``/``code_id``, and a status (open|reviewed|dismissed).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from potato.persistence import Migration, get_db, register_migration

# Confidence drop (on the SAME label) big enough to be worth a look even
# though the label itself didn't flip.
_CONFIDENCE_DROP_THRESHOLD = 0.25

_REVIEW_MIGRATION = Migration(
    name="0005_codebook_review_flag",
    sql="""
    CREATE TABLE IF NOT EXISTS codebook_review_flag (
        id             TEXT PRIMARY KEY,
        project        TEXT NOT NULL,
        instance_id    TEXT NOT NULL,
        schema_name    TEXT,
        code_id        TEXT,
        change_id      TEXT,
        old_label      TEXT,
        new_label      TEXT,
        old_confidence REAL,
        new_confidence REAL,
        severity       TEXT NOT NULL DEFAULT 'high',
        status         TEXT NOT NULL DEFAULT 'open',
        created_at     REAL NOT NULL,
        reviewed_by    TEXT,
        reviewed_at    REAL
    );
    CREATE INDEX IF NOT EXISTS idx_cbreview_open
        ON codebook_review_flag (project, status, created_at);
    CREATE INDEX IF NOT EXISTS idx_cbreview_change
        ON codebook_review_flag (project, change_id);
    """,
)

register_migration(_REVIEW_MIGRATION)


def _db(task_dir: str):
    register_migration(_REVIEW_MIGRATION)
    return get_db(task_dir)


def _norm(label: Any) -> Any:
    """Normalise a label for comparison. Lists/tuples (multiselect) ->
    a set of stripped strings; scalars -> a stripped lowercased string."""
    if isinstance(label, (list, tuple, set)):
        return frozenset(str(x).strip().lower() for x in label)
    if label is None:
        return None
    return str(label).strip().lower()


def _label_str(label: Any) -> str:
    if isinstance(label, (list, tuple, set)):
        return ", ".join(str(x) for x in label)
    return "" if label is None else str(label)


def significance(
    old_label: Any, new_label: Any,
    old_confidence: Optional[float] = None,
    new_confidence: Optional[float] = None,
) -> Optional[str]:
    """Decide whether a before/after label pair is worth human review.

    Returns a severity string ("high"|"medium") or None when the change
    is not significant. A flipped label is "high"; the same label with a
    materially lower confidence is "medium"; everything else is None.
    """
    if _norm(old_label) != _norm(new_label):
        return "high"
    if (old_confidence is not None and new_confidence is not None
            and (old_confidence - new_confidence) >= _CONFIDENCE_DROP_THRESHOLD):
        return "medium"
    return None


def record_flag(
    task_dir: str, *, project: str, instance_id: str,
    schema_name: Optional[str] = None, code_id: Optional[str] = None,
    change_id: Optional[str] = None, old_label: Any = None,
    new_label: Any = None, old_confidence: Optional[float] = None,
    new_confidence: Optional[float] = None, severity: str = "high",
) -> Dict[str, Any]:
    """Append one open review flag and return it."""
    fid = uuid.uuid4().hex
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO codebook_review_flag
               (id, project, instance_id, schema_name, code_id, change_id,
                old_label, new_label, old_confidence, new_confidence,
                severity, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
        (fid, project, instance_id, schema_name, code_id, change_id,
         _label_str(old_label), _label_str(new_label),
         old_confidence, new_confidence, severity, time.time()),
    )
    conn.commit()
    return get_flag(task_dir, fid)


def get_flag(task_dir: str, flag_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM codebook_review_flag WHERE id = ?", (flag_id,)
    ).fetchone()
    return dict(row) if row else None


def list_flags(
    task_dir: str, project: str, status: str = "open"
) -> List[Dict[str, Any]]:
    rows = _db(task_dir).execute(
        """SELECT * FROM codebook_review_flag
           WHERE project = ? AND status = ?
           ORDER BY
             CASE severity WHEN 'high' THEN 0 ELSE 1 END,
             created_at ASC""",
        (project, status),
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_flag(
    task_dir: str, flag_id: str, *, status: str, reviewed_by: str
) -> bool:
    """Mark a flag reviewed|dismissed. No-op if it isn't open."""
    if status not in ("reviewed", "dismissed"):
        raise ValueError("status must be 'reviewed' or 'dismissed'")
    conn = _db(task_dir)
    cur = conn.execute(
        """UPDATE codebook_review_flag
           SET status = ?, reviewed_by = ?, reviewed_at = ?
           WHERE id = ? AND status = 'open'""",
        (status, reviewed_by, time.time(), flag_id),
    )
    conn.commit()
    return cur.rowcount > 0


def evaluate_relabels(
    task_dir: str, *, project: str, change_id: Optional[str],
    relabels: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Score a batch of before/after re-labels and persist a flag for
    each significant one.

    Each item in ``relabels`` is a dict with: ``instance_id``,
    ``schema_name`` (optional), ``code_id`` (optional), ``old_label``,
    ``new_label``, and optional ``old_confidence``/``new_confidence``.
    Returns the flags that were created (significant ones only).
    """
    created: List[Dict[str, Any]] = []
    for item in relabels:
        sev = significance(
            item.get("old_label"), item.get("new_label"),
            item.get("old_confidence"), item.get("new_confidence"))
        if not sev:
            continue
        created.append(record_flag(
            task_dir, project=project, instance_id=item["instance_id"],
            schema_name=item.get("schema_name"),
            code_id=item.get("code_id"), change_id=change_id,
            old_label=item.get("old_label"),
            new_label=item.get("new_label"),
            old_confidence=item.get("old_confidence"),
            new_confidence=item.get("new_confidence"),
            severity=sev))
    return created


def open_count(task_dir: str, project: str) -> int:
    row = _db(task_dir).execute(
        """SELECT COUNT(*) AS n FROM codebook_review_flag
           WHERE project = ? AND status = 'open'""",
        (project,),
    ).fetchone()
    return int(row["n"]) if row else 0
