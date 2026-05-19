"""
Cases REST API (universal).

Blueprint mounted at /api/cases. Read-only: list cases (with
attributes) and resolve the case for an instance. Cases are
created/assigned by auto-detection at server start, not via this API.
Enabled when `cases` is configured or under QDA mode.
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, jsonify, request, session

from potato.cases import (
    attributes,
    case_for_instance,
    cases_enabled,
    list_cases,
)

logger = logging.getLogger(__name__)

cases_bp = Blueprint("cases", __name__, url_prefix="/api/cases")


def _config() -> dict:
    from potato.server_utils.config_module import config
    return config


def _ctx():
    config = _config()
    if not cases_enabled(config):
        return None, ("disabled",)
    if not session.get("username"):
        return None, ("unauth",)
    return {
        "task_dir": config.get("task_dir", "."),
        "project": config.get("annotation_task_name") or "default",
    }, None


def cases_view(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        ctx, err = _ctx()
        if err == ("disabled",):
            return jsonify({
                "error": "Cases are not enabled in this deployment.",
                "hint": "Set cases.enabled: true (on by default in "
                        "qda_mode).",
            }), 503
        if err == ("unauth",):
            return jsonify({"error": "Not authenticated"}), 401
        return view(ctx, *args, **kwargs)
    return wrapper


@cases_bp.route("", methods=["GET"])
@cases_view
def list_all(ctx):
    cases = list_cases(ctx["task_dir"], ctx["project"])
    for c in cases:
        c["attributes"] = attributes(ctx["task_dir"], c["id"])
    return jsonify({"cases": cases})


@cases_bp.route("/instance/<path:instance_id>", methods=["GET"])
@cases_view
def for_instance(ctx, instance_id):
    case = case_for_instance(ctx["task_dir"], ctx["project"], instance_id)
    if case is None:
        return jsonify({"case": None})
    case["attributes"] = attributes(ctx["task_dir"], case["id"])
    return jsonify({"case": case})
