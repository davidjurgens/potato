"""Whose annotations a request reads or writes.

On an ordinary page that is the logged-in annotator. On a live collaborative
page the page names its session (the ``X-Potato-Collab`` header, a ``collab``
query argument, or ``collab.sid`` in a JSON body) and the owner is the team
user; the logged-in member is the *actor*. In a blind-first session, an item
not yet revealed is the member's own again: their blind answer.

Only the data routes a page calls about the item it shows ask this. Routes
keyed on the annotator's own cursor or own paradata keep using the session
user.

A write through one of these routes (span clear, link or event delete,
entity-link update) holds the session's lock from ``annotation_owner(...,
write=True)`` to the end of the request, and the change is logged as an edit
once the route has answered with success: see ``finish_tracked_write``.
"""

from __future__ import annotations

from typing import Optional, Tuple

from flask import g, jsonify, request, session

from potato.collab import state as collab_state


def requested_session_id() -> Optional[str]:
    sid = request.headers.get("X-Potato-Collab") or request.args.get("collab")
    if not sid and request.is_json:
        body = request.get_json(silent=True)
        if isinstance(body, dict) and isinstance(body.get("collab"), dict):
            sid = body["collab"].get("sid")
    return sid or None


def _refuse(message: str, status: int):
    return None, None, (jsonify({"status": "error", "error": message,
                                 "message": message}), status)


def annotation_owner(instance_id: Optional[str] = None, *, write: bool = False
                     ) -> Tuple[Optional[str], object, object]:
    """``(owner, collab_session, refusal)`` for the current request.

    ``refusal`` is a response to return as-is when the request names a
    session it may not use.
    """
    username = session.get("username")
    sid = requested_session_id()
    if not sid:
        return username, None, None
    from potato.collab.manager import get_collab_manager
    manager = get_collab_manager()
    if manager is None:
        return _refuse("Live sessions are not enabled", 404)
    collab_session = manager.get_session(sid)
    if collab_session is None:
        return _refuse("Unknown session", 404)
    if not collab_session.is_member(username):
        return _refuse("Join the session first", 403)
    if instance_id is not None and str(instance_id) not in collab_session.item_ids:
        return _refuse("That item is not in this session", 404)
    item = str(instance_id) if instance_id is not None else (
        collab_session.members[username].viewing or collab_session.item_ids[0])
    if collab_session.is_blind(item):
        # Before the reveal, a member reads and writes their own answer.
        if write and username in collab_session.blind_done.get(item, []):
            return _refuse("You marked your answer as done", 409)
        return username, collab_session, None
    if write:
        if not collab_session.can_edit(username):
            return _refuse("You cannot edit in this session", 403)
        if instance_id is not None:
            _begin_tracked_write(manager, collab_session, username, str(instance_id))
    return collab_session.team_user, collab_session, None


def session_covers(instance_id) -> bool:
    """Whether the request names a live session this user is in, holding the item.

    For read-only data routes that check the annotator's own assignment: in a
    session the item is assigned to the team user, not to the member.
    """
    try:
        _owner, collab_session, refusal = annotation_owner(str(instance_id))
    except Exception:  # noqa: BLE001 - no session machinery, no cover
        return False
    return refusal is None and collab_session is not None


def viewing_item(collab_session):
    """The item this member is on in the session (their own cursor)."""
    from potato.item_state_management import get_item_state_manager
    member = collab_session.members.get(session.get("username"))
    iid = member.viewing if member is not None and member.viewing else collab_session.item_ids[0]
    ism = get_item_state_manager()
    return ism.get_item(iid) if ism.has_item(iid) else None


def _begin_tracked_write(manager, collab_session, actor, instance_id):
    from potato.user_state_management import get_user_state_manager
    if getattr(g, "_collab_write", None) is not None:
        return
    lock = manager.raw_session_lock(collab_session)
    lock.acquire()
    try:
        team = get_user_state_manager().get_user_state(collab_session.team_user)
        before = collab_state.item_snapshot(team, instance_id)
    except BaseException:
        # Nothing is recorded in g yet, so teardown would never release it.
        lock.release()
        raise
    g._collab_write = {
        "manager": manager, "session": collab_session, "actor": actor,
        "instance_id": instance_id, "lock": lock, "before": before,
        "via": request.path,
    }


def finish_tracked_write(response):
    """``after_request``: log a successful tracked write as an edit."""
    pending = getattr(g, "_collab_write", None)
    if pending is None or response.status_code >= 400:
        return response
    from potato.user_state_management import get_user_state_manager
    try:
        session_ = pending["session"]
        team = get_user_state_manager().get_user_state(session_.team_user)
        after = collab_state.item_snapshot(team, pending["instance_id"])
        event = pending["manager"].record_edit(
            session_, pending["actor"], pending["instance_id"], pending["before"], after,
            via="write")
        if event is not None:
            # Some of these routes change the store without saving it.
            from potato.annotation_commit import finish_annotation_write
            finish_annotation_write(team, pending["instance_id"], session_.team_user)
    except Exception:  # noqa: BLE001 - the write itself already succeeded
        import logging
        logging.getLogger(__name__).exception("Could not log a collaborative write")
    return response


def release_tracked_write(_exc=None):
    """``teardown_request``: always let go of the session lock."""
    pending = getattr(g, "_collab_write", None)
    if pending is not None:
        g._collab_write = None
        try:
            pending["lock"].release()
        except RuntimeError:
            pass
