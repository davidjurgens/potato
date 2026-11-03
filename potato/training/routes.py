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

import json
import logging
import os
import time
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


from potato.server_utils.origin_check import same_origin_required as _same_origin_required


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
        queue_positions={q["run_id"]: q["position"] for q in manager.queue()},
        trainers=_trainer_rows(),
        schemas=_schema_rows(),
        backends=_backend_rows(),
        trainer_params=(_config().get("model_training", {}) or {}).get(
            "trainer_params") or {},
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
    from potato.training.hub import NOT_A_MODEL, model_files
    from potato.training.registry import trainer_info
    hub_files = [f for f in model_files(os.path.join(manager.run_dir(run_id),
                                                     "artifacts"))
                 if f not in NOT_A_MODEL]
    return render_template(
        "admin/training_run.html", run=run.to_dict(),
        status=manager.status(), events=_recent_events(manager, run_id),
        splits=store.run_item_splits(_config(), run_id),
        datasets_enabled=_datasets_enabled(),
        hub_pushable=run.status == "success" and bool(hub_files),
        hub_pushes=store.hub_pushes(_config(), run_id),
        run_licence_ack=bool(getattr(trainer_info(run.trainer), "licence_ack", False)),
        run_licence=getattr(trainer_info(run.trainer), "licence", ""))


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
    manager = _manager()
    return jsonify(dict(manager.status(), queue=manager.queue()))


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
    body, refused = _json_object()
    if refused:
        return refused
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
                                   trigger="api",
                                   backend=body.get("backend") or None,
                                   queue=body.get("queue", True) is not False)
    if outcome.get("started"):
        status = 200
    elif outcome.get("queued"):
        status = 202
    else:
        status = outcome.pop("http_status", 409)
    return jsonify(outcome), status


@training_bp.route("/api/backends", methods=["GET"])
@admin_required
@_enabled_required
def api_backends():
    return jsonify({"backends": _backend_rows()})


@training_bp.route("/api/backends/<name>/check", methods=["POST"])
@admin_required
@_enabled_required
@_same_origin_required
def api_check_backend(name):
    """Connect to a backend and report its Python, GPUs and gaps.

    For an ssh backend this opens a real connection, so it takes a few
    seconds. The local backend is not checked here: answering would mean
    importing torch into the server process.
    """
    from potato.training.backends import load_backends

    backend = load_backends(_config()).get(name)
    if backend is None:
        return jsonify({"ok": False,
                        "message": "No backend named %r" % name}), 404
    if backend.type == "local":
        return jsonify({"ok": True, "message":
                        "Runs on this machine; the run log names the device."})
    if backend.type == "agent":
        from potato.training import store
        rows = [r for r in store.list_backends(_config())
                if r["name"] == name]
        if not rows:
            return jsonify({"ok": False, "message":
                            "No token issued. Run: potato training register "
                            "%s <config.yaml>" % name})
        seen = rows[0].get("last_seen")
        return jsonify({"ok": bool(seen), "agent": rows[0], "message": (
            "Last heard from %d seconds ago" % (time.time() - seen)
            if seen else "Token issued; no agent has connected yet.")})

    from potato.training.launchers import check_backend
    return jsonify(check_backend(backend))


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
    predictions and the prelabels they put in item data.
    """
    from potato.training import store
    from potato.training.writeback import clear_published

    config = _config()
    records = store.load_predictions(config, run_id=run_id)
    removed = store.delete_predictions_for_run(config, run_id)
    clear_published(config, records)
    return jsonify({"retracted": removed})


@training_bp.route("/api/runs/<run_id>/pin-split", methods=["POST"])
@admin_required
@_enabled_required
@_same_origin_required
def api_pin_split(run_id):
    """Save one of a run's splits as a dataset version.

    Body: ``{"dataset": name, "split": "val"|"test"|"train"}`` (``split``
    defaults to ``val``). The examples carry the items' agreed human labels
    for the run's schemes and are marked with the split's name, so the
    version is a fixed evaluation set for the datasets' experiment runner.
    A dataset that already exists gains a new version holding this split
    only: saving run 2's val split into run 1's dataset must not mix in
    items run 2 trained on. The model's prelabels are left out of the
    inputs.
    """
    from potato.model_review import prediction_field
    from potato.training import store

    body, refused = _json_object()
    if refused:
        return refused
    dataset = str(body.get("dataset") or "").strip()
    split = str(body.get("split") or "val")
    if not dataset:
        return jsonify({"error": "dataset is required"}), 400
    run = store.load_run(_config(), run_id)
    if run is None:
        return jsonify({"error": "No such run: %s" % run_id}), 404

    splits = store.run_item_splits(_config(), run_id)
    ids = sorted(i for i, s in splits.items() if s == split)
    if not ids:
        return jsonify({"error": "Run %s has no %s items" % (run_id, split),
                        "splits": sorted(set(splits.values()))}), 400

    from potato.eval_datasets.manager import get_datasets_manager
    dm = get_datasets_manager()
    if dm is None:
        return jsonify({"error": "Datasets are not enabled",
                        "hint": "Set datasets.enabled: true in your "
                                "config."}), 400
    try:
        version = dm.import_from_instances(
            dataset, instance_ids=ids, include_annotations=True,
            note="training run %s, %s split" % (run_id, split),
            split=split, replace=True,
            drop_inputs=[prediction_field(_config())],
            schemes=list(run.schema_names) or None)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"dataset": dataset, "split": split,
                    "imported": version.example_count,
                    "version": version.to_dict()}), 201


@training_bp.route("/api/runs/<run_id>/push-to-hub", methods=["POST"])
@admin_required
@_enabled_required
@_same_origin_required
def api_push_to_hub(run_id):
    """Publish a run's model to the Hugging Face Hub.

    Body: ``{"repo_id", "confirm_repo_id", "private": true, "token_env":
    "HF_TOKEN", "licence": "", "accept_licence": false}``. The repository is
    named twice because a push publishes; a mismatch is refused. A trainer
    whose licence needs confirming on use needs ``accept_licence`` here too,
    since its weights carry that licence.
    """
    from flask import session

    from potato.training import store
    from potato.training.hub import HubPushError, push
    from potato.training.registry import trainer_info

    body, refused = _json_object()
    if refused:
        return refused
    run = store.load_run(_config(), run_id)
    if run is None:
        return jsonify({"error": "No such run: %s" % run_id}), 404
    repo_id = str(body.get("repo_id") or "").strip()
    if repo_id != str(body.get("confirm_repo_id") or "").strip():
        return jsonify({"error": "Type the repository name twice, the same "
                                 "both times: a push publishes the model"}), 400
    info = trainer_info(run.trainer)
    if info is not None and info.licence_ack and body.get("accept_licence") is not True:
        return jsonify({"error": "%s models are licensed %s, which applies to "
                                 "the pushed weights. Confirm with "
                                 "accept_licence." % (run.trainer, info.licence),
                        "needs_licence_ack": True}), 400
    try:
        outcome = push(_config(), run,
                       os.path.join(_manager().run_dir(run_id), "artifacts"),
                       repo_id, private=body.get("private", True) is not False,
                       token_env=str(body.get("token_env") or "HF_TOKEN"),
                       licence=str(body.get("licence") or "").strip(),
                       pushed_by=str(session.get("username", "") or "admin"),
                       trainer_licence=info.licence if info else "")
    except HubPushError as exc:
        return jsonify({"error": str(exc)}), exc.status
    except Exception as exc:  # noqa: BLE001 - the Hub's own errors
        logger.warning("Hub push of %s failed", run_id, exc_info=True)
        return jsonify({"error": "The Hub refused the push: %s" % exc}), 502
    return jsonify(outcome), 201


@training_bp.route("/api/pinned", methods=["GET"])
@admin_required
@_enabled_required
def api_pinned():
    from potato.training import store
    return jsonify({"pinned": store.pinned_items(_config())})


@training_bp.route("/api/pinned", methods=["POST"])
@admin_required
@_enabled_required
@_same_origin_required
def api_pin():
    """Pin items to the train split of every later run.

    Body: ``{"slice": name}`` to pin what a catalog slice resolves to (such
    as ``model-found-nothing``), or ``{"instance_ids": [...]}``. Pinned items
    with no human label yet are counted as waiting by each run and train once
    someone labels them.
    """
    from flask import session

    from potato.training import store

    body, refused = _json_object()
    if refused:
        return refused
    slice_name = body.get("slice")
    ids = body.get("instance_ids")
    if slice_name:
        try:
            from potato.curation.manager import get_curation_manager
            mgr = get_curation_manager()
        except Exception:
            mgr = None
        if mgr is None:
            return jsonify({"error": "The catalog is not enabled, so slices "
                                     "cannot be resolved"}), 400
        slc = mgr.slices.get(slice_name)
        if slc is None:
            return jsonify({"error": "No slice named %r" % slice_name}), 404
        ids = list(mgr.resolve(slc))
        if not ids:
            return jsonify({"error": "Slice %r matches no items. A slice "
                                     "resolves over the catalog index, so "
                                     "build the index first if it is empty."
                                     % slice_name}), 400
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "Name a slice, or give instance_ids"}), 400

    from potato.item_state_management import get_item_state_manager
    ism = get_item_state_manager()
    known = [str(i) for i in ids if ism is None or ism.has_item(str(i))]
    unknown = len(ids) - len(known)
    added = store.pin_items(_config(), known, source=str(slice_name or ""),
                            added_by=str(session.get("username", "")))
    # Train items have no prelabel (write-back keeps it off them), so a
    # slice such as model-found-nothing matches them too; say how many of
    # these the last run already trained on.
    last = store.latest_run(_config())
    in_train = (len(set(known) & store.training_split_ids(_config(), last.run_id))
                if last is not None else 0)
    return jsonify({"pinned": added, "already_pinned": len(known) - added,
                    "unknown": unknown, "in_last_run_train": in_train,
                    "total": len(store.pinned_items(_config()).get(
                        "hard_example", []))})


@training_bp.route("/api/pinned", methods=["DELETE"])
@admin_required
@_enabled_required
@_same_origin_required
def api_unpin():
    """Unpin ``instance_ids``, or every pinned item when the body has none
    (no body, ``{}``, or ``"instance_ids": null``). Anything else is refused: a
    bare string must not read as "all"."""
    from potato.training import store

    body, refused = _json_object()
    if refused:
        return refused
    ids = body.get("instance_ids")
    if ids is not None and not (isinstance(ids, list) and ids and all(
            isinstance(i, (str, int)) and not isinstance(i, bool) for i in ids)):
        return jsonify({"error": "instance_ids must be a non-empty list of "
                                 "ids; leave it out to unpin everything"}), 400
    removed = store.unpin_items(_config(), [str(i) for i in ids]
                                if ids is not None else None)
    return jsonify({"unpinned": removed})


# -------------------------------------------------------------- helpers

def _json_object():
    """``(body, None)``, or ``(None, response)`` refusing the request.

    No body is ``{}``. Anything else must parse as a JSON object: with
    ``get_json(silent=True) or {}``, invalid JSON and falsy JSON (``[]``,
    ``""``, ``0``, ``false``) became ``{}`` too, which for DELETE /pinned
    means "unpin everything".
    """
    raw = request.get_data(cache=True)
    if not raw.strip():
        return {}, None
    try:
        body = json.loads(raw)
    except ValueError:
        return None, (jsonify({"error": "The body is not valid JSON"}), 400)
    if not isinstance(body, dict):
        return None, (jsonify({"error": "Send a JSON object"}), 400)
    return body, None


def _datasets_enabled() -> bool:
    try:
        from potato.eval_datasets.manager import get_datasets_manager
        return get_datasets_manager() is not None
    except Exception:
        return False


def _trainer_rows():
    """Trainers with their parameter names, for the start form's hint, and
    what in this project's config stops one from running."""
    from potato.training.registry import get_trainer_class, list_trainers

    config = _config()
    rows = list_trainers()
    for row in rows:
        try:
            cls = get_trainer_class(row["name"])
            schema = cls.params_schema() or {}
            row["param_names"] = sorted(schema.get("properties") or {})
            row["config_problem"] = cls.config_problem(config) or ""
        except Exception:  # noqa: BLE001 - an unimportable trainer is data
            row["param_names"] = []
            row["config_problem"] = ""
    return rows


def _backend_rows():
    from potato.training.backends import default_backend_name, load_backends

    config = _config()
    default = default_backend_name(config)
    rows = []
    for backend in load_backends(config).values():
        row = backend.to_public_dict()
        row["default"] = backend.name == default
        rows.append(row)
    return rows


def _item_sample(limit: int = 50):
    """Item data for the first *limit* items, or [] when there is no store."""
    try:
        from potato.item_state_management import get_item_state_manager
        manager = get_item_state_manager()
        ids = manager.get_instance_ids()[:limit]
        return [manager.get_item(i).get_data() for i in ids]
    except Exception:  # noqa: BLE001 - no store in some test harnesses
        return []


def _schema_rows():
    """Schemes in this project, with the trainers that could fit each."""
    from potato.training.dataset import guess_modality
    from potato.training.registry import (get_trainer_class, kind_of_schema,
                                          trainers_for_schema)

    sample = _item_sample()
    config = _config()

    def runnable(name):
        # decision-calibrate fits every radio scheme, and runs only with a
        # decision model configured.
        try:
            return not get_trainer_class(name).config_problem(config)
        except Exception:  # noqa: BLE001
            return True

    rows = []
    for scheme in _config().get("annotation_schemes", []) or []:
        name = scheme.get("name")
        if not name:
            continue
        # Without the modality an image trainer was offered, and preselected,
        # for a text scheme, and failed only after the bundle was built.
        modality = guess_modality(_config(), scheme, sample) if sample else None
        matches = [t for t in trainers_for_schema(scheme, modality=modality)
                   if runnable(t.name)]
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
