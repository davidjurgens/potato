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

Threads and issues:
- A reply belongs to its thread's first memo (the root). It takes the root's
  instance and visibility, and anyone who can read the root can read and
  reply to the thread.
- An issue is a root with a status, ``open`` or ``resolved``. Its status can be
  changed by the root's author, its assignee, or an adjudicator; its assignee
  by the root's author or an adjudicator.
- An anchor is a text range ``{start, end[, field]}`` or, for an issue raised
  on a drawn shape, ``{shape: {schema, type, label, coordinates}}``. Shapes
  carry no stored id, so the shape is recorded as drawn and matched back by
  its geometry.
"""

from __future__ import annotations

import time

from typing import Any, Dict, List, Optional

from . import store

VALID_VISIBILITY = ("private", "shared")
VALID_STATUS = ("open", "resolved")


class MemoError(Exception):
    """Base error for memo operations (maps to 4xx at the API layer)."""


class MemoNotFound(MemoError):
    pass


class MemoPermissionError(MemoError):
    pass


def _can_read(memo: Dict[str, Any], requester: str, is_privileged: bool) -> bool:
    """Read access to a thread root (a reply is read through its root).

    The assignee of an issue can read it, private or not: an issue assigned
    to someone who cannot see it is an issue nobody can resolve.
    """
    return (
        is_privileged
        or memo["created_by"] == requester
        or memo["visibility"] == "shared"
        or bool(memo.get("assignee")) and memo["assignee"] == requester
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
    issue: bool = False,
    assignee: Optional[str] = None,
) -> Dict[str, Any]:
    body = (body or "").strip()
    if not body:
        raise MemoError("Memo body must not be empty")
    if visibility not in VALID_VISIBILITY:
        raise MemoError(
            f"visibility must be one of {VALID_VISIBILITY} (got {visibility!r})"
        )
    _check_anchor(anchor)
    if issue and assignee is not None and not str(assignee).strip():
        assignee = None
    return store.create(
        task_dir, project=project, instance_id=instance_id, body=body,
        created_by=created_by, anchor=anchor, visibility=visibility,
        status="open" if issue else None,
        assignee=str(assignee).strip() if issue and assignee else None,
    )


def _check_anchor(anchor: Any) -> None:
    if anchor is None:
        return
    if not isinstance(anchor, dict):
        raise MemoError("anchor must be {start, end[, field]}, {shape: {...}}, or null")
    if "shape" in anchor:
        shape = anchor["shape"]
        if (not isinstance(shape, dict) or not shape.get("schema") or not shape.get("type")
                or shape.get("coordinates") is None):
            raise MemoError("a shape anchor needs schema, type and coordinates")
        return
    if "start" not in anchor or "end" not in anchor:
        raise MemoError("anchor must be {start, end[, field]}, {shape: {...}}, or null")


def list_visible(
    task_dir: str,
    *,
    project: str,
    instance_id: str,
    requester: str,
    is_privileged: bool = False,
) -> List[Dict[str, Any]]:
    """Memos on an instance the requester is allowed to see.

    A reply is visible exactly when its thread's root is: it follows the
    root's visibility, including a later change to it.
    """
    memos = store.list_for_instance(task_dir, project, instance_id)
    roots = {m["id"]: m for m in memos if not m.get("parent_id")}
    visible = []
    for m in memos:
        root = roots.get(m.get("parent_id")) if m.get("parent_id") else m
        if root is not None and _can_read(root, requester, is_privileged):
            visible.append(with_permissions(m, requester, is_privileged))
    return visible


def with_permissions(memo: Dict[str, Any], requester: str,
                     is_privileged: bool = False) -> Dict[str, Any]:
    """The memo plus what this requester may do with it, for the page to show.

    The server still checks every action; these only keep the page from
    offering buttons that would be refused.
    """
    own = memo["created_by"] == requester
    is_root = not memo.get("parent_id")
    issue = is_root and bool(memo.get("status"))
    return {
        **memo,
        "can_edit": own,
        "can_delete": own or is_privileged,
        "can_resolve": issue and (own or is_privileged
                                  or bool(memo.get("assignee")) and memo["assignee"] == requester),
        "can_assign": issue and (own or is_privileged),
    }


def _root_of(task_dir: str, memo: Dict[str, Any]) -> Dict[str, Any]:
    if memo.get("parent_id"):
        root = store.get(task_dir, memo["parent_id"])
        if root is None:
            raise MemoNotFound("The thread this reply belongs to no longer exists")
        return root
    return memo


def reply_to(
    task_dir: str,
    memo_id: str,
    *,
    requester: str,
    body: str,
    is_privileged: bool = False,
) -> Dict[str, Any]:
    """Add a reply to the thread ``memo_id`` belongs to."""
    root = _root_of(task_dir, _load_readable(task_dir, memo_id, requester, is_privileged))
    body = (body or "").strip()
    if not body:
        raise MemoError("Reply must not be empty")
    return store.create(
        task_dir, project=root["project"], instance_id=root["instance_id"], body=body,
        created_by=requester, visibility=root["visibility"], parent_id=root["id"],
    )


def set_status(
    task_dir: str,
    memo_id: str,
    *,
    requester: str,
    status: str,
    is_privileged: bool = False,
) -> Dict[str, Any]:
    """Open or resolve an issue (a thread root with a status)."""
    memo = _load_readable(task_dir, memo_id, requester, is_privileged)
    if memo.get("parent_id"):
        raise MemoError("Only the first memo of a thread has a status")
    if status not in VALID_STATUS:
        raise MemoError(f"status must be one of {VALID_STATUS} (got {status!r})")
    if not (is_privileged or memo["created_by"] == requester
            or (memo.get("assignee") and memo["assignee"] == requester)):
        raise MemoPermissionError(
            "Only the issue's author, its assignee or an adjudicator may change its status")
    if status == "resolved":
        return store.set_thread(task_dir, memo_id, status="resolved",
                                resolved_by=requester, resolved_at=time.time())
    return store.set_thread(task_dir, memo_id, status="open", resolved_by=None, resolved_at=None)


def set_assignee(
    task_dir: str,
    memo_id: str,
    *,
    requester: str,
    assignee: Optional[str],
    is_privileged: bool = False,
) -> Dict[str, Any]:
    """Assign an issue to someone, or clear the assignment with an empty value.

    The assignee can then read and reply to the thread, even when it is
    private (see ``_can_read``).
    """
    memo = _load_readable(task_dir, memo_id, requester, is_privileged)
    if memo.get("parent_id"):
        raise MemoError("Only the first memo of a thread can be assigned")
    if not memo.get("status"):
        raise MemoError("Only an issue can be assigned; raise it as an issue first")
    if not (is_privileged or memo["created_by"] == requester):
        raise MemoPermissionError("Only the issue's author or an adjudicator may assign it")
    assignee = (assignee or "").strip() or None
    return store.set_thread(task_dir, memo_id, assignee=assignee)


def list_issues(
    task_dir: str,
    *,
    project: str,
    requester: str,
    is_privileged: bool = False,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Issues across the project that the requester may see."""
    if status is not None and status not in VALID_STATUS:
        raise MemoError(f"status must be one of {VALID_STATUS} (got {status!r})")
    return [with_permissions(m, requester, is_privileged)
            for m in store.list_issues(task_dir, project, status=status, assignee=assignee)
            if _can_read(m, requester, is_privileged)]


def _load_or_404(task_dir: str, memo_id: str) -> Dict[str, Any]:
    memo = store.get(task_dir, memo_id)
    if memo is None:
        raise MemoNotFound(f"Memo {memo_id} not found")
    return memo


def _load_readable(task_dir: str, memo_id: str, requester: str,
                   is_privileged: bool) -> Dict[str, Any]:
    """The memo, or MemoNotFound when the requester may not read it.

    Not-found rather than forbidden, the same for every action: a refusal
    that says why also says the memo exists.
    """
    memo = _load_or_404(task_dir, memo_id)
    root = memo if not memo.get("parent_id") else store.get(task_dir, memo["parent_id"])
    if root is None or not _can_read(root, requester, is_privileged):
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
    memo = _load_readable(task_dir, memo_id, requester, is_privileged)
    if memo["created_by"] != requester:
        raise MemoPermissionError("Only the memo author may edit it")
    if visibility is not None and memo.get("parent_id"):
        raise MemoError("A reply takes its thread's visibility; change the first memo's")
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
    memo = _load_readable(task_dir, memo_id, requester, is_privileged)
    if memo["created_by"] != requester and not is_privileged:
        raise MemoPermissionError(
            "Only the author or an admin/adjudicator may delete this memo"
        )
    store.delete(task_dir, memo_id)
