"""The ``/updateinstance`` interceptor for live collaborative pages.

A collaborative page sends its saves to ``/updateinstance`` like any other
page, with one addition in the body (a beacon cannot carry headers):

    "collab": {"sid": "<session>", "base_rev": <rev the page reflects>,
               "save_id": "<client id>", "stale": {"<key>": <rev>}}

``stale`` gives a revision per key where the page shows a different revision
from ``base_rev``: an older one for a widget that could not show a teammate's
change, a newer one for a value the page took from the server after a refused
save. A key is a snapshot key or a whole single-choice scheme (``L:<schema>``).

The interceptor merges the save into the team's answer (see ``state.py``),
runs the ordinary write for the team user on behalf of the member, and logs
what changed. A save without the field, from a member, for an item their team
holds, is refused: it would store the item under the member's own name.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import jsonify

from potato.collab import state as collab_state
from potato.collab.manager import get_collab_manager
from potato.collab.models import CollabError

logger = logging.getLogger(__name__)


def _error(message: str, status: int):
    return jsonify({"status": "error", "message": message}), status


def _split(response):
    """(Response, status) from whatever a Flask view returned."""
    if isinstance(response, tuple):
        return response[0], (response[1] if len(response) > 1 else 200)
    return response, getattr(response, "status_code", 200)


def _with_collab(response, info: Dict[str, Any]):
    resp, status = _split(response)
    try:
        body = resp.get_json(silent=True)
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return response
    body["collab"] = info
    return jsonify(body), status


def intercept_update(username: str, payload: Any):
    """None for an ordinary save; otherwise the response to send."""
    manager = get_collab_manager()
    if manager is None or not isinstance(payload, dict):
        return None
    ctx = payload.get("collab")
    instance_id = payload.get("instance_id")
    if instance_id is None:
        return None
    instance_id = str(instance_id)

    if not ctx:
        held = manager.session_holding(username, instance_id)
        if held is None:
            return None
        if held.blind_first:
            # The member's own answer here is their blind answer: written
            # through the session only, and frozen once the item is revealed.
            return _error("This item belongs to your team's live session; "
                          f"open it from the session page (/collab/s/{held.session_id}).", 409)
        from potato.user_state_management import get_user_state_manager
        own = get_user_state_manager().get_user_state(username)
        if own is not None and instance_id in own.get_assigned_instance_ids():
            return None
        return _error("This item belongs to your team's live session; "
                      f"open it from the session page (/collab/s/{held.session_id}).", 409)

    if not isinstance(ctx, dict):
        return _error("'collab' must be an object", 400)
    session = manager.get_session(ctx.get("sid"))
    if session is None:
        return _error("Unknown session", 404)
    if not session.is_member(username):
        return _error("Join the session first", 403)
    if not session.can_edit(username):
        return _error("Observers cannot edit, and a closed session takes no edits", 403)
    if instance_id not in session.item_ids:
        return _error("That item is not in this session", 404)

    if ctx.get("rendered_blind") and not session.is_blind(instance_id):
        # The page showed the member's own answer; the item has since opened
        # to the team. Saving it now would put that answer in the team's.
        return _error("This item is now open to the team; reload it to see the team's answer.",
                      409)
    try:
        if session.is_blind(instance_id):
            return _write_blind(manager, session, username, instance_id, payload, ctx)
        return _merge_and_write(manager, session, username, instance_id, payload, ctx)
    except CollabError as exc:
        return _error(str(exc), exc.status)


def _who_changed(manager, session, instance_id, conflicts, base_rev):
    who = []
    for c in conflicts:
        author = manager._last_author(session, instance_id, c["key"], base_rev)
        who.append({"key": c["key"], "user": author, "theirs": c.get("theirs")})
    return who


def _rejected(manager, session, instance_id, conflicts, base_rev, rev_before):
    """``conflict_policy: reject``: refuse a save whose only changes were to
    values a teammate changed first."""
    who = _who_changed(manager, session, instance_id, conflicts, base_rev)
    names = sorted({w["user"] for w in who if w["user"]}) or ["a teammate"]
    return jsonify({
        "status": "error",
        "message": f"Not saved: {', '.join(names)} changed this first. "
                   "Your page now shows their answer.",
        "collab": {"rejected": True, "conflicts": who, "rev_before": rev_before,
                   "rev": rev_before, "seq": len(session.events), "overwrote": []},
    }), 409


def _write_blind(manager, session, username, instance_id, payload, ctx):
    """Before the reveal a member's save is their own answer, seen by no one."""
    from potato.routes import _update_instance_core
    from potato.user_state_management import get_user_state_manager
    if username in session.blind_done.get(instance_id, []):
        raise CollabError("You marked your answer as done; it opens to the team "
                          "when everyone is done", 409)
    from potato.phase import UserPhase
    usm = get_user_state_manager()
    own = usm.get_user_state(username)
    if own is None or own.get_phase() != UserPhase.ANNOTATION:
        # Outside the annotation phase a user's labels are filed under the
        # phase page they are on, not under the item: the answer would be lost.
        raise CollabError("Finish the study's opening pages (consent, instructions) "
                          "before answering on your own: open /annotate first.", 409)
    data = {k: v for k, v in payload.items() if k != "collab"}
    response = _update_instance_core(username, own, data, collab=ctx, allow_unassigned=True)
    _, status = _split(response)
    if status < 400:
        manager.note_blind_answer(session, username, instance_id)
    return _with_collab(response, {"blind": True, "rev_before": session.rev_of(instance_id),
                                   "rev": session.rev_of(instance_id),
                                   "seq": len(session.events), "overwrote": []})


def _merge_and_write(manager, session, username, instance_id, payload, ctx):
    from potato.routes import _update_instance_core
    from potato.server_utils.annotation_keys import split_annotation_key
    from potato.server_utils.schema_exclusivity import is_multiselect, is_single_select
    from potato.user_state_management import get_user_state_manager

    team_user = session.team_user
    data = {k: v for k, v in payload.items() if k != "collab"}
    frontend = any(k in data for k in ("annotations", "span_annotations",
                                       "link_annotations", "event_annotations"))
    with manager.session_lock(session):
        team = get_user_state_manager().get_user_state(team_user)
        current = collab_state.item_snapshot(team, instance_id)
        rev_before = session.rev_of(instance_id)
        try:
            base_rev = int(ctx.get("base_rev", rev_before))
        except (TypeError, ValueError):
            base_rev = rev_before
        base_rev = max(0, min(base_rev, rev_before))
        conflicts = []
        if frontend:
            base = manager.state_at(session, instance_id, base_rev, current)
            stale = ctx.get("stale") or {}
            if isinstance(stale, dict):
                for key, rev in stale.items():
                    try:
                        older = manager.state_at(session, instance_id, int(rev), current)
                    except (TypeError, ValueError):
                        continue
                    if key.startswith(collab_state.LABEL) and ":::" not in key:
                        # A whole single-choice scheme ("L:<schema>").
                        prefix = key + ":::"
                        for k in [k for k in base if k.startswith(prefix)]:
                            del base[k]
                        base.update({k: v for k, v in older.items() if k.startswith(prefix)})
                    elif key in older:
                        base[key] = older[key]
                    else:
                        base.pop(key, None)
            reject = manager.cfg.conflict_policy == "reject"
            merged = collab_state.merge_payload(
                data, base, current, split_key=split_annotation_key,
                is_single_select=lambda s: is_single_select(s, team_user),
                is_multiselect=lambda s: is_multiselect(s, team_user),
                keep_theirs=reject)
            data, conflicts = merged.payload, merged.conflicts
            if conflicts and reject:
                if not merged.changed:
                    return _rejected(manager, session, instance_id, conflicts, base_rev,
                                     rev_before)
                # The teammate's values stand; the rest of the save goes in.
                refused = _who_changed(manager, session, instance_id, conflicts, base_rev)
                conflicts = []
            else:
                refused = []
            if not merged.changed:
                return jsonify({"status": "success", "unchanged": True,
                                "collab": {"rev_before": rev_before, "rev": rev_before,
                                           "seq": len(session.events)}})
        response = _update_instance_core(team_user, team, data, actor=username,
                                         collab=ctx)
        _, status = _split(response)
        after = collab_state.item_snapshot(team, instance_id)
        event = None
        if status < 400:
            event = manager.record_edit(
                session, username, instance_id, current, after, conflicts=conflicts,
                save_id=ctx.get("save_id"), via="save", base_rev=base_rev)
        info = {"rev_before": rev_before, "rev": session.rev_of(instance_id),
                "seq": event["seq"] if event else len(session.events),
                "overwrote": event["data"]["overwrote"] if event else []}
        if refused:
            info.update(rejected=True, partial=True, conflicts=refused)
        return _with_collab(response, info)
