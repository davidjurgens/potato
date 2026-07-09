"""
Sessions REST API + page.

Blueprint serving the ``/sessions`` review page and the ``/api/sessions``
endpoints. Auth mirrors solo-mode conventions: session login for reads,
login + same-origin for the state-changing save, admin (or X-API-Key)
for the export endpoint.
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import (
    Blueprint, jsonify, redirect, render_template, request, session,
    url_for,
)

from potato.sessions.service import (
    SESSION_LEVEL_SUPPORTED_TYPES,
    get_session_level_schemes,
    session_aggregates,
    sessions_enabled,
    sessions_project,
    write_session_export,
)

logger = logging.getLogger(__name__)

sessions_bp = Blueprint("sessions", __name__)


def _config() -> dict:
    from potato.server_utils.config_module import config
    return config


def _ctx():
    config = _config()
    return {
        "config": config,
        "task_dir": config.get("task_dir", "."),
        "project": sessions_project(config),
    }


def _api_guard(f):
    """JSON 503/401 guard for /api/sessions endpoints."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not sessions_enabled(_config()):
            return jsonify({
                "error": "Sessions are not enabled in this deployment.",
                "hint": "Set sessions.enabled: true",
            }), 503
        if not session.get("username"):
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return wrapper


def _same_origin_required(f):
    """CSRF guard for state-changing routes (solo-mode pattern)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")
        host = request.host_url.rstrip("/")
        if origin and not origin.startswith(host):
            return jsonify({"error": "Cross-origin request rejected"}), 403
        if referer and not referer.startswith(host):
            return jsonify({"error": "Cross-origin request rejected"}), 403
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@sessions_bp.route("/sessions", methods=["GET"])
def sessions_page():
    config = _config()
    if not sessions_enabled(config):
        return redirect(url_for("home"))
    username = session.get("username")
    if not username:
        return redirect(url_for("home"))
    return render_template(
        "sessions.html",
        annotation_task_name=config.get(
            "annotation_task_name", "Annotation Task"),
        username=username,
        session_schemes=[_scheme_summary(s)
                         for s in get_session_level_schemes(config)],
    )


def _scheme_summary(scheme: dict) -> dict:
    """The scheme fields the page JS needs to render widgets."""
    labels = []
    for label in scheme.get("labels", []) or []:
        labels.append(label.get("name", "") if isinstance(label, dict)
                      else label)
    return {
        "name": scheme["name"],
        "annotation_type": scheme["annotation_type"],
        "description": scheme.get("description", scheme["name"]),
        "labels": labels,
        "size": scheme.get("size"),
        "min_label": scheme.get("min_label", ""),
        "max_label": scheme.get("max_label", ""),
        "min_value": scheme.get("min_value", 0),
        "max_value": scheme.get("max_value", 100),
    }


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@sessions_bp.route("/api/sessions", methods=["GET"])
@_api_guard
def list_sessions():
    ctx = _ctx()
    from potato.cases import store as case_store
    from potato.cases import annotations as case_annos

    username = session["username"]
    out = []
    for case in case_store.list_cases(ctx["task_dir"], ctx["project"]):
        annos = case_annos.annotations_for_case(ctx["task_dir"], case["id"])
        mine = {r["schema"] for r in annos if r["annotator"] == username}
        out.append({
            "case_id": case["id"],
            "name": case["name"],
            "n_traces": len(case_store.instances_for_case(
                ctx["task_dir"], case["id"])),
            "aggregates": session_aggregates(annos),
            "my_schemas_done": sorted(mine),
        })
    return jsonify({"sessions": out})


@sessions_bp.route("/api/sessions/<case_id>", methods=["GET"])
@_api_guard
def session_detail(case_id):
    ctx = _ctx()
    from potato.cases import store as case_store
    from potato.cases import annotations as case_annos
    from potato.item_state_management import get_item_state_manager

    case = case_store.get_case(ctx["task_dir"], case_id)
    if case is None or case["project"] != ctx["project"]:
        return jsonify({"error": "Unknown session"}), 404

    username = session["username"]
    instance_ids = case_store.instances_for_case(ctx["task_dir"], case_id)

    # Trace previews for the member list
    ism = get_item_state_manager()
    text_key = (_config().get("item_properties") or {}).get("text_key", "text")
    members = []
    for iid in instance_ids:
        preview = ""
        try:
            data = ism.get_item(iid).get_data()
            if isinstance(data, dict):
                raw = data.get(text_key) or data.get("task_description") or ""
                preview = str(raw)[:160]
        except Exception:
            pass
        members.append({"instance_id": iid, "preview": preview})

    annos = case_annos.annotations_for_case(ctx["task_dir"], case_id)
    mine = {r["schema"]: r["value"] for r in annos
            if r["annotator"] == username}
    return jsonify({
        "case_id": case_id,
        "name": case["name"],
        "attributes": case_store.attributes(ctx["task_dir"], case_id),
        "members": members,
        "my_annotations": mine,
        "aggregates": session_aggregates(annos),
    })


@sessions_bp.route("/api/sessions/<case_id>/annotate", methods=["POST"])
@_api_guard
@_same_origin_required
def annotate_session(case_id):
    ctx = _ctx()
    from potato.cases import store as case_store
    from potato.cases import annotations as case_annos

    case = case_store.get_case(ctx["task_dir"], case_id)
    if case is None or case["project"] != ctx["project"]:
        return jsonify({"error": "Unknown session"}), 404

    payload = request.get_json(silent=True) or {}
    schema = payload.get("schema")
    schemes = {s["name"]: s for s in get_session_level_schemes(ctx["config"])}
    if schema not in schemes:
        return jsonify({"error": f"Unknown session-level schema: {schema}"}), 400

    value = payload.get("value")
    if value is not None and not isinstance(value, dict):
        return jsonify({"error": "value must be an object or null"}), 400
    if value is not None:
        unknown = set(value) - {"value", "values"}
        if unknown:
            return jsonify({"error": "value accepts only 'value'/'values' keys"}), 400
        if "values" in value and not isinstance(value["values"], list):
            return jsonify({"error": "'values' must be a list"}), 400

    case_annos.set_annotation(
        ctx["task_dir"], case_id=case_id,
        annotator=session["username"], schema=schema, value=value,
    )
    export_path = write_session_export(ctx["config"])
    return jsonify({"status": "ok", "export": export_path})


@sessions_bp.route("/api/sessions/export", methods=["GET"])
def export_sessions():
    """Full session annotation dump (admin / X-API-Key)."""
    config = _config()
    if not sessions_enabled(config):
        return jsonify({"error": "Sessions not enabled"}), 503
    from potato.server_utils.rbac import get_rbac_manager, Permission
    if not get_rbac_manager().check(
            Permission.VIEW_ADMIN_DASHBOARD, request, session):
        return jsonify({"error": "Admin access required"}), 403

    ctx = _ctx()
    from potato.cases import store as case_store
    from potato.cases import annotations as case_annos
    rows = []
    for row in case_annos.annotations_for_project(
            ctx["task_dir"], ctx["project"]):
        rows.append({
            "session": row.get("case_name"),
            "case_id": row["case_id"],
            "annotator": row["annotator"],
            "schema": row["schema"],
            "value": row.get("value"),
            "updated_at": row.get("updated_at"),
            "instance_ids": case_store.instances_for_case(
                ctx["task_dir"], row["case_id"]),
        })
    return jsonify({"session_annotations": rows})
