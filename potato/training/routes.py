"""The training admin surface.

``/admin/training`` answers a question nothing else in Potato can: where did
this prelabel come from, and should you believe it. The run list carries both
numbers that matter -- the held-out score, which says how good the model looked
offline, and the deployed precision from review verdicts, which says how good
it turned out to be in front of a human.

Everything is polled rather than pushed. The status dict is cheap to read and
the run page refreshes it; an SSE stream is a later refinement, not a
prerequisite.
"""

from __future__ import annotations

import logging
import os
from functools import wraps

from flask import Blueprint, jsonify, render_template, request

from potato.server_utils.rbac import Permission, require_permission

logger = logging.getLogger(__name__)

training_bp = Blueprint("training", __name__, url_prefix="/admin/training")

admin_required = require_permission(Permission.VIEW_ADMIN_DASHBOARD)


def _enabled_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        from potato.training.manager import get_training_manager
        if get_training_manager() is None:
            return jsonify({
                "error": "Training is not enabled",
                "hint": "Set model_training.enabled: true in your config.",
            }), 400
        return f(*args, **kwargs)
    return wrapper


def _same_origin_required(f):
    """Reject cross-origin state changes.

    Mirrors the guard on the solo-mode POST routes: starting a training run is
    a side effect worth spending CPU on, so it should not be triggerable from
    another site with an admin's cookie.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        origin = request.headers.get("Origin")
        if origin:
            host = request.headers.get("Host", "")
            if host and host not in origin:
                return jsonify({"error": "Cross-origin request refused"}), 403
        return f(*args, **kwargs)
    return wrapper


def _manager():
    from potato.training.manager import get_training_manager
    return get_training_manager()


def _config():
    from potato.server_utils.config_module import config
    return config


# ---------------------------------------------------------------- pages

@training_bp.route("", methods=["GET"])
@admin_required
@_enabled_required
def training_page():
    manager = _manager()
    return render_template(
        "admin/training.html",
        status=manager.status(),
        runs=manager.history(limit=25),
        trainers=_trainer_rows(),
        schemas=_schema_rows(),
        writeback=(_config().get("model_training", {}) or {}).get("writeback", {}))


@training_bp.route("/runs/<run_id>", methods=["GET"])
@admin_required
@_enabled_required
def run_page(run_id):
    from potato.training import store

    run = store.load_run(_config(), run_id)
    if run is None:
        return jsonify({"error": "No such run: %s" % run_id}), 404

    manager = _manager()
    return render_template(
        "admin/training_run.html", run=run.to_dict(),
        status=manager.status(), events=_recent_events(manager, run_id),
        splits=store.run_item_splits(_config(), run_id))


# ------------------------------------------------------------------ api

@training_bp.route("/api/trainers", methods=["GET"])
@admin_required
def api_trainers():
    """Every trainer and what it can handle. Imports none of them."""
    from potato.training.registry import list_trainers
    return jsonify({"trainers": list_trainers()})


@training_bp.route("/api/schemas", methods=["GET"])
@admin_required
def api_schemas():
    return jsonify({"schemas": _schema_rows()})


@training_bp.route("/api/status", methods=["GET"])
@admin_required
@_enabled_required
def api_status():
    return jsonify(_manager().status())


@training_bp.route("/api/runs", methods=["GET"])
@admin_required
@_enabled_required
def api_runs():
    limit = min(int(request.args.get("limit", 50)), 500)
    return jsonify({"runs": _manager().history(limit=limit)})


@training_bp.route("/api/runs/<run_id>", methods=["GET"])
@admin_required
@_enabled_required
def api_run(run_id):
    from potato.training import store

    run = store.load_run(_config(), run_id)
    if run is None:
        return jsonify({"error": "No such run: %s" % run_id}), 404

    payload = run.to_dict()
    payload["review"] = _review_metrics(run_id)
    return jsonify(payload)


@training_bp.route("/api/runs", methods=["POST"])
@admin_required
@_enabled_required
@_same_origin_required
def api_start_run():
    body = request.get_json(silent=True) or {}
    trainer = body.get("trainer")
    schemas = body.get("schemas") or []

    if not trainer:
        return jsonify({"started": False, "error": "No trainer named"}), 400
    if isinstance(schemas, str):
        schemas = [schemas]
    if not schemas:
        return jsonify({"started": False, "error": "No schema selected"}), 400

    problem = _licence_problem(trainer, body.get("accept_licence", False))
    if problem:
        return jsonify({"started": False, "error": problem,
                        "needs_licence_ack": True}), 400

    outcome = _manager().start_run(trainer, schemas,
                                   params=body.get("params") or {},
                                   trigger="api")
    return jsonify(outcome), (200 if outcome.get("started") else 409)


@training_bp.route("/api/runs/<run_id>/cancel", methods=["POST"])
@admin_required
@_enabled_required
@_same_origin_required
def api_cancel(run_id):
    outcome = _manager().cancel(run_id)
    return jsonify(outcome), (200 if outcome.get("cancelled") else 400)


@training_bp.route("/api/runs/<run_id>/events", methods=["GET"])
@admin_required
@_enabled_required
def api_events(run_id):
    return jsonify({"events": _recent_events(_manager(), run_id,
                                             limit=int(request.args.get(
                                                 "limit", 200)))})


@training_bp.route("/api/runs/<run_id>/predictions", methods=["DELETE"])
@admin_required
@_enabled_required
@_same_origin_required
def api_retract(run_id):
    """Withdraw a run's prelabels.

    The undo for a write-back that turned out to be bad. Removes the stored
    predictions; item data catches up on the next restart, or immediately for
    items still resident.
    """
    from potato.training import store

    removed = store.delete_predictions_for_run(_config(), run_id)
    return jsonify({"retracted": removed})


# -------------------------------------------------------------- helpers

def _trainer_rows():
    from potato.training.registry import list_trainers
    return list_trainers()


def _schema_rows():
    """Schemes in this project, with the trainers that could fit each."""
    from potato.training.registry import kind_of_schema, trainers_for_schema

    rows = []
    for scheme in _config().get("annotation_schemes", []) or []:
        name = scheme.get("name")
        if not name:
            continue
        matches = trainers_for_schema(scheme)
        rows.append({
            "name": name,
            "annotation_type": scheme.get("annotation_type", ""),
            "kind": kind_of_schema(scheme),
            "trainers": [t.name for t in matches],
            "trainable": bool(matches),
        })
    return rows


def _licence_problem(trainer_name: str, accepted: bool):
    """Whether this trainer needs a licence acknowledgement first.

    Some training libraries are AGPL. Training a model with one can put
    obligations on whoever ships the result, and that belongs in front of the
    person clicking the button rather than in a changelog.
    """
    from potato.training.registry import trainer_info

    info = trainer_info(trainer_name)
    if info is None or not info.licence_ack or accepted:
        return None
    return ("%s is licensed %s. Training with it may place obligations on how "
            "you distribute the resulting model. Re-submit with "
            "accept_licence: true to confirm. %s"
            % (trainer_name, info.licence, info.licence_url)).strip()


def _recent_events(manager, run_id: str, limit: int = 200):
    path = os.path.join(manager.run_dir(run_id), "events.jsonl")
    if not os.path.isfile(path):
        return []
    import json
    events = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    return events[-limit:]


def _review_metrics(run_id: str):
    """Deployed precision for this run's predictions, from review verdicts.

    Distinct from the held-out score, and more informative: it is measured on
    predictions a human actually looked at.
    """
    try:
        from potato import model_review
        from potato.training import store

        config = _config()
        predicted = {(p["instance_id"], p["schema_name"])
                     for p in store.load_predictions(config, run_id=run_id)}
        if not predicted:
            return None

        verdicts = [v for v in model_review.load_verdicts(config)
                    if (v.instance_id, v.schema_name) in predicted]
        if not verdicts:
            return {"n_reviewed": 0,
                    "note": "No predictions from this run have been reviewed yet."}
        return model_review.review_metrics(verdicts)
    except Exception:
        logger.debug("Could not compute review metrics for %s", run_id,
                     exc_info=True)
        return None
