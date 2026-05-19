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
    new_rev = revision.bump_revision(task_dir, project)
    code = store.insert_code(
        task_dir, project=project, name=name, created_by=created_by,
        color=color, parent_id=parent_id, sort_order=len(siblings),
        code_id=code_id, created_revision=new_rev,
    )
    _notify(task_dir, project)
    return code


def rename_code(
    task_dir: str, code_id: str, *, new_name: str, project: str
) -> Dict[str, Any]:
    new_name = (new_name or "").strip()
    if not new_name:
        raise CodebookError("Code name must not be empty")
    code = _require(task_dir, code_id)
    clash = store.find_code(
        task_dir, project, code["parent_id"], new_name)
    if clash is not None and clash["id"] != code_id:
        raise DuplicateCodeError(
            f"A code named {new_name!r} already exists at this level")
    updated = store.update_code(task_dir, code_id, name=new_name)
    _notify(task_dir, project)
    return updated


def recolor_code(
    task_dir: str, code_id: str, *, color: str, project: str
) -> Dict[str, Any]:
    _require(task_dir, code_id)
    updated = store.update_code(task_dir, code_id, color=color)
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
    task_dir: str, code_id: str, *, new_parent_id: str, project: str
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
    updated = store.update_code(
        task_dir, code_id,
        parent_id=new_parent_id, sort_order=len(siblings))
    _notify(task_dir, project)
    return updated


def delete_code(
    task_dir: str, code_id: str, *, project: str
) -> int:
    """Delete a code and its entire subtree (and annotation links).
    Returns the number of code rows removed."""
    _require(task_dir, code_id)
    ids = _subtree_ids(task_dir, project, code_id)
    n = store.delete_codes(task_dir, ids)
    # Removing a code also changes the option set.
    from potato.codebook import revision
    revision.bump_revision(task_dir, project)
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
