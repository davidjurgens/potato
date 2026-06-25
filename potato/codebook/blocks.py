"""
Codebook content blocks — the living-document layer.

A code's (or a document-level section's) rich content is an ordered list
of **typed blocks**, each holding a markdown body. This is strictly
additive to the `codes` table: `Codebook.labels()` / `as_tree()` stay
content-free so the ICL prompt and live forms keep reading clean code
names. Content flows into AI prompts only via the distiller (separate),
never by joining into labels.

Two scopes share one table:
- per-code blocks:      ``code_id = <id>``,  ``section = ''``
- document-level blocks: ``code_id = ''``,   ``section = <DOC_SECTIONS member>``

Vocabulary is **data, not schema** (`BLOCK_TYPES`): a new block type is a
dict entry, no migration. `block_type` is stored as free TEXT.

Versioning / optimistic concurrency:
- Every save inserts the scope's new block set at ``version = max+1`` and
  soft-archives the previous live set (``archived_at``). Live blocks are
  ``archived_at IS NULL``; history survives in the table (and in
  `codebook_snapshot`).
- ``scope_version`` = ``MAX(version)`` over *all* rows in the scope
  (live or archived) so the optimistic token is strictly monotonic and
  never regresses after an archive. Callers compare-and-swap against it
  (the service holds a lock so check+replace is atomic).

No business rules live here (no permissions, no revision bump, no
notify) — that is `content_service`'s job. This module only persists rows.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration

# Per-code scope sentinel (mirrors store.ROOT for parent_id).
NO_CODE = ""   # code_id for a document-level block
NO_SECTION = ""  # section for a per-code block

# ---- vocabulary (single source of truth; extend without a migration) ----

# Each entry: heading (canonical markdown title), aliases (extra titles a
# parser accepts), semantic (does editing it change meaning enough to
# trigger annotator re-review?), order (default sort weight in a scope).
BLOCK_TYPES: Dict[str, Dict[str, Any]] = {
    "short_def": {
        "heading": "Short definition",
        "aliases": ["Summary", "Gloss", "One-liner"],
        "semantic": True, "order": 10,
    },
    "definition": {
        "heading": "Definition",
        "aliases": ["Full definition", "Meaning"],
        "semantic": True, "order": 20,
    },
    "use_when": {
        "heading": "Use when",
        "aliases": ["Inclusion", "Include when", "Apply when",
                    "Inclusion criteria"],
        "semantic": True, "order": 30,
    },
    "avoid_when": {
        "heading": "Avoid when",
        "aliases": ["Exclusion", "Exclude when", "Do not apply when",
                    "Don't apply when", "Exclusion criteria"],
        "semantic": True, "order": 40,
    },
    "example": {
        "heading": "Examples",
        "aliases": ["Example", "Positive examples"],
        "semantic": False, "order": 50,
    },
    "counter_example": {
        "heading": "Counter-examples",
        "aliases": ["Counter-example", "Counterexample", "Counterexamples",
                    "Non-example", "Non-examples", "Near misses"],
        "semantic": False, "order": 60,
    },
    "rationale": {
        "heading": "Rationale",
        "aliases": ["Why", "Reasoning"],
        "semantic": False, "order": 70,
    },
    "background": {
        "heading": "Background",
        "aliases": ["Motivation", "Context"],
        "semantic": False, "order": 80,
    },
    "downstream_usage": {
        "heading": "Downstream usage",
        "aliases": ["How codes are used", "Downstream use",
                    "How this code is used"],
        "semantic": False, "order": 90,
    },
    "keywords": {
        "heading": "Keywords",
        "aliases": ["Flags", "Cues", "Triggers"],
        "semantic": False, "order": 100,
    },
    "notes": {
        "heading": "Notes",
        "aliases": ["Note", "Annotator notes"],
        "semantic": False, "order": 110,
    },
    "custom": {
        # custom blocks carry their own heading in custom_label.
        "heading": "Note",
        "aliases": [],
        "semantic": False, "order": 1000,
    },
}

SEMANTIC_TYPES = frozenset(
    k for k, v in BLOCK_TYPES.items() if v.get("semantic"))

# Document-level section keys (code_id == NO_CODE).
DOC_SECTIONS = (
    "preamble",
    "general_instructions",
    "background",
    "downstream_usage",
)

DOC_SECTION_TITLES = {
    "preamble": "Preamble",
    "general_instructions": "General instructions",
    "background": "Background",
    "downstream_usage": "How codes are used downstream",
}


def is_valid_type(block_type: str) -> bool:
    return block_type in BLOCK_TYPES


def is_semantic(block_type: str) -> bool:
    return block_type in SEMANTIC_TYPES


# ---- migrations (new tables only; no ALTER, so order-independent) --------

_BLOCKS_MIGRATION = Migration(
    name="0004_codebook_blocks",
    sql="""
    CREATE TABLE IF NOT EXISTS code_block (
        id           TEXT PRIMARY KEY,
        project      TEXT NOT NULL,
        code_id      TEXT NOT NULL DEFAULT '',
        section      TEXT NOT NULL DEFAULT '',
        block_type   TEXT NOT NULL,
        custom_label TEXT,
        body_md      TEXT NOT NULL DEFAULT '',
        ordinal      INTEGER NOT NULL DEFAULT 0,
        version      INTEGER NOT NULL DEFAULT 1,
        created_by   TEXT NOT NULL,
        updated_by   TEXT NOT NULL,
        created_at   REAL NOT NULL,
        updated_at   REAL NOT NULL,
        archived_at  REAL
    );
    CREATE INDEX IF NOT EXISTS idx_code_block_scope
        ON code_block (project, code_id, archived_at);
    CREATE INDEX IF NOT EXISTS idx_code_block_doc
        ON code_block (project, section, archived_at);

    CREATE TABLE IF NOT EXISTS codebook_snapshot (
        id           TEXT PRIMARY KEY,
        project      TEXT NOT NULL,
        scope_kind   TEXT NOT NULL,
        scope_id     TEXT NOT NULL,
        snapshot_md  TEXT NOT NULL,
        blocks_json  TEXT NOT NULL,
        semantic     INTEGER NOT NULL DEFAULT 0,
        revision     INTEGER NOT NULL DEFAULT 0,
        sem_revision INTEGER NOT NULL DEFAULT 0,
        change_id    TEXT,
        actor        TEXT NOT NULL,
        actor_kind   TEXT NOT NULL DEFAULT 'human',
        created_at   REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_cb_snapshot_scope
        ON codebook_snapshot (project, scope_kind, scope_id, created_at);

    CREATE TABLE IF NOT EXISTS codebook_content_meta (
        project          TEXT PRIMARY KEY,
        content_revision INTEGER NOT NULL DEFAULT 0,
        sem_revision     INTEGER NOT NULL DEFAULT 0,
        updated_at       REAL NOT NULL
    );
    """,
)

register_migration(_BLOCKS_MIGRATION)


def _db(task_dir: str):
    register_migration(_BLOCKS_MIGRATION)
    return get_db(task_dir)


class StaleScopeError(Exception):
    """Raised by replace_scope_blocks when the caller's base version no
    longer matches the scope's current version (optimistic concurrency).
    Carries the current version so the service can build a 409 body."""

    def __init__(self, current_version: int):
        super().__init__(
            f"scope changed (now at version {current_version})")
        self.current_version = current_version


# ---- reads ---------------------------------------------------------------

def list_blocks(
    task_dir: str, project: str, *,
    code_id: str = NO_CODE, section: str = NO_SECTION,
) -> List[Dict[str, Any]]:
    """Live blocks for one scope, ordered by ordinal."""
    rows = _db(task_dir).execute(
        """SELECT * FROM code_block
           WHERE project = ? AND code_id = ? AND section = ?
             AND archived_at IS NULL
           ORDER BY ordinal ASC""",
        (project, code_id, section),
    ).fetchall()
    return [dict(r) for r in rows]


def get_block(task_dir: str, block_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM code_block WHERE id = ?", (block_id,)
    ).fetchone()
    return dict(row) if row else None


def scope_version(
    task_dir: str, project: str, *,
    code_id: str = NO_CODE, section: str = NO_SECTION,
) -> int:
    """Monotonic optimistic token for a scope = MAX(version) over ALL rows
    (live + archived), 0 if the scope has never been written. Counting
    archived rows is what keeps it from regressing after an archive."""
    row = _db(task_dir).execute(
        """SELECT MAX(version) AS m FROM code_block
           WHERE project = ? AND code_id = ? AND section = ?""",
        (project, code_id, section),
    ).fetchone()
    return int(row["m"]) if row and row["m"] is not None else 0


def has_any_content(task_dir: str, project: str) -> bool:
    row = _db(task_dir).execute(
        """SELECT 1 FROM code_block
           WHERE project = ? AND archived_at IS NULL LIMIT 1""",
        (project,),
    ).fetchone()
    return row is not None


# ---- content-revision counters ------------------------------------------
# Two counters, kept SEPARATE from the structural `codebook_revision` so the
# existing label-based stale machinery is untouched by prose edits:
#   content_revision — bumped on EVERY content save (cache-bust: the panel /
#                      page refetch rendered content when it moves).
#   sem_revision     — bumped only on SEMANTIC content saves (definition /
#                      use_when / avoid_when / short_def changed); drives the
#                      annotator re-review signal.

def current_content_revision(task_dir: str, project: str) -> int:
    row = _db(task_dir).execute(
        "SELECT content_revision FROM codebook_content_meta WHERE project = ?",
        (project,),
    ).fetchone()
    return int(row["content_revision"]) if row else 0


def current_sem_revision(task_dir: str, project: str) -> int:
    row = _db(task_dir).execute(
        "SELECT sem_revision FROM codebook_content_meta WHERE project = ?",
        (project,),
    ).fetchone()
    return int(row["sem_revision"]) if row else 0


def bump_content_meta(
    task_dir: str, project: str, *, semantic: bool
) -> Dict[str, int]:
    """Advance content_revision (always) and sem_revision (iff semantic).
    Returns the new {'content_revision', 'sem_revision'}."""
    conn = _db(task_dir)
    sem_inc = 1 if semantic else 0
    conn.execute(
        """INSERT INTO codebook_content_meta
               (project, content_revision, sem_revision, updated_at)
           VALUES (?, 1, ?, ?)
           ON CONFLICT(project) DO UPDATE SET
               content_revision = content_revision + 1,
               sem_revision = sem_revision + ?,
               updated_at = excluded.updated_at""",
        (project, sem_inc, time.time(), sem_inc),
    )
    conn.commit()
    return {
        "content_revision": current_content_revision(task_dir, project),
        "sem_revision": current_sem_revision(task_dir, project),
    }


# ---- writes --------------------------------------------------------------

def replace_scope_blocks(
    task_dir: str, *,
    project: str,
    code_id: str = NO_CODE,
    section: str = NO_SECTION,
    blocks: List[Dict[str, Any]],
    actor: str,
    base_version: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Replace a scope's live blocks with `blocks` (an ordered list of
    dicts with at least `block_type` and `body_md`; optional `custom_label`).

    If `base_version` is given, performs an optimistic compare-and-swap:
    raises `StaleScopeError(current)` if it no longer matches. Archives the
    previous live set and inserts the new set at version max+1.

    Atomicity / serialization is the caller's responsibility (the service
    holds a process lock so no two content saves interleave on the shared
    connection). Returns the new live blocks.
    """
    conn = _db(task_dir)
    current = scope_version(
        task_dir, project, code_id=code_id, section=section)
    if base_version is not None and base_version != current:
        raise StaleScopeError(current)
    new_version = current + 1
    now = time.time()
    # Archive the previous live set (history survives; never DELETE).
    conn.execute(
        """UPDATE code_block SET archived_at = ?, updated_at = ?
           WHERE project = ? AND code_id = ? AND section = ?
             AND archived_at IS NULL""",
        (now, now, project, code_id, section),
    )
    for i, b in enumerate(blocks):
        btype = b.get("block_type") or "custom"
        if not is_valid_type(btype):
            btype = "custom"
        custom_label = b.get("custom_label")
        if btype == "custom" and not custom_label:
            custom_label = BLOCK_TYPES["custom"]["heading"]
        conn.execute(
            """INSERT INTO code_block
                   (id, project, code_id, section, block_type, custom_label,
                    body_md, ordinal, version, created_by, updated_by,
                    created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, project, code_id, section, btype,
             custom_label, b.get("body_md") or "", i, new_version,
             actor, actor, now, now),
        )
    conn.commit()
    return list_blocks(
        task_dir, project, code_id=code_id, section=section)
