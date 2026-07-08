"""
Corpus Map Routes

Annotator-facing 2D corpus map + cluster browser, plus an admin rebuild trigger.
Shares the ``/corpus`` URL prefix with the event registry.

  GET  /corpus/map                     -> the three-zone annotator page
  GET  /corpus/api/map_data            -> cluster-colored points + clusters
  GET  /corpus/api/clusters            -> cluster list (sidebar)
  GET  /corpus/api/cluster/<cid>/docs  -> docs in a cluster
  GET  /corpus/api/knn/<doc_id>        -> k nearest neighbors of a doc
  GET  /corpus/api/build_status        -> ingest status (for polling)
  POST /corpus/api/rebuild             -> admin: rebuild the map (background)
"""

import logging
import threading
from functools import wraps

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for

from .manager import get_corpus_map_manager

logger = logging.getLogger(__name__)

corpus_map_bp = Blueprint("corpus_map", __name__, url_prefix="/corpus")


def _enabled_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if get_corpus_map_manager() is None:
            return jsonify({"error": "Corpus map not enabled"}), 400
        return f(*args, **kwargs)

    return wrapper


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


def api_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)

    return wrapper


def same_origin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")
        host = request.host_url.rstrip("/")
        if not origin and not referer:
            return f(*args, **kwargs)
        if origin and not origin.startswith(host):
            return jsonify({"error": "Cross-origin request rejected"}), 403
        if referer and not referer.startswith(host):
            return jsonify({"error": "Cross-origin request rejected"}), 403
        return f(*args, **kwargs)

    return wrapper


# Admin gate reuses the shared RBAC layer (shared API key stays superuser).
from potato.server_utils.rbac import require_permission, Permission

admin_required = require_permission(Permission.VIEW_ADMIN_DASHBOARD)


# ---- pages -----------------------------------------------------------------
@corpus_map_bp.route("/map", methods=["GET"])
@login_required
@_enabled_required
def map_page():
    return render_template("corpus_map/map.html")


# ---- reads -----------------------------------------------------------------
@corpus_map_bp.route("/api/map_data", methods=["GET"])
@api_login_required
@_enabled_required
def map_data():
    return jsonify(get_corpus_map_manager().map_data())


@corpus_map_bp.route("/api/clusters", methods=["GET"])
@api_login_required
@_enabled_required
def clusters():
    return jsonify({"clusters": get_corpus_map_manager().clusters()})


@corpus_map_bp.route("/api/cluster/<int:cluster_id>/docs", methods=["GET"])
@api_login_required
@_enabled_required
def cluster_docs(cluster_id):
    return jsonify({"docs": get_corpus_map_manager().cluster_docs(cluster_id)})


@corpus_map_bp.route("/api/knn/<doc_id>", methods=["GET"])
@api_login_required
@_enabled_required
def knn(doc_id):
    return jsonify({"neighbors": get_corpus_map_manager().knn(doc_id)})


@corpus_map_bp.route("/api/build_status", methods=["GET"])
@api_login_required
@_enabled_required
def build_status():
    return jsonify(get_corpus_map_manager().status())


# ---- navigation ------------------------------------------------------------
@corpus_map_bp.route("/api/goto", methods=["POST"])
@api_login_required
@same_origin_required
@_enabled_required
def goto_doc():
    """Point the user's reading pane at ``doc_id``.

    Cross-document event annotation needs every annotator to reach any document
    (the map is the navigator, not the assignment queue). If the document is not
    yet in the user's ordering, assign it (append), then jump. The caller reloads
    the /annotate iframe to render the now-current instance.
    """
    from potato.flask_server import get_user_state, go_to_id
    from potato.item_state_management import get_item_state_manager

    data = request.get_json(silent=True) or {}
    doc_id = data.get("doc_id")
    if not doc_id:
        return jsonify({"error": "Missing 'doc_id'"}), 400
    doc_id = str(doc_id)

    username = session["username"]
    user_state = get_user_state(username)
    ism = get_item_state_manager()

    if doc_id not in ism.get_instance_ids():
        return jsonify({"error": "Unknown doc_id"}), 404

    index = user_state.instance_id_to_order.get(doc_id)
    if index is None:
        # Not yet assigned to this user — append it so the whole corpus is reachable.
        user_state.assign_instance(ism.get_item(doc_id))
        index = user_state.instance_id_to_order.get(doc_id)

    go_to_id(username, index)
    return jsonify({"success": True, "doc_id": doc_id, "index": index})


# ---- admin -----------------------------------------------------------------
@corpus_map_bp.route("/api/rebuild", methods=["POST"])
@admin_required
@same_origin_required
@_enabled_required
def rebuild():
    mgr = get_corpus_map_manager()
    threading.Thread(target=lambda: mgr.build(force=True), daemon=True).start()
    return jsonify({"status": "rebuild started"})
