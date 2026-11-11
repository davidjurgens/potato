"""Flask blueprint for live collaborative sessions.

Pages (session auth, redirect to login):
- ``GET /collab/``                       lobby
- ``GET /collab/s/<sid>``                the item the member should be on
- ``GET /collab/s/<sid>/i/<iid>``        the annotation page, on the team's answer

APIs (session auth, JSON 401; POSTs carry the same-origin check):
- ``GET  /collab/api/list``
- ``POST /collab/api/create``                {name?, item_ids? | count?, mode?}
- ``POST /collab/api/<sid>/join``            {role?}
- ``POST /collab/api/<sid>/leave``
- ``GET  /collab/api/<sid>/state``
- ``GET  /collab/api/<sid>/events?since=N``
- ``GET  /collab/api/<sid>/stream?since=N``  (server-sent events, when enabled)
- ``POST /collab/api/<sid>/navigate``        {action, go_to?, instance_id?}
- ``POST /collab/api/<sid>/leader``          {username}
- ``POST /collab/api/<sid>/mode``            {mode}
- ``POST /collab/api/<sid>/presence``        {instance_id, focus?}
- ``POST /collab/api/<sid>/summon``          {instance_id}
- ``POST /collab/api/<sid>/message``         {text}
- ``POST /collab/api/<sid>/revert``          {seq}
- ``POST /collab/api/<sid>/close``
- ``GET  /collab/api/<sid>/item/<iid>``      the team's answer and its history
- ``POST /collab/api/<sid>/signoff``         {instance_id, ready}
- ``POST /collab/api/<sid>/blind_done``      {instance_id}
- ``POST /collab/api/<sid>/reveal``          {instance_id}
- ``POST /collab/api/<sid>/poll``            {instance_id, schema? | question+options}
- ``POST /collab/api/<sid>/poll/<pid>/vote`` {option}
- ``POST /collab/api/<sid>/poll/<pid>/close`` {apply?}
- ``POST /collab/api/<sid>/discuss``         {instance_id, body}
- ``GET  /collab/api/<sid>/metrics``         (members and admins)
- ``GET  /collab/api/<sid>/replay?instance_id=``  (members and admins)

Admin pages: ``GET /collab/admin`` (every session, live), ``GET
/collab/s/<sid>/observe`` (join read-only), ``GET /collab/s/<sid>/replay``.
"""

from __future__ import annotations

import json
import logging
import time
from functools import wraps

from flask import (
    Blueprint,
    Response,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
)

from potato.collab import state as collab_state
from potato.collab.context import finish_tracked_write, release_tracked_write
from potato.collab.manager import get_collab_manager
from potato.collab.models import FOLLOW, LEADER, MEMBER, OBSERVER, CollabError
from potato.server_utils.origin_check import same_origin_required

logger = logging.getLogger(__name__)

collab_bp = Blueprint("collab", __name__, url_prefix="/collab")

# Writes through the item data routes on a session page (span clear, link and
# event delete) are logged once they succeed, and their lock always released.
collab_bp.after_app_request(finish_tracked_write)
collab_bp.teardown_app_request(release_tracked_write)


def api_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return wrapper


def collab_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if get_collab_manager() is None:
            return jsonify({"error": "Live sessions are not enabled"}), 404
        return f(*args, **kwargs)
    return wrapper


def with_session(f):
    """Resolve ``<sid>``; map CollabError to its status."""
    @wraps(f)
    def wrapper(sid, *args, **kwargs):
        manager = get_collab_manager()
        collab_session = manager.get_session(sid)
        if collab_session is None:
            return jsonify({"error": f"Unknown session '{sid}'"}), 404
        try:
            return f(manager, collab_session, *args, **kwargs)
        except CollabError as exc:
            return jsonify({"error": str(exc)}), exc.status
    return wrapper


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _is_admin() -> bool:
    try:
        from potato.server_utils.rbac import Permission, get_rbac_manager
        return bool(get_rbac_manager().check(Permission.VIEW_ADMIN_DASHBOARD, request, session))
    except Exception:  # noqa: BLE001 - no RBAC configured
        return False


def _can_create(manager) -> bool:
    if manager.cfg.who_can_create == "any":
        return True
    return _is_admin()


def _member_or_admin(collab_session) -> bool:
    return collab_session.is_member(session.get("username")) or _is_admin()


def _item_url(collab_session, instance_id: str) -> str:
    return f"{request.script_root}/collab/s/{collab_session.session_id}/i/{instance_id}"


def _client_config(manager, collab_session, instance_id: str, username: str) -> dict:
    """What collab.js needs on the page (``window.potatoCollab``)."""
    cfg = manager.cfg
    return {
        "sid": collab_session.session_id,
        "name": collab_session.name,
        "team_user": collab_session.team_user,
        "me": username,
        "instance_id": instance_id,
        "item_ids": list(collab_session.item_ids),
        "rev": collab_session.rev_of(instance_id),
        "cursor": len(collab_session.events),
        "transport": cfg.transport,
        "poll_interval_ms": cfg.poll_interval_ms,
        "hidden_poll_interval_ms": cfg.hidden_poll_interval_ms,
        "base": request.script_root,
        "conflict_policy": cfg.conflict_policy,
        "sync_view": cfg.sync_view,
        "blind_first": collab_session.blind_first,
        "require_signoff": collab_session.require_signoff,
        "blind": collab_session.is_blind(instance_id),
        "role": (collab_session.members[username].role
                 if username in collab_session.members else None),
        "single_select": _single_select_schemes(collab_session),
    }


def _single_select_schemes(collab_session) -> list:
    """Schemes a quick poll can apply its winner to."""
    manager = get_collab_manager()
    return [{"name": s["name"], "options": manager._label_names(s)}
            for s in manager.app_config.get("annotation_schemes") or []
            if isinstance(s, dict) and s.get("name")
            and manager._is_single_choice(s["name"], collab_session)]


# ----------------------------------------------------------------------
# Pages


@collab_bp.route("/", methods=["GET"])
def lobby():
    manager = get_collab_manager()
    if manager is None:
        return "Live sessions are not enabled for this task", 404
    if "username" not in session:
        return redirect(request.script_root + "/")
    return render_template(
        "collab_lobby.html",
        username=session["username"],
        task_name=manager.app_config.get("annotation_task_name", "Annotation Task"),
        can_create=_can_create(manager),
        poll_interval_ms=manager.cfg.poll_interval_ms,
        is_admin=_is_admin(),
        blind_first_default=manager.cfg.blind_first,
        require_signoff_default=manager.cfg.require_signoff,
    )


@collab_bp.route("/s/<sid>", methods=["GET"])
def session_page(sid):
    manager = get_collab_manager()
    if manager is None:
        return "Live sessions are not enabled for this task", 404
    if "username" not in session:
        return redirect(request.script_root + "/")
    collab_session = manager.get_session(sid)
    if collab_session is None:
        return redirect(request.script_root + "/collab/")
    username = session["username"]
    if not collab_session.is_member(username):
        try:
            manager.join(collab_session, username)
        except CollabError:
            return redirect(request.script_root + "/collab/")
    member = collab_session.members[username]
    target = (collab_session.leader_view() if collab_session.mode == FOLLOW
              and member.following else None) or member.viewing or collab_session.item_ids[0]
    return redirect(_item_url(collab_session, target))


@collab_bp.route("/s/<sid>/i/<path:instance_id>", methods=["GET"])
def item_page(sid, instance_id):
    manager = get_collab_manager()
    if manager is None:
        return "Live sessions are not enabled for this task", 404
    if "username" not in session:
        return redirect(request.script_root + "/")
    collab_session = manager.get_session(sid)
    if collab_session is None:
        return redirect(request.script_root + "/collab/")
    username = session["username"]
    if not collab_session.is_member(username):
        return redirect(f"{request.script_root}/collab/s/{collab_session.session_id}")
    if instance_id not in collab_session.item_ids:
        return redirect(f"{request.script_root}/collab/s/{collab_session.session_id}")
    try:
        manager.view(collab_session, username, instance_id)
    except CollabError:
        pass
    from potato.flask_server import render_page_with_annotations
    context = _client_config(manager, collab_session, instance_id, username)
    # Before the reveal a member sees and edits their own answer.
    owner = username if collab_session.is_blind(instance_id) else collab_session.team_user
    response = make_response(render_page_with_annotations(
        owner, instance_id=instance_id, viewer=username, collab=context))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


# ----------------------------------------------------------------------
# Lobby APIs


@collab_bp.route("/api/list", methods=["GET"])
@collab_required
@api_login_required
def list_sessions():
    manager = get_collab_manager()
    return jsonify({"sessions": manager.list_sessions(session["username"]),
                    "can_create": _can_create(manager)})


@collab_bp.route("/api/create", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
def create_session():
    manager = get_collab_manager()
    if not _can_create(manager):
        return jsonify({"error": "Only admins can start a live session here"}), 403
    data = _body()
    item_ids = data.get("item_ids")
    if item_ids is not None and not (isinstance(item_ids, list)
                                     and all(isinstance(i, (str, int)) for i in item_ids)):
        return jsonify({"error": "item_ids must be a list of item ids"}), 400
    count = data.get("count")
    try:
        count = int(count) if count is not None else None
    except (TypeError, ValueError):
        return jsonify({"error": "count must be a number"}), 400
    def flag(key):
        value = data.get(key)
        return None if value is None else bool(value)
    try:
        created = manager.create_session(
            session["username"], name=(str(data.get("name") or "").strip()[:80] or None),
            item_ids=[str(i) for i in item_ids] if item_ids else None,
            count=count, mode=data.get("mode"), blind_first=flag("blind_first"),
            require_signoff=flag("require_signoff"))
    except CollabError as exc:
        return jsonify({"error": str(exc)}), exc.status
    return jsonify({"session": created.to_state(session["username"]),
                    "url": f"{request.script_root}/collab/s/{created.session_id}"})


# ----------------------------------------------------------------------
# Session APIs


@collab_bp.route("/api/<sid>/join", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def join(manager, collab_session):
    role = str(_body().get("role") or MEMBER)
    manager.join(collab_session, session["username"], role)
    return jsonify({"session": collab_session.to_state(session["username"])})


@collab_bp.route("/api/<sid>/leave", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def leave(manager, collab_session):
    manager.leave(collab_session, session["username"])
    return jsonify({"status": "ok"})


@collab_bp.route("/api/<sid>/state", methods=["GET"])
@collab_required
@api_login_required
@with_session
def state(manager, collab_session):
    username = session["username"]
    if not collab_session.is_member(username):
        return jsonify({"error": "Join the session first"}), 403
    payload = collab_session.to_state(username)
    payload["presence"] = manager.presence_of(collab_session)
    return jsonify(payload)


def _since() -> int:
    try:
        return max(0, int(request.args.get("since", 0)))
    except (TypeError, ValueError):
        return 0


def _visible(event: dict, collab_session, username: str) -> dict:
    """An event as one member may see it: an open poll's votes stay secret."""
    if event["type"] == "poll_vote" and event.get("user") != username:
        poll = collab_session.polls.get((event.get("data") or {}).get("poll_id"))
        if poll is not None and poll["open"]:
            return dict(event, data={"poll_id": poll["poll_id"]})
    return event


def _poll_payload(manager, collab_session, since: int, username: str) -> dict:
    raw = manager.events_since(collab_session, since)
    events = [_visible(e, collab_session, username) for e in raw]
    return {"events": events, "cursor": since + len(events),
            "state": collab_session.to_state(username),
            "presence": manager.presence_of(collab_session)}


@collab_bp.route("/api/<sid>/events", methods=["GET"])
@collab_required
@api_login_required
@with_session
def events(manager, collab_session):
    username = session["username"]
    if not collab_session.is_member(username):
        return jsonify({"error": "Join the session first"}), 403
    return jsonify(_poll_payload(manager, collab_session, _since(), username))


@collab_bp.route("/api/<sid>/stream", methods=["GET"])
@collab_required
@api_login_required
@with_session
def stream(manager, collab_session):
    """Server-sent events, capped: each open stream holds a server thread."""
    username = session["username"]
    if not collab_session.is_member(username):
        return jsonify({"error": "Join the session first"}), 403
    cfg = manager.cfg
    if cfg.transport != "sse":
        return jsonify({"error": "Server push is off; poll /events"}), 404
    with manager.lock:
        if manager.active_streams >= cfg.sse_max_streams:
            return jsonify({"error": "Too many open streams; poll /events"}), 429
        manager.active_streams += 1
    try:
        since = int(request.headers.get("Last-Event-ID") or _since())
    except (TypeError, ValueError):
        since = _since()

    def generate():
        cursor = since
        deadline = time.time() + cfg.sse_max_stream_seconds
        try:
            yield f"retry: {cfg.poll_interval_ms}\n\n"
            while time.time() < deadline:
                remaining = max(0.0, deadline - time.time())
                if manager.wait_for_events(collab_session, cursor, min(remaining, 10.0)):
                    payload = _poll_payload(manager, collab_session, cursor, username)
                    cursor = payload["cursor"]
                    yield (f"id: {cursor}\nevent: batch\n"
                           f"data: {json.dumps(payload, default=str)}\n\n")
                else:
                    yield ": keepalive\n\n"
        finally:
            with manager.lock:
                manager.active_streams = max(0, manager.active_streams - 1)

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@collab_bp.route("/api/<sid>/navigate", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def navigate(manager, collab_session):
    username = session["username"]
    data = _body()
    action = str(data.get("action") or "")
    target = manager.target_for(collab_session, username, action, data.get("go_to"),
                                data.get("instance_id"))
    is_leader = collab_session.leader == username
    following = True if (action == "follow" or is_leader) else False
    manager.view(collab_session, username, target, following=following)
    url = _item_url(collab_session, target)
    response = jsonify({"status": "ok", "instance_id": target, "url": url})
    response.headers["X-Potato-Location"] = url
    return response


@collab_bp.route("/api/<sid>/leader", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def leader(manager, collab_session):
    manager.set_leader(collab_session, session["username"],
                       str(_body().get("username") or ""))
    return jsonify({"session": collab_session.to_state(session["username"])})


@collab_bp.route("/api/<sid>/mode", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def mode(manager, collab_session):
    manager.set_mode(collab_session, session["username"], str(_body().get("mode") or ""))
    return jsonify({"session": collab_session.to_state(session["username"])})


@collab_bp.route("/api/<sid>/presence", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def presence(manager, collab_session):
    data = _body()
    focus = data.get("focus")
    manager.record_presence(collab_session, session["username"], {
        "instance_id": str(data.get("instance_id") or "") or None,
        "focus": str(focus)[:200] if focus else None,
        "view": data.get("view") if isinstance(data.get("view"), dict) else None,
    })
    return jsonify({"status": "ok"})


@collab_bp.route("/api/<sid>/summon", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def summon(manager, collab_session):
    manager.summon(collab_session, session["username"],
                   str(_body().get("instance_id") or ""))
    return jsonify({"status": "ok"})


@collab_bp.route("/api/<sid>/message", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def message(manager, collab_session):
    manager.message(collab_session, session["username"], str(_body().get("text") or ""))
    return jsonify({"status": "ok"})


@collab_bp.route("/api/<sid>/revert", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def revert(manager, collab_session):
    try:
        seq = int(_body().get("seq"))
    except (TypeError, ValueError):
        return jsonify({"error": "seq must be the number of a change"}), 400
    event = manager.revert(collab_session, session["username"], seq)
    return jsonify({"status": "ok", "event": event})


@collab_bp.route("/api/<sid>/close", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def close(manager, collab_session):
    manager.close(collab_session, session["username"])
    return jsonify({"status": "ok"})


@collab_bp.route("/api/<sid>/item/<path:instance_id>", methods=["GET"])
@collab_required
@api_login_required
@with_session
def item(manager, collab_session, instance_id):
    """The team's current answer for one item, its revision and history."""
    from potato.user_state_management import get_user_state_manager
    username = session["username"]
    if not collab_session.is_member(username):
        return jsonify({"error": "Join the session first"}), 403
    if instance_id not in collab_session.item_ids:
        return jsonify({"error": "That item is not in this session"}), 404
    if collab_session.is_blind(instance_id):
        # Nobody's answer is shown before the reveal, and the team's is empty.
        return jsonify({"instance_id": instance_id, "rev": collab_session.rev_of(instance_id),
                        "blind": True, "answer": {}, "history": [],
                        "status": collab_session.item_status(instance_id)})
    team = get_user_state_manager().get_user_state(collab_session.team_user)
    history = [{"seq": e["seq"], "ts": e["ts"], "user": e["user"],
                "rev": e["data"].get("rev"), "summary": e["data"].get("summary") or [],
                "via": e["data"].get("via"), "reverts": e["data"].get("reverts"),
                "overwrote": e["data"].get("overwrote") or []}
               for e in collab_session.edits_of(instance_id)]
    reveal = manager.reveal_of(collab_session, instance_id)
    return jsonify({"instance_id": instance_id,
                    "rev": collab_session.rev_of(instance_id),
                    "answer": collab_state.item_snapshot(team, instance_id),
                    "history": history,
                    "status": collab_session.item_status(instance_id),
                    "reveal": ({k: reveal["data"].get(k) for k in
                                ("units", "agreement", "answered", "seeded")}
                               if reveal else None)})


# ----------------------------------------------------------------------
# Sign-off, blind first, polls, discussion


def _iid(data) -> str:
    return str(data.get("instance_id") or "")


@collab_bp.route("/api/<sid>/signoff", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def signoff(manager, collab_session):
    data = _body()
    manager.signoff(collab_session, session["username"], _iid(data),
                    ready=bool(data.get("ready", True)))
    return jsonify({"status": "ok", "item": collab_session.item_status(_iid(data))})


@collab_bp.route("/api/<sid>/blind_done", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def blind_done(manager, collab_session):
    iid = _iid(_body())
    if iid not in collab_session.item_ids:
        return jsonify({"error": "That item is not in this session"}), 404
    manager.blind_done(collab_session, session["username"], iid)
    return jsonify({"status": "ok", "item": collab_session.item_status(iid)})


@collab_bp.route("/api/<sid>/reveal", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def reveal(manager, collab_session):
    iid = _iid(_body())
    manager.reveal(collab_session, session["username"], iid)
    return jsonify({"status": "ok", "item": collab_session.item_status(iid)})


@collab_bp.route("/api/<sid>/poll", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def open_poll(manager, collab_session):
    data = _body()
    options = data.get("options")
    if options is not None and not isinstance(options, list):
        return jsonify({"error": "options must be a list"}), 400
    event = manager.open_poll(collab_session, session["username"], _iid(data),
                              question=data.get("question"), options=options,
                              schema=data.get("schema") or None)
    return jsonify({"status": "ok", "poll_id": event["data"]["poll_id"]})


@collab_bp.route("/api/<sid>/poll/<pid>/vote", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def vote(manager, collab_session, pid):
    manager.vote(collab_session, session["username"], pid, str(_body().get("option") or ""))
    return jsonify({"status": "ok",
                    "poll": collab_session.poll_view(collab_session.polls[pid],
                                                     session["username"])})


@collab_bp.route("/api/<sid>/poll/<pid>/close", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def close_poll(manager, collab_session, pid):
    username = session["username"]
    apply = bool(_body().get("apply"))
    poll = collab_session.polls.get(pid)
    if poll is not None and not poll["open"] and apply:
        manager.apply_poll(collab_session, username, pid)
    else:
        manager.close_poll(collab_session, username, pid, apply=apply)
    return jsonify({"status": "ok",
                    "poll": collab_session.poll_view(collab_session.polls[pid], username)})


@collab_bp.route("/api/<sid>/discuss", methods=["POST"])
@collab_required
@api_login_required
@same_origin_required
@with_session
def discuss(manager, collab_session):
    from potato.memos.api import _ctx as memo_context
    task_dir, project, username, _priv, err = memo_context()
    if err:
        return jsonify({"error": "Notes are not available here"}), 503
    data = _body()
    memo = manager.discuss(collab_session, username, _iid(data),
                           str(data.get("body") or ""), task_dir, project)
    return jsonify({"status": "ok", "memo": memo})


# ----------------------------------------------------------------------
# Watching: metrics, replay, admin


@collab_bp.route("/api/<sid>/metrics", methods=["GET"])
@collab_required
@api_login_required
@with_session
def metrics(manager, collab_session):
    if not _member_or_admin(collab_session):
        return jsonify({"error": "Members and admins only"}), 403
    return jsonify(manager.metrics(collab_session))


@collab_bp.route("/api/<sid>/replay", methods=["GET"])
@collab_required
@api_login_required
@with_session
def replay_api(manager, collab_session):
    if not _member_or_admin(collab_session):
        return jsonify({"error": "Members and admins only"}), 403
    iid = str(request.args.get("instance_id") or collab_session.item_ids[0])
    return jsonify(manager.replay(collab_session, iid))


@collab_bp.route("/s/<sid>/replay", methods=["GET"])
def replay_page(sid):
    manager = get_collab_manager()
    if manager is None:
        return "Live sessions are not enabled for this task", 404
    if "username" not in session:
        return redirect(request.script_root + "/")
    collab_session = manager.get_session(sid)
    if collab_session is None or not _member_or_admin(collab_session):
        return redirect(request.script_root + "/collab/")
    return render_template(
        "collab_replay.html", task_name=manager.app_config.get("annotation_task_name",
                                                                 "Annotation Task"),
        session_info=collab_session.to_summary(), item_ids=list(collab_session.item_ids),
        instance_id=str(request.args.get("instance_id") or collab_session.item_ids[0]),
        username=session["username"])


@collab_bp.route("/s/<sid>/observe", methods=["GET"])
def observe(sid):
    """An admin joins read-only (configured teams too), then sees the session."""
    manager = get_collab_manager()
    if manager is None:
        return "Live sessions are not enabled for this task", 404
    if "username" not in session:
        return redirect(request.script_root + "/")
    collab_session = manager.get_session(sid)
    if collab_session is None:
        return redirect(request.script_root + "/collab/admin")
    username = session["username"]
    if not collab_session.is_member(username):
        if not _is_admin():
            return redirect(request.script_root + "/collab/")
        try:
            manager.join(collab_session, username, role=OBSERVER, admin=True)
        except CollabError:
            return redirect(request.script_root + "/collab/admin")
    return redirect(f"{request.script_root}/collab/s/{collab_session.session_id}")


@collab_bp.route("/admin", methods=["GET"])
def admin_page():
    manager = get_collab_manager()
    if manager is None:
        return "Live sessions are not enabled for this task", 404
    if "username" not in session:
        return redirect(request.script_root + "/")
    if not _is_admin():
        return "Admins only", 403
    return render_template(
        "collab_admin.html",
        task_name=manager.app_config.get("annotation_task_name", "Annotation Task"),
        username=session["username"], poll_interval_ms=manager.cfg.poll_interval_ms)


@collab_bp.route("/api/admin/overview", methods=["GET"])
@collab_required
@api_login_required
def admin_overview():
    if not _is_admin():
        return jsonify({"error": "Admins only"}), 403
    manager = get_collab_manager()
    rows = []
    for s in sorted(manager.sessions.values(), key=lambda x: -x.created_at):
        row = s.to_summary()
        row["metrics"] = manager.metrics(s)
        row["presence"] = manager.presence_of(s)
        row["members"] = [m.to_dict() for m in s.members.values()]
        rows.append(row)
    return jsonify({"sessions": rows})
