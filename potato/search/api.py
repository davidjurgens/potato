"""
Search REST API (universal).

Phase 1 exposes admin/adjudicator read-only search at
``/admin/api/search``. Read-only search is safe under every assignment
strategy and crowd backend (no self-selection), so it has no config
guard. Annotator search-and-claim is a separate, guarded endpoint.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, session

from .service import get_search, search_settings

logger = logging.getLogger(__name__)

search_bp = Blueprint("search", __name__)


def _config() -> dict:
    from potato.server_utils.config_module import config
    return config


def _annotator_claim_enabled() -> bool:
    return bool(search_settings(_config()).get("annotator_claim"))


def _serialize(hits) -> list:
    return [
        {"instance_id": h.instance_id, "snippet": h.snippet, "score": h.score}
        for h in hits
    ]


def _is_privileged() -> bool:
    """Admin (API key) or adjudicator may use admin search."""
    username = session.get("username")
    try:
        from potato.admin import admin_dashboard
        if admin_dashboard.check_admin_access():
            return True
    except Exception:
        pass
    if username:
        try:
            from potato.adjudication import get_adjudication_manager
            adj = get_adjudication_manager()
            if adj and adj.is_adjudicator(username):
                return True
        except Exception:
            pass
    return False


@search_bp.route("/admin/api/search", methods=["GET"])
def admin_search():
    if not _is_privileged():
        return jsonify({"error": "Admin or adjudicator access required"}), 403
    backend = get_search()
    if backend is None:
        return jsonify({
            "error": "Search is not enabled or unavailable in this "
                     "deployment.",
            "hint": "Set search.enabled: true (requires a SQLite build "
                    "with FTS5).",
        }), 503
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required"}), 400
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 500))
    except (TypeError, ValueError):
        limit = 50
    hits = backend.query(q, limit=limit)
    return jsonify({
        "query": q, "count": len(hits), "results": _serialize(hits),
    })


def _annotator_ctx():
    """(username, backend) for annotator search/claim, or an error tuple."""
    if not _annotator_claim_enabled():
        return None, None, ("disabled",)
    username = session.get("username")
    if not username:
        return None, None, ("unauth",)
    backend = get_search()
    if backend is None:
        return None, None, ("unavailable",)
    return username, backend, None


def _annotator_err(err):
    if err == ("disabled",):
        return jsonify({
            "error": "Annotator search-and-claim is not enabled.",
            "hint": "Set search.annotator_claim: true (subject to the "
                    "assignment-compatibility guard).",
        }), 403
    if err == ("unauth",):
        return jsonify({"error": "Not authenticated"}), 401
    if err == ("unavailable",):
        return jsonify({"error": "Search is not enabled or unavailable."}), 503
    return None


@search_bp.route("/api/search", methods=["GET"])
def annotator_search():
    """Annotator-facing corpus search. Gated by search.annotator_claim;
    the startup guard guarantees the assignment design is compatible."""
    username, backend, err = _annotator_ctx()
    if err:
        return _annotator_err(err)
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required"}), 400
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
    except (TypeError, ValueError):
        limit = 50
    hits = backend.query(q, limit=limit)
    return jsonify({
        "query": q, "count": len(hits), "results": _serialize(hits),
    })


@search_bp.route("/api/search/claim", methods=["POST"])
def annotator_claim():
    """Pull a matching instance into the requesting annotator's queue."""
    username, backend, err = _annotator_ctx()
    if err:
        return _annotator_err(err)
    data = request.get_json(silent=True) or {}
    instance_id = data.get("instance_id")
    if not instance_id:
        return jsonify({"error": "instance_id is required"}), 400
    try:
        from potato.item_state_management import get_item_state_manager
        from potato.user_state_management import get_user_state_manager
        ism = get_item_state_manager()
        try:
            item = ism.get_item(str(instance_id))
        except Exception:
            return jsonify({"error": f"Unknown instance {instance_id}"}), 404
        if item is None:
            return jsonify({"error": f"Unknown instance {instance_id}"}), 404
        user_state = get_user_state_manager().get_user_state(username)
        already = instance_id in user_state.get_assigned_instance_ids()
        user_state.assign_instance(item)
    except Exception as e:
        logger.error(f"Claim failed for {instance_id}: {e}")
        return jsonify({"error": "Could not claim instance"}), 500
    return jsonify({
        "claimed": str(instance_id),
        "already_assigned": bool(already),
    })
