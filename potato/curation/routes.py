"""
Admin routes for semantic curation (the "Catalog").

    GET  /admin/catalog                 HTML page (search + slices)
    POST /admin/catalog/api/build       build the embedding index over current items
    POST /admin/catalog/api/search      {query|anchor_id, top_k, threshold}
    GET  /admin/catalog/api/slices      list saved slices
    POST /admin/catalog/api/slices      create/update a slice
    GET  /admin/catalog/api/slices/<n>/resolve   resolve a slice -> instance ids
    DELETE /admin/catalog/api/slices/<n>
    POST /admin/catalog/api/slices/<n>/to_dataset  {dataset}  curate -> dataset
"""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, render_template, request, session

from potato.curation.manager import get_curation_manager
from potato.curation.slices import Slice

curation_bp = Blueprint("curation", __name__, url_prefix="/admin/catalog")


def _enabled_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if get_curation_manager() is None:
            return jsonify({"error": "Curation not enabled"}), 400
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        from potato.server_utils.admin_key import validate_admin_api_key
        from potato.flask_server import config as _config
        api_key = request.headers.get("X-API-Key") or session.get("admin_api_key")
        if not validate_admin_api_key(api_key, _config):
            return jsonify({"error": "Admin authentication required"}), 403
        return f(*args, **kwargs)
    return wrapper


@admin_required
@_enabled_required
def _noop():  # placeholder so decorators import cleanly
    pass


@curation_bp.route("", methods=["GET"])
@admin_required
@_enabled_required
def catalog_page():
    mgr = get_curation_manager()
    return render_template(
        "admin/catalog.html",
        indexed=len(mgr.index),
        slices=[s.to_dict() for s in mgr.slices.list()],
        embeddings_available=_embeddings_available(),
    )


def _embeddings_available() -> bool:
    from potato.curation.embeddings import is_available
    mgr = get_curation_manager()
    # If a custom embed_fn is wired, embeddings are always usable.
    return is_available() or (mgr is not None and mgr.embedder._embed_fn is not None)


@curation_bp.route("/api/build", methods=["POST"])
@admin_required
@_enabled_required
def api_build():
    body = request.get_json(silent=True) or {}
    count = get_curation_manager().build_index(max_items=body.get("max_items"))
    return jsonify({"indexed": count})


@curation_bp.route("/api/search", methods=["POST"])
@admin_required
@_enabled_required
def api_search():
    body = request.get_json(silent=True) or {}
    mgr = get_curation_manager()
    try:
        hits = mgr.search(query=body.get("query", ""), anchor_id=body.get("anchor_id", ""),
                          top_k=int(body.get("top_k", 10)),
                          threshold=float(body.get("threshold", 0.0)))
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"results": [{"instance_id": i, "score": round(s, 4)} for i, s in hits]})


@curation_bp.route("/api/slices", methods=["GET"])
@admin_required
@_enabled_required
def api_list_slices():
    return jsonify([s.to_dict() for s in get_curation_manager().slices.list()])


@curation_bp.route("/api/slices", methods=["POST"])
@admin_required
@_enabled_required
def api_save_slice():
    body = request.get_json(silent=True) or {}
    if not body.get("name"):
        return jsonify({"error": "name is required"}), 400
    mgr = get_curation_manager()
    mgr.slices.save(Slice.from_dict(body))
    return jsonify({"saved": True}), 201


@curation_bp.route("/api/slices/<name>/resolve", methods=["GET"])
@admin_required
@_enabled_required
def api_resolve_slice(name):
    mgr = get_curation_manager()
    slc = mgr.slices.get(name)
    if slc is None:
        return jsonify({"error": "not found"}), 404
    ids = mgr.resolve(slc)
    return jsonify({"name": name, "count": len(ids), "instance_ids": ids})


@curation_bp.route("/api/slices/<name>", methods=["DELETE"])
@admin_required
@_enabled_required
def api_delete_slice(name):
    return jsonify({"deleted": get_curation_manager().slices.delete(name)})


@curation_bp.route("/api/slices/<name>/to_dataset", methods=["POST"])
@admin_required
@_enabled_required
def api_slice_to_dataset(name):
    body = request.get_json(silent=True) or {}
    dataset = body.get("dataset")
    if not dataset:
        return jsonify({"error": "dataset is required"}), 400
    mgr = get_curation_manager()
    slc = mgr.slices.get(name)
    if slc is None:
        return jsonify({"error": "slice not found"}), 404
    ids = mgr.resolve(slc)
    if not ids:
        return jsonify({"error": "slice resolved to no instances"}), 400

    from potato.eval_datasets.manager import get_datasets_manager
    dm = get_datasets_manager()
    if dm is None:
        return jsonify({"error": "datasets not enabled"}), 400
    version = dm.import_from_instances(
        dataset, instance_ids=ids,
        include_annotations=bool(body.get("include_annotations", False)))
    return jsonify({"dataset": dataset, "imported": len(ids),
                    "version": version.to_dict()}), 201
