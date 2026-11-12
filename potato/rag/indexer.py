"""
RAG corpus indexing — codebook units (Phase C) and the lazy catch-up that
keeps embeddings fresh.

Chunking philosophy: one chunk per *retrievable codebook unit* so the side
feature can say which specific definition / clarification / exclusion rule /
example is relevant to an instance. Every chunk's ``source_ref`` is the
``code_id`` so the scoped changelog listener can invalidate exactly one
code's chunks (mirroring the scoped re-review, not flush-everything).

Freshness is two-level and restart-safe:
- chunk TEXT is kept current by re-chunking in the listener (cheap, no
  embedding), tracked by ``rag_meta.index_revision`` (the changelog bookmark);
- chunk VECTORS are recomputed by ``catch_up`` (lazy, at retrieval) for any
  row flagged ``stale`` — so an outdated definition is never retrieved.

The embedding model is PINNED per project (Amendment 1): the endpoint used
is always the pinned (provider, model); if it is unreachable we raise rather
than silently embed with a different model.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from potato.codebook.codebook import Codebook
from potato.rag import store
from potato.rag.embedding_endpoint import (
    BaseEmbeddingEndpoint,
    EmbeddingEndpointFactory,
)
from potato.rag.store import SOURCE_CODE, SOURCE_ICL

logger = logging.getLogger(__name__)


# ---- codebook chunking ---------------------------------------------------

def code_units(detail: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(field, text) chunks for one code's effective detail.

    ``field`` carries a per-item discriminator for the list fields
    (``exclusion_rule:0`` …) so each unit gets a distinct stable id while
    still sharing the code's ``source_ref``. The code name is folded into
    every chunk's text so a field is grounded to its code at retrieval.
    """
    name = detail.get("name") or ""
    units: List[Tuple[str, str]] = []

    definition = detail.get("definition")
    units.append(("summary", f"{name}: {definition}" if definition else name))

    if detail.get("clarification"):
        units.append(("clarification",
                      f"{name} — include: {detail['clarification']}"))
    if detail.get("negative_clarification"):
        units.append(("negative_clarification",
                      f"{name} — exclude: {detail['negative_clarification']}"))

    for i, rule in enumerate(detail.get("exclusion_rules") or []):
        if str(rule).strip():
            units.append((f"exclusion_rule:{i}",
                          f"{name} — do not apply when: {rule}"))

    for label, key in (("positive", "positive_examples"),
                       ("negative", "negative_examples")):
        for i, ex in enumerate(detail.get(key) or []):
            if not isinstance(ex, dict):
                continue
            text = (ex.get("text") or "").strip()
            if not text:
                continue
            why = (ex.get("why") or "").strip()
            suffix = f" ({why})" if why else ""
            units.append((f"{label}_example:{i}",
                          f"{name} {label} example: {text}{suffix}"))
    return units


# ---- endpoint resolution (pin-aware) -------------------------------------

def _endpoint_for(
    task_dir: str, project: str, config: Any,
    endpoint: Optional[BaseEmbeddingEndpoint],
) -> BaseEmbeddingEndpoint:
    """Resolve the embedding endpoint for this project, honoring the pin.

    - explicit endpoint -> validated against the pin (RagModelMismatch).
    - pinned, no endpoint -> rebuild the pinned (provider, model); raises
      EmbeddingError if unreachable (never a silent different-model fallback).
    - unpinned, no endpoint -> create_default (auto) to pick the model.
    """
    if endpoint is not None:
        store.check_pin(task_dir, project, endpoint.key)
        return endpoint
    pin = store.get_pin(task_dir, project)
    if pin:
        provider, _, model = pin["model"].partition(":")
        return EmbeddingEndpointFactory.create(provider, model=model, config=config)
    return EmbeddingEndpointFactory.create_default(config=config)


# ---- (re)chunking --------------------------------------------------------

def reindex_code(
    task_dir: str, project: str, code_id: str, *,
    cb: Optional[Codebook] = None,
) -> None:
    """Re-chunk a single code's units as STALE (delete-then-insert so a
    shrunk list field leaves no orphans). Embedding is deferred to
    ``catch_up``. If the code is gone/archived, just drop its chunks."""
    cb = cb or Codebook.load(task_dir, project)
    store.delete_chunks(task_dir, project, source_ref=code_id,
                        source_type=SOURCE_CODE)
    detail = cb.detail(code_id)
    if not detail:
        return
    for field, text in code_units(detail):
        store.upsert_chunk(
            task_dir, project=project, source_type=SOURCE_CODE,
            source_ref=code_id, field=field, text=text,
            vector=None, model=None, dim=None)  # stale until catch_up


def index_codebook_full(
    task_dir: str, project: str, *,
    endpoint: Optional[BaseEmbeddingEndpoint] = None, config: Any = None,
) -> int:
    """(Re)build the whole codebook corpus, embed it, pin the model, and set
    the changelog bookmark to the current revision. Returns chunks embedded."""
    from potato.codebook import current_revision

    ep = _endpoint_for(task_dir, project, config, endpoint)
    cb = Codebook.load(task_dir, project)
    store.delete_chunks(task_dir, project, source_type=SOURCE_CODE)
    for detail in cb.details_in_order():
        cid = detail["id"]
        for field, text in code_units(detail):
            store.upsert_chunk(
                task_dir, project=project, source_type=SOURCE_CODE,
                source_ref=cid, field=field, text=text,
                vector=None, model=None, dim=None)
    n = catch_up(task_dir, project, endpoint=ep, config=config)
    # Bookmark current revision so the listener only folds in *future*
    # edits (the full build already reflects everything up to here).
    if store.get_pin(task_dir, project) is not None:
        store.set_index_revision(task_dir, project, current_revision(task_dir, project))
    return n


def catch_up(
    task_dir: str, project: str, *,
    endpoint: Optional[BaseEmbeddingEndpoint] = None, config: Any = None,
) -> int:
    """Embed every stale chunk for the project under the pinned model.

    Establishes the pin on first embed; on later calls ``ensure_pin``
    enforces the pin (RagModelMismatch if the endpoint's model/dim differ).
    Returns the number of chunks (re)embedded.
    """
    stale = [c for c in store.stale_chunks(task_dir, project) if c["text"]]
    if not stale:
        return 0
    ep = _endpoint_for(task_dir, project, config, endpoint)
    vecs = ep.embed([c["text"] for c in stale])
    dim = int(vecs[0].shape[0])
    store.ensure_pin(task_dir, project, ep.key, dim)  # pin or enforce
    for chunk, vec in zip(stale, vecs):
        store.set_chunk_vector(task_dir, chunk["id"], vector=vec,
                               model=ep.key, dim=dim)
    return len(stale)


def sync_icl_entries(
    task_dir: str, project: str, entries: List[Dict[str, Any]], *,
    endpoint: Optional[BaseEmbeddingEndpoint] = None, config: Any = None,
) -> int:
    """Mirror the validated ICL library into the RAG corpus (Phase E).

    One chunk per entry (source_type='icl_example', source_ref=instance_id),
    embedding the entry's SOURCE TEXT (the thing being classified — not its
    label/reasoning). ``meta`` carries {label, gain} for the selector.
    Unchanged + already-embedded entries are skipped (content hash + meta);
    changed entries are re-chunked stale; dropped entries are deleted. Then
    catch_up embeds the stale ones. Returns chunks (re)embedded.
    """
    import json

    existing = {c["source_ref"]: c for c in
                store.get_chunks(task_dir, project, source_type=SOURCE_ICL)}
    keep = set()
    for e in entries:
        iid = e["instance_id"]
        keep.add(iid)
        meta = json.dumps({"label": e.get("label"),
                           "gain": float(e.get("gain") or 0.0)}, sort_keys=True)
        prev = existing.get(iid)
        if (prev is not None and prev["vector"] is not None
                and prev["content_hash"] == store.content_hash(e["text"])
                and prev["meta"] == meta):
            continue  # unchanged and already embedded
        store.upsert_chunk(
            task_dir, project=project, source_type=SOURCE_ICL,
            source_ref=iid, field=None, text=e["text"],
            vector=None, model=None, dim=None, meta=meta)  # stale
    for iid in existing:
        if iid not in keep:
            store.delete_chunks(task_dir, project, source_ref=iid,
                                source_type=SOURCE_ICL)
    return catch_up(task_dir, project, endpoint=endpoint, config=config)


def ensure_indexed(
    task_dir: str, project: str, *,
    endpoint: Optional[BaseEmbeddingEndpoint] = None, config: Any = None,
) -> None:
    """Lazy entry used before a query: full-build an unindexed project,
    else catch up any stale chunks."""
    if store.get_pin(task_dir, project) is None:
        index_codebook_full(task_dir, project, endpoint=endpoint, config=config)
    else:
        catch_up(task_dir, project, endpoint=endpoint, config=config)


def reindex_project(
    task_dir: str, project: str, *,
    endpoint: Optional[BaseEmbeddingEndpoint] = None, config: Any = None,
) -> int:
    """Explicit model-switch entry point (Amendment 1): drop the pin + all
    chunks and re-embed the whole project under the (new) model. This is the
    ONLY sanctioned way to change a project's embedding model."""
    store.clear_project(task_dir, project)
    return index_codebook_full(task_dir, project, endpoint=endpoint, config=config)


# ---- scoped changelog invalidation (mirrors _on_codebook_change) ---------

# Ops that change a code's prompt-facing TEXT (and thus its embeddings).
# recolor/move are excluded (no text change); create IS included so a new
# code becomes retrievable (unlike the re-review, which skips create).
_TEXT_OPS = {"create", "rename", "delete", "merge", "split"}


def _affected(changes: List[Dict[str, Any]]) -> Dict[str, str]:
    """code_id -> action ('delete' | 'reindex') for a batch of changelog rows."""
    out: Dict[str, str] = {}
    for ch in changes:
        op = ch.get("op") or ""
        if not (op in _TEXT_OPS or op.startswith("edit_")):
            continue
        cid = ch.get("code_id")
        if cid:
            # merge archives the source code -> drop its chunks.
            out[cid] = "delete" if op in ("delete", "merge") else \
                out.get(cid, "reindex")
        rel = ch.get("related_code_id")
        if op == "split" and rel:
            out.setdefault(rel, "reindex")
    return out


def on_codebook_change(task_dir: str, project: str) -> None:
    """Scoped RAG invalidation. No-op until the project is indexed (has a
    pin). Re-chunks only the affected codes as stale and advances the
    persisted bookmark; vectors are recomputed lazily by ``catch_up``."""
    try:
        if store.get_pin(task_dir, project) is None:
            return
        from potato.codebook import changelog, current_revision
        baseline = store.get_index_revision(task_dir, project) or 0
        cur = current_revision(task_dir, project)
        if cur <= baseline:
            return
        affected = _affected(changelog.changes_since(task_dir, project, baseline))
        if affected:
            cb = Codebook.load(task_dir, project)
            for cid, action in affected.items():
                if action == "delete":
                    store.delete_chunks(task_dir, project, source_ref=cid,
                                        source_type=SOURCE_CODE)
                else:
                    reindex_code(task_dir, project, cid, cb=cb)
        store.set_index_revision(task_dir, project, cur)
    except Exception:  # never break a codebook mutation
        logger.debug("RAG codebook sync skipped", exc_info=True)


def install_rag_codebook_sync() -> None:
    """Register the scoped RAG listener on the codebook change seam
    (idempotent — register_change_listener dedups by function identity),
    alongside the ICL-sync listener."""
    from potato.codebook.service import register_change_listener
    register_change_listener(on_codebook_change)
