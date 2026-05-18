"""
QDA Mode Routes

Flask blueprint for QDA-Mode-specific endpoints. Mounted at `/qda` so it
never collides with the universal `/admin/api/*` or `/api/*` namespaces.

In Phase 0 this is intentionally minimal: a status endpoint to verify the
mode is wired correctly. Memos and search endpoints land in their own
universal packages (`potato/memos/api.py`, `potato/search/api.py`) — not
here — because those features are not QDA-Mode-only.

Later phases add codebook, smart-codes, and network endpoints here.
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, jsonify

from .manager import get_qda_mode_manager

logger = logging.getLogger(__name__)


qda_mode_bp = Blueprint("qda_mode", __name__, url_prefix="/qda")


def qda_mode_required(view):
    """Decorator: return 503 if QDA Mode is not enabled.

    Mirrors potato/solo_mode/routes.py:solo_mode_required, but returns 503
    (Service Unavailable) instead of 400 — the endpoint exists in the URL
    space, the mode just isn't active in this deployment. Clients can tell
    the difference between "wrong request" (400) and "wrong deployment"
    (503).
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        manager = get_qda_mode_manager()
        if manager is None:
            return jsonify({
                "error": "QDA Mode not enabled in this deployment.",
                "hint": "Set qda_mode.enabled: true in your config.yaml.",
            }), 503
        return view(*args, **kwargs)
    return wrapper


@qda_mode_bp.route("/status", methods=["GET"])
def qda_mode_status():
    """Report whether QDA Mode is enabled and the resolved config summary.

    Always returns 200 — admins use this to confirm the mode is wired
    correctly. When disabled, returns ``{"enabled": false}`` so the UI
    can decide whether to render QDA panels.
    """
    manager = get_qda_mode_manager()
    if manager is None:
        return jsonify({"enabled": False})
    cfg = manager.config
    return jsonify({
        "enabled": True,
        "memos": {
            "enabled": cfg.memos.enabled,
            "show_sidebar_by_default": cfg.memos.show_sidebar_by_default,
        },
        "codebook": (
            None if cfg.codebook is None else
            {"enabled": cfg.codebook.enabled, "mode": cfg.codebook.mode}
        ),
        "task_dir": manager.task_dir,
    })
