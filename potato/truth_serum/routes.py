"""Flask blueprint for Truth Serum (surprisingly-popular scoring).

Annotator endpoints (session auth):
- ``POST /truth_serum/api/predict`` — record label + popularity prediction
- ``GET  /truth_serum/api/mine``    — this annotator's prediction for an instance

Admin endpoints (RBAC; debug mode and the shared admin key pass):
- ``GET /truth_serum/dashboard``  — verdicts + calibration dashboard
- ``GET /truth_serum/api/stats``  — dashboard aggregates
- ``GET /truth_serum/api/export`` — full JSON export (verdicts + raw predictions)
"""

import logging
from functools import wraps

from flask import Blueprint, jsonify, render_template, request, session

from potato.item_state_management import get_item_state_manager
from potato.server_utils.rbac import Permission, require_permission
from potato.truth_serum.manager import get_truth_serum_manager

logger = logging.getLogger(__name__)

truth_serum_bp = Blueprint("truth_serum", __name__, url_prefix="/truth_serum")

admin_required = require_permission(Permission.VIEW_ADMIN_DASHBOARD)


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


def truth_serum_required(f):
    """404 when Truth Serum isn't enabled for this task."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_truth_serum_manager() is None:
            return jsonify({"error": "Truth Serum not enabled"}), 404
        return f(*args, **kwargs)

    return decorated_function


def _scheme_labels(manager, schema_name):
    """Resolve the label list for a configured annotation scheme."""
    for scheme in manager.app_config.get("annotation_schemes", []) or []:
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


@truth_serum_bp.route("/api/predict", methods=["POST"])
@truth_serum_required
@api_login_required
@same_origin_required
def predict():
    """Record an annotator's label + predicted peer agreement for an instance."""
    manager = get_truth_serum_manager()
    data = request.get_json(silent=True) or {}
    instance_id = str(data.get("instance_id") or "")
    label = data.get("label")
    predicted_pct = data.get("predicted_pct")
    if not instance_id or not label or predicted_pct is None:
        return jsonify({"error": "instance_id, label, and predicted_pct are required"}), 400

    labels = _scheme_labels(manager, manager.ts_config.schema) or []
    if label not in labels:
        return jsonify({"error": f"Unknown label '{label}'"}), 400

    ism = get_item_state_manager()
    if not ism.has_item(instance_id):
        return jsonify({"error": f"Unknown instance '{instance_id}'"}), 404

    try:
        record = manager.record_prediction(
            session["username"], instance_id, label, predicted_pct)
    except (TypeError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"success": True, "prediction": record})


@truth_serum_bp.route("/api/mine", methods=["GET"])
@truth_serum_required
@api_login_required
def mine():
    """This annotator's stored prediction for an instance (widget restore)."""
    manager = get_truth_serum_manager()
    instance_id = str(request.args.get("instance_id") or "")
    if not instance_id:
        return jsonify({"error": "instance_id is required"}), 400
    record = manager.get_prediction(session["username"], instance_id)
    return jsonify({"prediction": record})


@truth_serum_bp.route("/dashboard", methods=["GET"])
@truth_serum_required
@admin_required
def dashboard():
    """Truth Serum dashboard: SP verdicts, disagreements, calibration."""
    manager = get_truth_serum_manager()
    return render_template(
        "truth_serum_dashboard.html",
        task_name=manager.app_config.get("annotation_task_name", "Annotation Task"),
    )


def _attach_text(manager, items, max_chars=280):
    """Attach a display snippet of each instance's text to result rows."""
    text_key = (manager.app_config.get("item_properties") or {}).get("text_key", "text")
    ism = get_item_state_manager()
    for row in items:
        text = ""
        try:
            if ism.has_item(row["instance_id"]):
                data = ism.get_item(row["instance_id"]).get_data()
                value = data.get(text_key)
                text = value if isinstance(value, str) else ism.get_item(row["instance_id"]).get_text()
        except Exception:  # display enrichment must never break stats
            text = ""
        if text and len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        row["text"] = text
    return items


@truth_serum_bp.route("/api/stats", methods=["GET"])
@truth_serum_required
@admin_required
def stats():
    manager = get_truth_serum_manager()
    payload = manager.get_stats()
    _attach_text(manager, payload["items"])
    # "disagreements" rows are the same dicts, already enriched in place.
    return jsonify(payload)


@truth_serum_bp.route("/api/export", methods=["GET"])
@truth_serum_required
@admin_required
def export():
    """Full export: item verdicts + raw predictions."""
    return jsonify(get_truth_serum_manager().export_records())
