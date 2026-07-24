"""Flask blueprint for Psychometrics (measurement-grade annotation).

Admin endpoints (RBAC; debug mode and the shared admin key pass):

- ``GET /psychometrics/dashboard``  — live abilities, difficulty, flags
- ``GET /psychometrics/api/stats``  — dashboard aggregates (forces a fresh fit)
- ``GET /psychometrics/api/export`` — enriched export: labels with error bars
- ``GET /psychometrics/api/design`` — power analysis (Monte Carlo, seeded)
"""

import logging
from functools import wraps

from flask import Blueprint, jsonify, render_template, request

from potato.item_state_management import get_item_state_manager
from potato.psychometrics.design import power_analysis
from potato.psychometrics.manager import get_psychometrics_manager
from potato.server_utils.rbac import Permission, require_permission

logger = logging.getLogger(__name__)

psychometrics_bp = Blueprint("psychometrics", __name__, url_prefix="/psychometrics")

admin_required = require_permission(Permission.VIEW_ADMIN_DASHBOARD)

# Request caps for the design endpoint (the CLI has no caps).
_MAX_DESIGN_ITEMS = 20000
_MAX_DESIGN_SIMS = 200
_MAX_DESIGN_ANNOTATORS = 10


def psychometrics_required(f):
    """404 when Psychometrics isn't enabled for this task."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_psychometrics_manager() is None:
            return jsonify({"error": "Psychometrics not enabled"}), 404
        return f(*args, **kwargs)

    return decorated_function


@psychometrics_bp.route("/dashboard", methods=["GET"])
@psychometrics_required
@admin_required
def dashboard():
    """Psychometrics dashboard: abilities, difficulty map, codebook flags."""
    manager = get_psychometrics_manager()
    return render_template(
        "psychometrics_dashboard.html",
        task_name=manager.app_config.get("annotation_task_name", "Annotation Task"),
    )


def _attach_text(manager, items, max_chars=200):
    """Attach a display snippet of each instance's text to result rows."""
    text_key = (manager.app_config.get("item_properties") or {}).get("text_key", "text")
    ism = get_item_state_manager()
    for row in items:
        text = ""
        try:
            if ism.has_item(row["instance_id"]):
                data = ism.get_item(row["instance_id"]).get_data()
                value = data.get(text_key)
                text = value if isinstance(value, str) else ism.get_item(row["instance_id"]).get_text()
        except Exception:  # display enrichment must never break stats
            text = ""
        if text and len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        row["text"] = text
    return items


@psychometrics_bp.route("/api/stats", methods=["GET"])
@psychometrics_required
@admin_required
def stats():
    manager = get_psychometrics_manager()
    payload = manager.get_stats()
    _attach_text(manager, payload["items"])
    # flagged_items rows are the same dicts, already enriched in place.
    return jsonify(payload)


@psychometrics_bp.route("/api/export", methods=["GET"])
@psychometrics_required
@admin_required
def export():
    """Enriched export: MAP labels with posteriors, bands, and abilities."""
    return jsonify(get_psychometrics_manager().export_records())


@psychometrics_bp.route("/api/design", methods=["GET"])
@psychometrics_required
@admin_required
def design():
    """Power analysis: alpha precision + cost per annotators-per-item value."""
    manager = get_psychometrics_manager()

    def _num(name, default, cast=float):
        raw = request.args.get(name)
        if raw is None or raw == "":
            return default
        return cast(raw)

    try:
        n_items = min(int(_num("items", 500, int)), _MAX_DESIGN_ITEMS)
        accuracy = _num("accuracy", 0.75)
        num_classes = int(_num("classes", 2, int))
        target_ci = _num("target_ci", 0.10)
        max_annotators = min(int(_num("max_annotators", 8, int)), _MAX_DESIGN_ANNOTATORS)
        n_sims = min(int(_num("sims", 60, int)), _MAX_DESIGN_SIMS)
        cost = _num("cost", manager.ps_config.cost_per_judgment)
        report = power_analysis(
            n_items=n_items,
            annotator_accuracy=accuracy,
            num_classes=num_classes,
            target_ci_width=target_ci,
            max_annotators=max_annotators,
            n_simulations=n_sims,
            cost_per_judgment=cost,
        )
    except (TypeError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(report.to_dict())
