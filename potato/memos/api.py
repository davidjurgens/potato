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
    list_issues,
    list_visible,
    reply_to,
    set_assignee,
    set_status,
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


def sidebar_open_by_default(config: dict) -> bool:
    """Whether the notes sidebar should start open.

    ``qda_mode.memos.show_sidebar_by_default`` was parsed, defaulted to True,
    and reported by /qda/config — and read by nobody, so the sidebar always
    started collapsed. The value is resolved through the QDA manager rather
    than re-parsed here, so there is one parser for it.
    """
    if not (config.get("qda_mode") or {}).get("enabled"):
        return False
    try:
        from potato.qda_mode.manager import get_qda_mode_manager
        manager = get_qda_mode_manager()
    except Exception:       # pragma: no cover - QDA package absent
        return False
    if manager is None:
        return False
    memos_cfg = getattr(manager.config, "memos", None)
    if memos_cfg is None or not getattr(memos_cfg, "enabled", False):
        return False
    return bool(getattr(memos_cfg, "show_sidebar_by_default", False))


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
    return jsonify({
        "memos": memos,
        "open_by_default": sidebar_open_by_default(_config()),
    })


def _item_exists(instance_id) -> bool:
    try:
        from potato.item_state_management import get_item_state_manager
        return get_item_state_manager().has_item(str(instance_id))
    except Exception:  # noqa: BLE001 - no item store (a bare test app): do not refuse
        return True


def _announce_assignment(memo, previous, by):
    """Emit memo.issue_assigned when an issue gains a new assignee.

    The panel shows each annotator the open issues assigned to them; the
    webhook is for teams that want the news elsewhere (a chat channel).
    """
    if not memo or not memo.get("assignee") or memo["assignee"] == previous:
        return
    try:
        from potato.webhooks import get_webhook_emitter
        from potato.webhooks.events import MEMO_ISSUE_ASSIGNED, build_issue_assigned_payload
        emitter = get_webhook_emitter()
        if emitter:
            emitter.emit(MEMO_ISSUE_ASSIGNED, build_issue_assigned_payload(
                memo["id"], memo.get("instance_id"), memo["assignee"], by,
                memo.get("status") or "open"))
    except Exception:  # noqa: BLE001 - the memo is saved; a webhook must not undo it
        logger.exception("Could not emit memo.issue_assigned for %s", memo.get("id"))


@memos_bp.route("", methods=["POST"])
@memos_required
def post_memo(task_dir, project, username, priv):
    data = request.get_json(silent=True) or {}
    instance_id = data.get("instance_id")
    if not instance_id:
        return jsonify({"error": "instance_id is required"}), 400
    if not _item_exists(instance_id):
        # A typo'd id made a note nobody could ever reach.
        return jsonify({"error": f"No item with instance_id {instance_id!r}"}), 400
    visibility = data.get("visibility") or _default_visibility(_config())

    def _do():
        memo = create_memo(
            task_dir, project=project, instance_id=instance_id,
            body=data.get("body", ""), created_by=username,
            anchor=data.get("anchor"), visibility=visibility,
            issue=bool(data.get("issue")), assignee=data.get("assignee"),
        )
        _announce_assignment(memo, None, username)
        return jsonify({"memo": memo})
    return _handle(_do)


@memos_bp.route("/issues", methods=["GET"])
@memos_required
def get_issues(task_dir, project, username, priv):
    """Issues across the project: ``?status=open|resolved``, ``?assignee=me``."""
    assignee = request.args.get("assignee") or None
    if assignee == "me":
        assignee = username

    def _do():
        issues = list_issues(
            task_dir, project=project, requester=username, is_privileged=priv,
            status=request.args.get("status") or None, assignee=assignee,
        )
        positions = _positions(username)
        for issue in issues:
            # Where the item sits in this user's own queue, so the panel can
            # jump to it. Absent when the item is not theirs, or jumping is off.
            if issue.get("instance_id") in positions:
                issue["position"] = positions[issue["instance_id"]]
        return jsonify({"issues": issues})
    return _handle(_do)


def _positions(username):
    if _config().get("jumping_to_id_disabled"):
        return {}
    try:
        from potato.user_state_management import get_user_state_manager
        state = get_user_state_manager().get_user_state(username)
        ordering = list(getattr(state, "instance_id_ordering", None) or [])
    except Exception:  # noqa: BLE001 - no queue: no jump links
        return {}
    return {iid: index for index, iid in enumerate(ordering)}


@memos_bp.route("/<memo_id>/reply", methods=["POST"])
@memos_required
def post_reply(task_dir, project, username, priv, memo_id):
    data = request.get_json(silent=True) or {}
    return _handle(lambda: (jsonify({"memo": reply_to(
        task_dir, memo_id, requester=username, is_privileged=priv,
        body=data.get("body", ""),
    )}), 201))


@memos_bp.route("/<memo_id>", methods=["PATCH"])
@memos_required
def patch_memo(task_dir, project, username, priv, memo_id):
    data = request.get_json(silent=True) or {}

    def _do():
        memo = None
        if "body" in data or "visibility" in data:
            memo = update_memo(task_dir, memo_id, requester=username, is_privileged=priv,
                               body=data.get("body"), visibility=data.get("visibility"))
        if "status" in data:
            memo = set_status(task_dir, memo_id, requester=username, is_privileged=priv,
                              status=data.get("status"))
        if "assignee" in data:
            from potato.memos import store as memo_store
            before = memo_store.get(task_dir, memo_id) or {}
            memo = set_assignee(task_dir, memo_id, requester=username, is_privileged=priv,
                                assignee=data.get("assignee"))
            _announce_assignment(memo, before.get("assignee"), username)
        if memo is None:
            memo = update_memo(task_dir, memo_id, requester=username, is_privileged=priv)
        return jsonify({"memo": memo})
    return _handle(_do)


@memos_bp.route("/<memo_id>", methods=["DELETE"])
@memos_required
def remove_memo(task_dir, project, username, priv, memo_id):
    def _do():
        delete_memo(task_dir, memo_id, requester=username, is_privileged=priv)
        return jsonify({"ok": True})
    return _handle(_do)
