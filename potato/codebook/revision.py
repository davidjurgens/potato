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

# Adds a parallel *semantic-revision* stamp to each annotation so prose
# edits to a code's meaning-bearing sections (definition / use_when /
# avoid_when / short_def) can softly flag the instance for re-review,
# independently of the structural (label) revision above.
_CONTENT_PROV_MIGRATION = Migration(
    name="0005_provenance_sem_revision",
    sql="""
    ALTER TABLE annotation_provenance ADD COLUMN sem_revision INTEGER
        NOT NULL DEFAULT 0;
    """,
)

# `codebook_revision` holds only the CURRENT revision and when it was last
# touched, so it cannot answer "when did revision 3 happen" -- and that is
# exactly the question the agreement timeline asks when it overlays a
# guideline edit against a change in agreement. One row per bump makes the
# answer exact instead of inferred from the earliest annotation stamped with
# it, which is only a lower bound and is missing entirely for a revision
# nobody annotated under.
_REVISION_HISTORY_MIGRATION = Migration(
    name="0006_codebook_revision_history",
    sql="""
    CREATE TABLE IF NOT EXISTS codebook_revision_history (
        project    TEXT NOT NULL,
        revision   INTEGER NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (project, revision)
    );
    CREATE INDEX IF NOT EXISTS idx_revision_history_time
        ON codebook_revision_history (project, created_at);
    """,
)

# Defensive: guarantee the codes table migration (0001_codebook) is
# registered before this module's ALTER, regardless of import path.
from potato.codebook.store import _CODEBOOK_MIGRATION as _CB_MIG

register_migration(_CB_MIG)
register_migration(_REVISION_MIGRATION)
register_migration(_CODES_REV_MIGRATION)
register_migration(_CONTENT_PROV_MIGRATION)
register_migration(_REVISION_HISTORY_MIGRATION)


def _db(task_dir: str):
    register_migration(_REVISION_MIGRATION)
    register_migration(_CODES_REV_MIGRATION)
    register_migration(_CONTENT_PROV_MIGRATION)
    register_migration(_REVISION_HISTORY_MIGRATION)
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
    revision = current_revision(task_dir, project)
    # One row per bump, so the agreement timeline can mark exactly when the
    # guidelines moved. INSERT OR IGNORE rather than a plain INSERT: a project
    # whose revision counter was rolled back by hand would otherwise crash the
    # codebook edit that triggered this.
    conn.execute(
        """INSERT OR IGNORE INTO codebook_revision_history
               (project, revision, created_at)
           VALUES (?, ?, ?)""",
        (project, revision, now),
    )
    conn.commit()
    return revision


def revision_history(task_dir: str, project: str) -> List[Dict[str, object]]:
    """
    Every recorded codebook bump, oldest first, as ``{revision, created_at}``.

    Revisions made before this table existed are not in it. Rather than
    silently returning a short list, callers get exactly what was recorded and
    :func:`potato.server_utils.iaa.drift.codebook_markers` fills the gap from
    ``annotation_provenance``, which is a lower bound on when a revision was
    in use.
    """
    rows = _db(task_dir).execute(
        """SELECT revision, created_at FROM codebook_revision_history
           WHERE project = ? ORDER BY created_at ASC, revision ASC""",
        (project,),
    ).fetchall()
    return [{"revision": int(r["revision"]), "created_at": float(r["created_at"])}
            for r in rows]


def revision_first_seen(task_dir: str, project: str) -> Dict[int, float]:
    """
    The earliest time each revision appears on a saved annotation.

    A lower bound on when the revision took effect, and the only evidence
    available for bumps that predate ``codebook_revision_history``.
    """
    rows = _db(task_dir).execute(
        """SELECT revision, MIN(updated_at) AS first_seen
           FROM annotation_provenance
           WHERE project = ? GROUP BY revision""",
        (project,),
    ).fetchall()
    return {int(r["revision"]): float(r["first_seen"]) for r in rows}


def current_sem_revision(task_dir: str, project: str) -> int:
    """The codebook's current semantic-content revision (bumped only by
    meaning-bearing prose edits). Lives in the content-meta table owned by
    blocks.py; read here so annotation stamping can pick it up."""
    try:
        from potato.codebook.blocks import current_sem_revision as _csr
        return _csr(task_dir, project)
    except Exception:
        return 0


def record_annotation(
    task_dir: str, project: str, instance_id: str, username: str
) -> int:
    """Stamp (project, instance_id, username) with the current structural
    AND semantic revisions at annotation save time. Idempotent upsert;
    returns the structural revision."""
    rev = current_revision(task_dir, project)
    sem = current_sem_revision(task_dir, project)
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO annotation_provenance
               (project, instance_id, username, revision, sem_revision,
                updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(project, instance_id, username) DO UPDATE SET
               revision = excluded.revision,
               sem_revision = excluded.sem_revision,
               updated_at = excluded.updated_at""",
        (project, instance_id, username, rev, sem, time.time()),
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


def touch_instances(
    task_dir: str, project: str, instance_ids: List[str]
) -> int:
    """Re-flag specific instances as stale after a retroactive codebook
    edit (merge/split/rename) that affected exactly them. Sets their
    stamped revision to current-1 so `stale_instances` resurfaces them —
    soft and dismissible, never a hard re-label gate (Phase 2 (B)
    policy). Only lowers a revision (never un-stales an already-older
    row), and never raises one above current."""
    if not instance_ids:
        return 0
    cur = current_revision(task_dir, project)
    if cur <= 0:
        return 0
    target = cur - 1
    qs = ",".join("?" * len(instance_ids))
    conn = _db(task_dir)
    cur_ = conn.execute(
        f"""UPDATE annotation_provenance
            SET revision = ?, updated_at = ?
            WHERE project = ? AND instance_id IN ({qs})
              AND revision > ?""",
        [target, time.time(), project, *instance_ids, target],
    )
    conn.commit()
    return cur_.rowcount


def instance_sem_revision(
    task_dir: str, project: str, instance_id: str, username: str
) -> Optional[int]:
    row = _db(task_dir).execute(
        """SELECT sem_revision FROM annotation_provenance
           WHERE project = ? AND instance_id = ? AND username = ?""",
        (project, instance_id, username),
    ).fetchone()
    return int(row["sem_revision"]) if row else None


def content_stale_instances(
    task_dir: str, project: str, username: str
) -> List[Dict[str, object]]:
    """This user's annotated instances whose stamped *semantic* revision is
    behind the current one — i.e. a code definition / inclusion / exclusion
    rule changed since they labeled. Soft + dismissible, never a hard gate
    (mirrors the label-based stale worklist)."""
    cur = current_sem_revision(task_dir, project)
    if cur <= 0:
        return []
    rows = _db(task_dir).execute(
        """SELECT instance_id, sem_revision FROM annotation_provenance
           WHERE project = ? AND username = ? AND sem_revision < ?
           ORDER BY sem_revision ASC, instance_id ASC""",
        (project, username, cur),
    ).fetchall()
    return [{
        "instance_id": r["instance_id"],
        "annotated_sem_revision": int(r["sem_revision"]),
        "current_sem_revision": cur,
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
