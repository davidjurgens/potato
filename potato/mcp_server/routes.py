"""
The live MCP control surface: `/api/mcp/*`, registered only when a task opts in.

One blueprint, one authorization gate, one audit log. The alternative -- adding
agent scopes to the 400-odd routes already in the app -- would spread the policy
across every file that ever grows a route, and there would be no single place to
read to find out what an agent can do.

The gate, in order, failing closed with a reason at every step:

    mcp.enabled          the blueprint exists at all
    token                a valid, unrevoked per-agent token
    mcp.tools            the admin named this tool
    mcp.destructive      and named it again, if it destroys work
    confirm: true        and the caller said so at call time
    rbac.check           the token's role carries the permission

Note what is *not* in that list: debug mode. `validate_admin_api_key()` returns
True unconditionally under `debug: true` and `RBACManager.check()` passes
everything except ADJUDICATE, so inheriting either would mean a debug server
hands full control to anyone who can reach the port. Registration itself refuses
under debug unless `mcp.allow_debug` is set.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request

from potato.mcp_server.live_tools import TOOLS, describe_tools
from potato.server_utils.agent_tokens import extract_bearer, verify_token

logger = logging.getLogger(__name__)

mcp_bp = Blueprint("mcp", __name__)

DEFAULT_AUDIT_LOG = "mcp_audit.jsonl"


def _config() -> Dict[str, Any]:
    """The live config. Read through the app so tests can hand it their own."""
    configured = current_app.config.get("mcp_task_config")
    if configured is not None:
        return configured
    from potato.server_utils.config_module import config

    return config


def _mcp_settings() -> Dict[str, Any]:
    return (_config().get("mcp") or {})


def audit(event: str, **fields) -> None:
    """Append one line to the audit log.

    Full control is on the table, so every attempt is recorded whether or not it
    was allowed -- refusals are the more interesting half.
    """
    settings = _mcp_settings()
    filename = settings.get("audit_log") or DEFAULT_AUDIT_LOG
    if not os.path.isabs(filename):
        filename = os.path.join(_config().get("task_dir") or ".", filename)

    record = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        "remote_addr": request.remote_addr if request else None,
        **fields,
    }
    try:
        os.makedirs(os.path.dirname(os.path.abspath(filename)) or ".", exist_ok=True)
        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError as e:  # pragma: no cover - never fail a request over logging
        logger.warning("Could not write the MCP audit log: %s", e)


def _refuse(reason: str, status: int = 403, **extra) -> Tuple[Any, int]:
    return jsonify({"error": reason, **extra}), status


def authorize(tool_name: str, payload: Optional[dict] = None):
    """Run the whole gate for `tool_name`. Returns (record, None) or (None, response)."""
    settings = _mcp_settings()
    payload = payload or {}

    if not settings.get("enabled"):
        return None, _refuse("The MCP surface is not enabled for this task.", 404)

    tool = TOOLS.get(tool_name)
    if tool is None:
        audit("unknown_tool", tool=tool_name)
        return None, _refuse(
            f"Unknown tool: {tool_name}", 404, valid_tools=sorted(TOOLS)
        )

    record = verify_token(extract_bearer(request.headers), _config())
    if record is None:
        audit("auth_failed", tool=tool_name)
        return None, _refuse(
            "A valid agent token is required. Send it as "
            "'Authorization: Bearer <token>'.",
            401,
        )

    granted = settings.get("tools") or []
    if tool_name not in granted:
        audit("not_granted", tool=tool_name, agent=record.name)
        return None, _refuse(
            f"'{tool_name}' is not in mcp.tools for this task.",
            403,
            granted_tools=sorted(granted),
        )

    if tool.destructive:
        if tool_name not in (settings.get("destructive") or []):
            audit("destructive_not_opted_in", tool=tool_name, agent=record.name)
            return None, _refuse(
                f"'{tool_name}' destroys work and is not listed in "
                f"mcp.destructive, which is a separate opt-in from mcp.tools.",
            )
        if payload.get("confirm") is not True:
            audit("destructive_unconfirmed", tool=tool_name, agent=record.name)
            return None, _refuse(
                f"'{tool_name}' destroys work. Pass \"confirm\": true to proceed.",
                400,
            )

    from potato.server_utils.rbac import get_rbac_manager

    manager = get_rbac_manager()
    if not manager.has_permission(record.name, tool.permission):
        # Fall back to the role on the token itself: the agent is not a
        # registered user, so `rbac.user_role_assignments` will not know it.
        from potato.server_utils.rbac import DEFAULT_ROLE_PERMISSIONS

        role_permissions = DEFAULT_ROLE_PERMISSIONS.get(record.role, set())
        if tool.permission not in role_permissions:
            audit("permission_denied", tool=tool_name, agent=record.name,
                  role=record.role, permission=tool.permission)
            return None, _refuse(
                f"The '{record.role}' role does not carry "
                f"'{tool.permission}', which '{tool_name}' requires."
            )

    scope = settings.get("scope") or {}
    users = scope.get("users")
    target_user = payload.get("username")
    if users and target_user and target_user not in users:
        audit("out_of_scope", tool=tool_name, agent=record.name, target=target_user)
        return None, _refuse(
            f"mcp.scope.users does not include {target_user!r}."
        )

    return record, None


def mcp_tool(tool_name: str):
    """Wrap a view in the gate, and audit the call that gets through."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            payload = request.get_json(silent=True) or {}
            record, refusal = authorize(tool_name, payload)
            if refusal is not None:
                return refusal
            audit("call", tool=tool_name, agent=record.name, role=record.role,
                  args=sorted(payload))
            return view(record, payload, *args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------- meta --

@mcp_bp.route("/api/mcp/manifest", methods=["GET"])
def manifest():
    """What this task exposes. Requires a token but no particular tool grant.

    An agent needs to discover its own permissions before it can use them, and
    the answer already tells it nothing it could not learn by trying each tool.
    """
    settings = _mcp_settings()
    if not settings.get("enabled"):
        return _refuse("The MCP surface is not enabled for this task.", 404)

    record = verify_token(extract_bearer(request.headers), _config())
    if record is None:
        audit("auth_failed", tool="manifest")
        return _refuse("A valid agent token is required.", 401)

    granted = settings.get("tools") or []
    return jsonify({
        "task": _config().get("annotation_task_name", ""),
        "agent": record.name,
        "role": record.role,
        "tools": describe_tools(granted),
        "destructive_enabled": sorted(settings.get("destructive") or []),
        "scope": settings.get("scope") or {},
    })


# --------------------------------------------------------------------- read --

@mcp_bp.route("/api/mcp/tools/get_status", methods=["POST"])
@mcp_tool("get_status")
def tool_get_status(record, payload):
    from potato.item_state_management import get_item_state_manager
    from potato.user_state_management import get_user_state_manager

    ism = get_item_state_manager()
    usm = get_user_state_manager()
    return jsonify({
        "task": _config().get("annotation_task_name", ""),
        "items": len(ism.get_instance_ids()),
        "annotators": len(usm.get_user_ids()),
    })


@mcp_bp.route("/api/mcp/tools/get_progress", methods=["POST"])
@mcp_tool("get_progress")
def tool_get_progress(record, payload):
    from potato.server_utils.progress_stats import compute_project_progress

    return jsonify(compute_project_progress())


@mcp_bp.route("/api/mcp/tools/list_annotators", methods=["POST"])
@mcp_tool("list_annotators")
def tool_list_annotators(record, payload):
    from potato.user_state_management import get_user_state_manager

    usm = get_user_state_manager()
    out = []
    for username in usm.get_user_ids():
        state = usm.get_user_state(username)
        out.append({
            "username": username,
            "assigned": state.get_assigned_instance_count(),
            "annotated": state.get_annotation_count(),
            "phase": str(state.get_phase()),
        })
    return jsonify({"annotators": out})


@mcp_bp.route("/api/mcp/tools/list_items", methods=["POST"])
@mcp_tool("list_items")
def tool_list_items(record, payload):
    from potato.item_state_management import get_item_state_manager

    ism = get_item_state_manager()
    limit = int(payload.get("limit", 50))
    offset = int(payload.get("offset", 0))
    ids = list(ism.get_instance_ids())[offset:offset + limit]
    return jsonify({
        "total": len(ism.get_instance_ids()),
        "offset": offset,
        "items": [
            {
                "instance_id": iid,
                "annotators": sorted(ism.get_annotators_for_item(iid) or []),
            }
            for iid in ids
        ],
    })


@mcp_bp.route("/api/mcp/tools/get_item", methods=["POST"])
@mcp_tool("get_item")
def tool_get_item(record, payload):
    from potato.item_state_management import get_item_state_manager

    instance_id = payload.get("instance_id")
    if not instance_id:
        return _refuse("instance_id is required", 400)

    ism = get_item_state_manager()
    item = ism.get_item(instance_id)
    if item is None:
        return _refuse(f"No such item: {instance_id}", 404)

    return jsonify({
        "instance_id": instance_id,
        "data": item.get_data(),
        "annotators": sorted(ism.get_annotators_for_item(instance_id) or []),
    })


@mcp_bp.route("/api/mcp/tools/get_agreement", methods=["POST"])
@mcp_tool("get_agreement")
def tool_get_agreement(record, payload):
    from potato.admin import AdminDashboard

    result = AdminDashboard().get_agreement_metrics()
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@mcp_bp.route("/api/mcp/tools/get_config", methods=["POST"])
@mcp_tool("get_config")
def tool_get_config(record, payload):
    config = _config()
    # Never hand back the secrets that live in the same dict.
    redacted = {
        k: v for k, v in config.items()
        if k not in {"secret_key", "admin_api_key", "mcp"}
        and not k.startswith("_")
    }
    return jsonify({"config": redacted})


# -------------------------------------------------------------------- write --

@mcp_bp.route("/api/mcp/tools/add_items", methods=["POST"])
@mcp_tool("add_items")
def tool_add_items(record, payload):
    from potato.item_state_management import get_item_state_manager

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return _refuse("items must be a non-empty list of objects", 400)

    config = _config()
    id_key = (config.get("item_properties") or {}).get("id_key", "id")

    ism = get_item_state_manager()
    added = []
    for item in items:
        if not isinstance(item, dict) or id_key not in item:
            return _refuse(f"every item needs a {id_key!r} field", 400)
        ism.add_item(str(item[id_key]), item)
        added.append(str(item[id_key]))

    audit("items_added", agent=record.name, count=len(added))
    return jsonify({
        "added": added,
        # Items added at runtime are stored and visible to admins but never
        # handed out unless the per-user cap is unlimited.
        "note": (
            "Runtime-added items are only assigned when "
            "max_annotations_per_user is -1."
            if config.get("max_annotations_per_user", -1) != -1 else None
        ),
    })


@mcp_bp.route("/api/mcp/tools/submit_annotation", methods=["POST"])
@mcp_tool("submit_annotation")
def tool_submit_annotation(record, payload):
    from potato.user_state_management import get_user_state_manager

    username = payload.get("username")
    instance_id = payload.get("instance_id")
    annotations = payload.get("annotations")
    if not username or not instance_id or not isinstance(annotations, dict):
        return _refuse(
            "username, instance_id and an annotations object are required", 400
        )

    usm = get_user_state_manager()
    state = usm.get_user_state(username)
    if state is None:
        return _refuse(f"No such annotator: {username}", 404)

    # Same four-argument shape /updateinstance uses, so an agent's annotation
    # is stored exactly like a human's rather than through a second path.
    state.set_annotation(
        instance_id,
        annotations,
        payload.get("span_annotations") or [],
        payload.get("behavioral_data") or {},
    )
    usm.save_user_state(username)
    audit("annotation_submitted", agent=record.name, target=username,
          instance_id=instance_id)
    return jsonify({"status": "ok", "instance_id": instance_id})


@mcp_bp.route("/api/mcp/tools/assign_items", methods=["POST"])
@mcp_tool("assign_items")
def tool_assign_items(record, payload):
    from potato.user_state_management import get_user_state_manager

    username = payload.get("username")
    max_instances = payload.get("max_instances")
    if not username or max_instances is None:
        return _refuse("username and max_instances are required", 400)

    usm = get_user_state_manager()
    state = usm.get_user_state(username)
    if state is None:
        return _refuse(f"No such annotator: {username}", 404)

    # Never below what they have already done -- annotations cannot be undone
    # by lowering a cap, and the admin route applies the same floor.
    max_instances = int(max_instances)
    current = state.get_annotation_count()
    if 0 <= max_instances < current:
        max_instances = current

    state.set_max_assignments(max_instances)
    usm.save_user_state(username)
    audit("assignment_changed", agent=record.name, target=username,
          max_instances=max_instances)
    return jsonify({"status": "ok", "username": username,
                    "max_instances": max_instances})


@mcp_bp.route("/api/mcp/tools/export_data", methods=["POST"])
@mcp_tool("export_data")
def tool_export_data(record, payload):
    from potato.export import export_registry

    fmt = payload.get("format")
    if not fmt:
        return _refuse(
            "format is required", 400,
            available=sorted(export_registry.list_exporters()),
        )

    config = _config()
    config_file = config.get("__config_file__")
    if not config_file:
        return _refuse("This server does not know its own config path.", 500)

    from potato.export.cli import build_export_context

    output = payload.get("output") or os.path.join(
        config.get("output_annotation_dir", "."), "exports", fmt
    )
    os.makedirs(output, exist_ok=True)
    context = build_export_context(config_file)
    result = export_registry.export(fmt, context, output, payload.get("options") or {})
    audit("exported", agent=record.name, format=fmt, output=output)
    return jsonify({"format": fmt, "output": output, "result": result})


# -------------------------------------------------------------- destructive --

@mcp_bp.route("/api/mcp/tools/delete_annotations", methods=["POST"])
@mcp_tool("delete_annotations")
def tool_delete_annotations(record, payload):
    from potato.user_state_management import get_user_state_manager

    username = payload.get("username")
    instance_id = payload.get("instance_id")
    if not username or not instance_id:
        return _refuse("username and instance_id are required", 400)

    usm = get_user_state_manager()
    state = usm.get_user_state(username)
    if state is None:
        return _refuse(f"No such annotator: {username}", 404)

    state.set_annotation(instance_id, {}, [], {})
    usm.save_user_state(username)
    audit("annotations_deleted", agent=record.name, target=username,
          instance_id=instance_id)
    return jsonify({"status": "deleted", "username": username,
                    "instance_id": instance_id})


def register_mcp_routes(flask_app, app_config) -> bool:
    """Register the blueprint if the task opts in. Returns whether it did.

    Refuses under `debug: true` unless `mcp.allow_debug` is set, because debug
    mode disables admin authentication server-wide.
    """
    settings = (app_config.get("mcp") or {})
    if not settings.get("enabled"):
        return False

    if app_config.get("debug") and not settings.get("allow_debug"):
        logger.error(
            "mcp.enabled is set but the server is in debug mode, which disables "
            "admin authentication. Refusing to register the MCP control "
            "surface. Set mcp.allow_debug: true to override."
        )
        return False

    if "mcp" in flask_app.blueprints:
        return True

    flask_app.register_blueprint(mcp_bp)

    # Registering the blueprint is not enough on its own -- see the invariant in
    # routes.py:configure_routes(). Blueprint rules do survive, but the endpoint
    # names are recorded here so a reader can confirm what got added.
    logger.info(
        "Registered the MCP control surface: %s tool(s) granted",
        len(settings.get("tools") or []),
    )
    return True
