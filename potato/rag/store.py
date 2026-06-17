"""
RAG vector store (project-scoped, durable, SQLite).

Matches the codebook/review persistence idiom: tables in the universal
``<task_dir>/project.sqlite`` via the shared migration layer. Vectors are
stored as float32 BLOBs; retrieval is brute-force cosine in numpy
(corpus is small — one guideline doc + a few hundred codes — so no FAISS).

Two tables:
- ``rag_chunk`` — one row per embedded unit (guideline chunk, codebook
  field, or ICL example), with its vector, the (provider:model) it was
  embedded under, a content hash, and a ``stale`` flag.
- ``rag_meta`` — per-project pin: the embedding model is chosen once (at
  first index creation) and PINNED. Cross-model cosine is meaningless, so
  callers must not mix models — see ``ensure_pin`` / ``check_pin`` and
  ``RagModelMismatch`` (Amendment 1). ``index_revision`` is the codebook
  changelog bookmark used by the scoped re-embedding listener (Phase C).
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from potato.persistence import Migration, get_db, register_migration
from potato.rag.embedding_endpoint import EmbeddingError

# Corpora identifiers (rag_chunk.source_type).
SOURCE_GUIDELINE = "guideline"
SOURCE_CODE = "code"
SOURCE_ICL = "icl_example"

_RAG_MIGRATION = Migration(
    name="0007_rag_index",
    sql="""
    CREATE TABLE IF NOT EXISTS rag_chunk (
        id           TEXT PRIMARY KEY,
        project      TEXT NOT NULL,
        source_type  TEXT NOT NULL,
        source_ref   TEXT,
        field        TEXT,
        text         TEXT NOT NULL,
        vector       BLOB,
        model        TEXT,
        dim          INTEGER,
        content_hash TEXT,
        stale        INTEGER NOT NULL DEFAULT 0,
        updated_at   REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_rag_chunk_type
        ON rag_chunk (project, source_type);
    CREATE INDEX IF NOT EXISTS idx_rag_chunk_ref
        ON rag_chunk (project, source_ref);

    CREATE TABLE IF NOT EXISTS rag_meta (
        project        TEXT PRIMARY KEY,
        model          TEXT NOT NULL,
        dim            INTEGER NOT NULL,
        index_revision INTEGER NOT NULL DEFAULT 0,
        updated_at     REAL NOT NULL
    );
    """,
)

register_migration(_RAG_MIGRATION)

# Canonical guideline document per project (Phase D). Separate from the
# prompt: written explicitly by the guideline producers and read by BOTH
# the RAG guideline indexer and (optionally) prompt assembly — so we never
# parse guidelines back out of the generated prompt (which is circular).
_RAG_GUIDELINE_MIGRATION = Migration(
    name="0008_rag_guideline_doc",
    sql="""
    CREATE TABLE IF NOT EXISTS rag_guideline_doc (
        project      TEXT PRIMARY KEY,
        text         TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        updated_at   REAL NOT NULL
    );
    """,
)

register_migration(_RAG_GUIDELINE_MIGRATION)

# Per-chunk JSON metadata (Phase E). ICL chunks carry {"label", "gain"} so
# the per-instance selector can blend the proven val_accuracy_gain and keep
# a per-label coverage floor; codebook/guideline chunks leave it NULL.
_RAG_META_MIGRATION = Migration(
    name="0009_rag_chunk_meta",
    sql="ALTER TABLE rag_chunk ADD COLUMN meta TEXT;",
)

register_migration(_RAG_META_MIGRATION)


class RagModelMismatch(EmbeddingError):
    """The active embedding model/dim differs from the project's pinned one.

    Serving cross-model cosine would silently poison retrieval, so the
    substrate refuses and points the caller at the explicit reindex entry
    point (``reindex_project``)."""


def _db(task_dir: str):
    register_migration(_RAG_MIGRATION)
    register_migration(_RAG_GUIDELINE_MIGRATION)
    register_migration(_RAG_META_MIGRATION)
    return get_db(task_dir)


# ---- canonical guideline document (Phase D) ------------------------------

def get_guideline_doc(task_dir: str, project: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT text, content_hash FROM rag_guideline_doc WHERE project = ?",
        (project,),
    ).fetchone()
    return dict(row) if row else None


def set_guideline_doc(task_dir: str, project: str, text: str,
                      chash: str) -> None:
    conn = _db(task_dir)
    conn.execute(
        """INSERT OR REPLACE INTO rag_guideline_doc
               (project, text, content_hash, updated_at)
           VALUES (?, ?, ?, ?)""",
        (project, text, chash, time.time()),
    )
    conn.commit()


# ---- vectors -------------------------------------------------------------

def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def pack_vector(vec: Any) -> bytes:
    return np.asarray(vec, dtype=np.float32).ravel().tobytes()


def unpack_vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


# ---- per-project model pin (Amendment 1) ---------------------------------

def get_pin(task_dir: str, project: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT model, dim, index_revision FROM rag_meta WHERE project = ?",
        (project,),
    ).fetchone()
    return dict(row) if row else None


def ensure_pin(task_dir: str, project: str, model: str, dim: int) -> Dict[str, Any]:
    """Pin (model, dim) for the project on first index creation; on every
    later call assert the same model+dim and raise RagModelMismatch
    otherwise. Returns the effective pin."""
    pin = get_pin(task_dir, project)
    if pin is None:
        conn = _db(task_dir)
        conn.execute(
            """INSERT INTO rag_meta (project, model, dim, index_revision,
                                     updated_at)
               VALUES (?, ?, ?, 0, ?)""",
            (project, model, int(dim), time.time()),
        )
        conn.commit()
        return {"model": model, "dim": int(dim), "index_revision": 0}
    if pin["model"] != model or int(pin["dim"]) != int(dim):
        raise RagModelMismatch(
            f"project {project!r} is pinned to {pin['model']} (dim={pin['dim']}); "
            f"refusing to mix in {model} (dim={dim}). Reindex to switch models.")
    return pin


def check_pin(task_dir: str, project: str, model: str,
              dim: Optional[int] = None) -> None:
    """Raise RagModelMismatch if the project is pinned to a different model
    (or dim). No-op if the project has no pin yet."""
    pin = get_pin(task_dir, project)
    if pin is None:
        return
    if pin["model"] != model or (dim is not None and int(pin["dim"]) != int(dim)):
        raise RagModelMismatch(
            f"project {project!r} is pinned to {pin['model']} (dim={pin['dim']}); "
            f"active model is {model} (dim={dim}). Reindex to switch models.")


# ---- codebook changelog bookmark (Phase C) -------------------------------

def get_index_revision(task_dir: str, project: str) -> Optional[int]:
    pin = get_pin(task_dir, project)
    return int(pin["index_revision"]) if pin else None


def set_index_revision(task_dir: str, project: str, revision: int) -> None:
    conn = _db(task_dir)
    conn.execute(
        "UPDATE rag_meta SET index_revision = ?, updated_at = ? WHERE project = ?",
        (int(revision), time.time(), project),
    )
    conn.commit()


# ---- chunk CRUD ----------------------------------------------------------

def upsert_chunk(
    task_dir: str, *, project: str, source_type: str,
    source_ref: Optional[str], field: Optional[str], text: str,
    vector: Optional[Any], model: Optional[str], dim: Optional[int],
    chunk_id: Optional[str] = None, meta: Optional[str] = None,
) -> str:
    """Insert or replace one chunk (PK = chunk_id; defaults to a stable id
    built from project/source_type/source_ref/field so re-indexing the same
    unit overwrites rather than duplicates). A NULL vector marks the row
    not-yet-embedded (stale). ``meta`` is optional JSON (e.g. ICL
    {label, gain})."""
    cid = chunk_id or _stable_id(project, source_type, source_ref, field)
    blob = pack_vector(vector) if vector is not None else None
    stale = 0 if vector is not None else 1
    conn = _db(task_dir)
    conn.execute(
        """INSERT OR REPLACE INTO rag_chunk
               (id, project, source_type, source_ref, field, text, vector,
                model, dim, content_hash, stale, updated_at, meta)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cid, project, source_type, source_ref, field, text, blob,
         model, dim, content_hash(text), stale, time.time(), meta),
    )
    conn.commit()
    return cid


def _stable_id(project: str, source_type: str,
               source_ref: Optional[str], field: Optional[str]) -> str:
    raw = f"{project}\x1f{source_type}\x1f{source_ref or ''}\x1f{field or ''}"
    return uuid.uuid5(uuid.NAMESPACE_URL, raw).hex


def get_chunk(task_dir: str, chunk_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM rag_chunk WHERE id = ?", (chunk_id,)).fetchone()
    return dict(row) if row else None


def get_chunks(
    task_dir: str, project: str, *, source_type: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> List[Dict[str, Any]]:
    q = "SELECT * FROM rag_chunk WHERE project = ?"
    p: List[Any] = [project]
    if source_type is not None:
        q += " AND source_type = ?"; p.append(source_type)
    if source_ref is not None:
        q += " AND source_ref = ?"; p.append(source_ref)
    return [dict(r) for r in _db(task_dir).execute(q, p).fetchall()]


def mark_stale(
    task_dir: str, project: str, *, source_ref: Optional[str] = None,
    source_type: Optional[str] = None,
) -> int:
    """Flag chunks stale (scoped re-embedding). Scope by source_ref (one
    code) and/or source_type; with neither, the whole project goes stale."""
    q = "UPDATE rag_chunk SET stale = 1, updated_at = ? WHERE project = ?"
    p: List[Any] = [time.time(), project]
    if source_ref is not None:
        q += " AND source_ref = ?"; p.append(source_ref)
    if source_type is not None:
        q += " AND source_type = ?"; p.append(source_type)
    conn = _db(task_dir)
    cur = conn.execute(q, p)
    conn.commit()
    return cur.rowcount


def delete_chunks(
    task_dir: str, project: str, *, source_ref: Optional[str] = None,
    source_type: Optional[str] = None,
) -> int:
    q = "DELETE FROM rag_chunk WHERE project = ?"
    p: List[Any] = [project]
    if source_ref is not None:
        q += " AND source_ref = ?"; p.append(source_ref)
    if source_type is not None:
        q += " AND source_type = ?"; p.append(source_type)
    conn = _db(task_dir)
    cur = conn.execute(q, p)
    conn.commit()
    return cur.rowcount


def stale_chunks(
    task_dir: str, project: str, *, source_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    q = "SELECT * FROM rag_chunk WHERE project = ? AND stale = 1"
    p: List[Any] = [project]
    if source_type is not None:
        q += " AND source_type = ?"; p.append(source_type)
    return [dict(r) for r in _db(task_dir).execute(q, p).fetchall()]


def set_chunk_vector(
    task_dir: str, chunk_id: str, *, vector: Any, model: str, dim: int,
) -> None:
    """Write a freshly computed vector and clear the stale flag."""
    conn = _db(task_dir)
    conn.execute(
        """UPDATE rag_chunk
           SET vector = ?, model = ?, dim = ?, stale = 0, updated_at = ?
           WHERE id = ?""",
        (pack_vector(vector), model, int(dim), time.time(), chunk_id),
    )
    conn.commit()


def clear_project(task_dir: str, project: str) -> int:
    """Drop all chunks AND the pin for a project (used by reindex)."""
    conn = _db(task_dir)
    cur = conn.execute("DELETE FROM rag_chunk WHERE project = ?", (project,))
    conn.execute("DELETE FROM rag_meta WHERE project = ?", (project,))
    conn.commit()
    return cur.rowcount


# ---- brute-force cosine search ------------------------------------------

def search(
    task_dir: str, project: str, query_vec: Any, *,
    source_type: Optional[str] = None, k: int = 10,
    model: Optional[str] = None,
) -> List[Tuple[Dict[str, Any], float]]:
    """Top-k by cosine similarity over the project's embedded, non-stale
    chunks. ``model`` (when given) restricts to rows embedded under that
    model — so a stray cross-model row can never contribute a score."""
    rows = [r for r in get_chunks(task_dir, project, source_type=source_type)
            if r["vector"] is not None and not r["stale"]
            and (model is None or r["model"] == model)]
    if not rows:
        return []
    mat = np.vstack([unpack_vector(r["vector"]) for r in rows])
    q = np.asarray(query_vec, dtype=np.float32).ravel()
    qn = float(np.linalg.norm(q))
    if qn == 0:
        return []
    row_norms = np.linalg.norm(mat, axis=1)
    safe = np.where(row_norms == 0, 1.0, row_norms)
    scores = (mat @ q) / (safe * qn)
    scores = np.where(row_norms == 0, 0.0, scores)
    order = np.argsort(-scores)[:k]
    return [(rows[i], float(scores[i])) for i in order]
