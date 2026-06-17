"""
RAG retrieval API.

Given an instance's text, return the most relevant guideline chunks
(Phase D) and a ranked list of codebook units (Phase C side feature).
Retrieval always does a lazy catch-up first so it never scores against a
stale (outdated-definition) chunk, and always restricts the cosine search
to the project's pinned model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import json

from potato.rag import indexer, store
from potato.rag.embedding_endpoint import BaseEmbeddingEndpoint, EmbeddingError
from potato.rag.store import SOURCE_CODE, SOURCE_GUIDELINE, SOURCE_ICL


def prepare_instance(
    task_dir: str, project: str, instance_text: str, *,
    endpoint: Optional[BaseEmbeddingEndpoint] = None, config: Any = None,
):
    """Resolve the pinned endpoint, catch up stale embeddings, and embed the
    instance text ONCE so guideline / codebook / ICL retrieval can share the
    vector (Req 5). Returns ``(endpoint, query_vec)`` — ``query_vec`` is
    None when nothing is indexed yet (no pin), and ``(None, None)`` when no
    embedder is available."""
    if not (instance_text or "").strip():
        return None, None
    try:
        ep = indexer._endpoint_for(task_dir, project, config, endpoint)
        indexer.catch_up(task_dir, project, endpoint=ep, config=config)
    except EmbeddingError:
        return None, None
    if store.get_pin(task_dir, project) is None:
        return ep, None
    return ep, ep.embed_one(instance_text)


def retrieve_guidelines(
    task_dir: str, project: str, instance_text: str, *,
    k: int = 5, endpoint: Optional[BaseEmbeddingEndpoint] = None,
    config: Any = None, query_vec=None,
) -> List[Dict[str, Any]]:
    """Top-k guideline chunks most relevant to ``instance_text`` (scores
    included). Lazily catches up any stale guideline embeddings first so a
    rewritten guideline is never served stale. Restricted to the pinned
    model. ``query_vec`` lets callers reuse one instance embedding (Req 5).
    Returns [] when no guidelines have been indexed."""
    if not (instance_text or "").strip():
        return []
    ep = indexer._endpoint_for(task_dir, project, config, endpoint)
    indexer.catch_up(task_dir, project, endpoint=ep, config=config)
    pin = store.get_pin(task_dir, project)
    if pin is None:
        return []
    qv = query_vec if query_vec is not None else ep.embed_one(instance_text)
    hits = store.search(task_dir, project, qv, source_type=SOURCE_GUIDELINE,
                        k=k, model=pin["model"])
    return [{"chunk_id": r["id"], "source_ref": r["source_ref"],
             "text": r["text"], "score": score} for r, score in hits]


def retrieve_icl_examples(
    task_dir: str, project: str, instance_text: str, *,
    k: int = 5, endpoint: Optional[BaseEmbeddingEndpoint] = None,
    config: Any = None, query_vec=None, min_per_label: int = 1,
    gain_weight: float = 0.5, mmr_lambda: float = 0.7,
) -> List[Dict[str, Any]]:
    """Rank validated ICL examples by blended similarity+gain, diversify with
    MMR, and keep a per-label coverage floor (Phase E). Assumes the ICL
    corpus was synced via ``indexer.sync_icl_entries``. ``query_vec`` shares
    one instance embedding (Req 5). Returns [{text, label, score, ...}]."""
    if not (instance_text or "").strip():
        return []
    ep = indexer._endpoint_for(task_dir, project, config, endpoint)
    indexer.catch_up(task_dir, project, endpoint=ep, config=config)
    pin = store.get_pin(task_dir, project)
    if pin is None:
        return []
    qv = query_vec if query_vec is not None else ep.embed_one(instance_text)
    hits = store.search(task_dir, project, qv, source_type=SOURCE_ICL,
                        k=max(50, k * 10), model=pin["model"])
    if not hits:
        return []
    candidates: List[Dict[str, Any]] = []
    for row, score in hits:
        meta = json.loads(row["meta"]) if row.get("meta") else {}
        candidates.append({
            "id": row["id"], "text": row["text"], "label": meta.get("label"),
            "gain": float(meta.get("gain") or 0.0),
            "vector": store.unpack_vector(row["vector"]), "similarity": score})
    from potato.rag.icl_select import select
    chosen = select(candidates, max_total=k, min_per_label=min_per_label,
                    gain_weight=gain_weight, mmr_lambda=mmr_lambda)
    return [{"text": c["text"], "label": c["label"], "score": c["_rel"],
             "similarity": c["similarity"], "gain": c["gain"]} for c in chosen]


def retrieve_codebook_units(
    task_dir: str, project: str, instance_text: str, *,
    k: int = 5, endpoint: Optional[BaseEmbeddingEndpoint] = None,
    config: Any = None, query_vec=None,
) -> List[Dict[str, Any]]:
    """Rank codebook units by relevance to ``instance_text``.

    Output is grouped by code (Amendment minor): one entry per code with its
    best score and the matching fields highlighted, best code first. This
    powers the "which parts of the codebook are relevant to this instance"
    side feature. It NEVER filters the classification label set — callers
    use it for ranking/highlighting only.
    """
    if not (instance_text or "").strip():
        return []
    ep = indexer._endpoint_for(task_dir, project, config, endpoint)
    indexer.ensure_indexed(task_dir, project, endpoint=ep, config=config)
    pin = store.get_pin(task_dir, project)
    if pin is None:
        return []

    qv = query_vec if query_vec is not None else ep.embed_one(instance_text)
    # Over-fetch chunks, then collapse to top-k codes.
    hits = store.search(task_dir, project, qv, source_type=SOURCE_CODE,
                        k=max(50, k * 10), model=pin["model"])
    if not hits:
        return []

    from potato.codebook.codebook import Codebook
    cb = Codebook.load(task_dir, project)

    grouped: Dict[str, Dict[str, Any]] = {}
    for row, score in hits:
        cid = row["source_ref"]
        entry = grouped.get(cid)
        if entry is None:
            detail = cb.detail(cid)
            entry = {
                "code_id": cid,
                "name": detail["name"] if detail else None,
                "score": score,
                "fields": [],
            }
            grouped[cid] = entry
        entry["score"] = max(entry["score"], score)
        entry["fields"].append({
            "field": row["field"], "text": row["text"], "score": score})

    ranked = sorted(grouped.values(), key=lambda e: e["score"], reverse=True)
    for entry in ranked:
        entry["fields"].sort(key=lambda f: f["score"], reverse=True)
    return ranked[:k]
