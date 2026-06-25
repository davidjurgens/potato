"""
HTTP routes for Datasets + Experiments.

Admin pages:
    GET  /datasets/admin                       overview (datasets + experiments)
    GET  /datasets/view/<name>                 one dataset (versions, examples)
    GET  /datasets/experiments/compare         side-by-side experiment comparison

JSON API:
    GET    /datasets/api/datasets              list datasets
    POST   /datasets/api/datasets              create dataset
    GET    /datasets/api/datasets/<name>       dataset detail (versions)
    DELETE /datasets/api/datasets/<name>       delete dataset
    POST   /datasets/api/datasets/<name>/examples   add examples
    POST   /datasets/api/datasets/<name>/tag        tag a version
    GET    /datasets/api/datasets/<name>/examples   list examples (as_of/splits)
    POST   /datasets/api/experiments/run       run an experiment
    GET    /datasets/api/experiments           list experiments
    GET    /datasets/api/experiments/<id>      experiment detail
"""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, Response, jsonify, render_template, request, session

from potato.eval_datasets.manager import get_datasets_manager
from potato.eval_datasets.models import Example
from potato.evaluators.registry import list_evaluators

# Flagship agent-trajectory evaluators surface first in the picker; the rest
# follow. Without this, alphabetical order buries trajectory_match / tool_use
# below the scroll fold (audit High finding).
_EVALUATOR_PRIORITY = ["trajectory_match", "tool_use", "tool_call_accuracy",
                       "llm_trajectory_judge"]


def _ordered_evaluators():
    evs = list_evaluators()
    rank = {name: i for i, name in enumerate(_EVALUATOR_PRIORITY)}
    return sorted(evs, key=lambda e: (rank.get(e["name"], len(rank)), e["name"]))

datasets_bp = Blueprint("datasets", __name__, url_prefix="/datasets")


def _enabled_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if get_datasets_manager() is None:
            return jsonify({"error": "Datasets not enabled"}), 400
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """Require a valid admin API key (X-API-Key header or session)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        from potato.server_utils.admin_key import validate_admin_api_key
        from potato.flask_server import config as _config

        api_key = request.headers.get("X-API-Key") or session.get("admin_api_key")
        if not validate_admin_api_key(api_key, _config):
            return jsonify({"error": "Admin authentication required"}), 403
        return f(*args, **kwargs)
    return wrapper


# ----- pages -----

@datasets_bp.route("/admin", methods=["GET"])
@admin_required
@_enabled_required
def admin():
    mgr = get_datasets_manager()
    datasets = mgr.store.list_datasets()
    experiments = mgr.experiments.list()
    return render_template(
        "admin/datasets.html",
        datasets=datasets,
        experiments=experiments,
        storage=mgr.settings.storage,
        evaluators=_ordered_evaluators(),
    )


@datasets_bp.route("/view/<name>", methods=["GET"])
@admin_required
@_enabled_required
def view_dataset(name):
    mgr = get_datasets_manager()
    ds = mgr.store.get_dataset(name)
    if ds is None:
        return render_template("error.html", message=f"Dataset '{name}' not found"), 404
    examples = mgr.store.list_examples(name, as_of=request.args.get("as_of", "latest"))
    return render_template(
        "admin/dataset_detail.html",
        dataset=ds,
        examples=examples,
        experiments=mgr.experiments.list(name),
    )


@datasets_bp.route("/experiments/compare", methods=["GET"])
@admin_required
@_enabled_required
def compare_experiments():
    mgr = get_datasets_manager()
    ids = [i for i in request.args.get("ids", "").split(",") if i]
    experiments = [mgr.experiments.get(i) for i in ids]
    experiments = [e for e in experiments if e is not None]
    # Union of evaluator keys across the selected experiments, stable-ordered.
    keys = []
    for e in experiments:
        for k in e.aggregate_scores:
            if k not in keys:
                keys.append(k)

    # Paired significance of each non-baseline experiment's delta vs the baseline
    # (experiments[0]), per metric. mean_diff is mean(exp) - mean(baseline) so the
    # sign matches the delta shown in the table. Keyed significance[exp_id][metric].
    from potato.server_utils.eval_stats import compare_experiments_metric
    significance = {}
    if len(experiments) >= 2:
        baseline = experiments[0]
        for e in experiments[1:]:
            significance[e.id] = {
                k: compare_experiments_metric(e, baseline, k) for k in keys
            }
    return render_template(
        "admin/experiment_compare.html",
        experiments=experiments,
        metric_keys=keys,
        significance=significance,
    )


# ----- dataset API -----

@datasets_bp.route("/api/datasets", methods=["GET"])
@admin_required
@_enabled_required
def api_list_datasets():
    mgr = get_datasets_manager()
    return jsonify([d.to_dict() for d in mgr.store.list_datasets()])


@datasets_bp.route("/api/datasets", methods=["POST"])
@admin_required
@_enabled_required
def api_create_dataset():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    mgr = get_datasets_manager()
    ds = mgr.store.create_dataset(name, body.get("description", ""))
    return jsonify(ds.to_dict()), 201


@datasets_bp.route("/api/datasets/<name>", methods=["GET"])
@admin_required
@_enabled_required
def api_get_dataset(name):
    mgr = get_datasets_manager()
    ds = mgr.store.get_dataset(name)
    if ds is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(ds.to_dict())


@datasets_bp.route("/api/datasets/<name>", methods=["DELETE"])
@admin_required
@_enabled_required
def api_delete_dataset(name):
    mgr = get_datasets_manager()
    return jsonify({"deleted": mgr.store.delete_dataset(name)})


@datasets_bp.route("/api/datasets/<name>/examples", methods=["GET"])
@admin_required
@_enabled_required
def api_list_examples(name):
    mgr = get_datasets_manager()
    splits = [s for s in request.args.get("splits", "").split(",") if s] or None
    examples = mgr.store.list_examples(name, as_of=request.args.get("as_of", "latest"), splits=splits)
    return jsonify([e.to_dict() for e in examples])


@datasets_bp.route("/api/datasets/<name>/optimize_export", methods=["GET"])
@admin_required
@_enabled_required
def api_optimize_export(name):
    """Eval→improve export (E12): a dataset as a GEPA/DSPy-ready optimization
    trainset. ?fmt=dspy|gepa, ?prompt=<seed prompt>. Feed to the external optimizer;
    review the proposed prompt diff before shipping."""
    from potato.server_utils.prompt_optimization import export_for_optimization
    mgr = get_datasets_manager()
    if mgr.store.get_dataset(name) is None:
        return jsonify({"error": "not found"}), 404
    examples = [e.to_dict() for e in mgr.store.list_examples(name, as_of="latest")]
    fmt = request.args.get("fmt", "dspy")
    if fmt not in ("dspy", "gepa"):
        return jsonify({"error": "fmt must be 'dspy' or 'gepa'"}), 400
    return jsonify(export_for_optimization(examples, prompt=request.args.get("prompt", ""), fmt=fmt))


@datasets_bp.route("/api/datasets/<name>/examples", methods=["POST"])
@admin_required
@_enabled_required
def api_add_examples(name):
    body = request.get_json(silent=True) or {}
    raw = body.get("examples", [])
    if not isinstance(raw, list) or not raw:
        return jsonify({"error": "examples must be a non-empty list"}), 400
    examples = [Example.from_dict(e) for e in raw]
    mgr = get_datasets_manager()
    version = mgr.store.add_examples(name, examples, note=body.get("note", ""))
    return jsonify(version.to_dict()), 201


@datasets_bp.route("/api/datasets/<name>/export", methods=["GET"])
@admin_required
@_enabled_required
def api_export_dataset(name):
    """Export a dataset version as SFT/DPO JSONL (downloadable attachment)."""
    fmt = (request.args.get("format") or "sft").lower()
    as_of = request.args.get("as_of", "latest")
    mgr = get_datasets_manager()
    if mgr.store.get_dataset(name) is None:
        return jsonify({"error": "not found"}), 404
    try:
        jsonl, skipped = mgr.export_jsonl(name, fmt, as_of=as_of)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    resp = Response(jsonl, mimetype="application/x-ndjson")
    resp.headers["Content-Disposition"] = f'attachment; filename="{name}_{fmt}.jsonl"'
    resp.headers["X-Skipped-Examples"] = str(skipped)
    return resp


@datasets_bp.route("/api/datasets/<name>/import_instances", methods=["POST"])
@admin_required
@_enabled_required
def api_import_instances(name):
    """Curate dataset examples from the live task's loaded instances.

    Body: {instance_ids?: [...], include_annotations?: bool,
           aggregation_method?: "majority"|"dawid_skene"}
    """
    body = request.get_json(silent=True) or {}
    mgr = get_datasets_manager()
    method = body.get("aggregation_method", "majority")
    if method not in ("majority", "dawid_skene"):
        return jsonify({"error": "aggregation_method must be 'majority' or 'dawid_skene'"}), 400
    try:
        version = mgr.import_from_instances(
            name,
            instance_ids=body.get("instance_ids"),
            include_annotations=bool(body.get("include_annotations", False)),
            aggregation_method=method,
        )
    except (ValueError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(version.to_dict()), 201


@datasets_bp.route("/api/datasets/<name>/import_traces", methods=["POST"])
@admin_required
@_enabled_required
def api_import_traces(name):
    """Curate examples from runtime-ingested traces only.

    Body: {source?: "webhook"|"langsmith"|"langfuse", include_annotations?: bool}
    """
    body = request.get_json(silent=True) or {}
    mgr = get_datasets_manager()
    try:
        version = mgr.import_from_traces(
            name,
            source=body.get("source"),
            include_annotations=bool(body.get("include_annotations", False)),
        )
    except (ValueError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(version.to_dict()), 201


@datasets_bp.route("/api/datasets/<name>/tag", methods=["POST"])
@admin_required
@_enabled_required
def api_tag_version(name):
    body = request.get_json(silent=True) or {}
    version_id = body.get("version_id")
    tag = body.get("tag")
    if not version_id or not tag:
        return jsonify({"error": "version_id and tag are required"}), 400
    mgr = get_datasets_manager()
    return jsonify({"tagged": mgr.store.tag_version(name, version_id, tag)})


# ----- experiment API -----

@datasets_bp.route("/api/experiments/run", methods=["POST"])
@admin_required
@_enabled_required
def api_run_experiment():
    body = request.get_json(silent=True) or {}
    dataset_name = body.get("dataset")
    specs = body.get("evaluators", [])
    if not dataset_name or not specs:
        return jsonify({"error": "dataset and evaluators are required"}), 400
    mgr = get_datasets_manager()
    try:
        exp = mgr.run(
            dataset_name,
            specs,
            name=body.get("name", ""),
            outputs_map=body.get("outputs_map"),
            as_of=body.get("as_of", "latest"),
            splits=body.get("splits"),
            metadata=body.get("metadata"),
        )
    except KeyError as e:  # unknown evaluator
        return jsonify({"error": str(e)}), 400
    return jsonify(exp.to_dict()), 201


@datasets_bp.route("/api/experiments", methods=["GET"])
@admin_required
@_enabled_required
def api_list_experiments():
    mgr = get_datasets_manager()
    dataset = request.args.get("dataset")
    exps = mgr.experiments.list(dataset)
    # Summaries only (omit per-example results for the list view).
    return jsonify([
        {
            "id": e.id, "name": e.name, "dataset_name": e.dataset_name,
            "dataset_version": e.dataset_version, "created_at": e.created_at,
            "example_count": e.example_count, "aggregate_scores": e.aggregate_scores,
        }
        for e in exps
    ])


@datasets_bp.route("/api/experiments/<experiment_id>", methods=["GET"])
@admin_required
@_enabled_required
def api_get_experiment(experiment_id):
    mgr = get_datasets_manager()
    exp = mgr.experiments.get(experiment_id)
    if exp is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(exp.to_dict())


@datasets_bp.route("/api/experiments/<experiment_id>/export_rewards", methods=["GET"])
@admin_required
@_enabled_required
def api_export_rewards(experiment_id):
    """Rubrics-as-Rewards export (E9): convert an experiment's rubric-DAG /
    agent-as-judge results into criterion-level reward-model training rows."""
    from potato.server_utils.rubric_reward import build_reward_dataset
    mgr = get_datasets_manager()
    exp = mgr.experiments.get(experiment_id)
    if exp is None:
        return jsonify({"error": "not found"}), 404
    records = []
    for r in exp.results:
        prompt = ""
        if isinstance(r.outputs, dict):
            prompt = r.outputs.get("prompt") or r.outputs.get("question") or ""
        for result in (r.results or []):
            records.append({"result": result, "prompt": str(prompt),
                            "response": str(r.outputs) if r.outputs is not None else ""})
    rows = build_reward_dataset(records)
    return jsonify({"experiment": experiment_id, "count": len(rows), "rows": rows})
