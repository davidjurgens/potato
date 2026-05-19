"""
Codebook REST API (universal).

Blueprint mounted at /api/codebook. Read access is open to any
authenticated annotator when the codebook is enabled; write access is
governed by the effective ``codebook_mode``:

- ``fixed``      → no API mutations (config/CLI only)
- ``extensible`` → authenticated users may *add* codes
- ``open``       → authenticated users may add / rename / recolor /
  move / delete

Adjudicators are privileged and may always mutate (any mode but
``fixed``-locked still applies — fixed means locked for everyone here;
use ``potato codebook`` / config to change a fixed codebook).

The single mutation path is the codebook service, so human and LLM
edits (solo mode) share one audit trail (``created_by``).
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, jsonify, request, session

from potato.codebook import (
    CodebookError,
    CodeNotFound,
    DuplicateCodeError,
    Codebook,
    create_code,
    delete_code,
    move_under,
    recolor_code,
    rename_code,
)
from potato.codebook.store import ROOT

logger = logging.getLogger(__name__)

codebook_bp = Blueprint("codebook", __name__, url_prefix="/api/codebook")


def _config() -> dict:
    from potato.server_utils.config_module import config
    return config


def codebook_enabled(config: dict) -> bool:
    """On when a codebook scheme/config is present, or under qda/solo."""
    if config.get("codebook_mode") is not None:
        return True
    cb = config.get("codebook")
    if isinstance(cb, dict) and cb.get("enabled") is not None:
        return bool(cb.get("enabled"))
    for s in config.get("annotation_schemes") or []:
        if isinstance(s, dict) and s.get("codebook"):
            return True
    return bool(
        (config.get("qda_mode") or {}).get("enabled")
        or (config.get("solo_mode") or {}).get("enabled")
    )


def _is_privileged(username: str) -> bool:
    try:
        from potato.adjudication import get_adjudication_manager
        adj = get_adjudication_manager()
        return bool(adj and adj.is_adjudicator(username))
    except Exception:
        return False


def _ctx():
    config = _config()
    if not codebook_enabled(config):
        return None, ("disabled",)
    username = session.get("username")
    if not username:
        return None, ("unauth",)
    from potato.server_utils.config_module import get_codebook_mode
    return {
        "task_dir": config.get("task_dir", "."),
        "project": config.get("annotation_task_name") or "default",
        "username": username,
        "privileged": _is_privileged(username),
        "mode": get_codebook_mode(config),
    }, None


def codebook_view(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        ctx, err = _ctx()
        if err == ("disabled",):
            return jsonify({
                "error": "Codebook is not enabled in this deployment.",
                "hint": "Add `codebook: true` to a scheme, or set "
                        "codebook_mode (on by default in qda/solo).",
            }), 503
        if err == ("unauth",):
            return jsonify({"error": "Not authenticated"}), 401
        return view(ctx, *args, **kwargs)
    return wrapper


def _can_mutate(ctx, *, need_open: bool) -> bool:
    if ctx["mode"] == "fixed":
        return False
    if ctx["privileged"]:
        return True
    if ctx["mode"] == "open":
        return True
    # extensible: add allowed, structural edits are not
    return not need_open


def _handle(fn):
    try:
        return fn()
    except CodeNotFound as e:
        return jsonify({"error": str(e)}), 404
    except DuplicateCodeError as e:
        return jsonify({"error": str(e)}), 409
    except CodebookError as e:
        return jsonify({"error": str(e)}), 400


@codebook_bp.route("", methods=["GET"])
@codebook_view
def get_codebook(ctx):
    cb = Codebook.load(ctx["task_dir"], ctx["project"])
    return jsonify({
        "mode": ctx["mode"],
        "labels": cb.labels(),
        "tree": cb.as_tree(),
        "can_add": _can_mutate(ctx, need_open=False),
        "can_edit": _can_mutate(ctx, need_open=True),
    })


@codebook_bp.route("", methods=["POST"])
@codebook_view
def add_code(ctx):
    if not _can_mutate(ctx, need_open=False):
        return jsonify({
            "error": f"Adding codes is not allowed (codebook_mode="
                     f"{ctx['mode']})."}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    return _handle(lambda: jsonify({"code": create_code(
        ctx["task_dir"], project=ctx["project"], name=name,
        created_by=ctx["username"], color=data.get("color"),
        parent_id=data.get("parent_id") or ROOT,
    )}))


@codebook_bp.route("/<code_id>", methods=["PATCH"])
@codebook_view
def edit_code(ctx, code_id):
    if not _can_mutate(ctx, need_open=True):
        return jsonify({
            "error": f"Editing codes requires codebook_mode=open "
                     f"(current: {ctx['mode']})."}), 403
    data = request.get_json(silent=True) or {}

    def _do():
        result = None
        if "name" in data:
            result = rename_code(
                ctx["task_dir"], code_id,
                new_name=data["name"], project=ctx["project"])
        if "color" in data:
            result = recolor_code(
                ctx["task_dir"], code_id,
                color=data["color"], project=ctx["project"])
        if "parent_id" in data:
            result = move_under(
                ctx["task_dir"], code_id,
                new_parent_id=data["parent_id"] or ROOT,
                project=ctx["project"])
        if result is None:
            return jsonify({"error": "nothing to update"}), 400
        return jsonify({"code": result})

    return _handle(_do)


@codebook_bp.route("/<code_id>", methods=["DELETE"])
@codebook_view
def remove_code(ctx, code_id):
    if not _can_mutate(ctx, need_open=True):
        return jsonify({
            "error": f"Deleting codes requires codebook_mode=open "
                     f"(current: {ctx['mode']})."}), 403
    return _handle(lambda: jsonify({"deleted": delete_code(
        ctx["task_dir"], code_id, project=ctx["project"])}))
