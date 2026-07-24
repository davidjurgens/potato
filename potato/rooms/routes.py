"""Flask blueprint for Multiplayer Annotation Rooms.

Pages (session auth, redirect to login):
- ``GET /rooms``            — lobby: open rooms + create form
- ``GET /rooms/<room_id>``  — live room page

APIs (session auth, JSON 401; POSTs carry the same-origin CSRF check):
- ``GET  /rooms/api/list``
- ``POST /rooms/api/create``            {room_type, n_items | item_ids}
- ``POST /rooms/api/<id>/join``         {role?}
- ``POST /rooms/api/<id>/leave``
- ``GET  /rooms/api/<id>/state``
- ``GET  /rooms/api/<id>/events?since=N&presence=N``
- ``POST /rooms/api/<id>/vote``         {label}
- ``POST /rooms/api/<id>/reveal``       (host)
- ``POST /rooms/api/<id>/advance``      (host)
- ``POST /rooms/api/<id>/close``        (host)
- ``POST /rooms/api/<id>/message``      {text}
- ``POST /rooms/api/<id>/presence``     {data}   (ephemeral, shadow mode)
- ``GET  /rooms/api/<id>/export``       (host or admin)
"""

import logging
import random
from functools import wraps

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    session,
)

from potato.item_state_management import get_item_state_manager
from potato.rooms.manager import get_rooms_manager
from potato.rooms.models import (
    HOST,
    HUDDLE,
    MEMBER,
    OBSERVER,
    ROOM_TYPES,
    SHADOW,
    RoomError,
)
from potato.server_utils.rbac import Permission, get_rbac_manager, require_permission

logger = logging.getLogger(__name__)

rooms_bp = Blueprint("rooms", __name__, url_prefix="/rooms")

admin_required = require_permission(Permission.VIEW_ADMIN_DASHBOARD)

MAX_ROOM_ITEMS = 200


def api_login_required(f):
    """JSON 401 (rather than a login redirect) for JS-called endpoints."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)

    return decorated_function


def same_origin_required(f):
    """Lightweight CSRF defense for state-changing routes (Origin/Referer check)."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")
        host = request.host_url.rstrip("/")
        if not origin and not referer:
            return f(*args, **kwargs)
        if origin and not origin.startswith(host):
            return jsonify({"error": "Cross-origin request rejected"}), 403
        if referer and not referer.startswith(host):
            return jsonify({"error": "Cross-origin request rejected"}), 403
        return f(*args, **kwargs)

    return decorated_function


def rooms_required(f):
    """404 when rooms aren't enabled for this task."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_rooms_manager() is None:
            return jsonify({"error": "Rooms not enabled"}), 404
        return f(*args, **kwargs)

    return decorated_function


def _get_room_or_404(room_id):
    room = get_rooms_manager().get_room(room_id)
    if room is None:
        return None, (jsonify({"error": f"Unknown room '{room_id}'"}), 404)
    return room, None


def _require_membership(room):
    """Non-members may not read a room's state or events."""
    if session["username"] not in room.members:
        return jsonify({"error": "Join the room first"}), 403
    return None


def _scheme_labels(app_config, schema_name):
    for scheme in app_config.get("annotation_schemes", []) or []:
        if scheme.get("name") != schema_name:
            continue
        labels = []
        for label in scheme.get("labels", []) or []:
            if isinstance(label, dict):
                name = label.get("name")
                if name:
                    labels.append(str(name))
            else:
                labels.append(str(label))
        return labels
    return None


def _item_text(app_config, instance_id, max_chars=2000):
    """Display text for an instance (text_key with get_text() fallback)."""
    try:
        ism = get_item_state_manager()
        if not ism.has_item(instance_id):
            return ""
        data = ism.get_item(instance_id).get_data()
        text_key = (app_config.get("item_properties") or {}).get("text_key", "text")
        value = data.get(text_key)
        text = value if isinstance(value, str) else ism.get_item(instance_id).get_text()
        text = text or ""
    except Exception:
        return ""
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


# ----------------------------------------------------------------------
# Pages

@rooms_bp.route("", methods=["GET"])
@rooms_bp.route("/", methods=["GET"])
def lobby():
    if get_rooms_manager() is None:
        return "Rooms are not enabled for this task", 404
    if "username" not in session:
        return redirect("/")
    manager = get_rooms_manager()
    return render_template(
        "rooms_lobby.html",
        username=session["username"],
        task_name=manager.app_config.get("annotation_task_name", "Annotation Task"),
        can_create=_can_create(session["username"]),
        poll_interval_ms=manager.rooms_config.poll_interval_ms,
    )


@rooms_bp.route("/<room_id>", methods=["GET"])
def room_page(room_id):
    if get_rooms_manager() is None:
        return "Rooms are not enabled for this task", 404
    if "username" not in session:
        return redirect("/")
    manager = get_rooms_manager()
    room = manager.get_room(room_id)
    if room is None:
        return redirect("/rooms")
    return render_template(
        "room.html",
        room_id=room.room_id,
        username=session["username"],
        task_name=manager.app_config.get("annotation_task_name", "Annotation Task"),
        poll_interval_ms=manager.rooms_config.poll_interval_ms,
    )


# ----------------------------------------------------------------------
# Lobby APIs

def _can_create(username):
    manager = get_rooms_manager()
    if manager.rooms_config.who_can_create == "any":
        return True
    return get_rbac_manager().check(
        Permission.VIEW_ADMIN_DASHBOARD, request, session)


@rooms_bp.route("/api/list", methods=["GET"])
@rooms_required
@api_login_required
def list_rooms():
    return jsonify({"rooms": get_rooms_manager().list_rooms()})


@rooms_bp.route("/api/disagreements", methods=["GET"])
@rooms_required
@api_login_required
def disagreements():
    """Items the team currently disagrees on — seeds for a huddle."""
    manager = get_rooms_manager()
    rows = manager.find_disagreements()[:MAX_ROOM_ITEMS]
    for row in rows:
        row["text"] = _item_text(manager.app_config, row["instance_id"],
                                 max_chars=200)
    return jsonify({"disagreements": rows})


@rooms_bp.route("/api/create", methods=["POST"])
@rooms_required
@api_login_required
@same_origin_required
def create_room():
    username = session["username"]
    if not _can_create(username):
        return jsonify({"error": "Room creation is restricted to admins"}), 403

    manager = get_rooms_manager()
    data = request.get_json(silent=True) or {}
    room_type = str(data.get("room_type") or "norming")
    if room_type not in ROOM_TYPES:
        return jsonify({"error": f"Unknown room type '{room_type}'"}), 400

    schema = manager.rooms_config.schema
    labels = _scheme_labels(manager.app_config, schema)
    if not labels:
        return jsonify({"error": f"No labels found for schema '{schema}'"}), 400

    ism = get_item_state_manager()
    settings = {}
    if room_type == HUDDLE:
        # Seed from live disagreements: the room walks the disputed items
        # with everyone's original annotations shown as context.
        seeds = manager.find_disagreements()
        if data.get("item_ids"):
            wanted = {str(i) for i in data["item_ids"]}
            seeds = [s for s in seeds if s["instance_id"] in wanted]
        seeds = seeds[:MAX_ROOM_ITEMS]
        if not seeds:
            return jsonify({"error": "No disagreements to huddle over"}), 400
        item_ids = [s["instance_id"] for s in seeds]
        settings["seed_annotations"] = {
            s["instance_id"]: s["annotations"] for s in seeds}
    elif data.get("item_ids"):
        item_ids = [str(i) for i in data["item_ids"]][:MAX_ROOM_ITEMS]
        unknown = [i for i in item_ids if not ism.has_item(i)]
        if unknown:
            return jsonify({"error": f"Unknown items: {unknown[:5]}"}), 400
    else:
        try:
            n_items = max(1, min(int(data.get("n_items", 10)), MAX_ROOM_ITEMS))
        except (TypeError, ValueError):
            return jsonify({"error": "n_items must be a number"}), 400
        all_ids = [item.get_id() for item in ism.items()]
        if not all_ids:
            return jsonify({"error": "No items loaded"}), 400
        item_ids = random.sample(all_ids, min(n_items, len(all_ids)))

    room = manager.create_room(username, room_type, item_ids, labels,
                               schema=schema, settings=settings)
    logger.info("rooms: %s created %s room %s (%d items)",
                username, room_type, room.room_id, len(item_ids))
    return jsonify({"success": True, "room_id": room.room_id})


# ----------------------------------------------------------------------
# Room APIs

@rooms_bp.route("/api/<room_id>/join", methods=["POST"])
@rooms_required
@api_login_required
@same_origin_required
def join_room(room_id):
    room, err = _get_room_or_404(room_id)
    if err:
        return err
    username = session["username"]
    data = request.get_json(silent=True) or {}
    role = str(data.get("role") or MEMBER)
    if role not in (MEMBER, OBSERVER):
        return jsonify({"error": f"Unknown role '{role}'"}), 400
    # In shadow rooms everyone but the host observes.
    if room.room_type == SHADOW and username != room.host:
        role = OBSERVER
    try:
        get_rooms_manager().join(room, username, role)
    except RoomError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"success": True,
                    "role": room.members[username].role})


@rooms_bp.route("/api/<room_id>/leave", methods=["POST"])
@rooms_required
@api_login_required
@same_origin_required
def leave_room(room_id):
    room, err = _get_room_or_404(room_id)
    if err:
        return err
    try:
        get_rooms_manager().leave(room, session["username"])
    except RoomError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"success": True})


@rooms_bp.route("/api/<room_id>/state", methods=["GET"])
@rooms_required
@api_login_required
def room_state(room_id):
    room, err = _get_room_or_404(room_id)
    if err:
        return err
    forbidden = _require_membership(room)
    if forbidden:
        return forbidden
    manager = get_rooms_manager()
    state = room.to_state(viewer=session["username"])
    if state["current_instance_id"]:
        state["item_text"] = _item_text(manager.app_config,
                                        state["current_instance_id"])
    state["metrics"] = manager.metrics(room)
    state["poll_interval_ms"] = manager.rooms_config.poll_interval_ms
    return jsonify(state)


@rooms_bp.route("/api/<room_id>/events", methods=["GET"])
@rooms_required
@api_login_required
def room_events(room_id):
    room, err = _get_room_or_404(room_id)
    if err:
        return err
    forbidden = _require_membership(room)
    if forbidden:
        return forbidden
    manager = get_rooms_manager()
    try:
        since = max(0, int(request.args.get("since", 0)))
    except (TypeError, ValueError):
        since = 0
    events = manager.events_since(room, since)
    payload = {
        "events": events,
        "cursor": len(room.events),
    }
    if room.room_type == SHADOW:
        try:
            presence_since = max(0, int(request.args.get("presence", 0)))
        except (TypeError, ValueError):
            presence_since = 0
        payload["presence"] = manager.presence_since(room, presence_since)
    return jsonify(payload)


def _room_action(room_id, action, *args):
    room, err = _get_room_or_404(room_id)
    if err:
        return err
    try:
        event = getattr(get_rooms_manager(), action)(room, session["username"], *args)
    except RoomError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"success": True, "seq": event["seq"]})


@rooms_bp.route("/api/<room_id>/vote", methods=["POST"])
@rooms_required
@api_login_required
@same_origin_required
def vote(room_id):
    data = request.get_json(silent=True) or {}
    label = data.get("label")
    if not label:
        return jsonify({"error": "label is required"}), 400
    return _room_action(room_id, "vote", str(label))


@rooms_bp.route("/api/<room_id>/reveal", methods=["POST"])
@rooms_required
@api_login_required
@same_origin_required
def reveal(room_id):
    return _room_action(room_id, "reveal")


@rooms_bp.route("/api/<room_id>/advance", methods=["POST"])
@rooms_required
@api_login_required
@same_origin_required
def advance(room_id):
    return _room_action(room_id, "advance")


@rooms_bp.route("/api/<room_id>/close", methods=["POST"])
@rooms_required
@api_login_required
@same_origin_required
def close(room_id):
    return _room_action(room_id, "close")


@rooms_bp.route("/api/<room_id>/message", methods=["POST"])
@rooms_required
@api_login_required
@same_origin_required
def message(room_id):
    data = request.get_json(silent=True) or {}
    return _room_action(room_id, "message", str(data.get("text") or ""))


@rooms_bp.route("/api/<room_id>/presence", methods=["POST"])
@rooms_required
@api_login_required
@same_origin_required
def presence(room_id):
    room, err = _get_room_or_404(room_id)
    if err:
        return err
    forbidden = _require_membership(room)
    if forbidden:
        return forbidden
    data = request.get_json(silent=True) or {}
    payload = data.get("data")
    if not isinstance(payload, dict):
        return jsonify({"error": "data must be an object"}), 400
    get_rooms_manager().record_presence(room, session["username"], payload)
    return jsonify({"success": True})


@rooms_bp.route("/api/<room_id>/export", methods=["GET"])
@rooms_required
@api_login_required
def export(room_id):
    room, err = _get_room_or_404(room_id)
    if err:
        return err
    username = session["username"]
    member = room.members.get(username)
    is_host = member is not None and member.role == HOST
    if not is_host and not get_rbac_manager().check(
            Permission.VIEW_ADMIN_DASHBOARD, request, session):
        return jsonify({"error": "Host or admin only"}), 403
    return jsonify(get_rooms_manager().export_room(room))
