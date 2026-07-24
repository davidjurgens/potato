"""Flask blueprint for Boundary Lab (counterfactual boundary probing).

Annotator endpoints (session auth):
- ``POST /boundary/api/probe``   — fetch/generate probes for (instance, schema, label)
- ``POST /boundary/api/respond`` — record a verdict (holds / flips / unsure)

Admin endpoints (RBAC; debug mode and the shared admin key pass):
- ``GET /boundary/dashboard``  — live dashboard page
- ``GET /boundary/api/stats``  — dashboard aggregates
- ``GET /boundary/api/export`` — contrast-set JSONL download
"""

import json
import logging
from functools import wraps

from flask import Blueprint, Response, jsonify, render_template, request, session

from potato.boundary.manager import VALID_VERDICTS, get_boundary_manager
from potato.item_state_management import get_item_state_manager
from potato.server_utils.rbac import Permission, require_permission

logger = logging.getLogger(__name__)

boundary_bp = Blueprint("boundary", __name__, url_prefix="/boundary")

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


def boundary_required(f):
    """404 when Boundary Lab isn't enabled for this task."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_boundary_manager() is None:
            return jsonify({"error": "Boundary probing not enabled"}), 404
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


def _instance_text(manager, item):
    """Extract the annotatable text using the configured text_key."""
    text_key = (manager.app_config.get("item_properties") or {}).get("text_key", "text")
    data = item.get_data()
    text = data.get(text_key)
    if isinstance(text, str) and text.strip():
        return text
    return item.get_text()


@boundary_bp.route("/api/probe", methods=["POST"])
@boundary_required
@api_login_required
@same_origin_required
def probe():
    """Return probes for (instance_id, schema, label), generating on first request.

    Also returns this annotator's existing verdicts so the panel can restore
    completed state after navigation.
    """
    manager = get_boundary_manager()
    data = request.get_json(silent=True) or {}
    instance_id = str(data.get("instance_id") or "")
    schema = data.get("schema") or manager.boundary_config.schema
    label = data.get("label")
    if not instance_id or not schema or not label:
        return jsonify({"error": "instance_id, schema, and label are required"}), 400
    if schema != manager.boundary_config.schema:
        return jsonify({"error": f"Schema '{schema}' is not configured for probing"}), 400

    labels = _scheme_labels(manager, schema)
    if labels is None:
        return jsonify({"error": f"Unknown annotation scheme '{schema}'"}), 404
    if label not in labels:
        return jsonify({"error": f"Unknown label '{label}' for scheme '{schema}'"}), 400

    ism = get_item_state_manager()
    if not ism.has_item(instance_id):
        return jsonify({"error": f"Unknown instance '{instance_id}'"}), 404
    item = ism.get_item(instance_id)
    text = _instance_text(manager, item)
    if not text or not text.strip():
        return jsonify({"probes": [], "labels": labels, "responses": {}})

    try:
        probes = manager.get_or_generate_probes(
            instance_id, schema, label, labels, text, item_data=item.get_data()
        )
    except Exception:
        logger.exception("Boundary probe generation failed for instance %s", instance_id)
        return jsonify({"error": "Probe generation failed"}), 500

    responses = manager.get_user_responses(session["username"], instance_id, schema, label)
    return jsonify({
        "probes": [
            {k: p[k] for k in ("probe_id", "kind", "text", "edit_hint", "source")}
            for p in probes
        ],
        "labels": labels,
        "original_label": label,
        "original_text": text,
        "responses": responses,
        "rationale_on_flip": manager.boundary_config.rationale_on_flip,
    })


@boundary_bp.route("/api/respond", methods=["POST"])
@boundary_required
@api_login_required
@same_origin_required
def respond():
    """Record an annotator's verdict on a probe."""
    manager = get_boundary_manager()
    data = request.get_json(silent=True) or {}
    probe_id = data.get("probe_id")
    verdict = data.get("verdict")
    if not probe_id or verdict not in VALID_VERDICTS:
        return jsonify({
            "error": f"probe_id and a verdict in {list(VALID_VERDICTS)} are required"
        }), 400

    new_label = data.get("new_label")
    if verdict == "flips":
        if not new_label:
            return jsonify({"error": "new_label is required when verdict is 'flips'"}), 400
        labels = _scheme_labels(manager, manager.boundary_config.schema) or []
        if new_label not in labels:
            return jsonify({"error": f"Unknown label '{new_label}'"}), 400

    rationale = data.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        return jsonify({"error": "rationale must be a string"}), 400
    if rationale and len(rationale) > 2000:
        rationale = rationale[:2000]

    try:
        record = manager.record_response(
            session["username"], probe_id, verdict,
            new_label=new_label, rationale=rationale,
        )
    except KeyError:
        return jsonify({"error": f"Unknown probe_id '{probe_id}'"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"success": True, "response": record})


@boundary_bp.route("/dashboard", methods=["GET"])
@boundary_required
@admin_required
def dashboard():
    """Boundary Lab dashboard: sensitivity, consistency, contrast gallery."""
    manager = get_boundary_manager()
    return render_template(
        "boundary_dashboard.html",
        task_name=manager.app_config.get("annotation_task_name", "Annotation Task"),
    )


@boundary_bp.route("/api/stats", methods=["GET"])
@boundary_required
@admin_required
def stats():
    return jsonify(get_boundary_manager().get_stats())


@boundary_bp.route("/api/export", methods=["GET"])
@boundary_required
@admin_required
def export():
    """Download the collected contrast set as JSONL."""
    records = get_boundary_manager().export_contrast_set()
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    if body:
        body += "\n"
    return Response(
        body,
        mimetype="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=contrast_set.jsonl"},
    )
