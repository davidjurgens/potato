"""
Guideline corpus for the RAG substrate (Phase D).

The guideline document is a first-class canonical text per project, written
explicitly by the guideline producers (the edge-case-rule injection and,
later, the refinement loop) and read by the RAG indexer here. This avoids
the circular alternative of parsing guidelines back out of the assembled
prompt (which is itself partly built from retrieved guidelines).

Invalidation is a SEPARATE trigger from the codebook changelog: guideline
chunks go stale only when the guideline TEXT changes (content-hash guard),
not on codebook edits. Re-embedding is the same lazy catch-up the codebook
path uses (potato.rag.indexer.catch_up), so a rewritten guideline is never
served from a stale fragment.
"""

from __future__ import annotations

import re
from typing import List

from potato.rag import store
from potato.rag.store import SOURCE_GUIDELINE

_BULLET = ("-", "*", "•")


def chunk_guidelines(text: str) -> List[str]:
    """Split a guideline document into retrieval units: blank-line-separated
    paragraphs, with bullet lists exploded into one chunk per bullet."""
    out: List[str] = []
    for para in re.split(r"\n\s*\n", (text or "").strip()):
        lines = [ln.strip() for ln in para.splitlines() if ln.strip()]
        if not lines:
            continue
        if all(ln.lstrip().startswith(_BULLET) for ln in lines):
            for ln in lines:
                cleaned = ln.lstrip("-*• \t").strip()
                if cleaned:
                    out.append(cleaned)
        else:
            out.append(" ".join(lines).strip())
    return [c for c in out if c]


def get_guidelines(task_dir: str, project: str) -> str:
    doc = store.get_guideline_doc(task_dir, project)
    return doc["text"] if doc else ""


def set_guidelines(task_dir: str, project: str, text: str) -> bool:
    """Replace the canonical guideline doc. Re-chunks + marks guideline
    chunks stale ONLY when the text actually changes (content-hash guard);
    an unchanged save is a true no-op (no churn, no re-embed). Returns True
    if the document changed."""
    text = (text or "").strip()
    chash = store.content_hash(text)
    cur = store.get_guideline_doc(task_dir, project)
    if cur and cur["content_hash"] == chash:
        return False
    store.set_guideline_doc(task_dir, project, text, chash)
    # Re-chunk: delete the old guideline chunks, insert fresh stale ones.
    store.delete_chunks(task_dir, project, source_type=SOURCE_GUIDELINE)
    for i, chunk in enumerate(chunk_guidelines(text)):
        store.upsert_chunk(
            task_dir, project=project, source_type=SOURCE_GUIDELINE,
            source_ref=f"g{i}", field=None, text=chunk,
            vector=None, model=None, dim=None)  # stale until catch_up
    return True


def append_guidelines(task_dir: str, project: str, new_text: str) -> bool:
    """Append guideline lines the producers generated to the canonical doc,
    skipping lines already present (idempotent re-application). Returns True
    if anything was added."""
    new_text = (new_text or "").strip()
    if not new_text:
        return False
    existing = get_guidelines(task_dir, project)
    have = {ln.strip() for ln in existing.splitlines() if ln.strip()}
    additions = [ln for ln in new_text.splitlines()
                 if ln.strip() and ln.strip() not in have]
    if not additions:
        return False
    combined = (existing + "\n" + "\n".join(additions)).strip() \
        if existing else "\n".join(additions)
    return set_guidelines(task_dir, project, combined)
