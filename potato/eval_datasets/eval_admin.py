"""
Eval-task inspection & control API (Phase 2.5).

Extends the admin surface with eval-scoped views and controls under
``/admin/eval/...``, reusing the existing ``admin_required`` auth. It *composes*
the existing managers (ItemStateManager, UserStateManager) and the datasets /
experiments stores rather than duplicating the general admin diagnostics — for
full IAA use ``/admin/iaa``, for per-annotator timing ``/admin/api/annotators``.

Inspect:
    GET  /admin/eval/status            eval overview (datasets, experiments,
                                        annotation progress, ingested traces)
    GET  /admin/eval/progress          per-instance annotation status (capped)
    GET  /admin/eval/ingested_traces   runtime-ingested traces with source/counts

Control:
    POST /admin/eval/assignment        {action: "pause"|"resume"} freeze/resume
                                        new assignments (does not touch existing)
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from potato.eval_datasets.routes import admin_required, _enabled_required
from potato.eval_datasets.manager import get_datasets_manager, DatasetsManager

eval_admin_bp = Blueprint("eval_admin", __name__, url_prefix="/admin/eval")

_PROGRESS_CAP = 1000  # don't serialize unbounded instance lists


def _managers():
    from potato.item_state_management import get_item_state_manager
    from potato.user_state_management import get_user_state_manager
    return get_item_state_manager(), get_user_state_manager()


@eval_admin_bp.route("/status", methods=["GET"])
@admin_required
@_enabled_required
def status():
    mgr = get_datasets_manager()
    ism, usm = _managers()

    datasets = mgr.store.list_datasets()
    total_examples = sum((d.latest_version.example_count if d.latest_version else 0)
                         for d in datasets)
    experiments = mgr.experiments.list()
    latest_exp = experiments[-1] if experiments else None

    instances = {"total": 0, "annotated": 0, "multi_annotated": 0,
                 "remaining": 0, "ingested": 0}
    if ism is not None:
        ids = ism.get_instance_ids()
        instances["total"] = len(ids)
        instances["remaining"] = len(getattr(ism, "remaining_instance_ids", []))
        for iid in ids:
            annotators = ism.get_annotators_for_item(iid)
            n = len(annotators) if annotators else 0
            if n >= 1:
                instances["annotated"] += 1
            if n >= 2:
                instances["multi_annotated"] += 1
            try:
                if mgr._is_ingested_trace(iid, ism.get_item(iid)):
                    instances["ingested"] += 1
            except KeyError:
                pass

    return jsonify({
        "storage": mgr.settings.storage,
        "assignment_paused": ism.is_assignment_paused() if ism is not None else None,
        "users": usm.get_user_count() if usm is not None else 0,
        "datasets": {"count": len(datasets), "total_examples": total_examples},
        "experiments": {
            "count": len(experiments),
            "latest": ({"id": latest_exp.id, "name": latest_exp.name,
                        "aggregate_scores": latest_exp.aggregate_scores}
                       if latest_exp else None),
        },
        "instances": instances,
    })


@eval_admin_bp.route("/progress", methods=["GET"])
@admin_required
@_enabled_required
def progress():
    mgr = get_datasets_manager()
    ism, _ = _managers()
    rows = []
    truncated = False
    if ism is not None:
        ids = ism.get_instance_ids()
        if len(ids) > _PROGRESS_CAP:
            ids = ids[:_PROGRESS_CAP]
            truncated = True
        for iid in ids:
            try:
                item = ism.get_item(iid)
            except KeyError:
                continue
            annotators = ism.get_annotators_for_item(iid) or set()
            rows.append({
                "instance_id": str(iid),
                "source": mgr._item_source(item),
                "ingested": mgr._is_ingested_trace(iid, item),
                "num_annotators": len(annotators),
                "saturated": ism._item_is_saturated(iid) if hasattr(ism, "_item_is_saturated") else None,
                "triage_priority": item.metadata.get("triage_priority") if hasattr(item, "metadata") else None,
            })
    return jsonify({"instances": rows, "truncated": truncated, "cap": _PROGRESS_CAP})


@eval_admin_bp.route("/ingested_traces", methods=["GET"])
@admin_required
@_enabled_required
def ingested_traces():
    mgr = get_datasets_manager()
    ism, _ = _managers()
    by_source = {}
    rows = []
    if ism is not None:
        for iid in ism.get_instance_ids():
            try:
                item = ism.get_item(iid)
            except KeyError:
                continue
            if not mgr._is_ingested_trace(iid, item):
                continue
            src = mgr._item_source(item)
            by_source[src] = by_source.get(src, 0) + 1
            if len(rows) < _PROGRESS_CAP:
                rows.append({
                    "instance_id": str(iid),
                    "source": src,
                    "num_annotators": len(ism.get_annotators_for_item(iid) or set()),
                })
    return jsonify({"total": sum(by_source.values()), "by_source": by_source, "traces": rows})


@eval_admin_bp.route("/assignment", methods=["POST"])
@admin_required
@_enabled_required
def control_assignment():
    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").lower()
    ism, _ = _managers()
    if ism is None:
        return jsonify({"error": "no item state manager"}), 400
    if action == "pause":
        ism.pause_assignment()
    elif action == "resume":
        ism.resume_assignment()
    else:
        return jsonify({"error": "action must be 'pause' or 'resume'"}), 400
    return jsonify({"assignment_paused": ism.is_assignment_paused()})
