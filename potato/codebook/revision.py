"""
Codebook revision provenance.

A per-project monotonic ``codebook_revision`` counter, bumped on **any**
codebook change (create / rename / recolor / move / delete) — all
codebook edits are server-persisted and every one advances the
revision. Every saved annotation is stamped with the revision in
effect, so analysts can condition on the codebook state an annotation
was made against, and the UI can softly flag instances labeled under an
older codebook revision.

`codes.created_revision` records the revision a code first appeared in,
so the review worklist can show *which* codes were added since a given
instance was labeled (precision: a niche new code only resurfaces
instances that predate it).

Tables (own migrations, universal project.sqlite):
- ``codebook_revision(project PK, revision, updated_at)``
- ``annotation_provenance(project, instance_id, username, revision,
  updated_at)`` — PK(project, instance_id, username)
- ``codes.created_revision`` (added via ALTER; default 0 = pre-feature)
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration

_REVISION_MIGRATION = Migration(
    name="0002_codebook_revision",
    sql="""
    CREATE TABLE IF NOT EXISTS codebook_revision (
        project    TEXT PRIMARY KEY,
        revision   INTEGER NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS annotation_provenance (
        project     TEXT NOT NULL,
        instance_id TEXT NOT NULL,
        username    TEXT NOT NULL,
        revision    INTEGER NOT NULL,
        updated_at  REAL NOT NULL,
        PRIMARY KEY (project, instance_id, username)
    );
    CREATE INDEX IF NOT EXISTS idx_provenance_stale
        ON annotation_provenance (project, username, revision);
    """,
)

# Separate migration: add created_revision to the codes table (created
# by store.py's 0001_codebook, which registers first at import).
_CODES_REV_MIGRATION = Migration(
    name="0002_codes_created_revision",
    sql="""
    ALTER TABLE codes ADD COLUMN created_revision INTEGER NOT NULL
        DEFAULT 0;
    """,
)

# Defensive: guarantee the codes table migration (0001_codebook) is
# registered before this module's ALTER, regardless of import path.
from potato.codebook.store import _CODEBOOK_MIGRATION as _CB_MIG

register_migration(_CB_MIG)
register_migration(_REVISION_MIGRATION)
register_migration(_CODES_REV_MIGRATION)


def _db(task_dir: str):
    register_migration(_REVISION_MIGRATION)
    register_migration(_CODES_REV_MIGRATION)
    return get_db(task_dir)


def current_revision(task_dir: str, project: str) -> int:
    row = _db(task_dir).execute(
        "SELECT revision FROM codebook_revision WHERE project = ?",
        (project,),
    ).fetchone()
    return int(row["revision"]) if row else 0


def bump_revision(task_dir: str, project: str) -> int:
    """Increment (or initialise) the project's revision; return the new
    value. Called only for option-set-changing codebook ops."""
    conn = _db(task_dir)
    now = time.time()
    conn.execute(
        """INSERT INTO codebook_revision (project, revision, updated_at)
           VALUES (?, 1, ?)
           ON CONFLICT(project) DO UPDATE SET
               revision = revision + 1,
               updated_at = excluded.updated_at""",
        (project, now),
    )
    conn.commit()
    return current_revision(task_dir, project)


def record_annotation(
    task_dir: str, project: str, instance_id: str, username: str
) -> int:
    """Stamp (project, instance_id, username) with the current revision
    at annotation save time. Idempotent upsert; returns the revision."""
    rev = current_revision(task_dir, project)
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO annotation_provenance
               (project, instance_id, username, revision, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(project, instance_id, username) DO UPDATE SET
               revision = excluded.revision,
               updated_at = excluded.updated_at""",
        (project, instance_id, username, rev, time.time()),
    )
    conn.commit()
    return rev


def instance_revision(
    task_dir: str, project: str, instance_id: str, username: str
) -> Optional[int]:
    row = _db(task_dir).execute(
        """SELECT revision FROM annotation_provenance
           WHERE project = ? AND instance_id = ? AND username = ?""",
        (project, instance_id, username),
    ).fetchone()
    return int(row["revision"]) if row else None


def stale_instances(
    task_dir: str, project: str, username: str
) -> List[Dict[str, object]]:
    """This user's annotated instances whose stamped revision is behind
    the current one, with the count of codes added since."""
    cur = current_revision(task_dir, project)
    if cur <= 0:
        return []
    rows = _db(task_dir).execute(
        """SELECT instance_id, revision FROM annotation_provenance
           WHERE project = ? AND username = ? AND revision < ?
           ORDER BY revision ASC, instance_id ASC""",
        (project, username, cur),
    ).fetchall()
    out: List[Dict[str, object]] = []
    for r in rows:
        out.append({
            "instance_id": r["instance_id"],
            "annotated_revision": int(r["revision"]),
            "current_revision": cur,
            "codes_added_since": codes_added_since(
                task_dir, project, int(r["revision"])),
        })
    return out


def all_stale_instances(
    task_dir: str, project: str
) -> List[Dict[str, object]]:
    """Every (instance, user) annotated under an older revision —
    project-wide, for admin oversight."""
    cur = current_revision(task_dir, project)
    if cur <= 0:
        return []
    rows = _db(task_dir).execute(
        """SELECT instance_id, username, revision
           FROM annotation_provenance
           WHERE project = ? AND revision < ?
           ORDER BY revision ASC, instance_id ASC, username ASC""",
        (project, cur),
    ).fetchall()
    return [{
        "instance_id": r["instance_id"],
        "username": r["username"],
        "annotated_revision": int(r["revision"]),
        "current_revision": cur,
        "codes_added_since": codes_added_since(
            task_dir, project, int(r["revision"])),
    } for r in rows]


def codes_added_since(
    task_dir: str, project: str, revision: int
) -> List[str]:
    """Names of codes created after `revision` — the precise set that
    could change a label made at that revision."""
    rows = _db(task_dir).execute(
        """SELECT name FROM codes
           WHERE project = ? AND created_revision > ?
           ORDER BY created_revision ASC, name ASC""",
        (project, revision),
    ).fetchall()
    return [r["name"] for r in rows]
