"""
Codebook service — the single, audited mutation path.

All codebook writes (human *or* LLM, in standard / solo / QDA mode) go
through here so they share one audit trail (`created_by`), one set of
invariants (no duplicate siblings, no cycles, recursive delete), and one
change-notification hook (used by ICL to invalidate its prompt cache —
registered via `register_change_listener` to avoid a hard import edge).

Phase 1 ops: create / rename / recolor / move_under / delete.
merge / split are Phase 2.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from potato.codebook import store
from potato.codebook.codebook import Codebook

logger = logging.getLogger(__name__)


class CodebookError(Exception):
    """Base for codebook mutation errors."""


class CodeNotFound(CodebookError):
    pass


class DuplicateCodeError(CodebookError):
    pass


class CodebookCycleError(CodebookError):
    pass


# Change listeners: called (task_dir, project) after any successful
# mutation. ICL registers one to invalidate its prompt cache. Kept as a
# registry so codebook has no import dependency on the ICL/AI layer.
_CHANGE_LISTENERS: List[Callable[[str, str], None]] = []


def register_change_listener(fn: Callable[[str, str], None]) -> None:
    if fn not in _CHANGE_LISTENERS:
        _CHANGE_LISTENERS.append(fn)


def clear_change_listeners() -> None:
    """Tests only — the registry is process-global."""
    _CHANGE_LISTENERS.clear()


def _notify(task_dir: str, project: str) -> None:
    for fn in list(_CHANGE_LISTENERS):
        try:
            fn(task_dir, project)
        except Exception:  # a listener must never break a mutation
            logger.exception("codebook change listener failed")


def _require(task_dir: str, code_id: str) -> Dict[str, Any]:
    code = store.get_code(task_dir, code_id)
    if code is None:
        raise CodeNotFound(f"Code {code_id} not found")
    return code


def create_code(
    task_dir: str,
    *,
    project: str,
    name: str,
    created_by: str,
    color: Optional[str] = None,
    parent_id: str = store.ROOT,
    code_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    actor_kind: str = "human",
) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise CodebookError("Code name must not be empty")
    if parent_id != store.ROOT and store.get_code(task_dir, parent_id) is None:
        raise CodeNotFound(f"Parent code {parent_id} not found")
    if store.find_code(task_dir, project, parent_id, name) is not None:
        raise DuplicateCodeError(
            f"A code named {name!r} already exists at this level")
    siblings = store.children_of(task_dir, project, parent_id)
    # A new code changes the option set -> bump the project revision and
    # stamp the code with the revision it first appeared in.
    from potato.codebook import revision
    from potato.codebook import changelog
    new_rev = revision.bump_revision(task_dir, project)
    code = store.insert_code(
        task_dir, project=project, name=name, created_by=created_by,
        color=color, parent_id=parent_id, sort_order=len(siblings),
        code_id=code_id, created_revision=new_rev, details=details,
    )
    # Log creation so the version history is complete (previously only
    # rename/recolor/move/delete were logged).
    changelog.log_change(
        task_dir, project=project, op="create", code_id=code["id"],
        old_value=None, new_value=name, actor=created_by,
        actor_kind=actor_kind, revision=new_rev)
    _notify(task_dir, project)
    return code


def _restamp(task_dir: str, project: str, code_ids: List[str]) -> None:
    """Re-flag exactly the instances whose live links touch `code_ids`
    so the (B) review worklist resurfaces them (soft, dismissible)."""
    from potato.codebook import revision
    affected: List[str] = []
    seen = set()
    for cid in code_ids:
        for aid in store.affected_annotation_ids(task_dir, project, cid):
            if aid not in seen:
                seen.add(aid)
                affected.append(aid)
    revision.touch_instances(task_dir, project, affected)


def rename_code(
    task_dir: str, code_id: str, *, new_name: str, project: str,
    actor: str = "system", actor_kind: str = "human",
) -> Dict[str, Any]:
    new_name = (new_name or "").strip()
    if not new_name:
        raise CodebookError("Code name must not be empty")
    code = _require(task_dir, code_id)
    old_name = code["name"]
    clash = store.find_code(
        task_dir, project, code["parent_id"], new_name)
    if clash is not None and clash["id"] != code_id:
        raise DuplicateCodeError(
            f"A code named {new_name!r} already exists at this level")
    updated = store.update_code(task_dir, code_id, name=new_name)
    # Any codebook change bumps the revision (provenance: an instance
    # labeled before this change is flagged stale on revisit).
    from potato.codebook import revision
    from potato.codebook import changelog
    new_rev = revision.bump_revision(task_dir, project)
    changelog.log_change(
        task_dir, project=project, op="rename", code_id=code_id,
        old_value=old_name, new_value=new_name, actor=actor,
        actor_kind=actor_kind, revision=new_rev)
    _restamp(task_dir, project, [code_id])
    _notify(task_dir, project)
    return updated


def recolor_code(
    task_dir: str, code_id: str, *, color: str, project: str,
    actor: str = "system", actor_kind: str = "human",
) -> Dict[str, Any]:
    code = _require(task_dir, code_id)
    updated = store.update_code(task_dir, code_id, color=color)
    from potato.codebook import revision
    from potato.codebook import changelog
    new_rev = revision.bump_revision(task_dir, project)
    changelog.log_change(
        task_dir, project=project, op="recolor", code_id=code_id,
        old_value=code.get("color"), new_value=color, actor=actor,
        actor_kind=actor_kind, revision=new_rev)
    _restamp(task_dir, project, [code_id])
    _notify(task_dir, project)
    return updated


def update_code_fields(
    task_dir: str, code_id: str, *, details: Dict[str, Any], project: str,
    actor: str = "system", actor_kind: str = "human",
) -> Dict[str, Any]:
    """Update one or more structured fields (definition / clarification /
    negative_clarification / positive_example(+why) / negative_example
    (+why)). Every field changed here alters what the LLM sees, so this
    is a prompt-affecting edit: it bumps the revision once, logs one
    change row per field (full old->new for the version history), and
    softly re-flags the instances labeled with this code for review."""
    code = _require(task_dir, code_id)
    # Keep only known rich fields whose value actually changes.
    changed: Dict[str, Any] = {}
    for field in store.RICH_FIELDS:
        if field not in details:
            continue
        new_val = store._clean(details[field])
        if new_val != code.get(field):
            changed[field] = new_val
    if not changed:
        return code  # no-op: nothing to update, no revision churn

    updated = store.update_code(task_dir, code_id, details=changed)
    from potato.codebook import revision
    from potato.codebook import changelog
    new_rev = revision.bump_revision(task_dir, project)
    for field, new_val in changed.items():
        changelog.log_change(
            task_dir, project=project, op=f"edit_{field}", code_id=code_id,
            old_value=code.get(field), new_value=new_val, actor=actor,
            actor_kind=actor_kind, revision=new_rev)
    _restamp(task_dir, project, [code_id])
    _notify(task_dir, project)
    return updated


def _subtree_ids(task_dir: str, project: str, root_id: str) -> List[str]:
    cb = Codebook.load(task_dir, project)
    out: List[str] = []

    def walk(cid: str) -> None:
        out.append(cid)
        for kid in cb.children(cid):
            walk(kid["id"])

    walk(root_id)
    return out


def move_under(
    task_dir: str, code_id: str, *, new_parent_id: str, project: str,
    actor: str = "system", actor_kind: str = "human",
) -> Dict[str, Any]:
    code = _require(task_dir, code_id)
    if new_parent_id == code_id:
        raise CodebookCycleError("A code cannot be its own parent")
    if new_parent_id != store.ROOT:
        if store.get_code(task_dir, new_parent_id) is None:
            raise CodeNotFound(f"Parent code {new_parent_id} not found")
        if new_parent_id in _subtree_ids(task_dir, project, code_id):
            raise CodebookCycleError(
                "Cannot move a code under one of its own descendants")
    clash = store.find_code(
        task_dir, project, new_parent_id, code["name"])
    if clash is not None and clash["id"] != code_id:
        raise DuplicateCodeError(
            f"A code named {code['name']!r} already exists at the target")
    siblings = store.children_of(task_dir, project, new_parent_id)
    old_parent = code["parent_id"]
    updated = store.update_code(
        task_dir, code_id,
        parent_id=new_parent_id, sort_order=len(siblings))
    from potato.codebook import revision
    from potato.codebook import changelog
    new_rev = revision.bump_revision(task_dir, project)
    changelog.log_change(
        task_dir, project=project, op="move", code_id=code_id,
        old_value=old_parent, new_value=new_parent_id, actor=actor,
        actor_kind=actor_kind, revision=new_rev)
    _restamp(task_dir, project, [code_id])
    _notify(task_dir, project)
    return updated


def delete_code(
    task_dir: str, code_id: str, *, project: str,
    actor: str = "system", actor_kind: str = "human",
) -> int:
    """Delete a code and its entire subtree (and annotation links).
    Returns the number of code rows removed."""
    code = _require(task_dir, code_id)
    ids = _subtree_ids(task_dir, project, code_id)
    # Capture affected instances BEFORE the (existing) hard delete so
    # the worklist can still resurface them.
    from potato.codebook import revision
    from potato.codebook import changelog
    affected: List[str] = []
    seen = set()
    for cid in ids:
        for aid in store.affected_annotation_ids(task_dir, project, cid):
            if aid not in seen:
                seen.add(aid)
                affected.append(aid)
    n = store.delete_codes(task_dir, ids)
    # Removing a code also changes the option set.
    new_rev = revision.bump_revision(task_dir, project)
    changelog.log_change(
        task_dir, project=project, op="delete", code_id=code_id,
        old_value=code["name"], new_value=None, actor=actor,
        actor_kind=actor_kind, revision=new_rev)
    revision.touch_instances(task_dir, project, affected)
    _notify(task_dir, project)
    return n


# ---- annotation <-> code links (audited, same notify path) -------------

def apply_code(
    task_dir: str,
    *,
    project: str,
    annotation_id: str,
    code_id: str,
    created_by: str,
    started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
) -> None:
    _require(task_dir, code_id)
    store.link_annotation(
        task_dir, project=project, annotation_id=annotation_id,
        code_id=code_id, created_by=created_by,
        started_at=started_at, ended_at=ended_at)


def remove_code(
    task_dir: str, *, annotation_id: str, code_id: str
) -> bool:
    return store.unlink_annotation(task_dir, annotation_id, code_id)


def codes_on(task_dir: str, annotation_id: str) -> List[Dict[str, Any]]:
    return store.codes_for_annotation(task_dir, annotation_id)


# ---- Phase 2 (C): retroactive merge / split (append-only) --------------

def merge_codes(
    task_dir: str, *, project: str, src_id: str, dst_id: str,
    actor: str = "system", actor_kind: str = "human",
) -> Dict[str, Any]:
    """Fold `src` into `dst`: every live annotation link to src is
    re-pointed at dst (idempotent if the annotation already had dst),
    src's links are invalidated (not deleted), and src is archived (it
    leaves the palette/ICL prompt but its row + history survive).
    Affected instances are softly re-flagged for review."""
    if src_id == dst_id:
        raise CodebookError("Cannot merge a code into itself")
    src = _require(task_dir, src_id)
    dst = _require(task_dir, dst_id)
    from potato.codebook import revision, changelog

    affected = store.affected_annotation_ids(task_dir, project, src_id)
    new_rev = revision.bump_revision(task_dir, project)
    change_id = changelog.log_change(
        task_dir, project=project, op="merge", code_id=src_id,
        related_code_id=dst_id, old_value=src["name"],
        new_value=dst["name"], actor=actor, actor_kind=actor_kind,
        revision=new_rev)
    for aid in affected:
        link = store.get_link(task_dir, aid, src_id) or {}
        store.set_link_live(
            task_dir, project=project, annotation_id=aid,
            code_id=dst_id, created_by=link.get("created_by", actor),
            started_at=link.get("started_at"),
            ended_at=link.get("ended_at"))
    store.invalidate_links(
        task_dir, project=project, code_id=src_id, change_id=change_id)
    store.archive_code(task_dir, src_id)
    revision.touch_instances(task_dir, project, affected)
    _notify(task_dir, project)
    return {"merged": len(affected), "src_id": src_id,
            "dst_id": dst_id, "change_id": change_id}


def split_code(
    task_dir: str, *, project: str, src_id: str, annotator: str,
    new_name: Optional[str] = None, target_id: Optional[str] = None,
    actor: str = "system", actor_kind: str = "human",
) -> Dict[str, Any]:
    """Split `src` BY ANNOTATOR: move just `annotator`'s live links from
    src to a target code (existing `target_id`, or a new code named
    `new_name`). src stays live for other annotators; it is archived
    only if it ends up with no live links and no children."""
    src = _require(task_dir, src_id)
    if not annotator:
        raise CodebookError("An annotator must be given to split by")
    from potato.codebook import revision, changelog

    if target_id:
        target = _require(task_dir, target_id)
    elif new_name:
        target = create_code(
            task_dir, project=project, name=new_name,
            created_by=actor, parent_id=src["parent_id"])
    else:
        raise CodebookError("Provide either target_id or new_name")

    affected = store.affected_annotation_ids(
        task_dir, project, src_id, created_by=annotator)
    new_rev = revision.bump_revision(task_dir, project)
    change_id = changelog.log_change(
        task_dir, project=project, op="split", code_id=src_id,
        related_code_id=target["id"], old_value=src["name"],
        new_value=f"{target['name']} [{annotator}]", actor=actor,
        actor_kind=actor_kind, revision=new_rev)
    for aid in affected:
        link = store.get_link(task_dir, aid, src_id) or {}
        store.set_link_live(
            task_dir, project=project, annotation_id=aid,
            code_id=target["id"], created_by=annotator,
            started_at=link.get("started_at"),
            ended_at=link.get("ended_at"))
    store.invalidate_links(
        task_dir, project=project, code_id=src_id,
        change_id=change_id, created_by=annotator)
    # Archive src only if nothing live remains and it has no children.
    remaining = store.affected_annotation_ids(task_dir, project, src_id)
    children = Codebook.load(task_dir, project).children(src_id)
    if not remaining and not children:
        store.archive_code(task_dir, src_id)
    revision.touch_instances(task_dir, project, affected)
    _notify(task_dir, project)
    return {"moved": len(affected), "src_id": src_id,
            "target_id": target["id"], "change_id": change_id}
