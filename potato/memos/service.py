"""
Memo service (universal) — visibility + permission rules over the store.

Visibility model (decided 2026-05-18):
- ``private`` (default): visible to the author and to admins/adjudicators.
- ``shared``: visible to the author, admins/adjudicators, AND peer
  annotators on the same project.
- Admins/adjudicators can ALWAYS read every memo regardless of setting.

Permissions:
- Read: per the visibility rule above.
- Edit (body/visibility): author only.
- Delete: author OR an admin/adjudicator (moderation).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import store

VALID_VISIBILITY = ("private", "shared")


class MemoError(Exception):
    """Base error for memo operations (maps to 4xx at the API layer)."""


class MemoNotFound(MemoError):
    pass


class MemoPermissionError(MemoError):
    pass


def _can_read(memo: Dict[str, Any], requester: str, is_privileged: bool) -> bool:
    return (
        is_privileged
        or memo["created_by"] == requester
        or memo["visibility"] == "shared"
    )


def create_memo(
    task_dir: str,
    *,
    project: str,
    instance_id: str,
    body: str,
    created_by: str,
    anchor: Optional[Dict[str, Any]] = None,
    visibility: str = "private",
) -> Dict[str, Any]:
    body = (body or "").strip()
    if not body:
        raise MemoError("Memo body must not be empty")
    if visibility not in VALID_VISIBILITY:
        raise MemoError(
            f"visibility must be one of {VALID_VISIBILITY} (got {visibility!r})"
        )
    if anchor is not None:
        if not isinstance(anchor, dict) or "start" not in anchor or "end" not in anchor:
            raise MemoError("anchor must be {start, end[, field]} or null")
    return store.create(
        task_dir, project=project, instance_id=instance_id, body=body,
        created_by=created_by, anchor=anchor, visibility=visibility,
    )


def list_visible(
    task_dir: str,
    *,
    project: str,
    instance_id: str,
    requester: str,
    is_privileged: bool = False,
) -> List[Dict[str, Any]]:
    """Memos on an instance the requester is allowed to see."""
    return [
        m for m in store.list_for_instance(task_dir, project, instance_id)
        if _can_read(m, requester, is_privileged)
    ]


def _load_or_404(task_dir: str, memo_id: str) -> Dict[str, Any]:
    memo = store.get(task_dir, memo_id)
    if memo is None:
        raise MemoNotFound(f"Memo {memo_id} not found")
    return memo


def update_memo(
    task_dir: str,
    memo_id: str,
    *,
    requester: str,
    is_privileged: bool = False,
    body: Optional[str] = None,
    visibility: Optional[str] = None,
) -> Dict[str, Any]:
    memo = _load_or_404(task_dir, memo_id)
    if memo["created_by"] != requester:
        raise MemoPermissionError("Only the memo author may edit it")
    if body is not None and not body.strip():
        raise MemoError("Memo body must not be empty")
    if visibility is not None and visibility not in VALID_VISIBILITY:
        raise MemoError(
            f"visibility must be one of {VALID_VISIBILITY} (got {visibility!r})"
        )
    return store.update(
        task_dir, memo_id,
        body=body.strip() if body is not None else None,
        visibility=visibility,
    )


def delete_memo(
    task_dir: str,
    memo_id: str,
    *,
    requester: str,
    is_privileged: bool = False,
) -> None:
    memo = _load_or_404(task_dir, memo_id)
    if memo["created_by"] != requester and not is_privileged:
        raise MemoPermissionError(
            "Only the author or an admin/adjudicator may delete this memo"
        )
    store.delete(task_dir, memo_id)
