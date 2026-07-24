"""
Event Registry Routes

JSON API for cross-document event annotation. Consumed by the
`multi_document_event` schema's frontend (multi-document-event.js) and by the
corpus map. All state-changing routes require an authenticated session and pass
a lightweight same-origin (CSRF) check, mirroring solo_mode.

Blueprint shares the ``/corpus`` URL prefix with the corpus map so all
multi-document endpoints sit under one namespace.
"""

import logging
from functools import wraps

from flask import Blueprint, request, jsonify, session

from .manager import get_event_registry_manager, EvidenceCitation, StaleWriteError

logger = logging.getLogger(__name__)

event_registry_bp = Blueprint("event_registry", __name__, url_prefix="/corpus")


def _enabled_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if get_event_registry_manager() is None:
            return jsonify({"error": "Event registry not enabled"}), 400
        return f(*args, **kwargs)

    return wrapper


def api_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)

    return wrapper


def same_origin_required(f):
    """CSRF defense: reject cross-origin state-changing requests."""

    @wraps(f)
    def wrapper(*args, **kwargs):
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

    return wrapper


def _current_user() -> str:
    return session.get("username", "")


# ---- config / template -----------------------------------------------------
@event_registry_bp.route("/api/event_template", methods=["GET"])
@api_login_required
@_enabled_required
def event_template():
    mgr = get_event_registry_manager()
    return jsonify(
        {
            "template_name": mgr.template_name,
            "slots": mgr.slots,
            "allow_annotator_create": mgr.allow_annotator_create,
        }
    )


# ---- reads -----------------------------------------------------------------
@event_registry_bp.route("/api/events", methods=["GET"])
@api_login_required
@_enabled_required
def list_events():
    mgr = get_event_registry_manager()
    doc_id = request.args.get("doc_id")
    events = mgr.list_events(doc_id=doc_id if doc_id else None)
    return jsonify({"events": [e.to_dict() for e in events]})


@event_registry_bp.route("/api/event/<event_id>", methods=["GET"])
@api_login_required
@_enabled_required
def get_event(event_id):
    mgr = get_event_registry_manager()
    ev = mgr.get_event(event_id)
    if ev is None:
        return jsonify({"error": "Event not found"}), 404
    return jsonify(ev.to_dict())


# ---- mutations -------------------------------------------------------------
@event_registry_bp.route("/api/event", methods=["POST"])
@api_login_required
@same_origin_required
@_enabled_required
def create_event():
    mgr = get_event_registry_manager()
    if not mgr.allow_annotator_create:
        return jsonify({"error": "Annotator event creation disabled"}), 403
    data = request.get_json(silent=True) or {}
    ev = mgr.create_event(user=_current_user(), title=data.get("title", ""))
    doc_id = data.get("doc_id")
    if doc_id:
        mgr.add_member(ev.id, str(doc_id))
        ev = mgr.get_event(ev.id)
    return jsonify(ev.to_dict()), 201


@event_registry_bp.route("/api/event/<event_id>/slot", methods=["POST"])
@api_login_required
@same_origin_required
@_enabled_required
def update_slot(event_id):
    mgr = get_event_registry_manager()
    data = request.get_json(silent=True) or {}
    slot = data.get("slot")
    if not slot:
        return jsonify({"error": "Missing 'slot'"}), 400
    try:
        ev = mgr.update_slot(
            event_id, slot, data.get("value", ""), _current_user(),
            expected_updated_at=data.get("expected_updated_at"),
        )
    except StaleWriteError as e:
        # Another annotator changed this event first — tell the client to refresh.
        return jsonify({"error": "stale_write", "current": e.current.to_dict()}), 409
    if ev is None:
        return jsonify({"error": "Event not found"}), 404
    return jsonify(ev.to_dict())


@event_registry_bp.route("/api/event/<event_id>/title", methods=["POST"])
@api_login_required
@same_origin_required
@_enabled_required
def set_title(event_id):
    mgr = get_event_registry_manager()
    data = request.get_json(silent=True) or {}
    ev = mgr.set_title(event_id, data.get("title", ""))
    if ev is None:
        return jsonify({"error": "Event not found"}), 404
    return jsonify(ev.to_dict())


@event_registry_bp.route("/api/event/<event_id>/member", methods=["POST"])
@api_login_required
@same_origin_required
@_enabled_required
def set_member(event_id):
    mgr = get_event_registry_manager()
    data = request.get_json(silent=True) or {}
    doc_id = data.get("doc_id")
    if not doc_id:
        return jsonify({"error": "Missing 'doc_id'"}), 400
    attach = data.get("attach", True)
    ev = mgr.add_member(event_id, str(doc_id)) if attach else mgr.remove_member(event_id, str(doc_id))
    if ev is None:
        return jsonify({"error": "Event not found"}), 404
    return jsonify(ev.to_dict())


@event_registry_bp.route("/api/event/<event_id>/evidence", methods=["POST"])
@api_login_required
@same_origin_required
@_enabled_required
def add_evidence(event_id):
    mgr = get_event_registry_manager()
    data = request.get_json(silent=True) or {}
    required = ("slot", "doc_id")
    if not all(data.get(k) for k in required):
        return jsonify({"error": "Missing slot or doc_id"}), 400
    citation = EvidenceCitation(
        slot_name=data["slot"],
        doc_id=str(data["doc_id"]),
        span_start=int(data.get("start", 0)),
        span_end=int(data.get("end", 0)),
        quoted_text=data.get("text", ""),
        span_id=data.get("span_id", ""),
        created_by=_current_user(),
    )
    ev = mgr.add_evidence(event_id, citation)
    if ev is None:
        return jsonify({"error": "Event not found"}), 404
    return jsonify(ev.to_dict())


@event_registry_bp.route("/api/event/<event_id>/evidence/<int:index>", methods=["DELETE"])
@api_login_required
@same_origin_required
@_enabled_required
def remove_evidence(event_id, index):
    mgr = get_event_registry_manager()
    ev = mgr.remove_evidence(event_id, index)
    if ev is None:
        return jsonify({"error": "Event not found"}), 404
    return jsonify(ev.to_dict())


@event_registry_bp.route("/api/event/<event_id>", methods=["DELETE"])
@api_login_required
@same_origin_required
@_enabled_required
def delete_event(event_id):
    mgr = get_event_registry_manager()
    ok = mgr.delete_event(event_id)
    if not ok:
        return jsonify({"error": "Event not found"}), 404
    return jsonify({"success": True})
