"""
Admin routes for the multi-model arena.

    GET  /admin/arena                 HTML page
    POST /admin/arena/api/run         {prompt} -> per-model responses
    POST /admin/arena/api/preference  {prompt, winner, ranking} -> record a pick
    GET  /admin/arena/api/leaderboard Bradley-Terry + Elo + win-rate per model
    GET  /admin/arena/api/export_dpo  human preferences as DPO (chosen/rejected) pairs
"""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, render_template, request, session

from potato.arena.manager import get_arena_manager

arena_bp = Blueprint("arena", __name__, url_prefix="/admin/arena")


def _enabled_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if get_arena_manager() is None:
            return jsonify({"error": "Arena not enabled"}), 400
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        from potato.server_utils.admin_key import validate_admin_api_key
        from potato.flask_server import config as _config
        api_key = request.headers.get("X-API-Key") or session.get("admin_api_key")
        if not validate_admin_api_key(api_key, _config):
            return jsonify({"error": "Admin authentication required"}), 403
        return f(*args, **kwargs)
    return wrapper


@arena_bp.route("", methods=["GET"])
@admin_required
@_enabled_required
def arena_page():
    mgr = get_arena_manager()
    return render_template(
        "admin/arena.html",
        models=mgr.model_labels(),
        leaderboard=mgr.leaderboard(),
    )


@arena_bp.route("/api/run", methods=["POST"])
@admin_required
@_enabled_required
def api_run():
    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    mgr = get_arena_manager()
    if not mgr.settings.models:
        return jsonify({"error": "no models configured"}), 400
    return jsonify({"prompt": prompt, "results": mgr.run(prompt)})


@arena_bp.route("/api/preference", methods=["POST"])
@admin_required
@_enabled_required
def api_preference():
    body = request.get_json(silent=True) or {}
    winner = body.get("winner")
    if not winner:
        return jsonify({"error": "winner is required"}), 400
    mgr = get_arena_manager()
    mgr.record_preference(body.get("prompt", ""), winner, body.get("ranking"))
    return jsonify({"recorded": True, "leaderboard": mgr.leaderboard()})


@arena_bp.route("/api/leaderboard", methods=["GET"])
@admin_required
@_enabled_required
def api_leaderboard():
    return jsonify({"leaderboard": get_arena_manager().leaderboard()})


@arena_bp.route("/api/export_dpo", methods=["GET"])
@admin_required
@_enabled_required
def api_export_dpo():
    """Arena human preferences as DPO triples (prompt, chosen, rejected)."""
    pairs = get_arena_manager().export_dpo()
    return jsonify({"count": len(pairs), "pairs": pairs})


@arena_bp.route("/api/suggest_pairs", methods=["GET"])
@admin_required
@_enabled_required
def api_suggest_pairs():
    """Active preference selection (E10): which response pairs to label next.

    ?k=N (default 10), ?strategy=uncertainty|moderate_margin|random.
    """
    from potato.server_utils.active_preference import STRATEGIES
    strategy = request.args.get("strategy", "uncertainty")
    if strategy not in STRATEGIES:
        return jsonify({"error": f"strategy must be one of {STRATEGIES}"}), 400
    try:
        k = int(request.args.get("k", 10))
    except (TypeError, ValueError):
        k = 10
    pairs = get_arena_manager().suggest_pairs(k=k, strategy=strategy)
    return jsonify({"count": len(pairs), "strategy": strategy, "pairs": pairs})
