"""Flask blueprint for Pocket Mode (mobile-first annotation PWA).

- ``GET /pocket``                     — the mobile annotation page (session auth)
- ``GET /pocket/api/task``            — task name, schema specs, capability verdict
- ``GET /pocket/api/batch?n=``        — next items for the card stack / offline queue
- ``GET /pocket/manifest.webmanifest`` — PWA manifest
- ``GET /pocket/sw.js``               — service worker (served under /pocket so its
                                        scope covers the app shell)

Annotation saves go through the EXISTING ``/updateinstance`` endpoint with the
same payload the desktop page sends — Pocket Mode adds no new write path.
"""

import logging
from functools import wraps
from typing import Any, Dict, Optional

from flask import (
    Blueprint,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from potato.pocket.config import (
    PocketConfig,
    parse_pocket_config,
    pocket_capability,
)

logger = logging.getLogger(__name__)

pocket_bp = Blueprint("pocket", __name__, url_prefix="/pocket")

# Initialized by init_pocket() on every server boot path (run_server,
# create_app, FlaskTestServer) — the module must not rely on importing a
# specific flask_server module instance (the __main__ vs potato.flask_server
# split makes that unreliable).
_app_config: Optional[Dict[str, Any]] = None
_pocket_config: Optional[PocketConfig] = None


def init_pocket(app_config: Dict[str, Any]) -> Optional[PocketConfig]:
    """Store config for the blueprint. Returns None when disabled."""
    global _app_config, _pocket_config
    if not (app_config.get("pocket") or {}).get("enabled", False):
        _app_config = None
        _pocket_config = None
        return None
    _app_config = app_config
    _pocket_config = parse_pocket_config(app_config)
    capable, incompatible = pocket_capability(app_config)
    if not capable:
        logger.warning(
            "Pocket Mode enabled but schemes %s are not touch-capable; "
            "/pocket will explain rather than degrade", incompatible)
    logger.info("Pocket Mode enabled (batch_size=%d)", _pocket_config.batch_size)
    return _pocket_config


def clear_pocket() -> None:
    global _app_config, _pocket_config
    _app_config = None
    _pocket_config = None


def pocket_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if _pocket_config is None:
            return jsonify({"error": "Pocket Mode not enabled"}), 404
        return f(*args, **kwargs)

    return decorated_function


def api_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)

    return decorated_function


def pocket_routing_state() -> Dict[str, Any]:
    """What device routing should do for this task.

    Safe to call whether or not Pocket Mode is enabled — used by the
    annotate route (server-side redirect) and by /pocket/api/routing
    (the client-side coarse-pointer fallback and the mobile warning).
    ``capable`` reflects the task's schemas regardless of the pocket
    config, so "this task is not mobile friendly" warnings stay accurate
    even when Pocket Mode is off.
    """
    enabled = _pocket_config is not None
    app_config = _app_config
    if app_config is None:
        try:
            from potato.server_utils.config_module import config as app_config
        except Exception:
            app_config = {}
    capable, incompatible = pocket_capability(app_config or {})
    auto_redirect = bool(_pocket_config.auto_redirect) if enabled else False
    return {
        "enabled": enabled,
        "capable": capable,
        "auto_redirect": auto_redirect,
        "available": enabled and capable and auto_redirect,
        "incompatible_schemes": incompatible,
    }


def _scheme_spec(scheme: Dict[str, Any]) -> Dict[str, Any]:
    labels = []
    for label in scheme.get("labels", []) or []:
        if isinstance(label, dict):
            if label.get("name"):
                labels.append(str(label["name"]))
        else:
            labels.append(str(label))
    return {
        "name": scheme.get("name"),
        "annotation_type": scheme.get("annotation_type"),
        "description": scheme.get("description", ""),
        "labels": labels,
        # slider/likert extras the client renderers need
        "min": scheme.get("min", scheme.get("min_value")),
        "max": scheme.get("max", scheme.get("max_value")),
        "size": scheme.get("size"),
    }


def _serialize_annotations(raw: Dict[Any, Any]) -> Dict[str, Dict[str, Any]]:
    """{schema: {label: value}} from the in-memory label->value mapping."""
    out: Dict[str, Dict[str, Any]] = {}
    for key, value in (raw or {}).items():
        schema = getattr(key, "schema", None)
        name = getattr(key, "name", None)
        if schema is None and isinstance(key, (tuple, list)) and len(key) == 2:
            schema, name = key
        if schema is None:
            continue
        out.setdefault(str(schema), {})[str(name)] = value
    return out


@pocket_bp.route("", methods=["GET"], strict_slashes=False)
@pocket_required
def page():
    if "username" not in session:
        return redirect(url_for("login"))
    # Opening /pocket explicitly clears a previous "Desktop site" choice.
    session.pop("force_desktop", None)
    try:
        from potato.pocket.devices import get_device_tracker
        get_device_tracker().record(
            session["username"], request.headers.get("User-Agent"), "pocket")
    except Exception:  # tracking must never break the page
        logger.debug("pocket: device tracking failed", exc_info=True)
    return render_template(
        "pocket.html",
        task_name=_app_config.get("annotation_task_name", "Annotation Task"),
    )


@pocket_bp.route("/api/routing", methods=["GET"])
@api_login_required
def routing():
    """Device-routing facts for the current task (works even when Pocket
    Mode is disabled — the annotation page uses this to decide whether to
    client-side redirect touch devices or warn them)."""
    return jsonify(pocket_routing_state())


@pocket_bp.route("/api/device_hint", methods=["POST"])
@api_login_required
def device_hint():
    """Client-side touch detection (primary pointer is coarse) for devices
    whose User-Agent looks like desktop — e.g. iPadOS Safari."""
    from potato.pocket.devices import get_device_tracker
    data = request.get_json(silent=True) or {}
    device = str(data.get("device") or "")
    get_device_tracker().record_client_hint(session["username"], device)
    return jsonify({"success": True})


@pocket_bp.route("/api/devices", methods=["GET"])
def devices():
    """Per-annotator device usage for the admin dashboard."""
    from potato.server_utils.rbac import Permission, get_rbac_manager
    if not get_rbac_manager().check(
            Permission.VIEW_ADMIN_DASHBOARD, request, session):
        return jsonify({"error": "Admin authentication required"}), 403
    from potato.pocket.devices import get_device_tracker
    payload = get_device_tracker().stats()
    payload["routing"] = pocket_routing_state()
    return jsonify(payload)


@pocket_bp.route("/api/task", methods=["GET"])
@pocket_required
@api_login_required
def task():
    capable, incompatible = pocket_capability(_app_config)
    return jsonify({
        "task_name": _app_config.get("annotation_task_name", "Annotation Task"),
        "capable": capable,
        "incompatible_schemes": incompatible,
        "schemas": [_scheme_spec(s)
                    for s in _app_config.get("annotation_schemes", []) or []],
        "batch_size": _pocket_config.batch_size,
    })


@pocket_bp.route("/api/batch", methods=["GET"])
@pocket_required
@api_login_required
def batch():
    """Next items for this annotator: unannotated first, in assignment order."""
    from potato.item_state_management import get_item_state_manager
    from potato.user_state_management import get_user_state_manager

    try:
        n = min(int(request.args.get("n", _pocket_config.batch_size)), 200)
    except ValueError:
        return jsonify({"error": "n must be an integer"}), 400

    username = session["username"]
    user_state = get_user_state_manager().get_user_state(username)
    ism = get_item_state_manager()
    # Users auto-routed here on their first visit have never run through
    # /annotate's assignment step — assign now or the card stack is empty.
    if not user_state.has_assignments():
        ism.assign_instances_to_user(user_state)
    text_key = (_app_config.get("item_properties") or {}).get("text_key", "text")

    items = []
    total = 0
    done = 0
    for instance_id in user_state.instance_id_ordering:
        total += 1
        existing = user_state.get_label_annotations(instance_id)
        annotated = bool(existing)
        if annotated:
            done += 1
        if annotated or len(items) >= n:
            continue
        if not ism.has_item(instance_id):
            continue
        item = ism.get_item(instance_id)
        data = item.get_data()
        text = data.get(text_key)
        if not isinstance(text, str) or not text.strip():
            text = item.get_text()
        items.append({
            "instance_id": str(instance_id),
            "text": text,
            "annotations": _serialize_annotations(existing),
        })

    return jsonify({"items": items, "total": total, "done": done})


_MANIFEST = {
    "name": "Potato Pocket",
    "short_name": "Potato",
    "start_url": "/pocket",
    "scope": "/pocket",
    "display": "standalone",
    "background_color": "#f4f2f9",
    "theme_color": "#5b21b6",
    "icons": [{
        "src": "/static/pocket-icon.svg",
        "sizes": "any",
        "type": "image/svg+xml",
        "purpose": "any",
    }],
}


@pocket_bp.route("/manifest.webmanifest", methods=["GET"])
@pocket_required
def manifest():
    return jsonify(_MANIFEST)


@pocket_bp.route("/sw.js", methods=["GET"])
@pocket_required
def service_worker():
    """Serve the service worker from /pocket so its scope covers the shell."""
    from flask import current_app
    import os

    path = os.path.join(current_app.static_folder, "pocket-sw.js")
    try:
        with open(path, "r", encoding="utf-8") as f:
            body = f.read()
    except OSError:
        return Response("// service worker unavailable", mimetype="application/javascript")
    return Response(body, mimetype="application/javascript",
                    headers={"Cache-Control": "no-cache"})
