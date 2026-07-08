"""
Judge Calibration routes.

Admin-gated endpoints for the calibration wizard:
- GET  /judge_calibration/admin     -> wizard (prefilled from config)
- POST /judge_calibration/run       -> apply overrides + start generation
- GET  /judge_calibration/progress  -> generation progress (JSON, polled)
- POST /judge_calibration/report    -> build the report
- GET  /judge_calibration/report    -> rendered report.html
- GET  /judge_calibration/status    -> status (JSON)

Human blind-labeling happens through Potato's standard ``/annotate`` flow —
LLM labels live in a separate store and are never injected into the annotation
UI, so blindness is structural (no special UI needed here).

All endpoints require a valid admin API key (X-API-Key header or session),
matching the solo_mode pattern; debug mode bypasses the check.
"""

import logging
import os
from functools import wraps

from flask import Blueprint, Response, jsonify, render_template, request, session

from potato.judge_calibration.manager import get_judge_calibration_manager

logger = logging.getLogger(__name__)

judge_calibration_bp = Blueprint("judge_calibration", __name__, url_prefix="/judge_calibration")


def _enabled_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if get_judge_calibration_manager() is None:
            return jsonify({"error": "Judge Calibration not enabled"}), 400
        return f(*args, **kwargs)
    return wrapper


# Admin authorization now routes through RBAC: a valid shared admin key (or
# debug) still passes, and a logged-in user holding the ``view_admin_dashboard``
# permission is authorized without the key. The 403 contract is unchanged.
from potato.server_utils.rbac import require_permission, Permission

admin_required = require_permission(Permission.VIEW_ADMIN_DASHBOARD)


def _config_for_wizard(cfg):
    """Serialize the current config for prefilling the wizard form."""
    return {
        "prompt": cfg.prompt,
        "k_samples": cfg.k_samples,
        "max_items": cfg.max_items,
        "fraction": cfg.fraction,
        "models": [
            {
                "endpoint_type": m.endpoint_type,
                "model": m.model,
                "base_url": m.base_url,
                "temperature": m.temperature,
            }
            for m in cfg.models
        ],
        "sampling": {
            "strategy": cfg.sampling.strategy,
            "stratify_by": cfg.sampling.stratify_by,
            "sample_size": cfg.sampling.sample_size,
            "seed": cfg.sampling.seed,
        },
        "human": {"num_raters": cfg.human.num_raters, "gold": cfg.human.gold},
        "schemas": cfg.schemas,
        "calibration": {"n_bins": cfg.calibration.n_bins},
    }


@judge_calibration_bp.route("/admin", methods=["GET"])
@admin_required
@_enabled_required
def admin():
    manager = get_judge_calibration_manager()
    return render_template(
        "judge_calibration/wizard.html",
        config=_config_for_wizard(manager.config),
        status=manager.get_status(),
    )


@judge_calibration_bp.route("/status", methods=["GET"])
@admin_required
@_enabled_required
def status():
    return jsonify(get_judge_calibration_manager().get_status())


@judge_calibration_bp.route("/progress", methods=["GET"])
@admin_required
@_enabled_required
def progress():
    return jsonify(get_judge_calibration_manager().get_progress())


@judge_calibration_bp.route("/run", methods=["POST"])
@admin_required
@_enabled_required
def run():
    manager = get_judge_calibration_manager()
    overrides = request.get_json(silent=True) or {}
    force = bool(overrides.pop("force_restart", False))
    errors = manager.update_config(overrides)
    if errors:
        return jsonify({"error": "Invalid configuration", "errors": errors}), 400
    try:
        started = manager.start_generation(force_restart=force)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not started:
        return jsonify({"error": "Generation already in progress"}), 409
    return jsonify({"started": True, "progress": manager.get_progress()})


@judge_calibration_bp.route("/report", methods=["POST"])
@admin_required
@_enabled_required
def build_report():
    manager = get_judge_calibration_manager()
    if manager.is_generating():
        return jsonify({"error": "Generation still in progress"}), 409
    try:
        report = manager.build_report()
    except Exception as e:
        logger.exception("judge_calibration: report build failed")
        return jsonify({"error": str(e)}), 500
    return jsonify({"built": True, "report": report})


@judge_calibration_bp.route("/report", methods=["GET"])
@admin_required
@_enabled_required
def view_report():
    manager = get_judge_calibration_manager()
    html_path = os.path.join(manager.config.output.dir, manager.config.output.report_html)
    if os.path.exists(html_path):
        with open(html_path) as f:
            return Response(f.read(), mimetype="text/html")
    return render_template("judge_calibration/status.html", status=manager.get_status())
