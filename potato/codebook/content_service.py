"""
Codebook content service — the single audited path for prose edits.

Mirrors `service.py` (which owns *structural* code ops) for the living
document's *content*. One function, `save_scope`, is the only place that
mutates a scope's blocks, and it does the whole job atomically (under a
process lock, since the project DB connection is shared and not safe for
overlapping multi-statement writes):

  1. optimistic compare-and-swap on the scope version (stale -> 409);
  2. replace the scope's live blocks (append-only: old set archived);
  3. classify the edit as semantic (a meaning-bearing block changed) or
     cosmetic, honoring an explicit `minor` override;
  4. bump the content-revision (always) and semantic-revision (iff
     semantic) counters — kept separate from the structural
     `codebook_revision` so label-based staleness is untouched;
  5. append a `content_edit` row to the change log;
  6. snapshot the post-state (for history / diff / restore);
  7. re-flag affected instances for soft review when semantic;
  8. fire the codebook change listeners (ICL / distiller refresh) and the
     event bus (future live broadcast).

Scopes: a *code* (code_id) or a document-level *section* (one of
`blocks.DOC_SECTIONS`). The label list is never touched here — content is
strictly additive to `codes`.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from potato.codebook import blocks, changelog, snapshots
from potato.codebook import revision as _revision
from potato.codebook import service as _service
from potato.codebook import events as _events
from potato.codebook.codebook import Codebook

logger = logging.getLogger(__name__)

# One global lock: codebook content saves are infrequent (minutes/hours)
# and short, so serializing them across the process is cheap and makes the
# optimistic check+replace atomic on the shared connection. Different
# scopes still all succeed (serialized, not blocked).
_SAVE_LOCK = threading.RLock()

_VALID_SCOPE_KINDS = ("code", "section")


class ContentError(Exception):
    """Bad content request (unknown scope, invalid section, etc.)."""


class StaleContentError(Exception):
    """Optimistic-concurrency conflict: the caller's base version no longer
    matches the scope. Carries the current version and the current live
    blocks so the API can return a 409 with a diff to rebase onto."""

    def __init__(self, current_version: int,
                 current_blocks: List[Dict[str, Any]]):
        super().__init__(
            f"scope changed (now at version {current_version})")
        self.current_version = current_version
        self.current_blocks = current_blocks


def _scope_args(scope_kind: str, scope_id: str) -> Tuple[str, str]:
    if scope_kind not in _VALID_SCOPE_KINDS:
        raise ContentError(f"unknown scope_kind {scope_kind!r}")
    if scope_kind == "code":
        if not scope_id:
            raise ContentError("a code scope needs a code_id")
        return scope_id, blocks.NO_SECTION
    if scope_id not in blocks.DOC_SECTIONS:
        raise ContentError(
            f"unknown document section {scope_id!r}; "
            f"valid: {', '.join(blocks.DOC_SECTIONS)}")
    return blocks.NO_CODE, scope_id


def _sem_signature(block_list: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """The meaning-bearing slice of a block set, for semantic-change
    detection: (block_type, body) for every semantic-typed block, in
    order. Cosmetic blocks (examples, notes, background…) are ignored."""
    return [
        (b.get("block_type"), (b.get("body_md") or "").strip())
        for b in block_list
        if blocks.is_semantic(b.get("block_type") or "")
    ]


# ---- read ----------------------------------------------------------------

def block_types_vocab() -> List[Dict[str, Any]]:
    """The typed-block vocabulary as data, for a data-driven UI picker."""
    out = []
    for key, meta in blocks.BLOCK_TYPES.items():
        out.append({
            "key": key,
            "heading": meta["heading"],
            "semantic": bool(meta.get("semantic")),
            "order": meta.get("order", 999),
        })
    out.sort(key=lambda d: d["order"])
    return out


def get_scope(
    task_dir: str, project: str, scope_kind: str, scope_id: str
) -> Dict[str, Any]:
    code_id, section = _scope_args(scope_kind, scope_id)
    return {
        "scope_kind": scope_kind,
        "scope_id": scope_id,
        "blocks": blocks.list_blocks(
            task_dir, project, code_id=code_id, section=section),
        "scope_version": blocks.scope_version(
            task_dir, project, code_id=code_id, section=section),
    }


def get_document(task_dir: str, project: str) -> Dict[str, Any]:
    """Assemble the whole living document: document-level sections plus
    per-code blocks joined onto the live code tree (in tree order)."""
    cb = Codebook.load(task_dir, project)

    doc_sections = []
    for sect in blocks.DOC_SECTIONS:
        doc_sections.append({
            "section": sect,
            "title": blocks.DOC_SECTION_TITLES.get(sect, sect),
            "blocks": blocks.list_blocks(
                task_dir, project, section=sect),
            "scope_version": blocks.scope_version(
                task_dir, project, section=sect),
        })

    codes = []

    def walk(node: Dict[str, Any], depth: int) -> None:
        codes.append({
            "id": node["id"],
            "name": node["name"],
            "color": node.get("color"),
            "depth": depth,
            "blocks": blocks.list_blocks(
                task_dir, project, code_id=node["id"]),
            "scope_version": blocks.scope_version(
                task_dir, project, code_id=node["id"]),
        })
        for child in node.get("children", []):
            walk(child, depth + 1)

    for root in cb.as_tree():
        walk(root, 0)

    return {
        "revision": _revision.current_revision(task_dir, project),
        "content_revision": blocks.current_content_revision(
            task_dir, project),
        "sem_revision": blocks.current_sem_revision(task_dir, project),
        "doc_sections": doc_sections,
        "codes": codes,
        "block_types": block_types_vocab(),
        "doc_section_keys": list(blocks.DOC_SECTIONS),
    }


# ---- write ---------------------------------------------------------------

def save_scope(
    task_dir: str, *,
    project: str,
    scope_kind: str,
    scope_id: str,
    blocks_in: List[Dict[str, Any]],
    base_version: int,
    actor: str,
    actor_kind: str = "human",
    minor: bool = False,
) -> Dict[str, Any]:
    """Replace one scope's content. See module docstring for the full
    sequence. Raises StaleContentError on an optimistic-version conflict."""
    code_id, section = _scope_args(scope_kind, scope_id)

    with _SAVE_LOCK:
        old_blocks = blocks.list_blocks(
            task_dir, project, code_id=code_id, section=section)
        semantic = (
            not minor
            and _sem_signature(old_blocks) != _sem_signature(blocks_in))

        try:
            new_live = blocks.replace_scope_blocks(
                task_dir, project=project, code_id=code_id, section=section,
                blocks=blocks_in, actor=actor, base_version=base_version)
        except blocks.StaleScopeError as e:
            current = blocks.list_blocks(
                task_dir, project, code_id=code_id, section=section)
            raise StaleContentError(e.current_version, current)

        meta = blocks.bump_content_meta(
            task_dir, project, semantic=semantic)
        struct_rev = _revision.current_revision(task_dir, project)

        change_id = changelog.log_change(
            task_dir, project=project, op="content_edit",
            code_id=(scope_id if scope_kind == "code" else None),
            old_value=f"{scope_kind}:{scope_id}",
            new_value=("semantic" if semantic else "minor"),
            actor=actor, actor_kind=actor_kind,
            revision=meta["content_revision"])

        snapshots.record_snapshot(
            task_dir, project=project, scope_kind=scope_kind,
            scope_id=scope_id, blocks=new_live, semantic=semantic,
            revision=struct_rev, sem_revision=meta["sem_revision"],
            change_id=change_id, actor=actor, actor_kind=actor_kind)

        # Semantic prose change on a code -> softly re-flag the instances
        # coded with it (reuses the structural restamp machinery).
        if semantic and scope_kind == "code":
            _service._restamp(task_dir, project, [scope_id])

        # ICL / distiller prompt-cache invalidation.
        _service._notify(task_dir, project)

    _events.emit(_events.CodebookEvent(
        kind="content_saved", project=project, scope_kind=scope_kind,
        scope_id=scope_id, revision=struct_rev,
        sem_revision=meta["sem_revision"], actor=actor,
        payload={"semantic": semantic,
                 "content_revision": meta["content_revision"]}))

    new_version = blocks.scope_version(
        task_dir, project, code_id=code_id, section=section)
    return {
        "scope_kind": scope_kind,
        "scope_id": scope_id,
        "blocks": new_live,
        "scope_version": new_version,
        "semantic": semantic,
        "revision": struct_rev,
        "content_revision": meta["content_revision"],
        "sem_revision": meta["sem_revision"],
        "change_id": change_id,
    }


def restore_snapshot(
    task_dir: str, *, project: str, snapshot_id: str, actor: str,
    actor_kind: str = "human",
) -> Dict[str, Any]:
    """Restore an older snapshot by re-saving its blocks through the normal
    path (so the restore is itself audited + snapshotted — never a
    destructive rewind). Uses the scope's *current* version as the base, so
    a restore that races a newer edit raises StaleContentError."""
    snap = snapshots.get_snapshot(task_dir, snapshot_id)
    if not snap or snap["project"] != project:
        raise ContentError("snapshot not found")
    code_id, section = _scope_args(snap["scope_kind"], snap["scope_id"])
    base = blocks.scope_version(
        task_dir, project, code_id=code_id, section=section)
    return save_scope(
        task_dir, project=project, scope_kind=snap["scope_kind"],
        scope_id=snap["scope_id"], blocks_in=snap["blocks"],
        base_version=base, actor=actor, actor_kind=actor_kind)


def propose_content_edit(
    task_dir: str, *, project: str, scope_kind: str, scope_id: str,
    blocks_in: List[Dict[str, Any]], base_version: int, actor: str,
    actor_kind: str = "human", minor: bool = False,
) -> Dict[str, Any]:
    """Queue a content edit for human confirmation (locked-mode annotators
    and LLM agents). Routes through the SAME proposal store the structural
    ops use; op='content_edit'. Applied later via apply_content_proposal."""
    _scope_args(scope_kind, scope_id)  # validate
    return changelog.record_proposal(
        task_dir, project=project, op="content_edit",
        payload={
            "scope_kind": scope_kind, "scope_id": scope_id,
            "blocks": blocks_in, "base_version": base_version,
            "minor": minor,
        },
        actor=actor, actor_kind=actor_kind)


def apply_content_proposal(
    task_dir: str, *, project: str, payload: Dict[str, Any], actor: str,
) -> Dict[str, Any]:
    """Execute a confirmed content_edit proposal. Rebases onto the scope's
    current version (the proposal's stored base may be stale by now) so a
    confirm after newer edits does not silently clobber them — it raises
    StaleContentError if the proposed blocks were authored against content
    that has since changed materially. Callers surface that to the admin."""
    scope_kind = payload["scope_kind"]
    scope_id = payload["scope_id"]
    code_id, section = _scope_args(scope_kind, scope_id)
    stored_base = int(payload.get("base_version", 0))
    current = blocks.scope_version(
        task_dir, project, code_id=code_id, section=section)
    if stored_base != current:
        # The scope moved since the proposal was authored.
        raise StaleContentError(
            current,
            blocks.list_blocks(
                task_dir, project, code_id=code_id, section=section))
    return save_scope(
        task_dir, project=project, scope_kind=scope_kind, scope_id=scope_id,
        blocks_in=payload["blocks"], base_version=current, actor=actor,
        actor_kind="model", minor=bool(payload.get("minor")))
