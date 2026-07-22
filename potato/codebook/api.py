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
    update_code_fields,
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


@codebook_bp.route("/<code_id>", methods=["GET"])
@codebook_view
def get_code_detail(ctx, code_id):
    """Full record for one code, including the structured prompting
    fields (definition / clarification / examples)."""
    cb = Codebook.load(ctx["task_dir"], ctx["project"])
    detail = cb.detail(code_id)
    if detail is None:
        return jsonify({"error": "code not found"}), 404
    return jsonify({"code": detail})


@codebook_bp.route("/<code_id>/history", methods=["GET"])
@codebook_view
def code_history(ctx, code_id):
    """Version history for one code: every logged edit (create, rename,
    recolor, move, and each structured-field edit) oldest-first."""
    from potato.codebook import changelog
    rows = changelog.code_history(ctx["task_dir"], ctx["project"], code_id)
    return jsonify({"code_id": code_id, "history": rows, "count": len(rows)})


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


def _admin_ctx():
    """(task_dir, project, username, None) or (None,None,None, resp).
    Mirrors admin_stale's gate for the Phase 2 (C) retroactive ops."""
    from potato.server_utils.config_module import config as _cfg
    if not codebook_enabled(_cfg):
        return None, None, None, (
            jsonify({"error": "Codebook not enabled"}), 503)
    if not _admin_or_adjudicator():
        return None, None, None, (
            jsonify({"error": "Admin or adjudicator access required"}),
            403)
    return (_cfg.get("task_dir", "."),
            _cfg.get("annotation_task_name") or "default",
            session.get("username") or "admin", None)


@codebook_bp.route("/admin/merge", methods=["POST"])
def admin_merge():
    """Fold src into dst retroactively (append-only). Admin only."""
    td, project, user, err = _admin_ctx()
    if err:
        return err
    from potato.codebook import merge_codes
    data = request.get_json(silent=True) or {}
    src_id = (data.get("src_id") or "").strip()
    dst_id = (data.get("dst_id") or "").strip()
    if not src_id or not dst_id:
        return jsonify({"error": "src_id and dst_id are required"}), 400
    return _handle(lambda: jsonify(merge_codes(
        td, project=project, src_id=src_id, dst_id=dst_id,
        actor=user, actor_kind="human")))


@codebook_bp.route("/admin/split", methods=["POST"])
def admin_split():
    """Split a code by annotator retroactively. Admin only."""
    td, project, user, err = _admin_ctx()
    if err:
        return err
    from potato.codebook import split_code
    data = request.get_json(silent=True) or {}
    src_id = (data.get("src_id") or "").strip()
    annotator = (data.get("annotator") or "").strip()
    if not src_id or not annotator:
        return jsonify({
            "error": "src_id and annotator are required"}), 400
    return _handle(lambda: jsonify(split_code(
        td, project=project, src_id=src_id, annotator=annotator,
        new_name=(data.get("new_name") or "").strip() or None,
        target_id=(data.get("target_id") or "").strip() or None,
        actor=user, actor_kind="human")))


@codebook_bp.route("/admin/changes", methods=["GET"])
def admin_changes():
    """Full change-log for the before->after delta view. Admin only."""
    td, project, _user, err = _admin_ctx()
    if err:
        return err
    from potato.codebook import changelog
    rows = changelog.all_changes(td, project)
    return jsonify({"changes": rows, "count": len(rows)})


@codebook_bp.route("/admin/review", methods=["GET"])
def admin_review_queue():
    """Open output-change review flags: instances whose LLM label a
    codebook edit moved significantly. Admin/adjudicator only."""
    td, project, _user, err = _admin_ctx()
    if err:
        return err
    from potato.codebook import review
    status = request.args.get("status", "open")
    items = review.list_flags(td, project, status=status)
    idx = _instance_index_map()
    for it in items:
        it["index"] = idx.get(str(it["instance_id"]))
    return jsonify({"flags": items, "count": len(items)})


@codebook_bp.route("/admin/review/<flag_id>/resolve", methods=["POST"])
def admin_resolve_review(flag_id):
    """Mark a review flag reviewed | dismissed. Admin/adjudicator only."""
    td, project, user, err = _admin_ctx()
    if err:
        return err
    from potato.codebook import review
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "reviewed").strip()
    if status not in ("reviewed", "dismissed"):
        return jsonify({
            "error": "status must be 'reviewed' or 'dismissed'"}), 400
    flag = review.get_flag(td, flag_id)
    if not flag or flag["project"] != project:
        return jsonify({"error": "flag not found"}), 404
    ok = review.resolve_flag(
        td, flag_id, status=status, reviewed_by=user)
    if not ok:
        return jsonify({"error": f"flag already {flag['status']}"}), 409
    return jsonify({"resolved": True, "status": status})


@codebook_bp.route("/admin/review/run", methods=["POST"])
def admin_run_review():
    """On-demand re-review: re-label every instance that has a stored LLM
    prediction against the *current* codebook and flag the ones whose
    label moved. Unlike the automatic listener this works even when the
    background labeling thread isn't running — it just needs a configured
    labeling endpoint. Admin/adjudicator only.

    Optional JSON body: {"max_instances": <int>} to cap the sweep.
    """
    td, project, _user, err = _admin_ctx()
    if err:
        return err
    try:
        from potato.solo_mode import get_solo_mode_manager
        manager = get_solo_mode_manager()
    except Exception:
        manager = None
    if manager is None:
        return jsonify({
            "error": "Re-review requires a labeling model. Enable solo "
                     "mode (which configures the labeling endpoint) to "
                     "use this action.",
        }), 503
    data = request.get_json(silent=True) or {}
    max_instances = data.get("max_instances")
    try:
        max_instances = int(max_instances) if max_instances else None
    except (TypeError, ValueError):
        return jsonify({"error": "max_instances must be an integer"}), 400
    summary = manager.run_codebook_review_now(max_instances=max_instances)
    code = 200
    if summary.get("reason") and not summary.get("relabeled"):
        # Nothing ran (e.g. no endpoint configured) — surface it clearly.
        code = 503
    return jsonify(summary), code


@codebook_bp.route("/admin/suggest-from-notes", methods=["POST"])
def admin_suggest_from_notes():
    """On-demand: analyze accumulated human rationale notes (left during
    validation / disagreement resolution) and stage any resulting
    codebook-edit proposals for human review. Nothing changes until an
    admin confirms — same propose/confirm flow as any other model edit.
    Admin/adjudicator only (mirrors admin_run_review)."""
    td, project, _user, err = _admin_ctx()
    if err:
        return err
    try:
        from potato.solo_mode import get_solo_mode_manager
        manager = get_solo_mode_manager()
    except Exception:
        manager = None
    if manager is None:
        return jsonify({
            "error": "Suggesting edits from notes requires a labeling "
                     "model. Enable solo mode to use this action.",
        }), 503
    data = request.get_json(silent=True) or {}
    since = data.get("since") or 0.0
    result = manager.suggest_codebook_edits_from_notes(since=since)
    code = 200
    if result.get("reason") and not result.get("proposals"):
        code = 503
    return jsonify(result), code


@codebook_bp.route("/proposals", methods=["POST"])
@codebook_view
def submit_proposal(ctx):
    """Producer contract: a model/agent stages a codebook edit for human
    confirmation. `actor_kind=="model"` is the machine path (no admin
    gate — it only QUEUES; nothing changes until an admin confirms).
    A human-submitted proposal still requires edit rights."""
    data = request.get_json(silent=True) or {}
    op = (data.get("op") or "").strip()
    payload = data.get("payload") or {}
    actor_kind = (data.get("actor_kind") or "model").strip()
    if op not in ("merge", "split", "rename", "recolor", "move",
                  "delete", "update_fields"):
        return jsonify({"error": f"unsupported op {op!r}"}), 400
    if actor_kind != "model" and not _can_mutate(ctx, need_open=True):
        return jsonify({
            "error": "Proposing edits requires edit rights"}), 403
    from potato.codebook import changelog
    prop = changelog.record_proposal(
        task_dir=ctx["task_dir"], project=ctx["project"], op=op,
        payload=payload, actor=ctx["username"], actor_kind=actor_kind)
    return jsonify({"proposal": prop}), 201


@codebook_bp.route("/admin/proposals", methods=["GET"])
def admin_list_proposals():
    td, project, _user, err = _admin_ctx()
    if err:
        return err
    from potato.codebook import changelog
    items = changelog.list_proposals(td, project, status="pending")
    return jsonify({"proposals": items, "count": len(items)})


def _apply_proposed(td, project, op, payload, actor):
    """Dispatch a confirmed proposal through the audited service path."""
    from potato.codebook import (
        merge_codes, split_code, rename_code, recolor_code,
        move_under, delete_code)
    if op == "merge":
        return merge_codes(
            td, project=project, src_id=payload["src_id"],
            dst_id=payload["dst_id"], actor=actor, actor_kind="model")
    if op == "split":
        return split_code(
            td, project=project, src_id=payload["src_id"],
            annotator=payload["annotator"],
            new_name=payload.get("new_name"),
            target_id=payload.get("target_id"),
            actor=actor, actor_kind="model")
    if op == "rename":
        return rename_code(
            td, payload["code_id"], new_name=payload["new_name"],
            project=project, actor=actor, actor_kind="model")
    if op == "recolor":
        return recolor_code(
            td, payload["code_id"], color=payload["color"],
            project=project, actor=actor, actor_kind="model")
    if op == "move":
        return move_under(
            td, payload["code_id"],
            new_parent_id=payload.get("parent_id") or "",
            project=project, actor=actor, actor_kind="model")
    if op == "delete":
        return delete_code(
            td, payload["code_id"], project=project,
            actor=actor, actor_kind="model")
    if op == "update_fields":
        return update_code_fields(
            td, payload["code_id"],
            details=_rich_details(payload),
            project=project, actor=actor, actor_kind="model")
    raise CodebookError(f"unsupported op {op!r}")


@codebook_bp.route("/admin/proposals/<pid>/confirm", methods=["POST"])
def admin_confirm_proposal(pid):
    td, project, user, err = _admin_ctx()
    if err:
        return err
    from potato.codebook import changelog
    prop = changelog.get_proposal(td, pid)
    if not prop or prop["project"] != project:
        return jsonify({"error": "proposal not found"}), 404
    if prop["status"] != "pending":
        return jsonify({
            "error": f"proposal already {prop['status']}"}), 409

    def _do():
        result = _apply_proposed(
            td, project, prop["op"], prop["payload"], user)
        cid = changelog.log_change(
            td, project=project, op="llm_confirmed",
            old_value=prop["op"], new_value=str(result),
            actor=user, actor_kind="model",
            revision=current_revision(td, project))
        changelog.set_proposal_status(
            td, pid, status="confirmed", decided_by=user,
            change_id=result.get("change_id") or cid)
        return jsonify({"confirmed": True, "result": result})

    return _handle(_do)


@codebook_bp.route("/admin/proposals/<pid>/reject", methods=["POST"])
def admin_reject_proposal(pid):
    td, project, user, err = _admin_ctx()
    if err:
        return err
    from potato.codebook import changelog
    prop = changelog.get_proposal(td, pid)
    if not prop or prop["project"] != project:
        return jsonify({"error": "proposal not found"}), 404
    if prop["status"] != "pending":
        return jsonify({
            "error": f"proposal already {prop['status']}"}), 409
    cid = changelog.log_change(
        td, project=project, op="llm_rejected",
        old_value=prop["op"], new_value=None, actor=user,
        actor_kind="model", revision=0)
    changelog.set_proposal_status(
        td, pid, status="rejected", decided_by=user, change_id=cid)
    return jsonify({"rejected": True})


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
        details=_rich_details(data),
    )}))


def _rich_details(data: dict) -> dict:
    """Pull just the structured codebook-prompting fields out of a
    request body (ignoring name/color/parent_id/etc)."""
    from potato.codebook.store import RICH_FIELDS
    return {f: data[f] for f in RICH_FIELDS if f in data}


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
                new_name=data["name"], project=ctx["project"],
                actor=ctx["username"])
        if "color" in data:
            result = recolor_code(
                ctx["task_dir"], code_id,
                color=data["color"], project=ctx["project"],
                actor=ctx["username"])
        if "parent_id" in data:
            result = move_under(
                ctx["task_dir"], code_id,
                new_parent_id=data["parent_id"] or ROOT,
                project=ctx["project"], actor=ctx["username"])
        rich = _rich_details(data)
        if rich:
            result = update_code_fields(
                ctx["task_dir"], code_id, details=rich,
                project=ctx["project"], actor=ctx["username"])
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
