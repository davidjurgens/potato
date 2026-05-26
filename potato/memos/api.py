"""
Memos REST API (universal).

Blueprint mounted at /api/memos. Visibility/permission enforcement lives
in the service layer; this layer handles auth (logged-in user), the
feature gate (annotation_ui.memos), request parsing, and error mapping.

Privilege tier ("always read / may delete others"): adjudicators, via the
adjudication manager. Admin-dashboard memo moderation is a later follow-up.
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, jsonify, request, session

from . import (
    MemoError,
    MemoNotFound,
    MemoPermissionError,
    create_memo,
    delete_memo,
    list_visible,
    update_memo,
)

logger = logging.getLogger(__name__)

memos_bp = Blueprint("memos", __name__, url_prefix="/api/memos")


def _config() -> dict:
    from potato.server_utils.config_module import config
    return config


def memos_enabled(config: dict) -> bool:
    """Default: off in standard mode; on when qda_mode or solo_mode is on.
    Explicit annotation_ui.memos always wins."""
    ui = config.get("annotation_ui") or {}
    if isinstance(ui, dict) and "memos" in ui:
        return bool(ui["memos"])
    return bool(
        (config.get("qda_mode") or {}).get("enabled")
        or (config.get("solo_mode") or {}).get("enabled")
    )


def _default_visibility(config: dict) -> str:
    ui = config.get("annotation_ui") or {}
    v = ui.get("visibility") if isinstance(ui, dict) else None
    return v if v in ("private", "shared") else "private"


def _is_privileged(username: str) -> bool:
    try:
        from potato.adjudication import get_adjudication_manager
        adj = get_adjudication_manager()
        return bool(adj and adj.is_adjudicator(username))
    except Exception:
        return False


def _ctx():
    """(task_dir, project, username, is_privileged) or None if not usable."""
    config = _config()
    if not memos_enabled(config):
        return None, None, None, None, ("memos_disabled",)
    username = session.get("username")
    if not username:
        return None, None, None, None, ("unauthenticated",)
    task_dir = config.get("task_dir", ".")
    project = config.get("annotation_task_name") or "default"
    return task_dir, project, username, _is_privileged(username), None


def memos_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        task_dir, project, username, priv, err = _ctx()
        if err == ("memos_disabled",):
            return jsonify({
                "error": "Memos are not enabled in this deployment.",
                "hint": "Set annotation_ui.memos: true (on by default in "
                        "qda_mode/solo_mode).",
            }), 503
        if err == ("unauthenticated",):
            return jsonify({"error": "Not authenticated"}), 401
        return view(task_dir, project, username, priv, *args, **kwargs)
    return wrapper


def _handle(fn):
    """Map service exceptions to HTTP codes."""
    try:
        return fn()
    except MemoNotFound as e:
        return jsonify({"error": str(e)}), 404
    except MemoPermissionError as e:
        return jsonify({"error": str(e)}), 403
    except MemoError as e:
        return jsonify({"error": str(e)}), 400


@memos_bp.route("", methods=["GET"])
@memos_required
def list_memos(task_dir, project, username, priv):
    instance_id = request.args.get("instance_id")
    if not instance_id:
        return jsonify({"error": "instance_id is required"}), 400
    memos = list_visible(
        task_dir, project=project, instance_id=instance_id,
        requester=username, is_privileged=priv,
    )
    return jsonify({"memos": memos})


@memos_bp.route("", methods=["POST"])
@memos_required
def post_memo(task_dir, project, username, priv):
    data = request.get_json(silent=True) or {}
    instance_id = data.get("instance_id")
    if not instance_id:
        return jsonify({"error": "instance_id is required"}), 400
    visibility = data.get("visibility") or _default_visibility(_config())
    return _handle(lambda: jsonify({"memo": create_memo(
        task_dir, project=project, instance_id=instance_id,
        body=data.get("body", ""), created_by=username,
        anchor=data.get("anchor"), visibility=visibility,
    )}))


@memos_bp.route("/<memo_id>", methods=["PATCH"])
@memos_required
def patch_memo(task_dir, project, username, priv, memo_id):
    data = request.get_json(silent=True) or {}
    return _handle(lambda: jsonify({"memo": update_memo(
        task_dir, memo_id, requester=username, is_privileged=priv,
        body=data.get("body"), visibility=data.get("visibility"),
    )}))


@memos_bp.route("/<memo_id>", methods=["DELETE"])
@memos_required
def remove_memo(task_dir, project, username, priv, memo_id):
    def _do():
        delete_memo(task_dir, memo_id, requester=username, is_privileged=priv)
        return jsonify({"ok": True})
    return _handle(_do)
