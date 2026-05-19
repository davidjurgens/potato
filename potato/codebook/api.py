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
    codes_added_since,
    create_code,
    current_revision,
    delete_code,
    instance_revision,
    move_under,
    recolor_code,
    rename_code,
    stale_instances,
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


def _codebook_scheme_names() -> list:
    """Names of schemes opted into the codebook — the forms the tray
    refreshes in place after an add."""
    cfg = _config()
    return [s.get("name") for s in (cfg.get("annotation_schemes") or [])
            if isinstance(s, dict) and s.get("codebook") and s.get("name")]


def _instance_index_map() -> dict:
    """instance_id -> 0-based position, so the review worklist can jump
    via the existing index-based navigateToInstance()."""
    try:
        from potato.item_state_management import get_item_state_manager
        ids = get_item_state_manager().get_instance_ids()
        return {str(iid): i for i, iid in enumerate(ids)}
    except Exception:
        return {}


@codebook_bp.route("", methods=["GET"])
@codebook_view
def get_codebook(ctx):
    cb = Codebook.load(ctx["task_dir"], ctx["project"])
    return jsonify({
        "mode": ctx["mode"],
        "labels": cb.labels(),
        "tree": cb.as_tree(),
        "revision": current_revision(ctx["task_dir"], ctx["project"]),
        "schemes": _codebook_scheme_names(),
        "invivo_key": str(
            _config().get("codebook_invivo_key") or "i")[:1].lower(),
        "can_add": _can_mutate(ctx, need_open=False),
        "can_edit": _can_mutate(ctx, need_open=True),
    })


@codebook_bp.route("/version", methods=["GET"])
@codebook_view
def version(ctx):
    """Lightweight revision poll. The client checks this on each
    navigation and only re-fetches the full codebook (GET /api/codebook)
    when the revision has moved — instead of downloading the whole tree
    on every page load."""
    return jsonify({
        "revision": current_revision(ctx["task_dir"], ctx["project"])})


@codebook_bp.route("/provenance", methods=["GET"])
@codebook_view
def provenance(ctx):
    """Is one instance stale for the current annotator (labeled before
    later code additions)? Powers the dismissible revisit banner."""
    instance_id = request.args.get("instance_id")
    if not instance_id:
        return jsonify({"error": "instance_id is required"}), 400
    cur = current_revision(ctx["task_dir"], ctx["project"])
    ann = instance_revision(
        ctx["task_dir"], ctx["project"], instance_id, ctx["username"])
    added = ([] if ann is None or ann >= cur
             else codes_added_since(ctx["task_dir"], ctx["project"], ann))
    return jsonify({
        "instance_id": instance_id,
        "annotated_revision": ann,
        "current_revision": cur,
        "stale": bool(added),
        "codes_added_since": added,
    })


@codebook_bp.route("/stale", methods=["GET"])
@codebook_view
def stale(ctx):
    """The current annotator's review worklist: their instances labeled
    under an older revision, each with the codes added since."""
    items = stale_instances(
        ctx["task_dir"], ctx["project"], ctx["username"])
    idx = _instance_index_map()
    for it in items:
        it["index"] = idx.get(str(it["instance_id"]))
    return jsonify({"stale": items, "count": len(items)})


def _admin_or_adjudicator() -> bool:
    try:
        from potato.admin import admin_dashboard
        if admin_dashboard.check_admin_access():
            return True
    except Exception:
        pass
    username = session.get("username")
    if username:
        try:
            from potato.adjudication import get_adjudication_manager
            adj = get_adjudication_manager()
            if adj and adj.is_adjudicator(username):
                return True
        except Exception:
            pass
    return False


@codebook_bp.route("/admin/stale", methods=["GET"])
def admin_stale():
    """Project-wide stale instances (all users) for oversight. Admin
    API key or adjudicator only."""
    from potato.server_utils.config_module import config as _cfg
    if not codebook_enabled(_cfg):
        return jsonify({"error": "Codebook not enabled"}), 503
    if not _admin_or_adjudicator():
        return jsonify({
            "error": "Admin or adjudicator access required"}), 403
    from potato.codebook.revision import all_stale_instances
    task_dir = _cfg.get("task_dir", ".")
    project = _cfg.get("annotation_task_name") or "default"
    items = all_stale_instances(task_dir, project)
    return jsonify({"stale": items, "count": len(items)})


@codebook_bp.route("/similar", methods=["GET"])
@codebook_view
def similar(ctx):
    """Soft suggest-on-create: existing codes that closely match a
    proposed name (Phase 2 #1). Read-only — drives a non-blocking
    "Use «X»?" prompt before the in-vivo / on-the-fly add commits."""
    from potato.codebook.similar import similar_code_names
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"name": name, "matches": []})
    cb = Codebook.load(ctx["task_dir"], ctx["project"])
    return jsonify({
        "name": name,
        "matches": similar_code_names(cb.labels(), name),
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
