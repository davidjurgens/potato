"""
Admin routes for the automation engine (inspection).

    GET /admin/automation/status    rules + counters + by-action breakdown
    GET /admin/automation/outcomes  recent action outcomes
    GET /admin/automation           HTML admin page

Rules are configured in the YAML ``automation`` block (declarative); these
endpoints inspect what's configured and what has fired.
"""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, render_template, request, session

from potato.automation.manager import get_automation_manager

automation_bp = Blueprint("automation", __name__, url_prefix="/admin/automation")


def _enabled_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if get_automation_manager() is None:
            return jsonify({"error": "Automation not enabled"}), 400
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


@automation_bp.route("/status", methods=["GET"])
@admin_required
@_enabled_required
def status():
    return jsonify(get_automation_manager().get_status())


@automation_bp.route("/outcomes", methods=["GET"])
@admin_required
@_enabled_required
def outcomes():
    limit = request.args.get("limit", default=100, type=int)
    return jsonify({"outcomes": get_automation_manager().recent_outcomes(limit)})


@automation_bp.route("", methods=["GET"])
@admin_required
@_enabled_required
def admin_page():
    mgr = get_automation_manager()
    return render_template(
        "admin/automation_rules.html",
        status=mgr.get_status(),
        outcomes=mgr.recent_outcomes(100),
    )
