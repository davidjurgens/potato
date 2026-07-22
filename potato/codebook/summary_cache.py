"""
Cache for LLM-generated summaries of over-long codebook prose fields.

Summarization (see ``summarizer.py``) only changes what gets *rendered*
into the prompt — the ``codes`` table's ``definition`` /
``clarification`` / ``negative_clarification`` columns always keep the
full text an author wrote. This is a side cache keyed by a hash of the
source text, so a field that hasn't changed since its last summarization
doesn't re-trigger an LLM call on every prompt render.
"""

from __future__ import annotations

import time
from typing import Optional

from potato.persistence import Migration, get_db, register_migration

_MIGRATION = Migration(
    name="0001_codebook_field_summary",
    sql="""
    CREATE TABLE IF NOT EXISTS codebook_field_summary (
        code_id     TEXT NOT NULL,
        field       TEXT NOT NULL,
        source_hash TEXT NOT NULL,
        summary     TEXT NOT NULL,
        created_at  REAL NOT NULL,
        PRIMARY KEY (code_id, field)
    );
    """,
)

register_migration(_MIGRATION)


def _db(task_dir: str):
    register_migration(_MIGRATION)
    return get_db(task_dir)


def get_cached(
    task_dir: str, code_id: str, field: str, source_hash: str
) -> Optional[str]:
    """The cached summary, or None if missing/stale (source text changed
    since it was cached — the caller will re-summarize and overwrite)."""
    row = _db(task_dir).execute(
        """SELECT summary FROM codebook_field_summary
           WHERE code_id = ? AND field = ? AND source_hash = ?""",
        (code_id, field, source_hash),
    ).fetchone()
    return row["summary"] if row else None


def set_cached(
    task_dir: str, code_id: str, field: str, source_hash: str, summary: str
) -> None:
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO codebook_field_summary
               (code_id, field, source_hash, summary, created_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (code_id, field) DO UPDATE SET
               source_hash = excluded.source_hash,
               summary = excluded.summary,
               created_at = excluded.created_at""",
        (code_id, field, source_hash, summary, time.time()),
    )
    conn.commit()
