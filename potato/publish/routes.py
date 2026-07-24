"""Admin routes for dataset publishing.

    GET  /admin/publish                 the publish wizard (HTML)
    GET  /admin/publish/api/defaults     config-derived form defaults
    POST /admin/publish/api/preview      run pipeline + card, no upload -> {card,...}
    POST /admin/publish/api/start        start a background publish job
    GET  /admin/publish/api/status       poll job status
    GET  /admin/publish/api/download     download the last local archive

Gated by ``Permission.EXPORT_DATA`` through the shared RBAC layer (the admin API key
is a superuser bypass). Tokens arrive in the POST body and are never persisted.
"""

from functools import wraps

from flask import (Blueprint, jsonify, render_template, request,
                   send_file, session)

from potato.publish.manager import get_publish_manager
from potato.server_utils.rbac import Permission, require_permission

publish_bp = Blueprint("publish", __name__, url_prefix="/admin/publish")

admin_required = require_permission(Permission.EXPORT_DATA)


def _enabled_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if get_publish_manager() is None:
            return jsonify({"error": "Publishing not enabled"}), 400
        return f(*args, **kwargs)
    return wrapper


def _split_request(data):
    """Pull the (options, metadata, target, credentials) tuple from a JSON body."""
    data = data or {}
    return (data.get("options") or {},
            data.get("metadata") or {},
            str(data.get("target", "archive")),
            data.get("credentials") or {})


@publish_bp.route("", methods=["GET"])
@admin_required
@_enabled_required
def publish_page():
    mgr = get_publish_manager()
    return render_template("admin/publish.html", defaults=mgr.defaults())


@publish_bp.route("/api/defaults", methods=["GET"])
@admin_required
@_enabled_required
def api_defaults():
    return jsonify(get_publish_manager().defaults())


@publish_bp.route("/api/preview", methods=["POST"])
@admin_required
@_enabled_required
def api_preview():
    options, metadata, target, _ = _split_request(request.get_json(silent=True))
    try:
        result = get_publish_manager().preview(options, metadata, target)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@publish_bp.route("/api/start", methods=["POST"])
@admin_required
@_enabled_required
def api_start():
    options, metadata, target, credentials = _split_request(
        request.get_json(silent=True))
    result = get_publish_manager().start_publish(options, metadata, target,
                                                 credentials)
    status = 202 if result.get("started") else 409
    return jsonify(result), status


@publish_bp.route("/api/status", methods=["GET"])
@admin_required
@_enabled_required
def api_status():
    return jsonify(get_publish_manager().status())


@publish_bp.route("/api/download", methods=["GET"])
@admin_required
@_enabled_required
def api_download():
    archive = get_publish_manager().last_archive()
    if not archive:
        return jsonify({"error": "No archive available"}), 404
    return send_file(archive, as_attachment=True)
